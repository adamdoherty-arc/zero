"""Approval request endpoints — HITL workflows."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import structlog

router = APIRouter()
logger = structlog.get_logger()


class ApprovalCreateRequest(BaseModel):
    request_type: str
    title: str
    description: Optional[str] = None
    context_data: Optional[dict] = None
    initiated_by: str = "system"
    route: Optional[str] = None
    expires_in_hours: int = 24
    auto_action_on_expiry: str = "reject"


class ApprovalDecisionRequest(BaseModel):
    decision_by: str = "user"
    reason: Optional[str] = None


@router.get("/pending")
async def list_pending(limit: int = Query(default=50, le=200)):
    from app.services.approval_service import get_approval_service
    return await get_approval_service().list_pending(limit=limit)


@router.get("/all")
async def list_all(
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    from app.services.approval_service import get_approval_service
    return await get_approval_service().list_all(status=status, limit=limit, offset=offset)


@router.get("/stats")
async def approval_stats():
    from app.services.approval_service import get_approval_service
    return await get_approval_service().get_stats()


@router.get("/{request_id}")
async def get_request(request_id: str):
    from app.services.approval_service import get_approval_service
    req = await get_approval_service().get_request(request_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    return req


@router.post("")
async def create_request(req: ApprovalCreateRequest):
    from app.services.approval_service import get_approval_service
    return await get_approval_service().create_approval_request(**req.model_dump())


@router.post("/{request_id}/approve")
async def approve(request_id: str, body: ApprovalDecisionRequest):
    from app.services.approval_service import get_approval_service
    result = await get_approval_service().approve(request_id, body.decision_by, body.reason)
    if not result:
        raise HTTPException(400, "Cannot approve — request not found or not pending")
    return result


@router.post("/{request_id}/reject")
async def reject(request_id: str, body: ApprovalDecisionRequest):
    from app.services.approval_service import get_approval_service
    result = await get_approval_service().reject(request_id, body.decision_by, body.reason)
    if not result:
        raise HTTPException(400, "Cannot reject — request not found or not pending")
    return result
