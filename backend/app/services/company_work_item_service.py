"""Company work-item service.

Zero's generic `tasks` table remains canonical. This service adds the
Company OS rules around those records: project scoping, richer filters,
seed-backlog import, task events, and approval-gated completion.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, or_, select, text

from app.db.models import CompanyTaskEventModel, CompanyWorkItemReviewModel, TaskModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.models.task import CompanyTaskEvent, CompanyWorkItemReview, Task, TaskCategory, TaskCreate, TaskPriority, TaskSource, TaskStatus, TaskUpdate
from app.services.approval_queue_service import get_approval_queue
from app.services.task_service import get_task_service


COMPANY_PROJECT_ID = "company"

HIGH_RISK_PATTERN = re.compile(
    r"\b("
    r"verify name on sunbiz|file florida llc|articles of organization|apply for ein|get ein|"
    r"choose registered agent|sign operating agreement|sign ip assignment|"
    r"open .*bank account|open .*credit card|apply for .*credit card|apply for .*business card|"
    r"get duval local business tax receipt|"
    r"asset transfer|equipment transfer|fair market value|fmv|robot purchase|robot transfer|software/ip|"
    r"schedule cpa|schedule attorney|hire cpa|hire attorney|set up business email|"
    r"configure dns|purchase domain|domain purchase|set up password vault|"
    r"publish|send .*proposal|client communication|public|linkedin|stripe account|"
    r"tax election|trademark filing|disclaimer"
    r")\b",
    re.I,
)
SQL_HIGH_RISK_PATTERN = (
    "verify name on sunbiz|file florida llc|articles of organization|apply for ein|get ein|"
    "choose registered agent|sign operating agreement|sign ip assignment|"
    "open .*bank account|open .*credit card|apply for .*credit card|apply for .*business card|"
    "get duval local business tax receipt|"
    "asset transfer|equipment transfer|fair market value|fmv|robot purchase|robot transfer|software/ip|"
    "schedule cpa|schedule attorney|hire cpa|hire attorney|set up business email|"
    "configure dns|purchase domain|domain purchase|set up password vault|"
    "publish|send .*proposal|client communication|public|linkedin|stripe account|"
    "tax election|trademark filing|disclaimer"
)

DOMAIN_ALIASES = {
    "admin": "Operations",
    "agent": "Agents",
    "dashboard": "Dashboard",
    "finance": "Finance",
    "formation": "Formation",
    "consulting": "Consulting",
    "product": "Product",
    "robotics": "Robotics",
    "second-brain": "Knowledge",
    "second brain": "Knowledge",
    "marketing": "Marketing",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _compact(value: str, *, limit: int = 180) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _text(task: Task | TaskCreate | TaskUpdate) -> str:
    return f"{getattr(task, 'title', '') or ''}"


def classify_risk(task: Task | TaskCreate | TaskUpdate) -> str:
    return "high" if HIGH_RISK_PATTERN.search(_text(task)) else "medium"


def infer_domain(title: str, description: Optional[str] = None, fallback: Optional[str] = None) -> str:
    source = f"{title} {description or ''}"
    match = re.search(r"\(([^)]+?)\s+Sprint\)", source, re.I)
    if match:
        key = match.group(1).strip().lower()
        return DOMAIN_ALIASES.get(key, match.group(1).strip().title())
    if fallback:
        return DOMAIN_ALIASES.get(fallback.lower(), fallback.title())
    for key, label in DOMAIN_ALIASES.items():
        if re.search(rf"\b{re.escape(key)}\b", source, re.I):
            return label
    return "Operations"


def _task_dump(task: Optional[Task]) -> dict[str, Any]:
    if not task:
        return {}
    return task.model_dump(mode="json")


async def ensure_company_work_item_schema() -> None:
    """Idempotently add Company OS task fields for live create_tables installs.

    The local Zero stack has historically used `Base.metadata.create_all()` at
    startup, which creates missing tables but does not alter existing ones. This
    keeps upgraded dev databases from 500ing when the ORM gains new company
    task columns before Alembic has been applied.
    """
    statements = [
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS domain VARCHAR(80)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_agent VARCHAR(100)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS risk_level VARCHAR(20) NOT NULL DEFAULT 'medium'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approval_state VARCHAR(20) NOT NULL DEFAULT 'none'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approval_id VARCHAR(64)",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS links JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS estimate_points INTEGER",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id VARCHAR(64)",
        "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS lease_id VARCHAR(64)",
        "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ",
        "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ",
        """
        CREATE TABLE IF NOT EXISTS company_task_events (
            id VARCHAR(64) PRIMARY KEY,
            task_id VARCHAR(64) NOT NULL,
            event_type VARCHAR(60) NOT NULL,
            actor VARCHAR(100) NOT NULL DEFAULT 'system',
            summary TEXT,
            before JSONB DEFAULT '{}'::jsonb,
            after JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS company_work_item_reviews (
            id VARCHAR(64) PRIMARY KEY,
            task_id VARCHAR(64) NOT NULL UNIQUE,
            score INTEGER NOT NULL DEFAULT 0,
            recommendation VARCHAR(40) NOT NULL DEFAULT 'keep',
            summary TEXT,
            missing_info JSONB DEFAULT '[]'::jsonb,
            action_steps JSONB DEFAULT '[]'::jsonb,
            acceptance_criteria JSONB DEFAULT '[]'::jsonb,
            automation_plan JSONB DEFAULT '{}'::jsonb,
            source_links JSONB DEFAULT '[]'::jsonb,
            reviewed_by VARCHAR(100) NOT NULL DEFAULT 'zero-company-operator',
            operator_run_id VARCHAR(64),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS company_agent_questions (
            id VARCHAR(64) PRIMARY KEY,
            question TEXT NOT NULL,
            context JSONB DEFAULT '{}'::jsonb,
            answer_type VARCHAR(30) NOT NULL DEFAULT 'text',
            options JSONB DEFAULT '[]'::jsonb,
            priority VARCHAR(20) NOT NULL DEFAULT 'medium',
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            asked_by_agent VARCHAR(64) NOT NULL DEFAULT 'ceo',
            task_id VARCHAR(64),
            agent_task_id VARCHAR(64),
            operator_run_id VARCHAR(64),
            source VARCHAR(80) NOT NULL DEFAULT 'company_agent',
            answer TEXT,
            answered_by VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT now(),
            answered_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_tasks_domain ON tasks (domain)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_owner_agent ON tasks (owner_agent)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_due_at ON tasks (due_at)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_scheduled_for ON tasks (scheduled_for)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_risk_level ON tasks (risk_level)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_approval_state ON tasks (approval_state)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_approval_id ON tasks (approval_id)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_sort_order ON tasks (sort_order)",
        "CREATE INDEX IF NOT EXISTS ix_tasks_parent_task_id ON tasks (parent_task_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_status_sort ON tasks (project_id, status, sort_order)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_domain_status ON tasks (project_id, domain, status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_due ON tasks (project_id, due_at)",
        "CREATE INDEX IF NOT EXISTS ix_company_task_events_task_id ON company_task_events (task_id)",
        "CREATE INDEX IF NOT EXISTS ix_company_task_events_event_type ON company_task_events (event_type)",
        "CREATE INDEX IF NOT EXISTS ix_company_task_events_actor ON company_task_events (actor)",
        "CREATE INDEX IF NOT EXISTS ix_company_task_events_created_at ON company_task_events (created_at)",
        "CREATE INDEX IF NOT EXISTS idx_company_task_events_task_created ON company_task_events (task_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_company_work_item_reviews_task_id ON company_work_item_reviews (task_id)",
        "CREATE INDEX IF NOT EXISTS ix_company_work_item_reviews_score ON company_work_item_reviews (score)",
        "CREATE INDEX IF NOT EXISTS ix_company_work_item_reviews_recommendation ON company_work_item_reviews (recommendation)",
        "CREATE INDEX IF NOT EXISTS ix_company_work_item_reviews_reviewed_by ON company_work_item_reviews (reviewed_by)",
        "CREATE INDEX IF NOT EXISTS ix_company_work_item_reviews_operator_run_id ON company_work_item_reviews (operator_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_company_work_item_reviews_created_at ON company_work_item_reviews (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_lease_id ON agent_tasks (lease_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_lease_expires_at ON agent_tasks (lease_expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_tasks_lease_status ON agent_tasks (lease_expires_at, status)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_answer_type ON company_agent_questions (answer_type)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_priority ON company_agent_questions (priority)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_status ON company_agent_questions (status)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_asked_by_agent ON company_agent_questions (asked_by_agent)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_task_id ON company_agent_questions (task_id)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_agent_task_id ON company_agent_questions (agent_task_id)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_operator_run_id ON company_agent_questions (operator_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_source ON company_agent_questions (source)",
        "CREATE INDEX IF NOT EXISTS ix_company_agent_questions_created_at ON company_agent_questions (created_at)",
        "CREATE INDEX IF NOT EXISTS idx_company_agent_questions_status_created ON company_agent_questions (status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_company_agent_questions_task_status ON company_agent_questions (task_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_company_agent_questions_agent_status ON company_agent_questions (asked_by_agent, status)",
    ]
    async with get_session() as session:
        for statement in statements:
            await session.execute(text(statement))
        await session.execute(
            text(
                """
                UPDATE tasks
                SET domain = CASE
                    WHEN coalesce(description, '') ILIKE '%Formation Sprint%' OR title ILIKE '%llc%' OR title ILIKE '%sunbiz%' OR title ILIKE '%ein%' OR title ILIKE '%registered agent%' THEN 'Formation'
                    WHEN coalesce(description, '') ILIKE '%Finance Sprint%' OR title ILIKE '%cpa%' OR title ILIKE '%receipt%' OR title ILIKE '%subscription%' OR title ILIKE '%asset%' THEN 'Finance'
                    WHEN coalesce(description, '') ILIKE '%Consulting Sprint%' OR title ILIKE '%consulting%' OR title ILIKE '%proposal%' OR title ILIKE '%crm%' THEN 'Consulting'
                    WHEN coalesce(description, '') ILIKE '%Product Sprint%' OR title ILIKE '%product%' OR title ILIKE '%mvp%' OR title ILIKE '%stripe%' THEN 'Product'
                    WHEN coalesce(description, '') ILIKE '%Robotics Sprint%' OR title ILIKE '%robotics%' OR title ILIKE '%3d%' OR title ILIKE '%printer%' THEN 'Robotics'
                    WHEN coalesce(description, '') ILIKE '%Marketing Sprint%' OR title ILIKE '%marketing%' OR title ILIKE '%website%' OR title ILIKE '%linkedin%' THEN 'Marketing'
                    WHEN coalesce(description, '') ILIKE '%Dashboard Sprint%' OR title ILIKE '%dashboard%' THEN 'Dashboard'
                    WHEN coalesce(description, '') ILIKE '%Agent Sprint%' OR title ILIKE '%agent%' THEN 'Agents'
                    WHEN coalesce(description, '') ILIKE '%Second-Brain Sprint%' OR coalesce(description, '') ILIKE '%Second Brain Sprint%' OR title ILIKE '%obsidian%' OR title ILIKE '%second brain%' THEN 'Knowledge'
                    ELSE 'Operations'
                END
                WHERE project_id = :project_id AND (domain IS NULL OR domain = '')
                """
            ),
            {"project_id": COMPANY_PROJECT_ID},
        )
        await session.execute(
            text(
                """
                UPDATE tasks
                SET owner_agent = CASE domain
                    WHEN 'Formation' THEN 'legal_compliance'
                    WHEN 'Finance' THEN 'finance_cpa'
                    WHEN 'Consulting' THEN 'consulting_revenue'
                    WHEN 'Product' THEN 'product'
                    WHEN 'Robotics' THEN 'robotics_lab'
                    WHEN 'Marketing' THEN 'marketing_content'
                    WHEN 'Dashboard' THEN 'engineering'
                    WHEN 'Agents' THEN 'chief_of_staff'
                    WHEN 'Knowledge' THEN 'knowledge_second_brain'
                    ELSE 'zero-company-operator'
                END
                WHERE project_id = :project_id AND (owner_agent IS NULL OR owner_agent = '')
                """
            ),
            {"project_id": COMPANY_PROJECT_ID},
        )
        await session.execute(
            text(
                """
                UPDATE tasks
                SET risk_level = 'high',
                    approval_state = CASE WHEN approval_state = 'none' THEN 'pending' ELSE approval_state END,
                    status = CASE WHEN status NOT IN ('done', 'blocked') THEN 'blocked' ELSE status END,
                    blocked_reason = coalesce(
                        blocked_reason,
                        'Approval-gated high-risk company task. Adam must approve or perform external/legal/financial/client/public/account actions.'
                    )
                WHERE project_id = :project_id
                  AND status != 'done'
                  AND title ~* :pattern
                """
            ),
            {"project_id": COMPANY_PROJECT_ID, "pattern": SQL_HIGH_RISK_PATTERN},
        )
        await session.execute(
            text(
                """
                WITH ordered AS (
                    SELECT id, row_number() OVER (ORDER BY created_at ASC, id ASC) AS rn
                    FROM tasks
                    WHERE project_id = :project_id
                )
                UPDATE tasks
                SET sort_order = ordered.rn
                FROM ordered
                WHERE tasks.id = ordered.id AND coalesce(tasks.sort_order, 0) = 0
                """
            ),
            {"project_id": COMPANY_PROJECT_ID},
        )


class CompanyWorkItemService:
    """Company scoped task operations."""

    async def list_work_items(
        self,
        *,
        status: Optional[str] = None,
        domain: Optional[str] = None,
        owner_agent: Optional[str] = None,
        risk_level: Optional[str] = None,
        approval_state: Optional[str] = None,
        filter_name: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 300,
    ) -> list[Task]:
        async with get_session() as session:
            query = select(TaskModel).where(TaskModel.project_id == COMPANY_PROJECT_ID)

            if status:
                query = query.where(TaskModel.status == status)
            elif filter_name != "archived":
                query = query.where(TaskModel.status != TaskStatus.ARCHIVED.value)
            if domain:
                query = query.where(func.lower(TaskModel.domain) == domain.lower())
            if owner_agent:
                query = query.where(TaskModel.owner_agent == owner_agent)
            if risk_level:
                query = query.where(TaskModel.risk_level == risk_level)
            if approval_state:
                query = query.where(TaskModel.approval_state == approval_state)
            if search:
                needle = f"%{search.strip()}%"
                query = query.where(or_(TaskModel.title.ilike(needle), TaskModel.description.ilike(needle)))

            if filter_name == "today":
                query = query.where(TaskModel.status.in_(["todo", "on_hold", "in_progress", "blocked"]))
            elif filter_name == "blocked":
                query = query.where(TaskModel.status == TaskStatus.BLOCKED.value)
            elif filter_name == "approval_gated":
                query = query.where(
                    or_(
                        TaskModel.approval_state == "pending",
                        TaskModel.blocked_reason.ilike("%approval%"),
                        TaskModel.risk_level.in_(["high", "critical"]),
                    )
                )
            elif filter_name == "formation":
                query = query.where(TaskModel.domain == "Formation")
            elif filter_name == "backlog":
                query = query.where(TaskModel.status == TaskStatus.BACKLOG.value)
            elif filter_name == "archived":
                query = query.where(TaskModel.status == TaskStatus.ARCHIVED.value)

            query = query.order_by(TaskModel.sort_order.asc(), TaskModel.created_at.desc()).limit(limit)
            rows = (await session.execute(query)).scalars().all()
        return [Task.model_validate(row, from_attributes=True) for row in rows]

    async def get_work_item(self, task_id: str) -> Optional[Task]:
        task = await get_task_service().get_task(task_id)
        if not task or task.project_id != COMPANY_PROJECT_ID:
            return None
        return task

    async def create_work_item(self, data: TaskCreate, *, actor: str = "user") -> Task:
        risk = data.risk_level or classify_risk(data)
        domain = data.domain or infer_domain(data.title, data.description)
        payload = data.model_copy(
            update={
                "project_id": COMPANY_PROJECT_ID,
                "domain": domain,
                "risk_level": risk,
                "approval_state": data.approval_state or ("pending" if risk in {"high", "critical"} else "none"),
                "owner_agent": data.owner_agent or "zero-company-operator",
            }
        )
        created = await get_task_service().create_task(payload)
        await self.record_event(created.id, "created", actor=actor, summary=f"Created {created.title}", after=_task_dump(created))

        if risk in {"high", "critical"}:
            blocked = await get_task_service().update_task(
                created.id,
                TaskUpdate(
                    status=TaskStatus.BLOCKED,
                    blocked_reason="Approval-gated high-risk company task. Adam must approve or perform external/legal/financial/client/public/account actions.",
                    approval_state="pending",
                ),
            )
            if blocked:
                await self.record_event(
                    blocked.id,
                    "blocked",
                    actor="zero-company-operator",
                    summary="High-risk task blocked at creation.",
                    before=_task_dump(created),
                    after=_task_dump(blocked),
                )
                return blocked
        return created

    async def update_work_item(
        self,
        task_id: str,
        updates: TaskUpdate,
        *,
        actor: str = "user",
        bypass_completion_approval: bool = False,
    ) -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None
        before = _task_dump(existing)

        # When evidence has already been recorded on the task (deliverable
        # outputs captured at a previous completion attempt), treat the gate
        # as satisfied for status transitions too. This makes the kanban drag
        # to "Completed" work as expected after the user has captured proof.
        already_has_evidence = bool(
            (existing.completion_outputs or {}).get("outputs")
            or (existing.completion_outputs or {}).get("note")
        )

        if updates.status == TaskStatus.DONE and not (bypass_completion_approval or already_has_evidence) and self._requires_completion_approval(existing):
            approval = await self._queue_completion_approval(existing, actor=actor)
            updated = await get_task_service().update_task(
                task_id,
                TaskUpdate(
                    status=TaskStatus.BLOCKED,
                    approval_state="pending",
                    approval_id=approval.get("id"),
                    blocked_reason="Completion is approval-gated. Adam must approve or perform the external action before this task can be done.",
                ),
            )
            if updated:
                await self.record_event(
                    task_id,
                    "approval_queued",
                    actor=actor,
                    summary=f"Queued approval before completing {existing.title}",
                    before=before,
                    after=_task_dump(updated),
                )
            return updated

        patch = updates
        update_values = updates.model_dump(exclude_unset=True)
        if "risk_level" not in update_values and ("title" in update_values or "description" in update_values):
            risk = classify_risk(existing.model_copy(update=update_values))
            patch = updates.model_copy(update={"risk_level": risk})
        # Stamp completed_at / started_at on status transitions so reports and
        # progress widgets see the right timestamps.
        if updates.status == TaskStatus.DONE and not existing.completed_at:
            patch = patch.model_copy(update={"completed_at": _now()})
        elif updates.status == TaskStatus.IN_PROGRESS and not existing.started_at:
            patch = patch.model_copy(update={"started_at": _now()})
        updated = await get_task_service().update_task(task_id, patch)
        if updated:
            await self.record_event(task_id, "updated", actor=actor, summary=f"Updated {updated.title}", before=before, after=_task_dump(updated))
        return updated

    async def complete_work_item(
        self,
        task_id: str,
        *,
        actor: str = "user",
        completion_note: Optional[str] = None,
        outputs: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None

        outputs = outputs or []
        recorded_at = _now().isoformat()
        new_description = existing.description or ""
        if completion_note:
            stamp = recorded_at[:10]
            new_description = (
                f"{new_description}\n\n---\nCompletion note ({stamp}, by {actor}): {completion_note.strip()}"
            ).strip()

        completion_outputs = {
            "recorded_at": recorded_at,
            "recorded_by": actor,
            "note": completion_note or "",
            "outputs": outputs,
        }

        # Persist outputs + note onto the task BEFORE the approval-gate check.
        # If the task hits the approval gate, the captured outputs must still be
        # visible in the task detail drawer so Adam can see what he recorded.
        if outputs or completion_note:
            pre_patch: dict[str, Any] = {"completion_outputs": completion_outputs}
            if completion_note:
                pre_patch["description"] = new_description
            await get_task_service().update_task(task_id, TaskUpdate(**pre_patch))

        if outputs:
            from app.models.company_facts import CompanyFactCreate
            from app.services.company_facts_service import get_company_facts_service

            facts_service = get_company_facts_service()
            for raw in outputs:
                try:
                    create = CompanyFactCreate(
                        key=str(raw.get("key", "")).strip(),
                        label=str(raw.get("label") or raw.get("key", "")).strip(),
                        value=str(raw.get("value", "")).strip(),
                        domain=(raw.get("domain") or existing.domain),
                        evidence_url=raw.get("evidence_url"),
                        sensitive=bool(raw.get("sensitive", False)),
                        notes=raw.get("notes"),
                    )
                except Exception:
                    continue
                if not create.key or not create.value:
                    continue
                await facts_service.upsert_fact(
                    create,
                    created_by=actor,
                    source="task_completion",
                    source_task_id=task_id,
                )

        # When Adam records outputs or a completion note, he is providing proof
        # he performed the high-risk action himself (got the EIN, filed the LLC,
        # opened the bank account). The approval gate exists to prevent agents
        # from doing those things autonomously - it should not block a human
        # operator recording the result. Bypass the gate when evidence is given.
        has_evidence = bool(outputs) or bool((completion_note or "").strip())
        return await self.update_work_item(
            task_id,
            TaskUpdate(status=TaskStatus.DONE),
            actor=actor,
            bypass_completion_approval=has_evidence,
        )

    async def reopen_work_item(self, task_id: str, *, actor: str = "user") -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None
        updated = await get_task_service().update_task(
            task_id,
            TaskUpdate(status=TaskStatus.IN_PROGRESS, approval_state="none", blocked_reason=""),
        )
        if updated:
            await self.record_event(task_id, "reopened", actor=actor, summary=f"Reopened {updated.title}", before=_task_dump(existing), after=_task_dump(updated))
        return updated

    async def duplicate_work_item(self, task_id: str, *, actor: str = "user") -> Optional[Task]:
        existing = await self.get_work_item(task_id)
        if not existing:
            return None
        clone = TaskCreate(
            title=f"Copy of {existing.title}",
            description=existing.description,
            category=existing.category,
            priority=existing.priority,
            source=TaskSource.MANUAL,
            source_reference=f"duplicated_from:{existing.id}",
            domain=existing.domain,
            owner_agent=existing.owner_agent,
            due_at=existing.due_at,
            scheduled_for=existing.scheduled_for,
            risk_level=existing.risk_level,
            tags=existing.tags,
            links=existing.links,
            estimate_points=existing.estimate_points,
            parent_task_id=existing.parent_task_id,
        )
        created = await self.create_work_item(clone, actor=actor)
        await self.record_event(created.id, "duplicated", actor=actor, summary=f"Duplicated from {existing.id}", after={"source_task_id": existing.id})
        return created

    async def delete_work_item(self, task_id: str, *, actor: str = "user") -> bool:
        existing = await self.get_work_item(task_id)
        if not existing:
            return False
        await self.record_event(task_id, "deleted", actor=actor, summary=f"Deleted {existing.title}", before=_task_dump(existing))
        return await get_task_service().delete_task(task_id)

    async def events(self, task_id: str, *, limit: int = 100) -> list[CompanyTaskEvent]:
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

    async def review(self, task_id: str) -> Optional[CompanyWorkItemReview]:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(CompanyWorkItemReviewModel)
                    .where(CompanyWorkItemReviewModel.task_id == task_id)
                    .limit(1)
                )
            ).scalars().first()
        if not row:
            return None
        return CompanyWorkItemReview.model_validate(row, from_attributes=True)

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
                id=f"cte-{uuid.uuid4().hex[:12]}",
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

    async def seed_status(self) -> dict[str, Any]:
        tasks = await self.list_work_items(limit=1)
        return {
            "has_live_tasks": bool(tasks),
            "seed_source": str(self._backlog_path()),
            "message": "Live editable company tasks exist." if tasks else "No live company tasks yet. Import the seed backlog to make the board editable.",
        }

    async def import_seed_backlog(self, *, actor: str = "user") -> dict[str, Any]:
        existing = await self.list_work_items(limit=500)
        existing_titles = {t.title.strip().lower() for t in existing}
        items = self._read_seed_backlog()
        created: list[Task] = []
        skipped = 0

        for item in items:
            if item["title"].strip().lower() in existing_titles:
                skipped += 1
                continue
            task = await self.create_work_item(
                TaskCreate(
                    title=item["title"],
                    description=f"({item['domain']} Sprint) Imported from docs/company/task-backlog.md.",
                    category=TaskCategory.CHORE,
                    priority=TaskPriority.HIGH if item["domain"] == "Formation" else TaskPriority.MEDIUM,
                    source=TaskSource.MANUAL,
                    source_reference="docs/company/task-backlog.md",
                    domain=item["domain"],
                    owner_agent=self._default_owner_for_domain(item["domain"]),
                    tags=[item["domain"].lower().replace(" ", "-"), "seed-import"],
                    sort_order=len(created) + skipped + 1,
                ),
                actor=actor,
            )
            created.append(task)
            existing_titles.add(task.title.strip().lower())

        return {"created": len(created), "skipped": skipped, "tasks": created}

    def _requires_completion_approval(self, task: Task) -> bool:
        return (task.risk_level in {"high", "critical"}) or bool(HIGH_RISK_PATTERN.search(_text(task)))

    async def _queue_completion_approval(self, task: Task, *, actor: str) -> dict[str, Any]:
        pending = await get_approval_queue().list(status="pending", limit=200)
        for approval in pending:
            args = approval.arguments or {}
            if args.get("task_id") == task.id and approval.tool_name == "company_work_item_completion_gate":
                return {
                    "id": approval.id,
                    "status": approval.status,
                    "summary": approval.summary,
                }
        tier = "financial" if re.search(r"\b(bank|card|purchase|subscription|cpa|attorney|registered agent|tax)\b", _text(task), re.I) else "write_external"
        row = await get_approval_queue().request(
            tool_name="company_work_item_completion_gate",
            tier=tier,
            summary=f"Approval needed before completing company task: {task.title}",
            arguments={
                "task_id": task.id,
                "title": task.title,
                "project_id": COMPANY_PROJECT_ID,
                "guardrail": "Adam must perform or approve filings, purchases, account changes, legal/tax decisions, client/public messages, and professional engagements.",
            },
            requested_by=actor,
        )
        return {"id": row.id, "status": row.status, "summary": row.summary}

    def _backlog_path(self) -> Path:
        configured = Path(get_settings().workspace_dir).resolve()
        candidates = [
            configured / "docs" / "company" / "task-backlog.md",
            configured.parent / "docs" / "company" / "task-backlog.md",
        ]
        for parent in Path(__file__).resolve().parents:
            candidates.append(parent / "docs" / "company" / "task-backlog.md")
        for path in candidates:
            if path.exists():
                return path
        return configured / "docs" / "company" / "task-backlog.md"

    def _read_seed_backlog(self) -> list[dict[str, str]]:
        path = self._backlog_path()
        if not path.exists():
            path = Path("docs/company/task-backlog.md")
        current_domain = "Operations"
        items: list[dict[str, str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            heading = re.match(r"^##\s+(.+?)\s+Sprint\s*$", line.strip())
            if heading:
                current_domain = infer_domain("", fallback=heading.group(1))
                continue
            task = re.match(r"^-\s+(?:\[ \]\s+)?(.+?)\.?\s*$", line.strip())
            if task:
                title = _compact(task.group(1), limit=220)
                items.append({"title": title, "domain": current_domain})
        return items

    @staticmethod
    def _default_owner_for_domain(domain: str) -> str:
        return {
            "Formation": "legal_compliance",
            "Finance": "finance_cpa",
            "Consulting": "consulting_revenue",
            "Product": "product",
            "Robotics": "robotics_lab",
            "Marketing": "marketing_content",
            "Dashboard": "engineering",
            "Agents": "chief_of_staff",
            "Knowledge": "knowledge_second_brain",
        }.get(domain, "zero-company-operator")


def get_company_work_item_service() -> CompanyWorkItemService:
    return CompanyWorkItemService()
