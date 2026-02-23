"""
Enhancement Engine API.

Exposes engine status, activity feed, toggle, config, and manual trigger.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


class ConfigUpdate(BaseModel):
    cycle_interval_minutes: Optional[int] = None
    max_improvements_per_cycle: Optional[int] = None
    max_improvements_per_hour: Optional[int] = None
    max_improvements_per_day: Optional[int] = None
    target_projects: Optional[list] = None
    auto_sprint_batch_threshold: Optional[int] = None
    cooldown_after_failure_minutes: Optional[int] = None
    analysis_model: Optional[str] = None


@router.get("/status")
async def get_engine_status():
    """Get engine status (enabled, running, stats)."""
    from app.services.continuous_enhancement_service import get_continuous_enhancement_service
    engine = get_continuous_enhancement_service()
    return await engine.get_status()


@router.get("/activity")
async def get_activity_feed(
    limit: int = 50,
    project: Optional[str] = None,
    event_type: Optional[str] = None,
    hours: Optional[int] = None,
):
    """Get activity feed, filterable by project and event_type."""
    from app.services.activity_log_service import get_activity_log_service
    activity_log = get_activity_log_service()

    since = None
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)

    events = await activity_log.get_events(
        limit=limit, project=project, event_type=event_type, since=since,
    )
    return {"events": events, "total": len(events)}


@router.get("/activity/summary")
async def get_activity_summary(hours: int = 24):
    """Get activity summary for the last N hours."""
    from app.services.activity_log_service import get_activity_log_service
    activity_log = get_activity_log_service()
    return await activity_log.get_summary(hours=hours)


@router.post("/toggle")
async def toggle_engine(body: ToggleRequest):
    """Enable or disable the engine."""
    from app.services.continuous_enhancement_service import get_continuous_enhancement_service
    engine = get_continuous_enhancement_service()
    await engine.set_enabled(body.enabled)
    return {"enabled": body.enabled}


@router.patch("/config")
async def update_engine_config(body: ConfigUpdate):
    """Update engine configuration (partial)."""
    from app.services.continuous_enhancement_service import get_continuous_enhancement_service
    engine = get_continuous_enhancement_service()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    config = await engine.update_config(updates)
    return config


@router.post("/trigger")
async def trigger_cycle():
    """Manually trigger one enhancement cycle."""
    from app.services.continuous_enhancement_service import get_continuous_enhancement_service
    import asyncio

    engine = get_continuous_enhancement_service()
    status = await engine.get_status()

    if status.get("running"):
        raise HTTPException(status_code=409, detail="Engine cycle already running")

    # Run in background so the request returns immediately
    asyncio.create_task(engine.run_cycle())
    return {"triggered": True, "message": "Enhancement cycle started"}
