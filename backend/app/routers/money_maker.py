"""
Money Maker API endpoints.
REST API for generating, researching, and managing money-making ideas.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.money_maker import (
    MoneyIdea, MoneyIdeaCreate, MoneyIdeaUpdate, MoneyIdeaAction,
    IdeaStatus, IdeaCategory
)
from app.services.money_maker_service import get_money_maker_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================
# IDEA CRUD
# ============================================

@router.get("", response_model=List[MoneyIdea])
async def list_ideas(
    status: Optional[IdeaStatus] = Query(None, description="Filter by status"),
    category: Optional[IdeaCategory] = Query(None, description="Filter by category"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Minimum viability score"),
    limit: int = Query(50, ge=1, le=200, description="Maximum ideas to return")
):
    """List ideas with optional filters, sorted by viability score."""
    service = get_money_maker_service()
    return await service.list_ideas(
        status=status,
        category=category,
        min_score=min_score,
        limit=limit
    )


@router.get("/top", response_model=List[MoneyIdea])
async def get_top_ideas(
    limit: int = Query(10, ge=1, le=50, description="Number of top ideas to return")
):
    """Get top ideas by viability score."""
    service = get_money_maker_service()
    return await service.get_top_ideas(limit=limit)


@router.get("/stats")
async def get_stats():
    """Get pipeline statistics."""
    service = get_money_maker_service()
    return await service.get_stats()


@router.get("/{idea_id}", response_model=MoneyIdea)
async def get_idea(idea_id: str):
    """Get a specific idea by ID."""
    service = get_money_maker_service()
    idea = await service.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.post("", response_model=MoneyIdea)
async def create_idea(idea_data: MoneyIdeaCreate):
    """Create a new idea manually."""
    service = get_money_maker_service()
    return await service.create_idea(idea_data)


@router.patch("/{idea_id}", response_model=MoneyIdea)
async def update_idea(idea_id: str, updates: MoneyIdeaUpdate):
    """Update an idea."""
    service = get_money_maker_service()
    idea = await service.update_idea(idea_id, updates)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.delete("/{idea_id}")
async def delete_idea(idea_id: str):
    """Delete an idea."""
    service = get_money_maker_service()
    deleted = await service.delete_idea(idea_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Idea not found")
    return {"status": "deleted", "idea_id": idea_id}


# ============================================
# IDEA GENERATION & RESEARCH
# ============================================

@router.post("/generate", response_model=List[MoneyIdea])
async def generate_ideas(
    count: int = Query(5, ge=1, le=20, description="Number of ideas to generate"),
    category: Optional[IdeaCategory] = Query(None, description="Focus on specific category"),
    focus_areas: Optional[str] = Query(None, description="Comma-separated focus areas")
):
    """Generate new ideas using LLM."""
    service = get_money_maker_service()

    areas = None
    if focus_areas:
        areas = [a.strip() for a in focus_areas.split(",")]

    return await service.generate_ideas(
        count=count,
        category=category,
        focus_areas=areas
    )


@router.post("/{idea_id}/research", response_model=MoneyIdea)
async def research_idea(idea_id: str):
    """Research an idea using web search and LLM analysis."""
    service = get_money_maker_service()
    idea = await service.research_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


# ============================================
# IDEA ACTIONS
# ============================================

@router.post("/{idea_id}/pursue")
async def pursue_idea(idea_id: str, action: MoneyIdeaAction = MoneyIdeaAction()):
    """
    Mark idea as pursuing and optionally create sprint tasks.

    If sprint_id is provided in the action body, tasks will be created
    from the idea's first_steps.
    """
    service = get_money_maker_service()
    idea = await service.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    return await service.pursue_idea(idea_id, action)


@router.post("/{idea_id}/park", response_model=MoneyIdea)
async def park_idea(idea_id: str, action: MoneyIdeaAction = MoneyIdeaAction()):
    """Park an idea for later consideration."""
    service = get_money_maker_service()
    idea = await service.park_idea(idea_id, action)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.post("/{idea_id}/reject", response_model=MoneyIdea)
async def reject_idea(idea_id: str, action: MoneyIdeaAction = MoneyIdeaAction()):
    """Reject an idea with optional reason."""
    service = get_money_maker_service()
    idea = await service.reject_idea(idea_id, action)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


# ============================================
# AUTONOMOUS CYCLE
# ============================================

@router.post("/cycle/run")
async def run_daily_cycle():
    """
    Manually trigger the full daily cycle:
    1. Generate new ideas
    2. Research top unresearched ideas
    3. Rank all ideas
    4. Send notifications for high-potential ideas
    """
    service = get_money_maker_service()
    return await service.run_daily_cycle()
