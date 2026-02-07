"""
Task management service.
Handles all task CRUD operations and business logic.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from app.models.task import Task, TaskCreate, TaskUpdate, TaskMove, TaskStatus
from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_sprints_path

logger = structlog.get_logger()


class TaskService:
    """Service for task management operations."""

    def __init__(self):
        self.storage = JsonStorage(get_sprints_path())
        self._tasks_file = "tasks.json"

    async def _load_data(self) -> Dict[str, Any]:
        """Load tasks data from storage."""
        return await self.storage.read(self._tasks_file)

    async def _save_data(self, data: Dict[str, Any]) -> bool:
        """Save tasks data to storage."""
        return await self.storage.write(self._tasks_file, data)

    async def list_tasks(
        self,
        sprint_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks with optional filters."""
        data = await self._load_data()
        tasks_data = data.get("tasks", [])

        tasks = []
        for t in tasks_data:
            # Apply filters
            if sprint_id and t.get("sprintId") != sprint_id:
                continue
            if project_id and t.get("projectId") != project_id:
                continue
            if status and t.get("status") != status.value:
                continue

            # Normalize field names for Pydantic
            normalized = self._normalize_task_data(t)
            tasks.append(Task(**normalized))

            if len(tasks) >= limit:
                break

        return tasks

    def _normalize_task_data(self, task_data: Dict) -> Dict:
        """Normalize task data from storage format to Pydantic model format."""
        return {
            "id": task_data.get("id"),
            "sprint_id": task_data.get("sprintId"),
            "project_id": task_data.get("projectId"),
            "title": task_data.get("title"),
            "description": task_data.get("description"),
            "status": task_data.get("status", "backlog"),
            "category": task_data.get("category", "feature"),
            "priority": task_data.get("priority", "medium"),
            "points": task_data.get("points"),
            "source": task_data.get("source", "MANUAL"),
            "source_reference": task_data.get("sourceReference"),
            "blocked_reason": task_data.get("blockedReason"),
            "started_at": task_data.get("startedAt"),
            "completed_at": task_data.get("completedAt"),
            "created_at": task_data.get("createdAt"),
            "updated_at": task_data.get("updatedAt"),
        }

    def _to_storage_format(self, task: Task) -> Dict:
        """Convert task to storage format (camelCase)."""
        return {
            "id": task.id,
            "sprintId": task.sprint_id,
            "projectId": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value if hasattr(task.status, 'value') else task.status,
            "category": task.category.value if hasattr(task.category, 'value') else task.category,
            "priority": task.priority.value if hasattr(task.priority, 'value') else task.priority,
            "points": task.points,
            "source": task.source.value if hasattr(task.source, 'value') else task.source,
            "sourceReference": task.source_reference,
            "blockedReason": task.blocked_reason,
            "startedAt": task.started_at.isoformat() if task.started_at else None,
            "completedAt": task.completed_at.isoformat() if task.completed_at else None,
            "createdAt": task.created_at.isoformat() if task.created_at else None,
            "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
        }

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        data = await self._load_data()
        for t in data.get("tasks", []):
            if t["id"] == task_id:
                normalized = self._normalize_task_data(t)
                return Task(**normalized)
        return None

    async def create_task(self, task_data: TaskCreate) -> Task:
        """Create a new task."""
        data = await self._load_data()

        # Generate new task ID
        next_id = data.get("nextTaskId", 1)
        task_id = f"task-{next_id}"

        now = datetime.utcnow()

        task = Task(
            id=task_id,
            sprint_id=task_data.sprint_id,
            project_id=task_data.project_id,
            title=task_data.title,
            description=task_data.description,
            status=TaskStatus.BACKLOG,
            category=task_data.category,
            priority=task_data.priority,
            points=task_data.points,
            source=task_data.source,
            source_reference=task_data.source_reference,
            blocked_reason=task_data.blocked_reason,
            created_at=now
        )

        # Add to tasks list
        tasks = data.get("tasks", [])
        tasks.append(self._to_storage_format(task))

        # Update data
        data["tasks"] = tasks
        data["nextTaskId"] = next_id + 1

        await self._save_data(data)

        # Update sprint points if assigned to a sprint
        if task.sprint_id:
            from app.services.sprint_service import get_sprint_service
            sprint_service = get_sprint_service()
            await sprint_service.update_sprint_points(task.sprint_id)

        logger.info("Task created", task_id=task_id, title=task.title)
        return task

    async def update_task(self, task_id: str, updates: TaskUpdate) -> Optional[Task]:
        """Update a task."""
        data = await self._load_data()
        tasks = data.get("tasks", [])

        for i, t in enumerate(tasks):
            if t["id"] == task_id:
                old_sprint_id = t.get("sprintId")

                # Apply updates
                update_dict = updates.model_dump(exclude_unset=True)
                for key, value in update_dict.items():
                    if value is not None:
                        # Convert snake_case to camelCase for storage
                        storage_key = key
                        if key == "sprint_id":
                            storage_key = "sprintId"
                        elif key == "project_id":
                            storage_key = "projectId"
                        elif key == "source_reference":
                            storage_key = "sourceReference"
                        elif key == "blocked_reason":
                            storage_key = "blockedReason"

                        # Handle enums
                        if hasattr(value, 'value'):
                            value = value.value

                        t[storage_key] = value

                t["updatedAt"] = datetime.utcnow().isoformat()
                tasks[i] = t
                data["tasks"] = tasks
                await self._save_data(data)

                # Update sprint points if needed
                from app.services.sprint_service import get_sprint_service
                sprint_service = get_sprint_service()

                new_sprint_id = t.get("sprintId")
                if old_sprint_id:
                    await sprint_service.update_sprint_points(old_sprint_id)
                if new_sprint_id and new_sprint_id != old_sprint_id:
                    await sprint_service.update_sprint_points(new_sprint_id)

                logger.info("Task updated", task_id=task_id)
                normalized = self._normalize_task_data(t)
                return Task(**normalized)

        return None

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
        data = await self._load_data()
        tasks = data.get("tasks", [])

        for i, t in enumerate(tasks):
            if t["id"] == task_id:
                sprint_id = t.get("sprintId")
                del tasks[i]
                data["tasks"] = tasks
                await self._save_data(data)

                # Update sprint points
                if sprint_id:
                    from app.services.sprint_service import get_sprint_service
                    sprint_service = get_sprint_service()
                    await sprint_service.update_sprint_points(sprint_id)

                logger.info("Task deleted", task_id=task_id)
                return True

        return False

    async def get_backlog(self) -> List[Task]:
        """Get all backlog tasks (not assigned to any sprint)."""
        data = await self._load_data()
        tasks_data = data.get("tasks", [])

        tasks = []
        for t in tasks_data:
            if not t.get("sprintId"):
                normalized = self._normalize_task_data(t)
                tasks.append(Task(**normalized))

        return tasks


@lru_cache()
def get_task_service() -> TaskService:
    """Get cached task service instance."""
    return TaskService()
