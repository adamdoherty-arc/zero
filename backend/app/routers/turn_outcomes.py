"""Turn outcome surface — feedback + trend.

Fed by the realtime handlers; consumed by the brain dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class FeedbackRequest(BaseModel):
    signal: str = Field(..., pattern="^(thumbs_up|thumbs_down)$")


@router.get("/recent")
async def recent(limit: int = Query(50, ge=1, le=500)):
    from app.services.turn_outcome_service import get_turn_outcome_service
    items = await get_turn_outcome_service().recent(limit=limit)
    return {"turns": [t.to_dict() for t in items]}


@router.get("/trend")
async def trend(hours: int = Query(24, ge=1, le=24 * 30)):
    from app.services.turn_outcome_service import get_turn_outcome_service
    return await get_turn_outcome_service().trend(hours=hours)


@router.post("/{turn_id}/feedback")
async def feedback(turn_id: str, req: FeedbackRequest):
    from app.services.turn_outcome_service import get_turn_outcome_service
    ok = await get_turn_outcome_service().feedback(turn_id, req.signal)
    if not ok:
        raise HTTPException(404, "turn not found")
    return {"ok": True, "turn_id": turn_id, "signal": req.signal}
