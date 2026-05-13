"""
Triggers API — declarative event→action mapping on top of integrations.

A trigger says: "when `gmail.new_message` matches predicate X, run action Y".
Actions can be tool calls, vault writes, agent prompts, or webhook POSTs.

Storage: JSON file at ``backend/app/data/triggers/rules.json``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from app.services.triggers_service import get_triggers_service

router = APIRouter()


class TriggerRuleIn(BaseModel):
    name: str
    event: str  # e.g. "gmail.new_message", "linear.issue_assigned"
    predicate: dict[str, Any] = {}  # JSON-shaped: {"subject_contains": "invoice"}
    action: dict[str, Any]  # {"type": "vault_write|tool|webhook", "params": {...}}
    enabled: bool = True


@router.get("/")
async def list_rules():
    return {"rules": get_triggers_service().list_rules()}


@router.post("/")
async def create_rule(rule: TriggerRuleIn):
    svc = get_triggers_service()
    created = await svc.create_rule(rule.dict())
    return created


@router.put("/{rule_id}")
async def update_rule(rule_id: str, rule: TriggerRuleIn):
    svc = get_triggers_service()
    updated = await svc.update_rule(rule_id, rule.dict())
    if not updated:
        raise HTTPException(status_code=404, detail="rule not found")
    return updated


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str):
    svc = get_triggers_service()
    ok = await svc.delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"status": "deleted"}


class TestEventIn(BaseModel):
    event: str
    payload: dict[str, Any] = {}


@router.post("/test-fire")
async def test_fire(req: TestEventIn):
    """Fire a synthetic event so the user can sanity-check a rule without
    waiting for the next auto-fetch tick."""
    svc = get_triggers_service()
    matched = await svc.dispatch(req.event, req.payload)
    return {"matched": [m for m in matched]}


@router.get("/recent")
async def recent_firings(limit: int = 50):
    svc = get_triggers_service()
    return {"firings": svc.recent(limit=limit)}
