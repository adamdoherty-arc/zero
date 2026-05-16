"""Loop runner service — dispatches one loop to the right runner.

Four runner kinds:
- claude_skill   : reads SKILL.md, sends to local Qwen via LiteLLM, captures output
- opencode       : OpenCode CLI daemon polls externally (P3, this side just queues)
- http           : POST to ADA/Legion endpoint (skill runs in that project)
- prompt_variant : in-process LLM call through Legion's prompt-evolution surface

Note on naming: `claude_skill` uses Anthropic's SKILL.md format because that's
what the user's existing skill library is written in. But for $0/day operation,
we run those skills against local Qwen3.6-35B-A3B abliterated, NOT Anthropic
Claude. The Anthropic Claude Code CLI continues to be the way YOU run skills
interactively; the loop framework runs them autonomously against local models.

Output contract for skills:
- Stdout/markdown is captured into loop_runs.output and the vault file
- <learning kind="..." confidence="..."> blocks are extracted into loop_learnings
- Trailing scorecard (lines starting with "score:" / "rating:") feeds the judge
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import httpx
import structlog

from app.services.loop_registry_service import get_loop_registry
from app.services.loop_report_sink_client import get_loop_sink
from app.services.vault_writer_service import get_vault_writer

logger = structlog.get_logger(__name__)

# Tag emitted by skills' self-learn sections so we can capture cross-project learnings.
LEARNING_BLOCK_RE = re.compile(
    r"<learning(?P<attrs>[^>]*)>(?P<body>.*?)</learning>",
    re.DOTALL | re.IGNORECASE,
)
LEARNING_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# Default LLM endpoint — shared Bifrost at host.docker.internal:4445 (post 2026-05-14)
_DEFAULT_LITELLM_URL = "http://host.docker.internal:4445/v1"
_DEFAULT_RUNNER_MODEL = "vllm-local/qwen3-chat"  # reasoning-off via Bifrost
_DEFAULT_RUNNER_TIMEOUT = 600.0  # 10 min hard ceiling

# llama.cpp serves Qwen3.6-35B with --ctx-size 16384 and --parallel 2, giving
# 8192 tokens per concurrent slot. Input+output must fit. Budget split:
#  - ~150 tokens system boilerplate
#  - <skill content> at ~1 token / 4 chars
#  - ~100 tokens user message
#  - max_tokens output below
# Total: 150 + (24000/4 ≈ 6000) + 100 + 1800 = ~8050 — fits in slot.
SKILL_CONTENT_CHAR_CAP = 24000   # ~6000 tokens — covers most skills in full
RUNNER_MAX_OUTPUT_TOKENS = 1800  # leaves ~350 token cushion within 8192 slot


class LoopRunnerService:
    """Dispatch one loop to its runner. P1: claude_skill + http live."""

    def __init__(self) -> None:
        self._registry = get_loop_registry()
        self._vault = get_vault_writer()
        self._sink = get_loop_sink()
        self._litellm_base = (
            os.environ.get("ZERO_VLLM_CHAT_URL")
            or os.environ.get("ZERO_LITELLM_URL")
            or _DEFAULT_LITELLM_URL
        ).rstrip("/")
        self._litellm_key = (
            os.environ.get("ZERO_VLLM_API_KEY")
            or os.environ.get("LITELLM_MASTER_KEY")
            or "EMPTY"
        )
        self._runner_model = os.environ.get("ZERO_LOOP_RUNNER_MODEL", _DEFAULT_RUNNER_MODEL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_due(self, *, max_runs: int = 5) -> list[dict[str, Any]]:
        """Pick the next-due enabled loops and dispatch them serially.

        IMPORTANT: opencode loops are handled by the external NSSM daemon —
        the daemon polls /api/loops/queue?runner=opencode separately. We must
        NOT dispatch them in-process, otherwise every tick double-dispatches
        and orphans `running` rows.
        """
        due = await self._registry.next_due_loops(within_seconds=300, limit=max_runs)
        results: list[dict[str, Any]] = []
        for loop in due:
            if loop.get("runner_kind") == "opencode":
                # Skip — daemon owns this dispatch path. Reschedule so the
                # loop doesn't reappear in /queue immediately for the daemon
                # before the daemon's next 60s poll consumes it.
                continue
            try:
                result = await self.dispatch(loop)
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "loop.dispatch_failed",
                    loop_id=loop["id"],
                    name=loop["name"],
                    error=str(exc),
                )
                results.append({"loop_id": loop["id"], "status": "failure", "error": str(exc)})
        return results

    async def dispatch_background(self, loop: dict[str, Any]) -> dict[str, Any]:
        """Start a dispatch and return immediately with the run_id.

        Used by `/api/loops/{id}/trigger` and team fan-out from Legion: the
        run can take minutes (claude_skill calls LiteLLM serially), so the
        HTTP caller mustn't block on it. We mark the run started here so the
        caller has an id to track, then schedule the rest as a background
        task. Status updates are visible via `GET /api/loops/runs/{run_id}`.
        """
        kind = loop["runner_kind"]
        run_id = await self._registry.mark_run_started(
            loop["id"],
            runner_kind=kind,
            runner_id=os.environ.get("LOOP_RUNNER_ID", "zero-inproc"),
        )
        loop_with_run = {**loop, "run_id": run_id}

        async def _bg():
            try:
                if kind == "claude_skill":
                    await self._run_claude_skill(loop_with_run)
                elif kind == "opencode":
                    await self._run_opencode(loop_with_run)
                elif kind == "http":
                    await self._run_http(loop_with_run)
                elif kind == "prompt_variant":
                    await self._run_prompt_variant(loop_with_run)
                else:
                    await self._registry.mark_run_completed(
                        run_id, status="failure", error=f"unknown runner_kind: {kind}"
                    )
                    await self._registry.reschedule(loop["id"])
            except Exception as exc:  # noqa: BLE001
                logger.error("loop.bg_dispatch_failed", loop_id=loop["id"], run_id=run_id, error=str(exc))
                try:
                    await self._registry.mark_run_completed(run_id, status="failure", error=str(exc))
                    await self._registry.reschedule(loop["id"])
                except Exception:
                    pass

        asyncio.create_task(_bg())
        return {"loop_id": loop["id"], "run_id": run_id, "status": "dispatched"}

    async def dispatch(self, loop: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one loop to its registered runner kind."""
        kind = loop["runner_kind"]

        # Sandbox safety gate — code-editing loops require explicit operator opt-in.
        if loop.get("sandbox_required"):
            sandbox_url = os.environ.get("ZERO_LOOP_SANDBOX_URL")
            ack = os.environ.get("ZERO_LOOP_SANDBOX_OK", "false").lower() in {"1", "true", "yes"}
            if not sandbox_url and not ack:
                fail_run = await self._registry.mark_run_started(
                    loop["id"], runner_kind=kind, runner_id="sandbox-gate",
                )
                await self._registry.mark_run_completed(
                    fail_run,
                    status="failure",
                    error=(
                        "loop has sandbox_required=true but no sandbox is wired in. "
                        "Set ZERO_LOOP_SANDBOX_URL=<legion sandbox endpoint> OR "
                        "ZERO_LOOP_SANDBOX_OK=true to acknowledge running unsandboxed."
                    ),
                )
                await self._registry.reschedule(loop["id"])
                return {"loop_id": loop["id"], "run_id": fail_run, "status": "blocked"}

        run_id = await self._registry.mark_run_started(
            loop["id"],
            runner_kind=kind,
            runner_id=os.environ.get("LOOP_RUNNER_ID", "zero-inproc"),
        )
        loop_with_run = {**loop, "run_id": run_id}

        if kind == "claude_skill":
            return await self._run_claude_skill(loop_with_run)
        if kind == "opencode":
            return await self._run_opencode(loop_with_run)
        if kind == "http":
            return await self._run_http(loop_with_run)
        if kind == "prompt_variant":
            return await self._run_prompt_variant(loop_with_run)

        await self._registry.mark_run_completed(
            run_id, status="failure", error=f"unknown runner_kind: {kind}"
        )
        await self._registry.reschedule(loop["id"])
        return {"loop_id": loop["id"], "run_id": run_id, "status": "failure"}

    # ------------------------------------------------------------------
    # claude_skill runner — reads SKILL.md, runs against local Qwen
    # ------------------------------------------------------------------

    async def _run_claude_skill(self, loop: dict[str, Any]) -> dict[str, Any]:
        run_id = loop["run_id"]
        target = loop["runner_target"]
        started_at = datetime.now(timezone.utc)

        # 1. Read the skill markdown
        try:
            skill_md = self._read_skill_markdown(target)
        except FileNotFoundError as exc:
            await self._registry.mark_run_completed(
                run_id, status="failure", error=f"skill not found: {exc}"
            )
            await self._registry.reschedule(loop["id"])
            return {"loop_id": loop["id"], "run_id": run_id, "status": "failure"}

        # 2. Build the prompt — SKILL.md goes in as the system message,
        #    a brief user message asks the model to perform the skill's purpose.
        system_prompt = (
            "You are an autonomous diagnostic and improvement agent running inside a "
            "24/7 cross-project self-improvement loop. The user is not present. "
            "The skill specification below describes the audit/check you must perform. "
            "Follow it as written. Output a markdown report. "
            "End with a short ## Self-Learn section if you discover a generalizable insight; "
            "wrap any cross-project learning in <learning kind=\"best_practice\" confidence=\"0.X\">"
            "summary line\\ndetail markdown</learning> tags so the framework can fan it out.\n\n"
            "=== SKILL SPECIFICATION ===\n"
            f"{skill_md}\n"
            "=== END SKILL SPECIFICATION ==="
        )
        user_msg = (
            f"Run loop `{loop['name']}` (owner: {loop['owner_project']}, run_id: {run_id}). "
            f"Time: {started_at.isoformat()}. Be concise — the framework will judge your output by "
            "how concretely actionable it is, not by length."
        )

        # 3. Call LiteLLM
        token_estimate = 0
        output_text = ""
        error_text: Optional[str] = None
        status = "failure"
        try:
            output_text, token_estimate = await self._call_litellm(
                system=system_prompt,
                user=user_msg,
                timeout_s=min(loop.get("wall_clock_budget_s") or _DEFAULT_RUNNER_TIMEOUT, _DEFAULT_RUNNER_TIMEOUT),
            )
            status = "success"
        except asyncio.TimeoutError:
            error_text = f"runner timeout after {loop.get('wall_clock_budget_s', _DEFAULT_RUNNER_TIMEOUT)}s"
            status = "timeout"
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"
            status = "failure"

        # 4. Vault mirror — durable visibility regardless of DB state
        ended_at = datetime.now(timezone.utc)
        duration_s = (ended_at - started_at).total_seconds()
        vault_relative: Optional[str] = None
        if self._vault.available():
            try:
                result = self._vault.write_loop_run(
                    loop_name=loop["name"],
                    run_id=run_id,
                    owner_project=loop["owner_project"],
                    runner_kind=loop["runner_kind"],
                    status=status,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_s=duration_s,
                    cost_tokens=token_estimate,
                    output=output_text,
                    error=error_text,
                )
                vault_relative = result.get("relative")
                self._vault.write_loop_index_entry(
                    loop_name=loop["name"],
                    run_id=run_id,
                    status=status,
                    judge_score=None,
                    started_at=started_at,
                    relative_path=vault_relative or "",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("loop.vault_write_failed", run_id=run_id, error=str(exc))

        # 5. Persist learnings (P3's crosspoll service consumes these)
        learnings = self.parse_learning_blocks(output_text)

        # 6. Push to Legion (or buffer if Legion is down)
        legion_run_id = await self._push_to_legion(
            loop=loop,
            run_id=run_id,
            status=status,
            duration_s=duration_s,
            judge_score=None,  # judge runs separately on a later tick
            vault_path=vault_relative,
            cost_tokens=token_estimate,
            extra_payload={"learnings_extracted": len(learnings), "model": self._runner_model},
        )

        # 7. Finalize the run row
        await self._registry.mark_run_completed(
            run_id,
            status=status,
            vault_path=vault_relative,
            cost_tokens=token_estimate,
            output=output_text[:50000] if output_text else None,
            error=error_text,
            legion_run_id=legion_run_id,
            run_metadata={
                "learnings_extracted": len(learnings),
                "model": self._runner_model,
            },
        )
        if learnings:
            await self._persist_learnings(run_id, loop["owner_project"], learnings)

        await self._registry.reschedule(loop["id"])
        logger.info(
            "loop.run_completed",
            loop_id=loop["id"],
            run_id=run_id,
            name=loop["name"],
            status=status,
            duration_s=round(duration_s, 1),
            tokens=token_estimate,
            learnings=len(learnings),
        )
        return {
            "loop_id": loop["id"],
            "run_id": run_id,
            "status": status,
            "duration_s": duration_s,
            "vault_path": vault_relative,
            "learnings": len(learnings),
        }

    # ------------------------------------------------------------------
    # http runner — POST to a project endpoint
    # ------------------------------------------------------------------

    async def _run_http(self, loop: dict[str, Any]) -> dict[str, Any]:
        """POST {loop_id, run_id, name} to the project endpoint and await response.

        The project endpoint runs the skill in its own process and returns
        {status, output, judge_score?, learnings?}. P1 implementation.
        """
        run_id = loop["run_id"]
        target = loop["runner_target"]
        started_at = datetime.now(timezone.utc)
        status = "failure"
        output_text = ""
        judge_score: Optional[float] = None
        error_text: Optional[str] = None

        try:
            timeout_s = min(loop.get("wall_clock_budget_s") or 600, 600)
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
                resp = await client.post(
                    target,
                    json={
                        "loop_id": loop["id"],
                        "run_id": run_id,
                        "name": loop["name"],
                        "owner_project": loop["owner_project"],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "success")
                output_text = data.get("output", "")
                judge_score = data.get("judge_score")
        except httpx.TimeoutException:
            status = "timeout"
            error_text = f"http timeout calling {target}"
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"

        ended_at = datetime.now(timezone.utc)
        duration_s = (ended_at - started_at).total_seconds()
        vault_relative: Optional[str] = None
        if self._vault.available():
            try:
                result = self._vault.write_loop_run(
                    loop_name=loop["name"],
                    run_id=run_id,
                    owner_project=loop["owner_project"],
                    runner_kind=loop["runner_kind"],
                    status=status,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_s=duration_s,
                    judge_score=judge_score,
                    output=output_text,
                    error=error_text,
                )
                vault_relative = result.get("relative")
            except Exception as exc:  # noqa: BLE001
                logger.warning("loop.vault_write_failed", run_id=run_id, error=str(exc))

        learnings = self.parse_learning_blocks(output_text)
        legion_run_id = await self._push_to_legion(
            loop=loop,
            run_id=run_id,
            status=status,
            duration_s=duration_s,
            judge_score=judge_score,
            vault_path=vault_relative,
            cost_tokens=None,
            extra_payload={"learnings_extracted": len(learnings)},
        )
        await self._registry.mark_run_completed(
            run_id,
            status=status,
            judge_score=judge_score,
            vault_path=vault_relative,
            output=output_text[:50000] if output_text else None,
            error=error_text,
            legion_run_id=legion_run_id,
            run_metadata={"learnings_extracted": len(learnings)},
        )
        if learnings:
            await self._persist_learnings(run_id, loop["owner_project"], learnings)
        await self._registry.reschedule(loop["id"])
        return {"loop_id": loop["id"], "run_id": run_id, "status": status}

    # ------------------------------------------------------------------
    # opencode runner — work-queue model, daemon polls externally
    # ------------------------------------------------------------------

    async def _run_opencode(self, loop: dict[str, Any]) -> dict[str, Any]:
        """OpenCode runs externally — leave the run row in `running` state for
        the OpenCode daemon to complete via /api/loops/runs/{id}/complete.

        Critically: reschedule so the loop doesn't reappear in /queue on
        every 5-min tick — that would stack phantom `running` rows that get
        reaped only after 1h. The daemon polls /queue every 60s, so the
        normal cadence is: scheduler tick → reschedule → daemon poll →
        daemon completes the existing `running` row by run_id.
        """
        run_id = loop["run_id"]
        await self._registry.reschedule(loop["id"])
        logger.info("loop.queued_for_opencode", loop_id=loop["id"], run_id=run_id)
        return {"loop_id": loop["id"], "run_id": run_id, "status": "queued"}

    # ------------------------------------------------------------------
    # prompt_variant runner — A/B test prompt variants against local Qwen
    # ------------------------------------------------------------------

    async def _run_prompt_variant(self, loop: dict[str, Any]) -> dict[str, Any]:
        """Pick a variant (active 95% / canary 5%) and run it as the system prompt.

        The variant payload IS the prompt — typically a modified skill markdown.
        Variant tracking (runs_count, successes, total_score) is updated atomically
        so the promotion service can decide canary -> active.
        """
        from app.db.models import LoopVariantModel
        from app.infrastructure.database import get_session

        run_id = loop["run_id"]
        started_at = datetime.now(timezone.utc)

        # 1. Pick variant with weighted random over (active, canaries).
        chosen_variant = await self._pick_variant(loop["id"])
        if chosen_variant is None:
            await self._registry.mark_run_completed(
                run_id, status="failure",
                error="no active variant — seed one first via POST /api/loops/{id}/variants",
            )
            await self._registry.reschedule(loop["id"])
            return {"loop_id": loop["id"], "run_id": run_id, "status": "failure"}

        # Update the run row to point at the chosen variant
        async with get_session() as session:
            from app.db.models import LoopRunModel
            await session.execute(
                __import__("sqlalchemy").update(LoopRunModel)
                .where(LoopRunModel.id == run_id)
                .values(variant_id=chosen_variant["id"])
            )
            await session.commit()

        # 2. Build prompt from variant payload
        system_prompt = chosen_variant["payload"]
        user_msg = (
            f"Execute the prompt above as a 24/7 autonomous loop. "
            f"Loop: {loop['name']} (variant: {chosen_variant['variant_label']}, run: {run_id}). "
            f"Time: {started_at.isoformat()}. Be concrete and actionable."
        )

        # 3. Call LLM
        token_estimate = 0
        output_text = ""
        error_text: Optional[str] = None
        status = "failure"
        try:
            output_text, token_estimate = await self._call_litellm(
                system=system_prompt,
                user=user_msg,
                timeout_s=min(loop.get("wall_clock_budget_s") or _DEFAULT_RUNNER_TIMEOUT, _DEFAULT_RUNNER_TIMEOUT),
            )
            status = "success"
        except asyncio.TimeoutError:
            error_text = "runner timeout"
            status = "timeout"
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"

        ended_at = datetime.now(timezone.utc)
        duration_s = (ended_at - started_at).total_seconds()

        # 4. Vault mirror
        vault_relative: Optional[str] = None
        if self._vault.available():
            try:
                result = self._vault.write_loop_run(
                    loop_name=loop["name"],
                    run_id=run_id,
                    owner_project=loop["owner_project"],
                    runner_kind=loop["runner_kind"],
                    status=status,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_s=duration_s,
                    cost_tokens=token_estimate,
                    variant_label=chosen_variant["variant_label"],
                    output=output_text,
                    error=error_text,
                )
                vault_relative = result.get("relative")
            except Exception as exc:  # noqa: BLE001
                logger.warning("loop.vault_write_failed", run_id=run_id, error=str(exc))

        learnings = self.parse_learning_blocks(output_text)

        # 5. Update variant counters (so the promotion service can compare).
        async with get_session() as session:
            from sqlalchemy import update as sa_update
            from app.db.models import LoopVariantModel as LVM
            increments = {
                "runs_count": LVM.runs_count + 1,
            }
            if status == "success":
                increments["successes"] = LVM.successes + 1
            await session.execute(
                sa_update(LVM).where(LVM.id == chosen_variant["id"]).values(**increments)
            )
            await session.commit()

        # 6. Push to Legion
        legion_run_id = await self._push_to_legion(
            loop=loop,
            run_id=run_id,
            status=status,
            duration_s=duration_s,
            judge_score=None,
            vault_path=vault_relative,
            cost_tokens=token_estimate,
            variant_label=chosen_variant["variant_label"],
            extra_payload={"learnings_extracted": len(learnings), "model": self._runner_model},
        )

        # 7. Finalize run row
        await self._registry.mark_run_completed(
            run_id,
            status=status,
            vault_path=vault_relative,
            cost_tokens=token_estimate,
            output=output_text[:50000] if output_text else None,
            error=error_text,
            legion_run_id=legion_run_id,
            run_metadata={
                "variant_id": chosen_variant["id"],
                "variant_label": chosen_variant["variant_label"],
                "is_canary": chosen_variant["is_canary"],
                "learnings_extracted": len(learnings),
                "model": self._runner_model,
            },
        )
        if learnings:
            await self._persist_learnings(run_id, loop["owner_project"], learnings)
        await self._registry.reschedule(loop["id"])
        return {
            "loop_id": loop["id"],
            "run_id": run_id,
            "status": status,
            "duration_s": duration_s,
            "variant_label": chosen_variant["variant_label"],
            "is_canary": chosen_variant["is_canary"],
        }

    async def _pick_variant(self, loop_id: int) -> Optional[dict[str, Any]]:
        """Weighted-random pick over active (95%) + canaries (canary_traffic_pct each)."""
        import random
        from app.db.models import LoopVariantModel
        from app.infrastructure.database import get_session
        from sqlalchemy import select as sa_select

        async with get_session() as session:
            stmt = (
                sa_select(LoopVariantModel)
                .where(LoopVariantModel.loop_id == loop_id)
                .where(LoopVariantModel.retired_at.is_(None))
            )
            variants = (await session.execute(stmt)).scalars().all()

        if not variants:
            return None

        # Build weights
        weights: list[tuple[Any, float]] = []
        canary_total = sum(v.canary_traffic_pct for v in variants if v.is_canary)
        for v in variants:
            if v.is_active and not v.is_canary:
                weights.append((v, max(0.0, 100.0 - canary_total)))
            elif v.is_canary:
                weights.append((v, float(v.canary_traffic_pct)))
            else:
                weights.append((v, 0.0))

        total_weight = sum(w for _, w in weights)
        if total_weight <= 0:
            chosen = variants[0]
        else:
            roll = random.uniform(0.0, total_weight)
            chosen = variants[0]
            cum = 0.0
            for v, w in weights:
                cum += w
                if roll <= cum:
                    chosen = v
                    break

        return {
            "id": chosen.id,
            "variant_label": chosen.variant_label,
            "payload": chosen.payload,
            "is_canary": chosen.is_canary,
            "is_active": chosen.is_active,
        }

    # ------------------------------------------------------------------
    # Legion mirror push (durable system of record)
    # ------------------------------------------------------------------

    async def _push_to_legion(
        self,
        *,
        loop: dict[str, Any],
        run_id: int,
        status: str,
        duration_s: Optional[float],
        judge_score: Optional[float],
        vault_path: Optional[str],
        cost_tokens: Optional[int],
        variant_label: Optional[str] = None,
        extra_payload: Optional[dict[str, Any]] = None,
    ) -> Optional[int]:
        envelope = {
            "zero_run_id": run_id,
            "loop_name": loop["name"],
            "owner_project": loop["owner_project"],
            "variant_label": variant_label,
            "status": status,
            "judge_score": judge_score,
            "duration_s": duration_s,
            "vault_path": vault_path,
            "cost_tokens": cost_tokens,
            "payload": {
                "runner_kind": loop["runner_kind"],
                "runner_target": loop["runner_target"],
                **(extra_payload or {}),
            },
        }
        result = await self._sink.push(envelope)
        legion_run_id = result.get("legion_run_id") if result.get("status") == "ok" else None
        if result.get("status") == "buffered":
            logger.info("loop.run_buffered_for_legion", run_id=run_id)

        # Fire-and-forget run-event to Legion's skills registry so the denorm
        # stats (run_count, avg_score, last_*) stay fresh. Best-effort: a 503
        # or timeout here doesn't block the run completion. This fires
        # regardless of the mirror push outcome — the run-event endpoint is
        # idempotent on (skill_name, run_id) and updates a different table
        # from the mirror, so they are independent durability concerns.
        skill_name = loop.get("skill_name") or loop["name"]
        if skill_name:
            try:
                learnings_count = (extra_payload or {}).get("learnings_extracted")
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    await client.post(
                        f"{self._sink._base}/api/skills/run-event",
                        json={
                            "skill_name": skill_name,
                            "run_id": run_id,
                            "status": status,
                            "judge_score": judge_score,
                            "cost_tokens": cost_tokens,
                            "learnings_count": learnings_count or 0,
                            "vault_path": vault_path,
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("loop.skill_run_event_failed", error=str(exc), skill_name=skill_name)

        return legion_run_id

    # ------------------------------------------------------------------
    # LLM call (LiteLLM, qwen3-chat, no streaming)
    # ------------------------------------------------------------------

    async def _call_litellm(
        self,
        *,
        system: str,
        user: str,
        timeout_s: float = _DEFAULT_RUNNER_TIMEOUT,
        model: Optional[str] = None,
    ) -> tuple[str, int]:
        """Single non-streaming chat completion against LiteLLM.

        Returns (output_text, token_estimate).
        """
        url = f"{self._litellm_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._litellm_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self._runner_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "max_tokens": RUNNER_MAX_OUTPUT_TOKENS,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return "", 0
        msg = choices[0].get("message", {})
        # Some Qwen3 variants and providers (Kimi K2.6) put the visible reply
        # in `reasoning_content` when thinking-mode leaks through. Concatenate
        # so we don't silently lose the output.
        text = msg.get("content") or ""
        if not text.strip():
            text = msg.get("reasoning_content") or ""
        usage = data.get("usage") or {}
        total_tokens = int(usage.get("total_tokens") or 0)
        return text, total_tokens

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_skill_markdown(self, target: str) -> str:
        """Resolve and read a skill markdown file.

        Project mounts:
          /projects/zero/.agents/skills/<name>/SKILL.md
          /projects/legion/.claude/skills/<name>/SKILL.md
          /projects/ada/.claude/skills/<name>/SKILL.md
          /projects/llmrouter/.claude/skills/<name>/SKILL.md
          /skills/<name>/SKILL.md (global ~/.claude/skills)
        """
        path = Path(target)
        if not path.exists():
            raise FileNotFoundError(target)
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        # Strip lone UTF-8 BOM if utf-8-sig didn't catch a mid-file one,
        # plus other invisible characters that occasionally break LiteLLM
        # request validation.
        content = content.lstrip("﻿")
        # Cap at slot-safe size so input + output fits the per-slot budget.
        if len(content) > SKILL_CONTENT_CHAR_CAP:
            content = content[:SKILL_CONTENT_CHAR_CAP] + "\n\n[…skill truncated for context window]"
        return content

    async def _persist_learnings(
        self,
        run_id: int,
        source_project: str,
        learnings: list[dict[str, Any]],
    ) -> None:
        """Write extracted learnings into loop_learnings."""
        from app.db.models import LoopLearningModel  # local import: avoid models cycle on cold start
        from app.infrastructure.database import get_session

        async with get_session() as session:
            for item in learnings:
                row = LoopLearningModel(
                    source_run_id=run_id,
                    source_project=source_project,
                    pattern_kind=item["kind"],
                    summary=item["summary"],
                    detail=item["detail"],
                    confidence=item["confidence"],
                    applied_to=[],
                )
                session.add(row)
            await session.commit()
        logger.info("loop.learnings_persisted", run_id=run_id, count=len(learnings))

    # ------------------------------------------------------------------
    # Output parsing — shared by all runners
    # ------------------------------------------------------------------

    @staticmethod
    def parse_learning_blocks(output: str) -> list[dict[str, Any]]:
        """Extract <learning kind="..." confidence="..."> blocks from skill output."""
        blocks: list[dict[str, Any]] = []
        for match in LEARNING_BLOCK_RE.finditer(output or ""):
            attrs = dict(LEARNING_ATTR_RE.findall(match.group("attrs") or ""))
            body = (match.group("body") or "").strip()
            if not body:
                continue
            summary, _, detail = body.partition("\n")
            raw_conf = attrs.get("confidence", "0.5")
            try:
                conf = float(raw_conf)
            except ValueError:
                logger.warning("loop.learning_confidence_invalid", raw=raw_conf)
                conf = 0.5
            blocks.append({
                "kind": (attrs.get("kind") or "best_practice").lower(),
                "confidence": max(0.0, min(1.0, conf)),
                "summary": summary.strip()[:500] or "(no summary)",
                "detail": (detail.strip() or summary.strip())[:8000],
            })
        return blocks


@lru_cache(maxsize=1)
def get_loop_runner() -> LoopRunnerService:
    return LoopRunnerService()
