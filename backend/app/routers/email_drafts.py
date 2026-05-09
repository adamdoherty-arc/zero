"""Smart email drafting + per-account approval pool API."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Any

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


# ---------------------------------------------------------------------------
# Per-account draft pool — Reachy drafts, Adam approves. Separate from the
# pure draft generator above so the surface stays orthogonal: generate vs.
# queue/approve. The voice loop and the dashboard both interact through
# this surface.
# ---------------------------------------------------------------------------

class PoolAddRequest(BaseModel):
    account_id: str = Field("default", description="Gmail account scope")
    to: str
    subject: str
    body: str
    thread_id: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class PoolUpdateRequest(BaseModel):
    body: str


class PoolRejectRequest(BaseModel):
    reason: str = ""


@router.get("/pool")
async def pool_list(
    account_id: Optional[str] = None,
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|sent|failed)$"),
    limit: int = Query(100, ge=1, le=500),
):
    from app.services.email_draft_pool_service import get_email_draft_pool
    drafts = await get_email_draft_pool().list_drafts(
        account_id=account_id, status=status, limit=limit,
    )
    return {"drafts": [d.to_dict() for d in drafts]}


@router.get("/pool/stats")
async def pool_stats():
    from app.services.email_draft_pool_service import get_email_draft_pool
    return await get_email_draft_pool().stats()


@router.post("/pool")
async def pool_add(req: PoolAddRequest):
    from app.services.email_draft_pool_service import get_email_draft_pool
    d = await get_email_draft_pool().add_draft(
        account_id=req.account_id,
        to=req.to,
        subject=req.subject,
        body=req.body,
        thread_id=req.thread_id,
        meta=req.meta,
    )
    return d.to_dict()


@router.get("/pool/{draft_id}")
async def pool_get(draft_id: str):
    from app.services.email_draft_pool_service import get_email_draft_pool
    d = await get_email_draft_pool().get_draft(draft_id)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d.to_dict()


@router.patch("/pool/{draft_id}")
async def pool_update(draft_id: str, req: PoolUpdateRequest):
    from app.services.email_draft_pool_service import get_email_draft_pool
    d = await get_email_draft_pool().update_body(draft_id, req.body)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d.to_dict()


@router.post("/pool/{draft_id}/approve")
async def pool_approve(draft_id: str):
    from app.services.email_draft_pool_service import get_email_draft_pool
    d = await get_email_draft_pool().approve(draft_id)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d.to_dict()


@router.post("/pool/{draft_id}/reject")
async def pool_reject(draft_id: str, req: PoolRejectRequest):
    from app.services.email_draft_pool_service import get_email_draft_pool
    d = await get_email_draft_pool().reject(draft_id, reason=req.reason)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d.to_dict()
