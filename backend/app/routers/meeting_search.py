"""Meeting search endpoint."""

from fastapi import APIRouter, Query
import structlog

from app.infrastructure.database import get_session
from app.models.meeting import MeetingSearchResponse, MeetingSearchResult

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/")
async def search_meetings(
    q: str = Query(..., min_length=1),
    search_type: str = Query("hybrid"),
    limit: int = Query(20, ge=1, le=100),
):
    from app.services.meeting_search_service import get_meeting_search_service
    search_svc = get_meeting_search_service()
    async with get_session() as db:
        results = await search_svc.search(q, db, search_type=search_type, limit=limit)
        return MeetingSearchResponse(
            results=[MeetingSearchResult(**r) for r in results],
            total=len(results),
            query=q,
        )
