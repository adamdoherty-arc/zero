"""
Task management API endpoints.
Following ADA patterns for task CRUD operations.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.task import Task, TaskCreate, TaskUpdate, TaskMove, TaskStatus
from app.services.task_service import get_task_service

router = APIRouter()
logger = structlog.get_logger()


@router.get("", response_model=List[Task])
async def list_tasks(
    sprint_id: Optional[str] = Query(None, description="Filter by sprint ID"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    status: Optional[TaskStatus] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500, description="Maximum tasks to return")
):
    """Get tasks with optional filters."""
    service = get_task_service()
    return await service.list_tasks(sprint_id=sprint_id, project_id=project_id, status=status, limit=limit)


@router.get("/backlog", response_model=List[Task])
async def get_backlog():
    """Get all backlog tasks (not assigned to any sprint)."""
    service = get_task_service()
    return await service.get_backlog()


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: str):
    """Get task by ID."""
    service = get_task_service()
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("", response_model=Task)
async def create_task(task_data: TaskCreate):
    """Create a new task."""
    service = get_task_service()
    return await service.create_task(task_data)


@router.patch("/{task_id}", response_model=Task)
async def update_task(task_id: str, updates: TaskUpdate):
    """Update a task."""
    service = get_task_service()
    task = await service.update_task(task_id, updates)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/move", response_model=Task)
async def move_task(task_id: str, move: TaskMove):
    """Move task to a new status."""
    service = get_task_service()
    task = await service.move_task(task_id, move)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """Delete a task."""
    service = get_task_service()
    deleted = await service.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "deleted", "task_id": task_id}
