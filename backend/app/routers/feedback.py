"""Feedback & preference learning API."""
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()


class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=-1, le=1, description="-1 bad, 0 neutral, 1 good")
    session_id: Optional[str] = None
    message_id: Optional[int] = None
    feedback_type: str = "response_quality"
    comment: Optional[str] = None
    context: Optional[dict] = None


@router.post("/")
async def submit_feedback(req: FeedbackRequest):
    from app.services.feedback_service import get_feedback_service
    svc = get_feedback_service()
    return await svc.record_feedback(
        rating=req.rating,
        session_id=req.session_id,
        message_id=req.message_id,
        feedback_type=req.feedback_type,
        comment=req.comment,
        context=req.context,
    )


@router.get("/stats")
async def feedback_stats():
    from app.services.feedback_service import get_feedback_service
    return await get_feedback_service().get_feedback_stats()


@router.get("/preferences")
async def get_preferences(category: Optional[str] = None):
    from app.services.feedback_service import get_feedback_service
    return await get_feedback_service().get_preferences(category)
