"""Agent Approvals Router — tool-call gating for SecondBrain §6 guardrails.

Separate from the legacy general-purpose `approvals` router. This one is
tier-based (read | write_local | write_external | financial) and used by the
supervisor + specialist graph nodes to pause at tool boundaries.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.services.approval_queue_service import get_approval_queue

router = APIRouter(
    prefix="/api/agent-approvals",
    tags=["agent-approvals"],
    dependencies=[Depends(require_auth)],
)


class ApprovalDecision(BaseModel):
    # ACT-2 (supervise ee392aa1): a bare `str` let an invalid status (typo like
    # "approve", or "maybe") pass Pydantic and hit the service's raw ValueError,
    # surfacing as a generic 500 (logged as unhandled_exception). A Literal makes
    # FastAPI reject bad input with a structured 422 before the service runs.
    status: Literal["approved", "rejected"] = Field(..., description="approved | rejected")
    reason: Optional[str] = None
    decided_by: str = Field(default="user")


def _serialize(row) -> dict:
    from app.services.approval_queue_service import ApprovalQueueService

    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "tier": row.tier,
        "summary": row.summary,
        "arguments": row.arguments,
        "requested_by": row.requested_by,
        # A-1 (supervise zero 6a8c5562): report the status as of NOW. The raw
        # column still reads "pending" until the hourly sweep flips it, and the
        # frontend gates its Approve/Reject buttons on status === 'pending' —
        # so a dead approval used to render as actionable and 404 on click.
        "status": ApprovalQueueService.effective_status(row),
        "decision_reason": row.decision_reason,
        "decided_by": row.decided_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.get("")
async def list_approvals(status: Optional[str] = None, limit: int = 50):
    svc = get_approval_queue()
    rows = await svc.list(status=status, limit=limit)
    return [_serialize(r) for r in rows]


@router.get("/{approval_id}")
async def get_approval(approval_id: str):
    svc = get_approval_queue()
    row = await svc.get(approval_id)
    if not row:
        raise HTTPException(404, f"Approval {approval_id} not found")
    return _serialize(row)


@router.post("/{approval_id}/decide")
async def decide(approval_id: str, decision: ApprovalDecision):
    svc = get_approval_queue()
    row = await svc.decide(
        approval_id=approval_id,
        status=decision.status,
        decided_by=decision.decided_by,
        reason=decision.reason,
    )
    if not row:
        # ACT-7 (supervise fc9c5829): a None from decide() collapsed three very
        # different causes into one "not found or already decided" 404 — an unknown
        # id, an already-decided row, and (per the Fix-123 A1 guard) a still-pending
        # row whose expires_at has passed. An operator approving a financial request
        # two minutes past its 30-min TTL got the same message as a typo'd id, with
        # nothing to suggest the right action is "ask the agent to re-request".
        # Re-read the row and answer with the actual reason.
        existing = await svc.get(approval_id)
        if existing is None:
            raise HTTPException(404, f"Approval {approval_id} not found")
        effective = svc.effective_status(existing)
        if effective == "expired":
            raise HTTPException(
                410,
                f"Approval {approval_id} expired at {existing.expires_at.isoformat()} "
                f"and can no longer be approved; a new request must be raised.",
            )
        raise HTTPException(
            409,
            f"Approval {approval_id} is already '{effective}' and cannot be decided again.",
        )
    return _serialize(row)


@router.post("/expire-stale")
async def expire_stale():
    svc = get_approval_queue()
    n = await svc.expire_stale()
    return {"expired": n}
