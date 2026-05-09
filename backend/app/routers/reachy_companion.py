"""Reachy companion console API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.reachy_companion import (
    CompanionEvent,
    CompanionEventCreate,
    CompanionModeRequest,
    CompanionPolicy,
    CompanionPolicyPatch,
    CompanionSkillTriggerResponse,
)
from app.services.reachy_companion_service import get_reachy_companion_service

router = APIRouter()


@router.get("/status")
async def companion_status():
    return await get_reachy_companion_service().get_status()


@router.get("/events", response_model=list[CompanionEvent])
async def companion_events(limit: int = Query(50, ge=1, le=300)):
    return get_reachy_companion_service().list_events(limit=limit)


@router.post("/events", response_model=CompanionEvent)
async def companion_create_event(event: CompanionEventCreate):
    return get_reachy_companion_service().record_event(event)


@router.get("/timeline", response_model=list[CompanionEvent])
async def companion_timeline(limit: int = Query(50, ge=1, le=300)):
    return get_reachy_companion_service().list_events(limit=limit)


@router.get("/policy", response_model=CompanionPolicy)
async def companion_policy():
    return get_reachy_companion_service().get_policy()


@router.patch("/policy", response_model=CompanionPolicy)
async def companion_policy_update(patch: CompanionPolicyPatch):
    return get_reachy_companion_service().update_policy(patch)


@router.post("/modes", response_model=CompanionPolicy)
async def companion_set_mode(request: CompanionModeRequest):
    return await get_reachy_companion_service().set_mode(
        request.mode,
        reason=request.reason,
        apply_actions=request.apply_actions,
    )


@router.get("/skills")
async def companion_skills():
    return {"skills": [skill.model_dump() for skill in get_reachy_companion_service().list_skills()]}


@router.post("/skills/{skill_id}/trigger", response_model=CompanionSkillTriggerResponse)
async def companion_trigger_skill(skill_id: str):
    try:
        return await get_reachy_companion_service().trigger_skill(skill_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

