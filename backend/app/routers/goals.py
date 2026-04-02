"""Goal tracking API."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

router = APIRouter()


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "general"
    target_date: Optional[datetime] = None
    milestones: Optional[list] = None


class GoalProgressUpdate(BaseModel):
    progress_pct: float = Field(..., ge=0, le=100)
    note: Optional[str] = None
    blockers: Optional[list] = None


@router.post("/")
async def create_goal(req: GoalCreate):
    from app.services.goal_tracking_service import get_goal_tracking_service
    return await get_goal_tracking_service().create_goal(
        title=req.title,
        description=req.description,
        category=req.category,
        target_date=req.target_date,
        milestones=req.milestones,
    )


@router.get("/")
async def list_goals(status: str = "active"):
    from app.services.goal_tracking_service import get_goal_tracking_service
    return await get_goal_tracking_service().list_goals(status=status)


@router.put("/{goal_id}/progress")
async def update_progress(goal_id: str, req: GoalProgressUpdate):
    from app.services.goal_tracking_service import get_goal_tracking_service
    return await get_goal_tracking_service().update_progress(
        goal_id=goal_id,
        progress_pct=req.progress_pct,
        note=req.note,
        blockers=req.blockers,
    )


@router.get("/alerts")
async def get_alerts():
    from app.services.goal_tracking_service import get_goal_tracking_service
    return await get_goal_tracking_service().get_anticipatory_alerts()
