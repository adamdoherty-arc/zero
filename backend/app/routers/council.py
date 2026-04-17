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
    return await svc.conduct_vote(decision_id)


@router.get("/decisions", response_model=list[CouncilDecision])
async def list_decisions(status: Optional[str] = None, limit: int = 20):
    svc = get_council_service()
    return await svc.list_decisions(status=status, limit=limit)


@router.get("/decisions/{decision_id}", response_model=CouncilDecision)
async def get_decision(decision_id: str):
    svc = get_council_service()
    decision = await svc.get_decision(decision_id)
    if not decision:
        raise HTTPException(404, f"Decision {decision_id} not found")
    return decision
