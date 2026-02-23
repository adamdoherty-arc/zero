"""
Sprint management service.
Proxies all sprint operations through Legion (source of truth).
Falls back to PostgreSQL when Legion is unavailable.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from functools import lru_cache
import structlog

from sqlalchemy import select

from app.models.sprint import (
    Sprint, SprintStatus,
    LEGION_TO_ZERO_STATUS, ZERO_TO_LEGION_STATUS,
)
from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.db.models import SprintModel
from app.services.legion_client import get_legion_client

logger = structlog.get_logger()


class SprintService:
    """Service for sprint management — proxies to Legion."""

    def __init__(self):
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

    def _model_to_sprint(self, row: SprintModel) -> Sprint:
        """Convert a SprintModel ORM row to Zero's Sprint Pydantic model."""
        return Sprint(
            id=row.id,
            number=row.number,
            name=row.name,
            description=row.description,
            status=SprintStatus(row.status) if row.status else SprintStatus.PLANNING,
            start_date=row.start_date,
            end_date=row.end_date,
            duration_days=row.duration_days or 14,
            goals=row.goals or [],
            total_points=row.total_points or 0,
            completed_points=row.completed_points or 0,
            project_id=row.project_id,
            project_name=row.project_name,
            created_at=row.created_at or datetime.utcnow(),
            updated_at=row.updated_at,
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
        """Get sprints from Legion. Falls back to PostgreSQL."""
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
            logger.warning("legion_unavailable_falling_back_to_db", error=str(e))
            return await self._load_db_sprints(status=status, limit=limit)

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
            return await self._get_db_sprint(sprint_id)

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
            return await self._get_db_current()

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
    # POSTGRESQL FALLBACK
    # ============================================

    async def _load_db_sprints(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Sprint]:
        """Fallback: load sprints from PostgreSQL."""
        async with get_session() as session:
            stmt = select(SprintModel)
            if status:
                stmt = stmt.where(SprintModel.status == status)
            stmt = stmt.order_by(SprintModel.number.desc()).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._model_to_sprint(r) for r in rows]

    async def _get_db_sprint(self, sprint_id: str) -> Optional[Sprint]:
        """Fallback: get single sprint from PostgreSQL."""
        async with get_session() as session:
            # Try by primary key first
            row = await session.get(SprintModel, sprint_id)
            if row:
                return self._model_to_sprint(row)
            # Try by number (sprint_id might be a number string)
            try:
                num = int(sprint_id)
                stmt = select(SprintModel).where(SprintModel.number == num)
                result = await session.execute(stmt)
                row = result.scalars().first()
                if row:
                    return self._model_to_sprint(row)
            except (ValueError, TypeError):
                pass
            return None

    async def _get_db_current(self) -> Optional[Sprint]:
        """Fallback: get current (active) sprint from PostgreSQL."""
        async with get_session() as session:
            stmt = (
                select(SprintModel)
                .where(SprintModel.status == "active")
                .order_by(SprintModel.number.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row:
                return self._model_to_sprint(row)
            return None


@lru_cache()
def get_sprint_service() -> SprintService:
    """Get cached sprint service instance."""
    return SprintService()
