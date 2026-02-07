"""
Sprint management service.
Proxies all sprint operations through Legion (source of truth).
Falls back to local JSON storage when Legion is unavailable.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from app.models.sprint import (
    Sprint, SprintCreate, SprintUpdate, SprintStatus,
    LEGION_TO_ZERO_STATUS, ZERO_TO_LEGION_STATUS,
)
from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_settings, get_sprints_path
from app.services.legion_client import get_legion_client

logger = structlog.get_logger()


class SprintService:
    """Service for sprint management — proxies to Legion."""

    def __init__(self):
        self.storage = JsonStorage(get_sprints_path())
        self._sprints_file = "sprints.json"
        self._project_names_cache: Optional[Dict[int, str]] = None
        self._cache_time: Optional[datetime] = None

    # ============================================
    # LEGION DATA MAPPING
    # ============================================

    def _map_legion_sprint(self, data: Dict[str, Any], project_name: Optional[str] = None) -> Sprint:
        """Convert a Legion sprint dict to Zero's Sprint model."""
        raw_status = data.get("status", "planned")
        status = LEGION_TO_ZERO_STATUS.get(raw_status, "planning")

        # Calculate duration from planned dates
        duration = 14
        start = data.get("planned_start")
        end = data.get("planned_end")
        if start and end:
            try:
                s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                duration = max(1, (e - s).days)
            except (ValueError, TypeError):
                pass

        return Sprint(
            id=str(data["id"]),
            number=data["id"],
            name=data.get("name", f"Sprint {data['id']}"),
            description=data.get("description"),
            status=SprintStatus(status),
            start_date=start,
            end_date=end,
            duration_days=duration,
            goals=[],
            total_points=data.get("total_tasks", 0),
            completed_points=data.get("completed_tasks", 0),
            project_id=data.get("project_id"),
            project_name=project_name,
            created_at=data.get("created_at", datetime.utcnow()),
        )

    async def _get_project_names(self) -> Dict[int, str]:
        """Get project ID -> name mapping with simple caching."""
        now = datetime.utcnow()
        if (
            self._project_names_cache is not None
            and self._cache_time is not None
            and (now - self._cache_time).seconds < 300
        ):
            return self._project_names_cache

        try:
            legion = get_legion_client()
            projects = await legion.list_projects()
            self._project_names_cache = {
                p["id"]: p.get("name", "Unknown") for p in projects
            }
            self._cache_time = now
        except Exception:
            if self._project_names_cache is None:
                self._project_names_cache = {}
        return self._project_names_cache

    # ============================================
    # SPRINT OPERATIONS (LEGION-FIRST)
    # ============================================

    async def list_sprints(
        self,
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Sprint]:
        """Get sprints from Legion. Falls back to local JSON."""
        try:
            legion = get_legion_client()
            legion_status = ZERO_TO_LEGION_STATUS.get(status) if status else None
            legion_sprints = await legion.list_sprints(
                project_id=project_id,
                status=legion_status,
                limit=limit,
            )
            project_names = await self._get_project_names()
            return [
                self._map_legion_sprint(s, project_names.get(s.get("project_id")))
                for s in legion_sprints
            ]
        except Exception as e:
            logger.warning("legion_unavailable_falling_back_to_local", error=str(e))
            return await self._load_local_sprints()

    async def get_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Get a single sprint from Legion."""
        try:
            legion = get_legion_client()
            legion_sprint = await legion.get_sprint(int(sprint_id))
            if not legion_sprint:
                return None
            project_names = await self._get_project_names()
            return self._map_legion_sprint(
                legion_sprint,
                project_names.get(legion_sprint.get("project_id")),
            )
        except Exception as e:
            logger.warning("legion_get_sprint_failed", sprint_id=sprint_id, error=str(e))
            return await self._get_local_sprint(sprint_id)

    async def get_current_sprint(self) -> Optional[Sprint]:
        """Get the active sprint for Zero's project."""
        settings = get_settings()
        try:
            legion = get_legion_client()
            legion_sprint = await legion.get_current_sprint(settings.zero_legion_project_id)
            if not legion_sprint:
                return None
            return self._map_legion_sprint(legion_sprint)
        except Exception as e:
            logger.warning("legion_get_current_sprint_failed", error=str(e))
            return await self._get_local_current()

    async def create_sprint(self, sprint_data: SprintCreate) -> Sprint:
        """Create a new sprint in Legion."""
        settings = get_settings()
        legion = get_legion_client()
        result = await legion.create_sprint({
            "name": sprint_data.name,
            "project_id": sprint_data.project_id or settings.zero_legion_project_id,
        })
        project_names = await self._get_project_names()
        return self._map_legion_sprint(result, project_names.get(result.get("project_id")))

    async def start_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Start a sprint in Legion."""
        legion = get_legion_client()
        result = await legion.update_sprint(int(sprint_id), {"status": "active"})
        if not result:
            return None
        project_names = await self._get_project_names()
        return self._map_legion_sprint(result, project_names.get(result.get("project_id")))

    async def complete_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Complete a sprint in Legion."""
        legion = get_legion_client()
        result = await legion.update_sprint(int(sprint_id), {"status": "completed"})
        if not result:
            return None
        project_names = await self._get_project_names()
        return self._map_legion_sprint(result, project_names.get(result.get("project_id")))

    async def update_sprint(self, sprint_id: str, updates: SprintUpdate) -> Optional[Sprint]:
        """Update a sprint in Legion."""
        legion = get_legion_client()
        update_dict = {}
        if updates.name is not None:
            update_dict["name"] = updates.name
        if updates.status is not None:
            update_dict["status"] = ZERO_TO_LEGION_STATUS.get(updates.status.value, updates.status.value)
        result = await legion.update_sprint(int(sprint_id), update_dict)
        if not result:
            return None
        project_names = await self._get_project_names()
        return self._map_legion_sprint(result, project_names.get(result.get("project_id")))

    # ============================================
    # BOARD (combines sprint + local tasks)
    # ============================================

    async def get_board(self, sprint_id: str) -> Dict[str, Any]:
        """Get Kanban board data for a sprint."""
        from app.services.task_service import get_task_service
        task_service = get_task_service()

        sprint = await self.get_sprint(sprint_id)
        if not sprint:
            return {}

        tasks = await task_service.list_tasks(sprint_id=sprint_id)

        columns: Dict[str, list] = {
            "backlog": [],
            "todo": [],
            "in_progress": [],
            "review": [],
            "testing": [],
            "done": [],
            "blocked": [],
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
                "by_status": {status: len(task_list) for status, task_list in columns.items()},
            },
        }

    # ============================================
    # LOCAL FALLBACK
    # ============================================

    async def _load_local_sprints(self) -> List[Sprint]:
        """Fallback: load from local JSON."""
        data = await self.storage.read(self._sprints_file)
        sprints_data = data.get("sprints", [])
        return [Sprint(**s) for s in sprints_data]

    async def _get_local_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Fallback: get single sprint from local JSON."""
        data = await self.storage.read(self._sprints_file)
        for s in data.get("sprints", []):
            if s.get("id") == sprint_id or str(s.get("number")) == sprint_id:
                return Sprint(**s)
        return None

    async def _get_local_current(self) -> Optional[Sprint]:
        """Fallback: get current sprint from local JSON."""
        data = await self.storage.read(self._sprints_file)
        current_id = data.get("currentSprintId")
        if not current_id:
            return None
        return await self._get_local_sprint(current_id)


@lru_cache()
def get_sprint_service() -> SprintService:
    """Get cached sprint service instance."""
    return SprintService()
