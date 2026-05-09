"""Wake-word + camera presence policy API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

router = APIRouter()


class PolicyPatch(BaseModel):
    wake_engine: str | None = Field(None, pattern="^(openwakeword|custom|off)$")
    wake_model: str | None = None
    custom_model_path: str | None = None
    presence_enabled: bool | None = None
    presence_grace_s: float | None = None
    presence_camera_id: str | None = None
    barge_in_grace_s: float | None = None
    notes: str | None = None


@router.get("/policy")
async def get_policy():
    from app.services.wake_presence_service import get_wake_presence_service
    return (await get_wake_presence_service().get_policy()).to_dict()


@router.put("/policy")
async def put_policy(patch: PolicyPatch = Body(default=PolicyPatch())):
    from app.services.wake_presence_service import get_wake_presence_service
    return (
        await get_wake_presence_service().update_policy(patch.model_dump(exclude_unset=True))
    ).to_dict()


@router.get("/snapshot")
async def snapshot():
    from app.services.wake_presence_service import get_wake_presence_service
    return await get_wake_presence_service().snapshot_policy()


@router.post("/presence/seen")
async def presence_seen():
    """Pulse from the vision pipeline: 'Adam is looking at me right now.'"""
    from app.services.wake_presence_service import get_wake_presence_service
    await get_wake_presence_service().saw_presence()
    return {"ok": True}
