"""
Research Agent API endpoints.
REST API for managing research topics, findings, and the self-improvement cycle.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.research import (
    ResearchTopic, ResearchTopicCreate, ResearchTopicUpdate,
    ResearchTopicStatus, ResearchFinding, FindingStatus,
    ResearchCycleResult, ResearchStats,
)
from app.services.research_service import get_research_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================
# TOPICS
# ============================================

@router.get("/topics", response_model=List[ResearchTopic])
async def list_topics(
    status: Optional[ResearchTopicStatus] = Query(None, description="Filter by status"),
):
    """List research topics."""
    service = get_research_service()
    return await service.list_topics(status=status)


@router.post("/topics", response_model=ResearchTopic)
async def create_topic(topic_data: ResearchTopicCreate):
    """Create a new research topic."""
    service = get_research_service()
    return await service.create_topic(topic_data)


@router.get("/topics/{topic_id}", response_model=ResearchTopic)
async def get_topic(topic_id: str):
    """Get a specific research topic."""
    service = get_research_service()
    topic = await service.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.patch("/topics/{topic_id}", response_model=ResearchTopic)
async def update_topic(topic_id: str, updates: ResearchTopicUpdate):
    """Update a research topic."""
    service = get_research_service()
    topic = await service.update_topic(topic_id, updates)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str):
    """Delete a research topic."""
    service = get_research_service()
    deleted = await service.delete_topic(topic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "deleted", "topic_id": topic_id}


@router.post("/topics/seed")
async def seed_default_topics():
    """Seed default research topics."""
    service = get_research_service()
    created = await service.seed_default_topics()
    return {
        "status": "seeded",
        "created": len(created),
        "topics": [{"id": t.id, "name": t.name} for t in created],
    }


# ============================================
# FINDINGS
# ============================================

@router.get("/findings", response_model=List[ResearchFinding])
async def list_findings(
    topic_id: Optional[str] = Query(None, description="Filter by topic ID"),
    status: Optional[FindingStatus] = Query(None, description="Filter by status"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Minimum composite score"),
    limit: int = Query(50, ge=1, le=200, description="Maximum findings to return"),
):
    """List research findings with optional filters."""
    service = get_research_service()
    return await service.list_findings(
        topic_id=topic_id, status=status, min_score=min_score, limit=limit
    )


@router.get("/findings/top", response_model=List[ResearchFinding])
async def get_top_findings(
    limit: int = Query(10, ge=1, le=50, description="Number of top findings"),
):
    """Get top findings by composite score."""
    service = get_research_service()
    return await service.list_findings(limit=limit)


@router.get("/findings/{finding_id}", response_model=ResearchFinding)
async def get_finding(finding_id: str):
    """Get a specific finding."""
    service = get_research_service()
    finding = await service.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.post("/findings/{finding_id}/review", response_model=ResearchFinding)
async def review_finding(finding_id: str):
    """Mark a finding as reviewed."""
    service = get_research_service()
    finding = await service.review_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.post("/findings/{finding_id}/dismiss", response_model=ResearchFinding)
async def dismiss_finding(finding_id: str):
    """Dismiss a finding as not relevant."""
    service = get_research_service()
    finding = await service.dismiss_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.post("/findings/{finding_id}/create-task")
async def create_task_from_finding(finding_id: str):
    """Create a Legion task from a research finding."""
    service = get_research_service()
    result = await service.create_task_from_finding(finding_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ============================================
# RESEARCH CYCLES
# ============================================

@router.post("/cycle/run")
async def run_daily_cycle():
    """Manually trigger the daily research cycle."""
    service = get_research_service()
    return await service.run_daily_cycle()


@router.post("/cycle/deep-dive")
async def run_weekly_deep_dive():
    """Manually trigger the weekly deep dive research."""
    service = get_research_service()
    return await service.run_weekly_deep_dive()


@router.get("/cycles", response_model=List[ResearchCycleResult])
async def get_recent_cycles(
    limit: int = Query(10, ge=1, le=50, description="Number of recent cycles"),
):
    """Get recent research cycle history."""
    service = get_research_service()
    return await service.get_recent_cycles(limit=limit)


# ============================================
# INTELLIGENCE
# ============================================

@router.get("/stats", response_model=ResearchStats)
async def get_stats():
    """Get research pipeline statistics."""
    service = get_research_service()
    return await service.get_stats()


@router.get("/knowledge")
async def get_knowledge_summary(
    topic: Optional[str] = Query(None, description="Filter by topic keyword"),
):
    """Get knowledge base summary."""
    service = get_research_service()
    summary = await service.get_knowledge_summary(topic=topic)
    return {"summary": summary}


@router.get("/knowledge/search", response_model=List[ResearchFinding])
async def search_knowledge(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search the knowledge base."""
    service = get_research_service()
    return await service.search_knowledge(q, limit=limit)


@router.post("/feedback")
async def submit_feedback(
    finding_id: str = Query(..., description="Finding ID"),
    action: str = Query(..., description="Feedback action: useful, not_useful, dismissed"),
):
    """Submit feedback on a finding for self-improvement."""
    if action not in ("useful", "not_useful", "dismissed", "created_task"):
        raise HTTPException(status_code=400, detail="Invalid action")
    service = get_research_service()
    await service.record_feedback(finding_id, action)
    return {"status": "recorded", "finding_id": finding_id, "action": action}


@router.post("/recalibrate")
async def recalibrate():
    """Trigger self-improvement recalibration based on accumulated feedback."""
    service = get_research_service()
    return await service.recalibrate_topics()
