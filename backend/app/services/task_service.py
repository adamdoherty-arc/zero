"""
Task management service.
Handles all task CRUD operations and business logic.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from sqlalchemy import select, func as sa_func

from app.models.task import Task, TaskCreate, TaskUpdate, TaskMove, TaskStatus
from app.infrastructure.database import get_session
from app.db.models import TaskModel

logger = structlog.get_logger()


class TaskService:
    """Service for task management operations."""

    async def list_tasks(
        self,
        sprint_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks with optional filters."""
        async with get_session() as session:
            query = select(TaskModel)

            if sprint_id:
                query = query.where(TaskModel.sprint_id == sprint_id)
            if project_id:
                query = query.where(TaskModel.project_id == project_id)
            if status:
                query = query.where(TaskModel.status == status.value)

            query = query.order_by(TaskModel.created_at.desc()).limit(limit)

            result = await session.execute(query)
            rows = result.scalars().all()

            return [Task.model_validate(row, from_attributes=True) for row in rows]

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        async with get_session() as session:
            row = await session.get(TaskModel, task_id)
            if row is None:
                return None
            return Task.model_validate(row, from_attributes=True)

    async def create_task(self, task_data: TaskCreate) -> Task:
        """Create a new task."""
        async with get_session() as session:
            # Generate new task ID by counting existing tasks + 1
            count_result = await session.execute(
                select(sa_func.count()).select_from(TaskModel)
            )
            next_id = count_result.scalar_one() + 1
            task_id = f"task-{next_id}"

            now = datetime.utcnow()

            orm_obj = TaskModel(
                id=task_id,
                sprint_id=task_data.sprint_id,
                project_id=task_data.project_id,
                title=task_data.title,
                description=task_data.description,
                status=TaskStatus.BACKLOG.value,
                category=task_data.category.value if hasattr(task_data.category, 'value') else task_data.category,
                priority=task_data.priority.value if hasattr(task_data.priority, 'value') else task_data.priority,
                points=task_data.points,
                source=task_data.source.value if hasattr(task_data.source, 'value') else task_data.source,
                source_reference=task_data.source_reference,
                blocked_reason=task_data.blocked_reason,
                created_at=now,
            )

            session.add(orm_obj)
            # Flush to populate server defaults before reading back
            await session.flush()

            task = Task.model_validate(orm_obj, from_attributes=True)

        logger.info("Task created", task_id=task_id, title=task.title)
        return task

    async def update_task(self, task_id: str, updates: TaskUpdate) -> Optional[Task]:
        """Update a task."""
        async with get_session() as session:
            row = await session.get(TaskModel, task_id)
            if row is None:
                return None

            old_sprint_id = row.sprint_id

            # Apply updates
            update_dict = updates.model_dump(exclude_unset=True)
            for key, value in update_dict.items():
                if value is not None:
                    # Convert enums to their string values
                    if hasattr(value, 'value'):
                        value = value.value
                    setattr(row, key, value)

            row.updated_at = datetime.utcnow()

            await session.flush()

            task = Task.model_validate(row, from_attributes=True)

        logger.info("Task updated", task_id=task_id)
        return task

    async def move_task(self, task_id: str, move: TaskMove) -> Optional[Task]:
        """Move task to a new status."""
        task = await self.get_task(task_id)
        if not task:
            return None

        now = datetime.utcnow()

        # Track status transitions
        updates: Dict[str, Any] = {"status": move.status}

        if move.status == TaskStatus.IN_PROGRESS and not task.started_at:
            updates["started_at"] = now.isoformat()

        if move.status == TaskStatus.DONE:
            updates["completed_at"] = now.isoformat()

        if move.status == TaskStatus.BLOCKED:
            updates["blocked_reason"] = move.reason

        # Apply updates via update_task
        return await self.update_task(task_id, TaskUpdate(**updates))

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        async with get_session() as session:
            row = await session.get(TaskModel, task_id)
            if row is None:
                return False

            await session.delete(row)

        logger.info("Task deleted", task_id=task_id)
        return True

    async def get_backlog(self) -> List[Task]:
        """Get all backlog tasks (not assigned to any sprint)."""
        async with get_session() as session:
            query = select(TaskModel).where(
                (TaskModel.sprint_id.is_(None)) | (TaskModel.sprint_id == "backlog")
            )
            query = query.order_by(TaskModel.created_at.desc())

            result = await session.execute(query)
            rows = result.scalars().all()

            return [Task.model_validate(row, from_attributes=True) for row in rows]


@lru_cache()
def get_task_service() -> TaskService:
    """Get cached task service instance."""
    return TaskService()
