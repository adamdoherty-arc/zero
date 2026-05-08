"""Voice Bridge Router — control + turn-log endpoints for the host-side LiveKit process."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.services.voice_bridge_service import get_voice_bridge

router = APIRouter(
    prefix="/api/voice",
    tags=["voice-bridge"],
    dependencies=[Depends(require_auth)],
)


class TurnLogRequest(BaseModel):
    user_utterance: str = Field(..., max_length=4000)
    zero_reply: str = Field(..., max_length=16000)
    tool_calls: Optional[list[str]] = None


@router.get("/health")
async def health():
    svc = get_voice_bridge()
    return await svc.health()


@router.post("/enable")
async def enable():
    svc = get_voice_bridge()
    return await svc.enable()


@router.post("/disable")
async def disable():
    svc = get_voice_bridge()
    return await svc.disable()


@router.post("/turn")
async def log_turn(req: TurnLogRequest):
    svc = get_voice_bridge()
    return await svc.log_turn(
        user_utterance=req.user_utterance,
        zero_reply=req.zero_reply,
        tool_calls=req.tool_calls,
    )
