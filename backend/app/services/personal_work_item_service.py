"""Personal work-item service.

Mirrors `company_work_item_service` but scoped to `project_id = "personal"`.
Intentionally lean: no high-risk pattern matching, no auto-approval gates, no
LLM completion reviews. The `tasks.domain` column is repurposed as a *topic*
(e.g., "VA Disability", "Health", "Finance") so the UI can isolate one topic
at a time and hide the rest.

Uses the same `tasks` table and the same `company_task_events` audit log; only
the project_id filter differs. That means no new migration is required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select, text

from app.db.models import CompanyTaskEventModel, TaskModel
from app.infrastructure.database import get_session
from app.models.task import CompanyTaskEvent, Task, TaskCreate, TaskStatus, TaskUpdate
from app.services.task_service import get_task_service


PERSONAL_PROJECT_ID = "personal"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _task_dump(task: Optional[Task]) -> dict[str, Any]:
    return task.model_dump(mode="json") if task else {}


async def ensure_personal_project_indexes() -> None:
    """Idempotently create indexes that speed up personal-board queries.

    Reuses the same columns as the company board; only the project_id filter
    differs. Safe to call repeatedly.
    """
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_tasks_personal_status_sort ON tasks (project_id, status, sort_order) WHERE project_id = 'personal'",
        "CREATE INDEX IF NOT EXISTS idx_tasks_personal_domain ON tasks (project_id, domain) WHERE project_id = 'personal'",
    ]
    async with get_session() as session:
        for statement in statements:
            await session.execute(text(statement))


class PersonalWorkItemService:
    """Personal-scope task operations. Topic == domain."""

    async def list_work_items(
        self,
        *,
        status: Optional[str] = None,
        topic: Optional[str] = None,
        priority: Optional[str] = None,
        search: Optional[str] = None,
        filter_name: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 500,
    ) -> list[Task]:
        async with get_session() as session:
            query = select(TaskModel).where(TaskModel.project_id == PERSONAL_PROJECT_ID)

            if status:
                query = query.where(TaskModel.status == status)
            elif not include_archived and filter_name != "archived":
                query = query.where(TaskModel.status != TaskStatus.ARCHIVED.value)

            if topic:
                # `list_topics` coalesces NULL domain to "General" so the dropdown
                # shows a single bucket. Mirror that here so filtering by "General"
                # also matches rows whose domain was never set.
                if topic.lower() == "general":
                    query = query.where(
                        or_(TaskModel.domain.is_(None), func.lower(TaskModel.domain) == "general")
                    )
                else:
                    query = query.where(func.lower(TaskModel.domain) == topic.lower())
            if priority:
                query = query.where(TaskModel.priority == priority)
            if search:
                needle = f"%{search.strip()}%"
                query = query.where(or_(TaskModel.title.ilike(needle), TaskModel.description.ilike(needle)))

            if filter_name == "today":
                query = query.where(TaskModel.status.in_(["todo", "on_hold", "in_progress", "blocked"]))
            elif filter_name == "blocked":
                query = query.where(TaskModel.status == TaskStatus.BLOCKED.value)
            elif filter_name == "backlog":
                query = query.where(TaskModel.status == TaskStatus.BACKLOG.value)
            elif filter_name == "archived":
                query = query.where(TaskModel.status == TaskStatus.ARCHIVED.value)

            query = query.order_by(TaskModel.sort_order.asc(), TaskModel.created_at.desc()).limit(limit)
            rows = (await session.execute(query)).scalars().all()
        return [Task.model_validate(row, from_attributes=True) for row in rows]

    async def list_topics(self) -> list[dict[str, Any]]:
        """Return distinct topics on the personal board with counts.

        Used by the frontend topic selector. Sorted alphabetically; topics with
        any non-archived work bubble up first.
        """
        async with get_session() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            coalesce(domain, 'General') AS topic,
                            count(*) AS total,
                            count(*) FILTER (WHERE status NOT IN ('done','archived')) AS open,
                            count(*) FILTER (WHERE status = 'done') AS done
                        FROM tasks
                        WHERE project_id = :project_id
                          AND status != 'archived'
                        GROUP BY coalesce(domain, 'General')
                        ORDER BY open DESC, topic ASC
                        """
                    ),
                    {"project_id": PERSONAL_PROJECT_ID},
                )
            ).all()
        return [
            {"topic": row.topic, "total": row.total, "open": row.open, "done": row.done}
            for row in rows
        ]

    async def get_work_item(self, task_id: str) -> Optional[Task]:
        task = await get_task_service().get_task(task_id)
        if not task or task.project_id != PERSONAL_PROJECT_ID:
            return None
        return task

    async def create_work_item(self, data: TaskCreate, *, actor: str = "user") -> Task:
        # We bypass `task_service.create_task` because that path generates IDs via
        # `count(*) + 1`, which collides when there are gaps in the sequence
        # (deleted tasks leave the highest id ahead of the count). Personal tasks
        # use UUID-suffixed IDs so they never collide with the existing sequence
        # and don't perturb integer-counted task IDs elsewhere.
        task_id = f"ptask-{uuid.uuid4().hex[:12]}"
        now = _now()

        async with get_session() as session:
            row = TaskModel(
                id=task_id,
                sprint_id=data.sprint_id,
                project_id=PERSONAL_PROJECT_ID,
                title=data.title,
                description=data.description,
                status=TaskStatus.BACKLOG.value,
                category=data.category.value if hasattr(data.category, "value") else (data.category or "chore"),
                priority=data.priority.value if hasattr(data.priority, "value") else (data.priority or "medium"),
                points=data.points,
                source=data.source.value if hasattr(data.source, "value") else (data.source or "MANUAL"),
                source_reference=data.source_reference,
                blocked_reason=data.blocked_reason,
                domain=data.domain or "General",
                owner_agent=data.owner_agent or "self",
                due_at=data.due_at,
                scheduled_for=data.scheduled_for,
                risk_level=data.risk_level or "low",
                approval_state=data.approval_state or "none",
                approval_id=data.approval_id,
                tags=data.tags or [],
                links=data.links or [],
                sort_order=data.sort_order or 0,
                estimate_points=data.estimate_points,
                parent_task_id=data.parent_task_id,
                created_at=now,
            )
            session.add(row)
            await session.flush()
            created = Task.model_validate(row, from_attributes=True)

        await self.record_event(
            created.id, "created", actor=actor, summary=f"Created {created.title}", after=_task_dump(created)
        )
        return created

    async def update_work_item(
        self, task_id: str, updates: TaskUpdate, *, actor: str = "user"
    ) -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None
        before = _task_dump(existing)

        patch = updates
        if updates.status == TaskStatus.DONE and not existing.completed_at:
            patch = patch.model_copy(update={"completed_at": _now()})
        elif updates.status == TaskStatus.IN_PROGRESS and not existing.started_at:
            patch = patch.model_copy(update={"started_at": _now()})

        updated = await get_task_service().update_task(task_id, patch)
        if updated:
            await self.record_event(
                task_id, "updated", actor=actor, summary=f"Updated {updated.title}", before=before, after=_task_dump(updated)
            )
        return updated

    async def complete_work_item(
        self,
        task_id: str,
        *,
        actor: str = "user",
        completion_note: Optional[str] = None,
    ) -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None

        if completion_note:
            stamp = _now().isoformat()[:10]
            new_description = (
                f"{existing.description or ''}\n\n---\nCompletion note ({stamp}, by {actor}): {completion_note.strip()}"
            ).strip()
            await get_task_service().update_task(task_id, TaskUpdate(description=new_description))

        return await self.update_work_item(task_id, TaskUpdate(status=TaskStatus.DONE), actor=actor)

    async def reopen_work_item(self, task_id: str, *, actor: str = "user") -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None
        updated = await get_task_service().update_task(
            task_id,
            TaskUpdate(status=TaskStatus.IN_PROGRESS, blocked_reason=""),
        )
        if updated:
            await self.record_event(
                task_id, "reopened", actor=actor, summary=f"Reopened {updated.title}",
                before=_task_dump(existing), after=_task_dump(updated),
            )
        return updated

    async def delete_work_item(self, task_id: str, *, actor: str = "user") -> bool:
        existing = await self.get_work_item(task_id)
        if not existing:
            return False
        await self.record_event(
            task_id, "deleted", actor=actor, summary=f"Deleted {existing.title}", before=_task_dump(existing)
        )
        return await get_task_service().delete_task(task_id)

    async def events(self, task_id: str, *, limit: int = 200) -> list[CompanyTaskEvent]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyTaskEventModel)
                    .where(CompanyTaskEventModel.task_id == task_id)
                    .order_by(CompanyTaskEventModel.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        return [CompanyTaskEvent.model_validate(row, from_attributes=True) for row in rows]

    async def delete_event(self, task_id: str, event_id: str) -> bool:
        """Delete a single event (used for notes only — users can remove typos)."""
        async with get_session() as session:
            row = await session.get(CompanyTaskEventModel, event_id)
            if not row or row.task_id != task_id or row.event_type != "note":
                return False
            await session.delete(row)
            await session.flush()
            return True

    async def record_event(
        self,
        task_id: str,
        event_type: str,
        *,
        actor: str = "system",
        summary: Optional[str] = None,
        before: Optional[dict[str, Any]] = None,
        after: Optional[dict[str, Any]] = None,
    ) -> CompanyTaskEvent:
        async with get_session() as session:
            row = CompanyTaskEventModel(
                id=f"pte-{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                event_type=event_type,
                actor=actor,
                summary=summary,
                before=before or {},
                after=after or {},
            )
            session.add(row)
            await session.flush()
            return CompanyTaskEvent.model_validate(row, from_attributes=True)


_singleton: Optional[PersonalWorkItemService] = None


def get_personal_work_item_service() -> PersonalWorkItemService:
    global _singleton
    if _singleton is None:
        _singleton = PersonalWorkItemService()
    return _singleton
