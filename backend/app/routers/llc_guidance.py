"""
LLC Formation Guidance API endpoints.
Guides users through LLC creation for TikTok Shop, consulting, and multi-venture businesses.
"""

from fastapi import APIRouter, HTTPException
from typing import List, Optional
import structlog

from app.models.llc_guidance import (
    GuidanceRequest, GuidanceResponse, StateInfo,
)
from app.services.llc_guidance_service import get_llc_guidance_service

router = APIRouter()
logger = structlog.get_logger()


@router.get("/states", response_model=List[StateInfo])
async def list_states():
    """Get LLC filing info for all tracked states."""
    service = get_llc_guidance_service()
    return service.get_all_states()


@router.get("/states/{state_code}", response_model=StateInfo)
async def get_state(state_code: str):
    """Get LLC filing info for a specific state."""
    service = get_llc_guidance_service()
    info = service.get_state_info(state_code)
    if not info:
        raise HTTPException(status_code=404, detail=f"State '{state_code}' not found in our database")
    return info


@router.post("/recommend-states")
async def recommend_states(business_types: List[str]):
    """Get recommended states for LLC formation based on business type."""
    service = get_llc_guidance_service()
    return service.get_recommended_states(business_types)


@router.post("/guidance", response_model=GuidanceResponse)
async def generate_guidance(request: GuidanceRequest):
    """Generate comprehensive LLC formation guidance."""
    service = get_llc_guidance_service()
    return await service.generate_guidance(request)


@router.post("/ask")
async def ask_question(question: str, context: Optional[dict] = None):
    """Ask a specific LLC-related question."""
    if not question or len(question.strip()) < 5:
        raise HTTPException(status_code=400, detail="Question must be at least 5 characters")
    service = get_llc_guidance_service()
    answer = await service.answer_question(question, context)
    return {"question": question, "answer": answer}
