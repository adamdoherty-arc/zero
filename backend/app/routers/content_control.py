"""Content production hard-freeze controls."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.infrastructure.auth import require_auth
from app.services.content_production_control_service import (
    get_content_production_control_service,
)


router = APIRouter(dependencies=[Depends(require_auth)])


class ContentProductionStatusUpdate(BaseModel):
    paused: bool
    reason: Optional[str] = None
    restore_previous_jobs: bool = True


@router.get("/status")
async def get_content_production_status() -> Dict[str, Any]:
    """Return persisted freeze policy plus affected scheduler jobs."""
    return await get_content_production_control_service().get_status()


@router.patch("/status")
async def update_content_production_status(
    body: ContentProductionStatusUpdate,
) -> Dict[str, Any]:
    """Pause/resume carousel, media, and image production."""
    return await get_content_production_control_service().set_paused(
        body.paused,
        reason=body.reason,
        restore_previous_jobs=body.restore_previous_jobs,
        updated_by="ui",
    )


@router.post("/sync-scheduler")
async def sync_content_production_scheduler() -> Dict[str, Any]:
    """Re-apply persisted freeze state to scheduler runtime and overrides."""
    service = get_content_production_control_service()
    result = await service.sync_scheduler_with_policy()
    status = await service.get_status()
    status["scheduler_result"] = result
    return status
