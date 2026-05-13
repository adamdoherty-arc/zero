"""
Telegram channel API.

  GET  /api/telegram/status      — configured/running/counts
  POST /api/telegram/start       — start the poll loop
  POST /api/telegram/stop        — stop it
  POST /api/telegram/send        — send a message to a chat
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.telegram_channel_service import get_telegram_channel_service

router = APIRouter()


class SendRequest(BaseModel):
    chat_id: int
    text: str
    parse_mode: Optional[str] = None


@router.get("/status")
async def status():
    return get_telegram_channel_service().status()


@router.post("/start")
async def start():
    svc = get_telegram_channel_service()
    if not svc.is_configured():
        raise HTTPException(
            status_code=400, detail="TELEGRAM_BOT_TOKEN env not set"
        )
    await svc.start()
    return svc.status()


@router.post("/stop")
async def stop():
    svc = get_telegram_channel_service()
    await svc.stop()
    return svc.status()


@router.post("/send")
async def send(req: SendRequest):
    svc = get_telegram_channel_service()
    if not svc.is_configured():
        raise HTTPException(
            status_code=400, detail="TELEGRAM_BOT_TOKEN env not set"
        )
    return await svc.send(req.chat_id, req.text, parse_mode=req.parse_mode)
