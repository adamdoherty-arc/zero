"""
Research Rules API endpoints.
Dynamic rules engine for scoring, categorization, and auto-actions on research findings.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.models.research_rules import (
    ResearchRule, ResearchRuleCreate, ResearchRuleUpdate,
    RuleType, RuleStats, RuleSuggestion,
)
from app.services.research_rules_service import get_research_rules_service

router = APIRouter(prefix="/api/research/rules", tags=["research-rules"])


# --- Rule CRUD ---

@router.get("", response_model=list[ResearchRule])
async def list_rules(
    rule_type: Optional[RuleType] = None,
    enabled: Optional[bool] = None,
    category_id: Optional[str] = None,
):
    """List all research rules with optional filters."""
    service = get_research_rules_service()
    return await service.list_rules(rule_type=rule_type, enabled=enabled, category_id=category_id)


@router.post("", response_model=ResearchRule)
async def create_rule(data: ResearchRuleCreate):
    """Create a new research rule."""
    service = get_research_rules_service()
    return await service.create_rule(data)


@router.get("/stats", response_model=RuleStats)
async def get_rule_stats():
    """Get rules engine statistics and effectiveness metrics."""
    service = get_research_rules_service()
    return await service.get_stats()


@router.get("/{rule_id}", response_model=ResearchRule)
async def get_rule(rule_id: str):
    """Get a specific research rule."""
    service = get_research_rules_service()
    rule = await service.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/{rule_id}", response_model=ResearchRule)
async def update_rule(rule_id: str, data: ResearchRuleUpdate):
    """Update a research rule."""
    service = get_research_rules_service()
    rule = await service.update_rule(rule_id, data)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str):
    """Delete a research rule."""
    service = get_research_rules_service()
    success = await service.delete_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted", "rule_id": rule_id}


@router.post("/{rule_id}/toggle", response_model=ResearchRule)
async def toggle_rule(rule_id: str):
    """Toggle a rule's enabled/disabled state."""
    service = get_research_rules_service()
    rule = await service.toggle_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


# --- Intelligence ---

@router.post("/suggest", response_model=list[RuleSuggestion])
async def suggest_rules(limit: int = Query(3, ge=1, le=10)):
    """Use LLM to analyze patterns and suggest new rules."""
    service = get_research_rules_service()
    return await service.suggest_rules(limit=limit)


@router.post("/recalibrate")
async def recalibrate_rules():
    """Run auto-recalibration: disable ineffective rules, boost effective ones."""
    service = get_research_rules_service()
    return await service.recalibrate_rules()


@router.post("/seed")
async def seed_default_rules():
    """Seed default rules (only if none exist)."""
    service = get_research_rules_service()
    count = await service.seed_default_rules()
    return {"status": "seeded", "rules_created": count}
