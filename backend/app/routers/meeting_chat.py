"""Meeting RAG chat endpoint."""

from fastapi import APIRouter
import structlog

from app.infrastructure.database import get_session
from app.models.meeting import MeetingChatRequest, MeetingChatResponse, MeetingChatSource

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/")
async def meeting_chat(request: MeetingChatRequest):
    from app.services.meeting_rag_service import get_meeting_rag_service
    rag = get_meeting_rag_service()
    async with get_session() as db:
        result = await rag.query(request.message, db, meeting_id=request.meeting_id)
        return MeetingChatResponse(
            answer=result["answer"],
            sources=[MeetingChatSource(**s) for s in result["sources"]],
        )
