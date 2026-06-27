"""
Council of Agents Router.
REST API for proposing, voting, and viewing council decisions.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.infrastructure.auth import require_auth
from app.models.agent_company import CouncilDecision, CouncilProposal
from app.services.council_service import get_council_service

router = APIRouter(prefix="/api/council", tags=["council"], dependencies=[Depends(require_auth)])


@router.post("/decisions", response_model=CouncilDecision, status_code=201)
async def propose_decision(req: CouncilProposal):
    """Submit a topic for council vote."""
    svc = get_council_service()
    return await svc.propose(req)


@router.post("/decisions/{decision_id}/vote", response_model=CouncilDecision)
async def conduct_vote(decision_id: str):
    """Run the 2-round debate + vote protocol."""
    svc = get_council_service()
    decision = await svc.get_decision(decision_id)
    if not decision:
        raise HTTPException(404, f"Decision {decision_id} not found")
    result = await svc.conduct_vote(decision_id)
    # RSN-5 (supervise 3c3ade8e): conduct_vote returns None when the decision is
    # concurrently deleted between the guard above and the tally write (RSN-3's
    # graceful bail). Without this check the None propagates into
    # response_model=CouncilDecision and FastAPI raises a 500 ResponseValidation
    # error instead of a clean 404.
    if result is None:
        raise HTTPException(404, f"Decision {decision_id} was deleted during the vote")
    return result


@router.get("/decisions", response_model=list[CouncilDecision])
async def list_decisions(
    status: Optional[str] = None, pending_only: bool = False, limit: int = 20
):
    # RSN-4 (supervise f8574c6d): the service supports pending_only (decision IS
    # NULL = an undecided proposal), but the router never exposed it. A caller
    # passing ?status=pending hit the `decision == "pending"` branch — a value
    # never written (only approve/reject/needs_revision/None) — so it always
    # returned []. Expose pending_only so undecided proposals are queryable.
    svc = get_council_service()
    return await svc.list_decisions(
        status=status, pending_only=pending_only, limit=limit
    )


@router.get("/decisions/{decision_id}", response_model=CouncilDecision)
async def get_decision(decision_id: str):
    svc = get_council_service()
    decision = await svc.get_decision(decision_id)
    if not decision:
        raise HTTPException(404, f"Decision {decision_id} not found")
    return decision
