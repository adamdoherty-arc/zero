"""F-40 — surface meeting-spawned tasks that are still open.

``meeting_followup_service`` tags every task it creates with
``meeting_followup`` and ``meeting:<id>``. This service queries those
tasks (status != done) so the prep brief, dashboard tile, and system-
status page can show "still open from prior meetings".

Read-only. Tasks are owned by ``task_service``; we just project them.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog
from sqlalchemy import select, or_

from app.infrastructure.database import get_session
from app.db.models import TaskModel  # type: ignore

logger = structlog.get_logger(__name__)


class MeetingOpenActionsService:
    async def list_open(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """All meeting-spawned tasks not yet completed."""
        async with get_session() as db:
            stmt = (
                select(TaskModel)
                .where(or_(TaskModel.tags.contains(["meeting_followup"]),
                           TaskModel.source_reference.like("meeting:%")))
                .where(TaskModel.status != "DONE")
                .order_by(TaskModel.created_at.desc())
                .limit(limit)
            )
            try:
                rows = (await db.execute(stmt)).scalars().all()
            except Exception:
                # tags column might be JSONB without contains — fall back to source_reference only
                rows = (
                    await db.execute(
                        select(TaskModel)
                        .where(TaskModel.source_reference.like("meeting:%"))
                        .where(TaskModel.status != "DONE")
                        .order_by(TaskModel.created_at.desc())
                        .limit(limit)
                    )
                ).scalars().all()
        return [self._serialize(r) for r in rows]

    async def open_for_attendees(
        self, *, attendees: list[str], limit: int = 5
    ) -> list[dict[str, Any]]:
        """Subset of open tasks whose owner tag matches any attendee email
        (best-effort substring match)."""
        all_open = await self.list_open(limit=100)
        if not attendees:
            return all_open[:limit]
        emails = [a.lower() for a in attendees if a]
        matched: list[dict[str, Any]] = []
        for t in all_open:
            tags = [str(x).lower() for x in (t.get("tags") or [])]
            owner_tag = next((tag for tag in tags if tag.startswith("owner:")), "")
            if not owner_tag:
                continue
            owner_hint = owner_tag.split(":", 1)[1].strip()
            if any(owner_hint and (e == owner_hint or e.startswith(owner_hint)) for e in emails):
                matched.append(t)
            if len(matched) >= limit:
                break
        return matched

    @staticmethod
    def _serialize(row: TaskModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "status": str(getattr(row, "status", "")) or "",
            "tags": list(getattr(row, "tags", None) or []),
            "source_reference": getattr(row, "source_reference", None),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "due_at": row.due_at.isoformat() if getattr(row, "due_at", None) else None,
        }


@lru_cache()
def get_meeting_open_actions_service() -> MeetingOpenActionsService:
    return MeetingOpenActionsService()
