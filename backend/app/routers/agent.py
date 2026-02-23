"""
Agent API router.
Provides endpoints for autonomous task submission, status monitoring,
and execution control.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()

router = APIRouter()


# ========================================
# Request/Response Models
# ========================================

class TaskSubmitRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=5000)
    project_path: Optional[str] = None
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low)$")


class AgentSettingsUpdate(BaseModel):
    max_files_per_task: Optional[int] = None
    max_lines_per_file: Optional[int] = None
    max_ollama_retries: Optional[int] = None
    ollama_timeout: Optional[int] = None
    coding_model: Optional[str] = None
    protected_paths: Optional[list] = None


# ========================================
# Endpoints
# ========================================

@router.post("/submit")
async def submit_task(request: TaskSubmitRequest):
    """Submit a task for autonomous execution."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()

    task = await service.submit_task(
        title=request.title,
        description=request.description,
        project_path=request.project_path,
        priority=request.priority,
    )
    return task


@router.get("/status")
async def get_status():
    """Get current agent execution status."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    return service.get_status()


@router.get("/queue")
async def get_queue():
    """Get queued tasks waiting for execution."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    return await service.get_queue()


@router.get("/history")
async def get_history(limit: int = 20):
    """Get completed task history."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    return await service.get_history(limit=min(limit, 100))


@router.get("/log/{task_id}")
async def get_task_log(task_id: str):
    """Get detailed execution log for a task."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    log = await service.get_task_log(task_id)
    if not log:
        raise HTTPException(status_code=404, detail="Task not found")
    return log


@router.post("/stop")
async def stop_execution():
    """Gracefully stop current task execution after the current step."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()

    if not service.is_busy():
        return {"status": "idle", "message": "No task currently running"}

    service.stop()
    return {"status": "stopping", "message": "Will stop after current step completes"}


@router.post("/pause")
async def pause_worker():
    """Pause the autonomous worker loop."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    service.pause()
    return {"status": "paused", "message": "Worker loop paused — no new tasks will be picked up"}


@router.post("/resume")
async def resume_worker():
    """Resume the autonomous worker loop."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    service.resume()
    return {"status": "resumed", "message": "Worker loop resumed"}


@router.get("/settings")
async def get_settings():
    """Get current agent execution settings."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    return service.get_settings()


@router.patch("/settings")
async def update_settings(request: AgentSettingsUpdate):
    """Update agent execution settings."""
    from app.services.task_execution_service import get_task_execution_service
    service = get_task_execution_service()
    updates = request.model_dump(exclude_unset=True)
    return await service.update_settings(updates)
