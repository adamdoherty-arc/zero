"""
Browser / computer-use API.

  GET    /api/browser-control/status        — backend availability + sessions
  POST   /api/browser-control/sessions      — open a URL, returns session id
  POST   /api/browser-control/sessions/{id}/click
  POST   /api/browser-control/sessions/{id}/type
  POST   /api/browser-control/sessions/{id}/extract
  POST   /api/browser-control/sessions/{id}/screenshot
  POST   /api/browser-control/sessions/{id}/close
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.services.browser_control_service import get_browser_control_service

router = APIRouter()


class OpenRequest(BaseModel):
    url: str
    timeout_s: float = 30.0


class ClickRequest(BaseModel):
    target: str


class TypeRequest(BaseModel):
    target: str
    value: str


class ExtractRequest(BaseModel):
    target: Optional[str] = None


@router.get("/status")
async def status():
    svc = get_browser_control_service()
    return {
        "available": svc.is_available(),
        "enabled": getattr(svc, "_enabled", False),
        "allowlist_count": len(getattr(svc, "_allowlist", ())),
        "session_count": len(svc.list_sessions()),
    }


@router.get("/sessions")
async def list_sessions():
    return {"sessions": get_browser_control_service().list_sessions()}


@router.post("/sessions")
async def open_session(req: OpenRequest):
    svc = get_browser_control_service()
    result = await svc.open(req.url, timeout_s=req.timeout_s)
    return result.__dict__


@router.post("/sessions/{session_id}/click")
async def click(session_id: str, req: ClickRequest):
    svc = get_browser_control_service()
    result = await svc.click(session_id, req.target)
    return result.__dict__


@router.post("/sessions/{session_id}/type")
async def type_text(session_id: str, req: TypeRequest):
    svc = get_browser_control_service()
    result = await svc.type_text(session_id, req.target, req.value)
    return result.__dict__


@router.post("/sessions/{session_id}/extract")
async def extract(session_id: str, req: ExtractRequest):
    svc = get_browser_control_service()
    result = await svc.extract_text(session_id, req.target)
    return result.__dict__


@router.post("/sessions/{session_id}/screenshot")
async def screenshot(session_id: str):
    svc = get_browser_control_service()
    result = await svc.screenshot(session_id)
    return result.__dict__


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: str):
    svc = get_browser_control_service()
    result = await svc.close(session_id)
    return result.__dict__
