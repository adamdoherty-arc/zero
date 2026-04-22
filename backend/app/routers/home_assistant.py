"""
Home Assistant bridge — thin REST wrapper over app.services.home_assistant_service.

Endpoints are intentionally minimal: status, list/get state, call service. The
Reachy-side "gesture on HA event" loop is not wired here; add a scheduler job
or websocket subscriber when the integration proves useful.
"""

from typing import Optional
import structlog

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.home_assistant_service import get_home_assistant_service

router = APIRouter()
logger = structlog.get_logger()


class HaServiceCall(BaseModel):
    domain: str = Field(..., description="e.g. 'light', 'switch', 'media_player'")
    service: str = Field(..., description="e.g. 'turn_on', 'toggle'")
    data: Optional[dict] = Field(default=None, description="Service data, e.g. {'entity_id': 'light.kitchen'}")


@router.get("/status")
async def status():
    return await get_home_assistant_service().get_status()


@router.get("/states")
async def list_states():
    svc = get_home_assistant_service()
    if not svc.configured:
        raise HTTPException(503, {"error": "home_assistant_not_configured"})
    return await svc.list_states()


@router.get("/states/{entity_id}")
async def get_state(entity_id: str):
    svc = get_home_assistant_service()
    if not svc.configured:
        raise HTTPException(503, {"error": "home_assistant_not_configured"})
    return await svc.get_state(entity_id)


@router.post("/service")
async def call_service(request: HaServiceCall):
    svc = get_home_assistant_service()
    if not svc.configured:
        raise HTTPException(503, {"error": "home_assistant_not_configured"})
    return await svc.call_service(request.domain, request.service, request.data)
