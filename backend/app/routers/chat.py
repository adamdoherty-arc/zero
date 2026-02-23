"""
Ask Zero Chat API

Endpoints:
- POST /stream        - Send a message (SSE streaming)
- POST /message       - Send a message (non-streaming)
- GET  /sessions      - List active sessions
- GET  /sessions/{id} - Get session history
- DELETE /sessions/{id} - Delete a session
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import structlog

from app.services.chat_service import ChatService

router = APIRouter()
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = Field(None, description="None = new conversation")
    project_id: Optional[str] = Field(None, description="Scope context to a project")


class ChatMessageResponse(BaseModel):
    content: str
    session_id: str
    sources: List[Dict[str, Any]] = []
    model: str = ""


class SessionInfo(BaseModel):
    session_id: str
    title: Optional[str] = None
    project_id: Optional[str] = None
    message_count: int = 0
    created_at: str = ""
    last_active: str = ""


class SessionHistory(BaseModel):
    session_id: str
    messages: List[Dict[str, str]]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/stream")
async def send_message_stream(request: ChatMessageRequest):
    """Send a chat message and get a streaming SSE response."""
    service = ChatService()

    async def event_generator():
        try:
            async for chunk in service.chat_stream(
                message=request.message,
                session_id=request.session_id,
                project_id=request.project_id,
            ):
                yield chunk
        except Exception as e:
            import json
            yield f'data: {json.dumps({"type": "error", "content": str(e)})}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(request: ChatMessageRequest):
    """Send a chat message and get a complete response."""
    service = ChatService()
    try:
        result = await service.chat(
            message=request.message,
            session_id=request.session_id,
            project_id=request.project_id,
        )
        return ChatMessageResponse(
            content=result.content,
            session_id=result.session_id,
            sources=result.sources,
            model=result.model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", response_model=List[SessionInfo])
async def list_sessions():
    """List all active chat sessions."""
    sessions = ChatService.list_sessions()
    return [SessionInfo(**s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionHistory)
async def get_session_history(session_id: str):
    """Get conversation history for a session."""
    history = ChatService.get_session_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionHistory(session_id=session_id, messages=history)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    if ChatService.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")
