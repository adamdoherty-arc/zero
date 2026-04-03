"""Smart email drafting API."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

class DraftReply(BaseModel):
    email_id: str
    intent: str = "reply"
    tone: str = "professional"
    key_points: Optional[List[str]] = None

class DraftNew(BaseModel):
    to: str
    subject: str
    intent: str
    key_points: Optional[List[str]] = None
    tone: str = "professional"

@router.post("/reply")
async def draft_reply(req: DraftReply):
    from app.services.email_draft_service import get_email_draft_service
    return await get_email_draft_service().draft_reply(
        email_id=req.email_id, intent=req.intent,
        tone=req.tone, key_points=req.key_points,
    )

@router.post("/new")
async def draft_new(req: DraftNew):
    from app.services.email_draft_service import get_email_draft_service
    return await get_email_draft_service().draft_new(
        to=req.to, subject=req.subject, intent=req.intent,
        key_points=req.key_points, tone=req.tone,
    )
