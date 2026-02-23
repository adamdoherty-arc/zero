"""
Sprint management API endpoints.
Proxies to Legion sprint manager.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import structlog

from app.models.sprint import Sprint
from app.services.sprint_service import get_sprint_service

router = APIRouter()
logger = structlog.get_logger()


@router.get("")
async def list_sprints(
    project_id: Optional[int] = Query(None, description="Filter by Legion project ID"),
    status: Optional[str] = Query(None, description="Filter by status (planning, active, completed, paused)"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
):
    """Get all sprints from Legion."""
    service = get_sprint_service()
    return await service.list_sprints(project_id=project_id, status=status, limit=limit)


@router.get("/current")
async def get_current_sprint():
    """Get the currently active sprint for Zero."""
    service = get_sprint_service()
    return await service.get_current_sprint()


@router.get("/{sprint_id}")
async def get_sprint(sprint_id: str):
    """Get sprint by ID."""
    service = get_sprint_service()
    sprint = await service.get_sprint(sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.get("/{sprint_id}/board")
async def get_sprint_board(sprint_id: str):
    """Get Kanban board data for a sprint."""
    service = get_sprint_service()
    board = await service.get_board(sprint_id)
    if not board:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return board
