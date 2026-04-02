"""Persistent conversation memory API."""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class SessionCreate(BaseModel):
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    channel: str = "web"


@router.post("/sessions")
async def create_session(req: SessionCreate):
    from app.services.memory_service import get_memory_service
    return await get_memory_service().create_session(
        session_id=req.session_id,
        project_id=req.project_id,
        channel=req.channel,
    )


@router.get("/sessions")
async def list_sessions(limit: int = 20, include_archived: bool = False):
    from app.services.memory_service import get_memory_service
    return await get_memory_service().list_sessions(limit=limit, include_archived=include_archived)


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 50):
    from app.services.memory_service import get_memory_service
    return await get_memory_service().get_messages(session_id, limit=limit)


@router.get("/search")
async def search_conversations(q: str = Query(..., min_length=2), limit: int = 10):
    from app.services.memory_service import get_memory_service
    return await get_memory_service().search_conversations(q, limit=limit)
