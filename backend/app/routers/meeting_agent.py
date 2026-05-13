"""
Meeting Agent API.

  GET  /api/meeting-agent/status            — driver availability + counts
  POST /api/meeting-agent/sessions          — join a meeting
  GET  /api/meeting-agent/sessions          — list past + current sessions
  GET  /api/meeting-agent/sessions/{id}     — single session detail
  POST /api/meeting-agent/sessions/{id}/speak   — make Zero speak
  POST /api/meeting-agent/sessions/{id}/leave   — leave the meeting
  POST /api/meeting-agent/sessions/{id}/ingest  — push a transcript chunk
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.meeting_agent_service import get_meeting_agent_service

router = APIRouter()


class JoinRequest(BaseModel):
    url: str
    title: Optional[str] = None
    display_name: str = "Zero"


class SpeakRequest(BaseModel):
    text: str


class IngestRequest(BaseModel):
    text: str
    speaker: Optional[str] = None


@router.get("/status")
async def status():
    svc = get_meeting_agent_service()
    return {
        "available": svc.is_available(),
        "session_count": len(svc.list_sessions(limit=999)),
    }


@router.post("/sessions")
async def join(req: JoinRequest):
    svc = get_meeting_agent_service()
    try:
        session = await svc.join(req.url, title=req.title, display_name=req.display_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "id": session.id,
        "url": session.url,
        "title": session.title,
        "status": session.status,
        "error": session.error,
    }


@router.get("/sessions")
async def list_sessions(limit: int = 50):
    return {"sessions": get_meeting_agent_service().list_sessions(limit=limit)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    svc = get_meeting_agent_service()
    s = svc.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


@router.post("/sessions/{session_id}/speak")
async def speak(session_id: str, req: SpeakRequest):
    svc = get_meeting_agent_service()
    try:
        return await svc.speak(session_id, req.text)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="session not found") from e


@router.post("/sessions/{session_id}/leave")
async def leave(session_id: str):
    svc = get_meeting_agent_service()
    try:
        return await svc.leave(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="session not found") from e


@router.post("/sessions/{session_id}/ingest")
async def ingest(session_id: str, req: IngestRequest):
    svc = get_meeting_agent_service()
    await svc.ingest_transcript(session_id, req.text, speaker=req.speaker)
    return {"status": "ok"}
