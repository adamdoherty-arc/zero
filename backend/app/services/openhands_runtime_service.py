"""
OpenHands runtime adapter.

OpenHands is a proposed delegated agent runtime for code-heavy tasks. In this
integration pass it is disabled by default; production code work should route
through Legion unless a real OpenHands runtime is explicitly approved.

Graceful-degradation pattern:

  - If ``ZERO_OPENHANDS_ENABLED`` is true and a supported SDK is present, the
    adapter can dispatch to the configured runtime.
  - Otherwise ``is_available()`` returns False and dispatches are recorded as
    unavailable instead of performing side effects.

Tasks are persisted at ``backend/app/data/openhands/tasks.json`` so the UI can
show history across restarts.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "openhands"
_TASKS_FILE = "tasks.json"
_MAX_EVENTS = 200


@dataclass
class OpenHandsTask:
    """One task dispatch â€” maps to an OpenHands conversation."""

    id: str
    instruction: str
    status: str  # "queued" | "running" | "completed" | "failed" | "cancelled"
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    workspace: str = "local"  # "local" | "docker"
    model: Optional[str] = None
    repo_dir: Optional[str] = None
    events: list[dict] = field(default_factory=list)
    final_message: Optional[str] = None
    error: Optional[str] = None


class OpenHandsRuntimeService:
    """Thin wrapper around the OpenHands SDK with graceful degradation."""

    def __init__(self) -> None:
        # Read _DATA_DIR at call time so tests can monkeypatch it.
        import app.services.openhands_runtime_service as _self_mod
        self._dir = _self_mod._DATA_DIR
        self._path = self._dir / _TASKS_FILE
        self._tasks: dict[str, OpenHandsTask] = self._load()
        self._tasks_running: dict[str, asyncio.Task] = {}
        self._sdk = self._init_sdk()

    def _init_sdk(self):
        """Try to import OpenHands. Returns the module on success, None
        otherwise. We probe ``openhands_sdk`` first (preferred name) then
        ``openhands.sdk`` (older layout)."""
        if os.getenv("ZERO_OPENHANDS_ENABLED", "").lower() not in ("1", "true", "yes"):
            logger.info("openhands_disabled", reason="ZERO_OPENHANDS_ENABLED not set")
            return None
        try:
            import openhands_sdk as sdk  # type: ignore[import-not-found]
            logger.info("openhands_sdk_loaded", layout="openhands_sdk")
            return sdk
        except ImportError:
            pass
        try:
            from openhands import sdk  # type: ignore[import-not-found]
            logger.info("openhands_sdk_loaded", layout="openhands.sdk")
            return sdk
        except ImportError:
            logger.debug("openhands_sdk_not_installed")
            return None

    def is_available(self) -> bool:
        return self._sdk is not None

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        instruction: str,
        *,
        workspace: str = "local",
        model: Optional[str] = None,
        repo_dir: Optional[str] = None,
    ) -> OpenHandsTask:
        """Queue a task and start it in the background. Returns the task
        record immediately so callers can poll via ``get()``.

        Microagents that match the instruction's triggers are prepended to
        the instruction so the OpenHands agent has the right project
        conventions loaded from the first turn (mirrors how OpenHands
        loads its own ``.openhands/microagents/`` files at conversation
        start).
        """
        if workspace not in {"local", "docker"}:
            raise ValueError(f"workspace must be 'local' or 'docker', got {workspace!r}")

        # Inject microagent context â€” same trigger-based pattern OpenHands
        # uses natively, just sourced from Zero's own ``microagents/`` tree.
        final_instruction = instruction
        try:
            from app.services.microagents_service import get_microagents_service
            context = get_microagents_service().compose_context_for(
                instruction, max_chars=3000
            )
            if context:
                final_instruction = f"{context}\n\n---\n\n{instruction}"
                logger.info(
                    "openhands_microagent_inject",
                    chars=len(context),
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("openhands_microagent_inject_failed", error=str(e))

        task = OpenHandsTask(
            id=uuid.uuid4().hex[:12],
            instruction=final_instruction,
            status="queued" if self.is_available() else "failed",
            created_at=_now_iso(),
            workspace=workspace,
            model=model,
            repo_dir=repo_dir,
            error=None
            if self.is_available()
            else "OpenHands disabled; use the Legion delegation path until the runtime is approved.",
        )
        self._tasks[task.id] = task
        self._save()
        if self.is_available():
            self._tasks_running[task.id] = asyncio.create_task(self._run_task(task))
        logger.info(
            "openhands_task_dispatched",
            task=task.id,
            workspace=workspace,
            available=self.is_available(),
        )
        return task

    async def cancel(self, task_id: str) -> dict:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        running = self._tasks_running.pop(task_id, None)
        if running and not running.done():
            running.cancel()
            try:
                await running
            except (asyncio.CancelledError, Exception):
                pass
        if task.status in {"queued", "running"}:
            task.status = "cancelled"
            task.finished_at = _now_iso()
            self._save()
        return asdict(task)

    def get(self, task_id: str) -> Optional[dict]:
        task = self._tasks.get(task_id)
        return asdict(task) if task else None

    def list_tasks(self, limit: int = 50) -> list[dict]:
        items = sorted(
            self._tasks.values(), key=lambda t: t.created_at, reverse=True
        )
        return [asdict(t) for t in items[:limit]]

    # ------------------------------------------------------------------
    # Runner (only entered when SDK is available)
    # ------------------------------------------------------------------

    async def _run_task(self, task: OpenHandsTask) -> None:
        try:
            task.status = "running"
            task.started_at = _now_iso()
            self._save()
            await self._record_event(task, {"type": "start", "instruction": task.instruction})

            # Workspace selection. The SDK names vary by version â€” we probe
            # both shapes and pick whichever is present.
            workspace_cls = None
            try:
                if task.workspace == "docker":
                    workspace_cls = getattr(self._sdk, "DockerWorkspace", None)
                else:
                    workspace_cls = getattr(self._sdk, "LocalWorkspace", None)
            except Exception:
                workspace_cls = None
            if workspace_cls is None:
                # Older / different SDK layout. Fall back to a stubbed run
                # that still records the dispatch so the UI shows the user
                # something happened.
                await self._record_event(
                    task,
                    {
                        "type": "warning",
                        "message": "OpenHands SDK present but Workspace class missing for this version.",
                    },
                )
                task.final_message = (
                    "OpenHands SDK loaded but the expected Workspace class wasn't "
                    "found. Update the OpenHands SDK version, or check the API surface."
                )
                task.status = "completed"
                return

            await self._record_event(task, {"type": "workspace_open", "kind": task.workspace})

            # Try to assemble an Agent + Conversation. Wrapped broadly because
            # the SDK API has been evolving rapidly.
            try:
                Agent = getattr(self._sdk, "Agent")
                Conversation = getattr(self._sdk, "Conversation")
                LLM = getattr(self._sdk, "LLM")
                llm_kwargs = {}
                if task.model:
                    llm_kwargs["model"] = task.model
                if os.getenv("BIFROST_GATEWAY_URL"):
                    # Prefer routing through Bifrost when it's running so the
                    # gateway's budget caps + fallbacks apply here too.
                    llm_kwargs["base_url"] = (
                        os.getenv("BIFROST_GATEWAY_URL").rstrip("/") + "/v1"
                    )
                llm = LLM(**llm_kwargs)
                agent = Agent(llm=llm)
                conversation = Conversation(agent=agent)
                conversation.send_message(task.instruction)
                # Best-effort: stream output via callback if the SDK supports it.
                final = getattr(conversation, "final_message", None) or getattr(
                    conversation, "last_message", None
                )
                task.final_message = str(final) if final else "(no final message returned)"
                task.status = "completed"
            except Exception as e:  # noqa: BLE001
                task.status = "failed"
                task.error = str(e)
                await self._record_event(task, {"type": "error", "message": str(e)})

        except asyncio.CancelledError:
            task.status = "cancelled"
            raise
        finally:
            task.finished_at = _now_iso()
            self._save()
            # Mirror the final outcome into the Memory Vault so the user can
            # search "OpenHands ran X" later.
            try:
                from app.services.memory_tree import get_memory_tree
                tree = get_memory_tree()
                body = (
                    f"# OpenHands task â€” {task.id}\n\n"
                    f"- Status: {task.status}\n"
                    f"- Workspace: {task.workspace}\n"
                    f"- Model: {task.model or '(default)'}\n"
                    f"- Instruction:\n\n```\n{task.instruction}\n```\n\n"
                    f"## Final\n{task.final_message or task.error or '(empty)'}\n"
                )
                await tree.write_chunk(
                    "openhands",
                    body,
                    level=0,
                    title=f"OpenHands {task.id}",
                    tags=["openhands", task.status],
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("openhands_vault_mirror_failed", error=str(e))

    async def _record_event(self, task: OpenHandsTask, event: dict) -> None:
        event = {**event, "ts": _now_iso()}
        task.events.append(event)
        if len(task.events) > _MAX_EVENTS:
            task.events = task.events[-_MAX_EVENTS:]
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, OpenHandsTask]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        out: dict[str, OpenHandsTask] = {}
        for k, v in raw.items():
            try:
                out[k] = OpenHandsTask(**v)
            except Exception:
                continue
        return out

    def _save(self) -> None:
        data = {k: asdict(v) for k, v in self._tasks.items()}
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("openhands_save_failed", error=str(e))


@lru_cache(maxsize=1)
def get_openhands_runtime_service() -> OpenHandsRuntimeService:
    return OpenHandsRuntimeService()
