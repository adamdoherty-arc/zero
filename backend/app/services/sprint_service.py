"""
Sprint management service.
Handles all sprint CRUD operations and business logic.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from app.models.sprint import Sprint, SprintCreate, SprintUpdate, SprintStatus
from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_sprints_path

logger = structlog.get_logger()


class SprintService:
    """Service for sprint management operations."""

    def __init__(self):
        self.storage = JsonStorage(get_sprints_path())
        self._sprints_file = "sprints.json"

    async def _load_data(self) -> Dict[str, Any]:
        """Load sprints data from storage."""
        return await self.storage.read(self._sprints_file)

    async def _save_data(self, data: Dict[str, Any]) -> bool:
        """Save sprints data to storage."""
        return await self.storage.write(self._sprints_file, data)

    async def list_sprints(self) -> List[Sprint]:
        """Get all sprints."""
        data = await self._load_data()
        sprints_data = data.get("sprints", [])
        return [Sprint(**s) for s in sprints_data]

    async def get_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Get sprint by ID."""
        data = await self._load_data()
        for s in data.get("sprints", []):
            if s["id"] == sprint_id:
                return Sprint(**s)
        return None

    async def get_current_sprint(self) -> Optional[Sprint]:
        """Get the currently active sprint."""
        data = await self._load_data()
        current_id = data.get("currentSprintId")
        if not current_id:
            return None
        return await self.get_sprint(current_id)

    async def create_sprint(self, sprint_data: SprintCreate) -> Sprint:
        """Create a new sprint."""
        data = await self._load_data()

        # Generate new sprint ID and number
        next_number = data.get("nextSprintNumber", 1)
        sprint_id = f"sprint-{next_number}"

        # Calculate dates
        now = datetime.utcnow()
        end_date = now + timedelta(days=sprint_data.duration_days)

        sprint = Sprint(
            id=sprint_id,
            number=next_number,
            name=sprint_data.name,
            description=sprint_data.description,
            status=SprintStatus.PLANNING,
            start_date=now,
            end_date=end_date,
            duration_days=sprint_data.duration_days,
            goals=sprint_data.goals,
            total_points=0,
            completed_points=0,
            created_at=now
        )

        # Add to sprints list
        sprints = data.get("sprints", [])
        sprints.append(sprint.model_dump())

        # Update data
        data["sprints"] = sprints
        data["nextSprintNumber"] = next_number + 1

        await self._save_data(data)
        logger.info("Sprint created", sprint_id=sprint_id, name=sprint.name)
        return sprint

    async def update_sprint(self, sprint_id: str, updates: SprintUpdate) -> Optional[Sprint]:
        """Update a sprint."""
        data = await self._load_data()
        sprints = data.get("sprints", [])

        for i, s in enumerate(sprints):
            if s["id"] == sprint_id:
                # Apply updates
                update_dict = updates.model_dump(exclude_unset=True)
                for key, value in update_dict.items():
                    if value is not None:
                        # Convert snake_case keys to match storage format
                        storage_key = key
                        if key == "duration_days":
                            storage_key = "durationDays"
                        elif key == "start_date":
                            storage_key = "startDate"
                        elif key == "end_date":
                            storage_key = "endDate"
                        elif key == "total_points":
                            storage_key = "totalPoints"
                        elif key == "completed_points":
                            storage_key = "completedPoints"
                        elif key == "created_at":
                            storage_key = "createdAt"
                        s[storage_key] = value

                s["updatedAt"] = datetime.utcnow().isoformat()
                sprints[i] = s
                data["sprints"] = sprints
                await self._save_data(data)

                logger.info("Sprint updated", sprint_id=sprint_id)
                return Sprint(**s)

        return None

    async def start_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Start a sprint (set to active)."""
        data = await self._load_data()

        # First, pause any currently active sprint
        current_id = data.get("currentSprintId")
        if current_id and current_id != sprint_id:
            await self.update_sprint(current_id, SprintUpdate(status=SprintStatus.PAUSED))

        # Set this sprint as active
        updates = SprintUpdate(status=SprintStatus.ACTIVE)
        sprint = await self.update_sprint(sprint_id, updates)

        if sprint:
            data = await self._load_data()
            data["currentSprintId"] = sprint_id
            await self._save_data(data)
            logger.info("Sprint started", sprint_id=sprint_id)

        return sprint

    async def complete_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Complete a sprint."""
        updates = SprintUpdate(status=SprintStatus.COMPLETED)
        sprint = await self.update_sprint(sprint_id, updates)

        if sprint:
            data = await self._load_data()
            if data.get("currentSprintId") == sprint_id:
                data["currentSprintId"] = None
                await self._save_data(data)
            logger.info("Sprint completed", sprint_id=sprint_id)

        return sprint

    async def get_board(self, sprint_id: str) -> Dict[str, Any]:
        """Get Kanban board data for a sprint."""
        from app.services.task_service import get_task_service
        task_service = get_task_service()

        sprint = await self.get_sprint(sprint_id)
        if not sprint:
            return {}

        tasks = await task_service.list_tasks(sprint_id=sprint_id)

        # Group tasks by status
        columns = {
            "backlog": [],
            "todo": [],
            "in_progress": [],
            "review": [],
            "testing": [],
            "done": [],
            "blocked": []
        }

        for task in tasks:
            status = task.status.value if hasattr(task.status, 'value') else task.status
            if status in columns:
                columns[status].append(task.model_dump())

        return {
            "sprint": sprint.model_dump(),
            "columns": columns,
            "stats": {
                "total_tasks": len(tasks),
                "total_points": sum(t.points or 0 for t in tasks),
                "completed_points": sum(t.points or 0 for t in tasks if t.status.value == "done"),
                "by_status": {status: len(tasks) for status, tasks in columns.items()}
            }
        }

    async def update_sprint_points(self, sprint_id: str) -> None:
        """Recalculate and update sprint points from tasks."""
        from app.services.task_service import get_task_service
        task_service = get_task_service()

        tasks = await task_service.list_tasks(sprint_id=sprint_id)

        total = sum(t.points or 0 for t in tasks)
        completed = sum(t.points or 0 for t in tasks if t.status.value == "done")

        data = await self._load_data()
        sprints = data.get("sprints", [])

        for i, s in enumerate(sprints):
            if s["id"] == sprint_id:
                s["totalPoints"] = total
                s["completedPoints"] = completed
                sprints[i] = s
                break

        data["sprints"] = sprints
        await self._save_data(data)


@lru_cache()
def get_sprint_service() -> SprintService:
    """Get cached sprint service instance."""
    return SprintService()
