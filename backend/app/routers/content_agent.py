"""
Content Agent API endpoints.
REST API for managing content topics, examples, rules, generation, and performance.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import structlog

from app.models.content_agent import (
    ContentTopic, ContentTopicCreate, ContentTopicUpdate,
    ContentTopicStatus, ContentExample, ContentExampleCreate,
    ContentGenerateRequest, ContentGenerateResponse,
    RuleGenerateRequest, RuleUpdateRequest,
    ContentAgentStats,
)
from app.services.content_agent_service import get_content_agent_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================
# TOPICS
# ============================================

@router.get("/topics", response_model=List[ContentTopic])
async def list_topics(
    status: Optional[ContentTopicStatus] = Query(None),
    niche: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
):
    """List content topics."""
    service = get_content_agent_service()
    return await service.list_topics(
        status=status.value if status else None,
        niche=niche,
        platform=platform,
    )


@router.post("/topics", response_model=ContentTopic)
async def create_topic(data: ContentTopicCreate):
    """Create a content topic."""
    service = get_content_agent_service()
    return await service.create_topic(data)


@router.get("/topics/{topic_id}", response_model=ContentTopic)
async def get_topic(topic_id: str):
    """Get a content topic with rules."""
    service = get_content_agent_service()
    topic = await service.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.patch("/topics/{topic_id}", response_model=ContentTopic)
async def update_topic(topic_id: str, updates: ContentTopicUpdate):
    """Update a content topic."""
    service = get_content_agent_service()
    topic = await service.update_topic(topic_id, updates)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str):
    """Delete a content topic."""
    service = get_content_agent_service()
    deleted = await service.delete_topic(topic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "deleted", "topic_id": topic_id}


# ============================================
# EXAMPLES
# ============================================

@router.get("/topics/{topic_id}/examples", response_model=List[ContentExample])
async def list_examples(
    topic_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """List examples for a content topic."""
    service = get_content_agent_service()
    return await service.list_examples(topic_id, limit=limit)


@router.post("/topics/{topic_id}/examples", response_model=ContentExample)
async def add_example(topic_id: str, data: ContentExampleCreate):
    """Add an example to a content topic."""
    data.topic_id = topic_id
    service = get_content_agent_service()
    return await service.add_example(data)


@router.delete("/examples/{example_id}")
async def delete_example(example_id: str):
    """Delete a content example."""
    service = get_content_agent_service()
    deleted = await service.delete_example(example_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Example not found")
    return {"status": "deleted", "example_id": example_id}


# ============================================
# RULES
# ============================================

@router.post("/topics/{topic_id}/generate-rules")
async def generate_rules(topic_id: str, req: Optional[RuleGenerateRequest] = None):
    """Generate content rules from examples using LLM."""
    service = get_content_agent_service()
    focus = req.focus if req else None
    rules = await service.generate_rules(topic_id, focus=focus)
    return {"topic_id": topic_id, "rules": rules, "count": len(rules)}


@router.patch("/rules", response_model=ContentTopic)
async def update_rule(req: RuleUpdateRequest):
    """Update a specific rule text."""
    service = get_content_agent_service()
    topic = await service.update_rule(req)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic or rule not found")
    return topic


@router.delete("/topics/{topic_id}/rules/{rule_id}", response_model=ContentTopic)
async def delete_rule(topic_id: str, rule_id: str):
    """Delete a rule from a topic."""
    service = get_content_agent_service()
    topic = await service.delete_rule(topic_id, rule_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


# ============================================
# CONTENT GENERATION
# ============================================

@router.post("/generate", response_model=ContentGenerateResponse)
async def generate_content(req: ContentGenerateRequest):
    """Generate content via AIContentTools."""
    service = get_content_agent_service()
    return await service.generate_content(req)


@router.get("/performance")
async def list_performance(
    topic_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List content performance records."""
    from sqlalchemy import select
    from app.infrastructure.database import get_session
    from app.db.models import ContentPerformanceModel

    async with get_session() as session:
        query = select(ContentPerformanceModel).order_by(
            ContentPerformanceModel.synced_at.desc()
        )
        if topic_id:
            query = query.where(ContentPerformanceModel.topic_id == topic_id)
        query = query.limit(limit)

        result = await session.execute(query)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "topic_id": r.topic_id,
                "platform": r.platform,
                "content_type": r.content_type,
                "views": r.views,
                "likes": r.likes,
                "comments": r.comments,
                "shares": r.shares,
                "engagement_rate": r.engagement_rate,
                "performance_score": r.performance_score,
                "rules_applied": r.rules_applied or [],
                "posted_at": r.posted_at.isoformat() if r.posted_at else None,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None,
            }
            for r in rows
        ]


@router.post("/sync-performance")
async def sync_performance(topic_id: Optional[str] = Query(None)):
    """Trigger performance sync from AIContentTools."""
    service = get_content_agent_service()
    updated = await service.sync_performance_metrics(topic_id)
    return {"status": "synced", "updated": updated}


# ============================================
# RESEARCH & IMPROVEMENT
# ============================================

@router.post("/topics/{topic_id}/research-trends")
async def research_trends(topic_id: str):
    """Research content trends for a topic."""
    service = get_content_agent_service()
    return await service.research_content_trends(topic_id)


@router.post("/topics/{topic_id}/competitor-analysis")
async def competitor_analysis(topic_id: str):
    """Run competitor analysis for a topic."""
    service = get_content_agent_service()
    return await service.run_competitor_analysis(topic_id)


@router.post("/improvement-cycle")
async def run_improvement_cycle(topic_id: Optional[str] = Query(None)):
    """Run the self-improvement cycle."""
    service = get_content_agent_service()
    return await service.run_improvement_cycle(topic_id)


# ============================================
# STATS
# ============================================

@router.get("/stats")
async def get_stats():
    """Get content agent statistics."""
    service = get_content_agent_service()
    return await service.get_stats()
