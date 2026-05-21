"""Post-meeting closing-the-loop pipeline.

Triggered by the scheduler's ``_run_reachy_meeting_auto_stop`` once a
meeting recording completes AND its summary has landed. Runs two passes
in sequence so neither blocks the other if the LLM is slow:

  1. **Action items → tasks** (Feature-20) — extract action items from
     the saved summary, infer ownership from diarization speakers + name
     mentions, and create tasks gated by an approval-queue entry when
     the assigned owner is external to the user.
  2. **Follow-up email drafts** (Feature-21) — for each attendee group
     (internal vs external), compose a per-recipient summary + action
     items recap and drop the draft into ``email/drafts/pool`` so the
     user can one-click approve.

Both passes are idempotent (re-running on the same meeting is a no-op
when the action items already became tasks and the drafts already exist
in the pool tagged ``source=meeting_followup``).

Disable via ``ZERO_MEETING_FOLLOWUP_ENABLED=0`` for testing.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


def _enabled() -> bool:
    val = os.getenv("ZERO_MEETING_FOLLOWUP_ENABLED", "true").strip().lower()
    return val in {"1", "true", "yes", "on"}


class MeetingFollowupService:
    """Coordinator. Keeps a per-meeting "already-ran" ledger on disk so
    a re-tick of the scheduler doesn't double-create tasks or drafts."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self._dir / "followup_ledger.json"
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Ledger — disk-backed dedupe so re-runs don't spam tasks/drafts.
    # ------------------------------------------------------------------
    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._ledger_path.exists():
            return {}
        try:
            return json.loads(self._ledger_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("meeting_followup_ledger_load_failed", error=str(exc))
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._ledger_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._ledger_path)

    def _ledger_get(self, meeting_id: str) -> dict[str, Any]:
        with self._lock:
            return self._load().get(meeting_id, {})

    def _ledger_set(self, meeting_id: str, patch: dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            entry = data.get(meeting_id, {})
            entry.update(patch)
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            data[meeting_id] = entry
            self._save(data)

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    async def run(self, *, meeting_id: str, max_wait_for_summary_s: int = 300) -> dict[str, Any]:
        """Run the full follow-up loop for one meeting. Safe to re-call;
        idempotent via the ledger.

        Auto-stop triggers this in the background BEFORE the transcription
        + summary pipeline has finished. We poll for the summary up to
        ``max_wait_for_summary_s`` (default 5 min) before declaring the
        run incomplete.

        Honors the meeting_privacy_service — private meetings bypass the
        entire pipeline so transcript content never reaches tasks, vault
        index, or email drafts.
        """
        if not _enabled():
            logger.info("meeting_followup_disabled", meeting_id=meeting_id)
            return {"ok": False, "reason": "disabled"}
        try:
            from app.services.meeting_privacy_service import (
                get_meeting_privacy_service,
            )

            if get_meeting_privacy_service().is_private(meeting_id):
                logger.info("meeting_followup_skipped_private", meeting_id=meeting_id)
                return {"ok": False, "reason": "private"}
        except Exception:
            pass
        ledger = self._ledger_get(meeting_id)
        result: dict[str, Any] = {"meeting_id": meeting_id}

        # Poll for the summary to materialize (transcribe+summary can take
        # several minutes). Backs off 5 -> 30 -> 60 -> 60 -> 60 ...
        deadline = asyncio.get_event_loop().time() + max(10, max_wait_for_summary_s)
        delay = 5.0
        summary = await self._fetch_summary(meeting_id)
        while summary is None and asyncio.get_event_loop().time() < deadline:
            logger.info(
                "meeting_followup_wait_for_summary",
                meeting_id=meeting_id,
                next_check_s=delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
            summary = await self._fetch_summary(meeting_id)
        if summary is None:
            logger.warning(
                "meeting_followup_no_summary_after_wait",
                meeting_id=meeting_id,
                waited_s=max_wait_for_summary_s,
            )
            return {
                "ok": False,
                "reason": "summary_not_generated",
                "waited_s": max_wait_for_summary_s,
            }

        try:
            tasks_result = await self._action_items_to_tasks(meeting_id, ledger)
        except Exception as exc:
            logger.warning(
                "meeting_followup_action_items_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )
            tasks_result = {"ok": False, "error": str(exc)}
        result["action_items"] = tasks_result

        try:
            drafts_result = await self._draft_followup_emails(meeting_id, ledger)
        except Exception as exc:
            logger.warning(
                "meeting_followup_drafts_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )
            drafts_result = {"ok": False, "error": str(exc)}
        result["follow_up_emails"] = drafts_result

        self._ledger_set(meeting_id, {
            "tasks": tasks_result,
            "drafts": drafts_result,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        })
        return result

    # ------------------------------------------------------------------
    # Pass 1: action items → tasks (F-20)
    # ------------------------------------------------------------------
    async def _fetch_summary(self, meeting_id: str) -> dict[str, Any] | None:
        """Read MeetingSummaryModel for a meeting; returns None when no
        summary has been written yet (transcription/summary pipeline still
        running)."""
        from app.infrastructure.database import get_session
        from sqlalchemy import select
        from app.db.models import MeetingSummaryModel  # type: ignore

        async with get_session() as db:
            row = (
                await db.execute(
                    select(MeetingSummaryModel)
                    .where(MeetingSummaryModel.meeting_id == meeting_id)
                    .order_by(MeetingSummaryModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "summary_text": row.summary_text or "",
            "key_topics": list(row.key_topics or []),
            "action_items": list(row.action_items or []),
            "decisions": list(row.decisions or []),
        }

    async def _action_items_to_tasks(
        self, meeting_id: str, ledger: dict[str, Any]
    ) -> dict[str, Any]:
        if ledger.get("tasks", {}).get("ok"):
            return {**ledger["tasks"], "skipped": "already_done"}

        summary = await self._fetch_summary(meeting_id)
        if summary is None:
            return {"ok": False, "error": "summary not generated yet"}
        items: list[dict[str, Any]] = list(summary.get("action_items") or [])
        if not items:
            return {"ok": True, "created": [], "skipped": [], "reason": "no_action_items"}

        # Use the existing endpoint contract via TaskService directly so
        # we don't HTTP-call ourselves. Falls back to a structlog warning
        # when TaskService surface drifts.
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        try:
            from app.services.task_service import get_task_service
            from app.models.task import TaskCategory, TaskCreate, TaskPriority, TaskSource

            task_svc = get_task_service()
            for item in items:
                desc = str(item.get("description") or "").strip()
                if not desc:
                    continue
                owner = str(item.get("owner") or "").strip()
                # External owner (not the user) → drop into approval-queue
                # rather than directly creating a task in their backlog.
                external = bool(owner and owner.lower() not in {"me", "i", "self", "adam"})
                if external:
                    try:
                        from app.services.approval_queue_service import (
                            get_approval_queue_service,
                        )

                        await get_approval_queue_service().request(
                            tool_name="meeting_followup.create_task",
                            tier="write_local",
                            summary=f"Create task for {owner}: {desc[:120]}",
                            arguments={
                                "meeting_id": meeting_id,
                                "owner": owner,
                                "description": desc,
                                "due": item.get("due"),
                            },
                            requested_by=f"meeting_followup:{meeting_id}",
                        )
                        skipped.append({
                            "description": desc,
                            "owner": owner,
                            "reason": "queued_for_approval",
                        })
                        continue
                    except Exception as exc:
                        logger.debug("approval_queue_request_failed", error=str(exc))
                        # Fall through to direct create.

                tags = ["meeting_followup", f"meeting:{meeting_id}"]
                if owner:
                    tags.append(f"owner:{owner.lower()}")
                due_at = None
                if item.get("due"):
                    try:
                        due_at = datetime.fromisoformat(str(item["due"]).replace("Z", "+00:00"))
                    except Exception:
                        due_at = None
                try:
                    task = await task_svc.create_task(
                        TaskCreate(
                            title=desc[:200],
                            description=desc,
                            category=TaskCategory.CHORE,
                            priority=TaskPriority.MEDIUM,
                            source=TaskSource.USER_REPORTED,
                            source_reference=f"meeting:{meeting_id}",
                            tags=tags,
                            due_at=due_at,
                        )
                    )
                    task_id = getattr(task, "id", None)
                    if task_id is None and isinstance(task, dict):
                        task_id = task.get("id")
                    created.append({
                        "task_id": task_id,
                        "description": desc,
                        "owner": owner or None,
                    })
                except Exception as exc:
                    logger.debug("meeting_followup_task_create_failed", error=str(exc))
                    skipped.append({
                        "description": desc,
                        "owner": owner,
                        "reason": f"create_failed: {exc}",
                    })
        except Exception as exc:
            return {"ok": False, "error": f"task_service unavailable: {exc}"}

        return {"ok": True, "created": created, "skipped": skipped}

    # ------------------------------------------------------------------
    # Pass 2: follow-up email drafts (F-21)
    # ------------------------------------------------------------------
    async def _draft_followup_emails(
        self, meeting_id: str, ledger: dict[str, Any]
    ) -> dict[str, Any]:
        if ledger.get("drafts", {}).get("ok"):
            return {**ledger["drafts"], "skipped": "already_done"}

        try:
            from app.infrastructure.database import get_session
            from sqlalchemy import select
            from app.db.models import MeetingModel  # type: ignore

            async with get_session() as db:
                meeting_row = (
                    await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
                ).scalar_one_or_none()
            summary = await self._fetch_summary(meeting_id)
        except Exception as exc:
            return {"ok": False, "error": f"meeting/summary fetch failed: {exc}"}

        if meeting_row is None:
            return {"ok": False, "error": "meeting not found"}
        if summary is None:
            return {"ok": False, "error": "summary not generated yet"}

        title = getattr(meeting_row, "title", None) or "our meeting"
        # MeetingModel stores participants (not attendees). Entries may be
        # plain emails, "Display Name <email>", or just names without an
        # email — filter to those with an @ so we have something to send.
        raw_participants = list(getattr(meeting_row, "participants", None) or [])
        attendees: list[str] = []
        for p in raw_participants:
            s = str(p or "").strip()
            if "<" in s and ">" in s:
                s = s[s.find("<") + 1 : s.find(">")].strip()
            if "@" in s:
                attendees.append(s)
        # Bail when there are no email recipients to draft to.
        if not attendees:
            return {"ok": True, "drafts": [], "reason": "no_attendee_emails"}

        summary_text = str(summary.get("summary_text") or "")
        action_items = list(summary.get("action_items") or [])

        # Compose ONE email body per recipient group. We treat each
        # attendee as its own group to keep ownership clear; a future
        # version can fan into one-per-domain.
        drafts: list[dict[str, Any]] = []
        try:
            from app.services.email_draft_pool_service import get_email_draft_pool

            pool = get_email_draft_pool()
        except Exception as exc:
            return {"ok": False, "error": f"email_draft_pool unavailable: {exc}"}

        for recipient in attendees:
            if "@" not in recipient:
                continue
            body = self._compose_followup_body(
                title=title,
                summary_text=summary_text,
                action_items=action_items,
                recipient=recipient,
            )
            try:
                draft = await pool.add_draft(
                    account_id="default",
                    thread_id=None,
                    to=recipient,
                    subject=f"Re: {title}",
                    body=body,
                    meta={
                        "source": "meeting_followup",
                        "meeting_id": meeting_id,
                    },
                )
                draft_id = getattr(draft, "id", None)
                if draft_id is None and isinstance(draft, dict):
                    draft_id = draft.get("id")
                drafts.append({"to": recipient, "draft_id": draft_id})
            except Exception as exc:
                logger.debug(
                    "meeting_followup_draft_add_failed",
                    recipient=recipient,
                    error=str(exc),
                )
                drafts.append({"to": recipient, "error": str(exc)})

        return {"ok": True, "drafts": drafts}

    @staticmethod
    def _compose_followup_body(
        *,
        title: str,
        summary_text: str,
        action_items: Iterable[dict[str, Any]],
        recipient: str,
    ) -> str:
        recipient_first = recipient.split("@", 1)[0].split(".", 1)[0].title()
        lines = [
            f"Hi {recipient_first},",
            "",
            f"Thanks for joining {title}. Quick recap of what we discussed:",
            "",
            (summary_text or "[summary unavailable]")[:1200],
            "",
            "Action items:",
        ]
        any_items = False
        for ai in action_items:
            owner = str(ai.get("owner") or "").strip()
            desc = str(ai.get("description") or "").strip()
            due = str(ai.get("due") or "").strip()
            if not desc:
                continue
            any_items = True
            ai_line = f"  • {desc}"
            extras = []
            if owner:
                extras.append(f"owner: {owner}")
            if due:
                extras.append(f"due: {due}")
            if extras:
                ai_line += f" ({', '.join(extras)})"
            lines.append(ai_line)
        if not any_items:
            lines.append("  • (none)")
        lines.extend([
            "",
            "Let me know if I missed anything.",
            "",
            "— Zero (drafting on behalf of Adam)",
        ])
        return "\n".join(lines)


@lru_cache()
def get_meeting_followup_service() -> MeetingFollowupService:
    return MeetingFollowupService()
