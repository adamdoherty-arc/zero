"""Zero's progress check-in agent for ADA AI LLC.

Runs on a schedule. Scans live company tasks for stalled work, blocked tasks
without recent action, and overdue items. Produces a structured check-in
report Adam sees on the Overview dashboard and (optionally) hears in the
morning brief.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import desc, select

from app.db.models import CompanyTaskEventModel
from app.infrastructure.database import get_session
from app.models.task import Task, TaskStatus
from app.services.company_setup_progress_service import get_company_setup_progress_service
from app.services.company_work_item_service import COMPANY_PROJECT_ID, get_company_work_item_service


logger = logging.getLogger(__name__)


STALE_DAYS = 3
OVERDUE_GRACE_HOURS = 12


def _enum(value: Any) -> str:
    return getattr(value, "value", value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class CompanyProgressCheckinService:
    """Zero, your personal chief of staff, checking in on company tasks."""

    async def run_checkin(self, *, requested_by: str = "scheduler") -> dict[str, Any]:
        tasks = await get_company_work_item_service().list_work_items(limit=500)
        events_by_task = await self._latest_events(tasks)
        now = _now()

        stalled: list[dict[str, Any]] = []
        overdue: list[dict[str, Any]] = []
        moved_recently: list[dict[str, Any]] = []
        ready_to_close: list[dict[str, Any]] = []

        for task in tasks:
            if _enum(task.status) in {TaskStatus.DONE.value, TaskStatus.ARCHIVED.value}:
                continue

            last_event = events_by_task.get(task.id)
            last_active = _to_aware(last_event.created_at) if last_event else _to_aware(task.updated_at or task.created_at)
            stale_for_days = (now - last_active).days if last_active else 999

            due = _to_aware(task.due_at)
            if due and due < now - timedelta(hours=OVERDUE_GRACE_HOURS):
                overdue.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "domain": task.domain or "Operations",
                        "priority": _enum(task.priority),
                        "due_at": due.isoformat(),
                        "overdue_hours": int((now - due).total_seconds() / 3600),
                    }
                )
                continue

            if _enum(task.status) == TaskStatus.IN_PROGRESS.value and stale_for_days >= STALE_DAYS:
                stalled.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "domain": task.domain or "Operations",
                        "priority": _enum(task.priority),
                        "stalled_days": stale_for_days,
                        "last_event": last_event.event_type if last_event else "none",
                    }
                )
                continue

            if _enum(task.status) == TaskStatus.BLOCKED.value and stale_for_days >= STALE_DAYS:
                stalled.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "domain": task.domain or "Operations",
                        "priority": _enum(task.priority),
                        "stalled_days": stale_for_days,
                        "last_event": last_event.event_type if last_event else "none",
                        "blocked_reason": task.blocked_reason,
                    }
                )
                continue

            if last_event and last_active and (now - last_active) < timedelta(days=1):
                moved_recently.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "domain": task.domain or "Operations",
                        "status": _enum(task.status),
                        "event": last_event.event_type,
                    }
                )

            if _enum(task.status) == TaskStatus.IN_PROGRESS.value and stale_for_days <= 1 and task.priority and _enum(task.priority) in {"critical", "high"}:
                ready_to_close.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "domain": task.domain or "Operations",
                        "priority": _enum(task.priority),
                    }
                )

        progress = await get_company_setup_progress_service().progress()

        summary = self._summarize(progress, stalled, overdue, moved_recently)
        report = {
            "summary": summary,
            "computed_at": now.isoformat(),
            "requested_by": requested_by,
            "setup_percent": progress["percent"],
            "setup_done": progress["done"],
            "setup_total": progress["total"],
            "stalled_count": len(stalled),
            "overdue_count": len(overdue),
            "moved_recently_count": len(moved_recently),
            "stalled": stalled[:15],
            "overdue": overdue[:15],
            "moved_recently": moved_recently[:15],
            "ready_to_close": ready_to_close[:10],
            "next_unblocked": progress["next_unblocked"],
            "critical_blocked": progress["critical_blocked"],
        }

        logger.info(
            "company_progress_checkin_done stalled=%d overdue=%d setup_pct=%d",
            len(stalled),
            len(overdue),
            progress["percent"],
        )
        return report

    async def _latest_events(self, tasks: list[Task]) -> dict[str, CompanyTaskEventModel]:
        ids = [t.id for t in tasks]
        if not ids:
            return {}
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyTaskEventModel)
                    .where(CompanyTaskEventModel.task_id.in_(ids))
                    .order_by(desc(CompanyTaskEventModel.created_at))
                )
            ).scalars().all()
        latest: dict[str, CompanyTaskEventModel] = {}
        for row in rows:
            if row.task_id not in latest:
                latest[row.task_id] = row
        return latest

    @staticmethod
    def _summarize(
        progress: dict[str, Any],
        stalled: list[dict[str, Any]],
        overdue: list[dict[str, Any]],
        moved_recently: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = []
        parts.append(
            f"Company setup is {progress['percent']}% done "
            f"({progress['done']} of {progress['total']} launch-critical tasks complete)."
        )
        if overdue:
            parts.append(f"{len(overdue)} task(s) are overdue.")
        if stalled:
            parts.append(f"{len(stalled)} task(s) have not moved in {STALE_DAYS}+ days.")
        if moved_recently:
            parts.append(f"{len(moved_recently)} task(s) moved in the last 24 hours.")
        if not stalled and not overdue:
            parts.append("Nothing is stuck right now.")
        if progress.get("next_unblocked"):
            top = progress["next_unblocked"][0]
            parts.append(f"The single highest-leverage next task is: {top['title']} ({top['domain']}).")
        return " ".join(parts)


@lru_cache()
def get_company_progress_checkin_service() -> CompanyProgressCheckinService:
    return CompanyProgressCheckinService()
