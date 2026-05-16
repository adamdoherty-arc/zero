"""Post-completion LLM review for company tasks.

When Adam marks a company task complete, Zero asks an LLM to look at the task,
the related tasks, the company state, and answer:

1. Did Adam create all the follow-up tasks this completion unlocks? List the
   ones that are missing.
2. Does the command center need new infrastructure (a new dashboard tile, a
   scheduler job, a doc page, an automation rule) to manage what this task
   just unlocked?
3. Did the task actually complete the goal (a quick sanity check based on the
   review packet's acceptance criteria)?

The verdict is stored on the work-item review row so the dashboard can show it
and Adam can act on follow-ups.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import select

from app.db.models import CompanyWorkItemReviewModel, TaskModel
from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.models.task import (
    CompanyWorkItemReview,
    Task,
    TaskCategory,
    TaskCreate,
    TaskPriority,
    TaskSource,
)
from app.services.company_walkthroughs import walkthrough_for
from app.services.company_work_item_service import (
    COMPANY_PROJECT_ID,
    get_company_work_item_service,
    infer_domain,
)


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are Zero, ADA AI LLC's chief-of-staff agent. A company-setup task was just "
    "marked complete. Audit the completion and produce a structured JSON verdict. "
    "Be concrete, brief, and honest. If something is missing, say so. "
    "Do NOT recommend actions Zero is not allowed to take autonomously (filings, "
    "purchases, account changes, public/client communications, tax/legal decisions). "
    "Those can show up as follow-up tasks for Adam."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CompanyCompletionReviewService:
    """Runs LLM-driven post-completion audit on company work items."""

    async def review_completion(
        self,
        task_id: str,
        *,
        actor: str = "dashboard",
        auto_create_followups: bool = True,
    ) -> dict[str, Any]:
        task = await get_company_work_item_service().get_work_item(task_id)
        if task is None:
            return {"error": f"task {task_id} not found"}

        review_packet = await get_company_work_item_service().review(task_id)
        related_tasks = await self._related_tasks(task)
        walkthrough = (
            (review_packet.walkthrough if review_packet and review_packet.walkthrough else None)
            or walkthrough_for(task.title, task.description or "")
        )

        prompt = self._build_prompt(task, review_packet, related_tasks, walkthrough)
        verdict = await self._call_llm(prompt)
        verdict["reviewed_at"] = _now().isoformat()
        verdict["reviewed_by"] = actor

        await self._save_verdict(task_id, verdict)

        created_followups: list[dict[str, Any]] = []
        if auto_create_followups:
            created_followups = await self._create_followups(task, verdict)
        verdict["created_followups"] = created_followups

        await get_company_work_item_service().record_event(
            task_id,
            "completion_reviewed",
            actor=actor,
            summary=(
                f"Zero's completion review scored this task {verdict.get('quality_score', 'n/a')}/100; "
                f"{len(verdict.get('missing_followups') or [])} missing follow-ups, "
                f"{len(created_followups)} auto-created."
            ),
            after={
                "quality_score": verdict.get("quality_score"),
                "missing_followups": verdict.get("missing_followups"),
                "infrastructure_suggestions": verdict.get("infrastructure_suggestions"),
                "created_followups": created_followups,
            },
        )

        return verdict

    async def _related_tasks(self, task: Task) -> list[Task]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(TaskModel)
                    .where(TaskModel.project_id == COMPANY_PROJECT_ID)
                    .order_by(TaskModel.created_at.desc())
                    .limit(60)
                )
            ).scalars().all()
        return [Task.model_validate(row, from_attributes=True) for row in rows if row.id != task.id]

    def _build_prompt(
        self,
        task: Task,
        review_packet: Optional[CompanyWorkItemReview],
        related_tasks: list[Task],
        walkthrough: Optional[dict[str, Any]],
    ) -> str:
        unlocks = (walkthrough or {}).get("what_this_unlocks") or []
        acceptance = (review_packet.acceptance_criteria if review_packet else []) or []
        related_lines = "\n".join(
            f"- [{t.status.value if hasattr(t.status, 'value') else t.status}] {t.title} ({t.domain or 'Operations'})"
            for t in related_tasks[:40]
        ) or "  (no other live company tasks)"

        completion_outputs = task.completion_outputs or {}
        outputs = completion_outputs.get("outputs") or []
        outputs_lines: list[str] = []
        if outputs:
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                label = item.get("label") or item.get("key") or "?"
                value = "[REDACTED]" if item.get("sensitive") else str(item.get("value", ""))
                outputs_lines.append(f"- {label}: {value}")
        outputs_block = "\n".join(outputs_lines) or "  (no structured outputs captured)"
        completion_note = completion_outputs.get("note") or ""

        expected_fields = (walkthrough or {}).get("completion_fields") or []
        expected_keys = {field.get("key") for field in expected_fields if isinstance(field, dict)}
        captured_keys = {item.get("key") for item in outputs if isinstance(item, dict)}
        missing_keys = sorted(expected_keys - captured_keys)
        missing_block = (
            "\n".join(f"- {k}" for k in missing_keys) if missing_keys else "  (none)"
        )

        return (
            f"COMPLETED TASK\n"
            f"Title: {task.title}\n"
            f"Domain: {task.domain or 'Operations'}\n"
            f"Owner agent: {task.owner_agent or 'unknown'}\n"
            f"Description:\n{task.description or '(no description)'}\n\n"
            f"ACCEPTANCE CRITERIA THIS TASK SHOULD HAVE MET\n"
            + ("\n".join(f"- {item}" for item in acceptance) or "  (none recorded)")
            + "\n\n"
            f"WHAT COMPLETING THIS TASK UNLOCKS\n"
            + ("\n".join(f"- {item}" for item in unlocks) or "  (no curated unlocks)")
            + "\n\n"
            f"OUTPUTS ADAM RECORDED AT COMPLETION\n{outputs_block}\n\n"
            f"COMPLETION NOTE FROM ADAM\n{completion_note or '  (no note)'}\n\n"
            f"EXPECTED COMPLETION FIELDS NOT FILLED IN (walkthrough keys missing from outputs)\n{missing_block}\n\n"
            f"OTHER LIVE COMPANY TASKS\n{related_lines}\n\n"
            "Reduce quality_score below 60 if expected completion fields are missing or empty.\n"
            "Produce JSON only (no markdown fences), exactly this shape:\n"
            "{\n"
            '  "quality_score": int (0-100, how completely the acceptance criteria appear satisfied),\n'
            '  "summary": str (one or two sentences for Adam),\n'
            '  "looks_complete": bool,\n'
            '  "concerns": [str, ...],\n'
            '  "missing_followups": [\n'
            '    {"title": str, "why": str, "domain": str, "priority": "critical"|"high"|"medium"|"low"}\n'
            "  ],\n"
            '  "infrastructure_suggestions": [\n'
            '    {"surface": "dashboard tile"|"scheduler job"|"doc page"|"automation rule"|"approval gate"|"other", "name": str, "rationale": str}\n'
            "  ]\n"
            "}\n"
        )

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        client = get_unified_llm_client()
        try:
            raw = await client.chat(
                prompt,
                system=SYSTEM_PROMPT,
                task_type="company_review",
                temperature=0.2,
                max_tokens=1200,
            )
        except Exception as exc:
            logger.warning("company_completion_review_llm_failed: %s", exc)
            return self._fallback_verdict(reason=f"LLM call failed: {exc}")

        parsed = self._parse_json(raw)
        if not parsed:
            return self._fallback_verdict(reason="LLM returned non-JSON output.", raw=raw[:500])

        parsed.setdefault("quality_score", 0)
        parsed.setdefault("summary", "")
        parsed.setdefault("looks_complete", False)
        parsed.setdefault("concerns", [])
        parsed.setdefault("missing_followups", [])
        parsed.setdefault("infrastructure_suggestions", [])
        return parsed

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict[str, Any]]:
        if not raw:
            return None
        candidate = raw.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
            candidate = re.sub(r"\s*```$", "", candidate)
        try:
            value = json.loads(candidate)
        except Exception:
            match = re.search(r"\{.*\}", candidate, re.S)
            if not match:
                return None
            try:
                value = json.loads(match.group(0))
            except Exception:
                return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _fallback_verdict(*, reason: str, raw: str = "") -> dict[str, Any]:
        return {
            "quality_score": 50,
            "summary": f"Zero could not run the LLM completion review. {reason}",
            "looks_complete": True,
            "concerns": [reason] + ([f"raw: {raw}"] if raw else []),
            "missing_followups": [],
            "infrastructure_suggestions": [],
            "fallback": True,
        }

    async def _save_verdict(self, task_id: str, verdict: dict[str, Any]) -> None:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(CompanyWorkItemReviewModel)
                    .where(CompanyWorkItemReviewModel.task_id == task_id)
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                from uuid import uuid4
                row = CompanyWorkItemReviewModel(
                    id=f"cwr-{uuid4().hex[:12]}",
                    task_id=task_id,
                    score=verdict.get("quality_score") or 0,
                    recommendation="keep",
                )
                session.add(row)
            row.completion_review = verdict
            row.updated_at = _now()
            await session.flush()

    async def _create_followups(
        self, parent: Task, verdict: dict[str, Any]
    ) -> list[dict[str, Any]]:
        followups: list[dict[str, Any]] = []
        priority_map = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
        }
        existing = await get_company_work_item_service().list_work_items(limit=500)
        existing_titles = {t.title.strip().lower() for t in existing}

        for item in (verdict.get("missing_followups") or [])[:8]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title or title.lower() in existing_titles:
                continue
            domain = str(item.get("domain") or parent.domain or "Operations")
            domain = infer_domain(title, item.get("why"), fallback=domain)
            priority_key = str(item.get("priority") or "medium").lower()
            try:
                created = await get_company_work_item_service().create_work_item(
                    TaskCreate(
                        title=title,
                        description=(
                            f"({domain} Sprint) Follow-up created by Zero after completing parent task '{parent.title}'.\n\n"
                            f"Why this is needed: {item.get('why') or 'No reason provided.'}"
                        ),
                        category=TaskCategory.CHORE,
                        priority=priority_map.get(priority_key, TaskPriority.MEDIUM),
                        source=TaskSource.ENHANCEMENT_ENGINE,
                        source_reference=f"completion_review:{parent.id}",
                        domain=domain,
                        owner_agent=parent.owner_agent,
                        tags=["completion-followup", domain.lower().replace(" ", "-")],
                        parent_task_id=parent.id,
                    ),
                    actor="zero-completion-review",
                )
            except Exception as exc:
                logger.warning("completion_review_followup_failed: %s", exc)
                continue
            existing_titles.add(title.lower())
            followups.append({"id": created.id, "title": created.title, "domain": created.domain})
        return followups


@lru_cache()
def get_company_completion_review_service() -> CompanyCompletionReviewService:
    return CompanyCompletionReviewService()
