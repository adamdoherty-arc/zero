"""
Sprint management API endpoints.
Following ADA patterns for sprint CRUD operations.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.sprint import Sprint, SprintCreate, SprintUpdate, SprintStatus
from app.services.sprint_service import get_sprint_service

router = APIRouter()
logger = structlog.get_logger()


@router.get("", response_model=List[Sprint])
async def list_sprints():
    """Get all sprints."""
    service = get_sprint_service()
    return await service.list_sprints()


@router.get("/current", response_model=Optional[Sprint])
async def get_current_sprint():
    """Get the currently active sprint."""
    service = get_sprint_service()
    sprint = await service.get_current_sprint()
    return sprint


@router.get("/{sprint_id}", response_model=Sprint)
async def get_sprint(sprint_id: str):
    """Get sprint by ID."""
    service = get_sprint_service()
    sprint = await service.get_sprint(sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.post("", response_model=Sprint)
async def create_sprint(sprint_data: SprintCreate):
    """Create a new sprint."""
    service = get_sprint_service()
    return await service.create_sprint(sprint_data)


@router.patch("/{sprint_id}", response_model=Sprint)
async def update_sprint(sprint_id: str, updates: SprintUpdate):
    """Update a sprint."""
    service = get_sprint_service()
    sprint = await service.update_sprint(sprint_id, updates)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.post("/{sprint_id}/start", response_model=Sprint)
async def start_sprint(sprint_id: str):
    """Start a sprint (set to active)."""
    service = get_sprint_service()
    sprint = await service.start_sprint(sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint


@router.post("/{sprint_id}/complete", response_model=Sprint)
async def complete_sprint(sprint_id: str):
    """Complete a sprint."""
    service = get_sprint_service()
    sprint = await service.complete_sprint(sprint_id)
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
