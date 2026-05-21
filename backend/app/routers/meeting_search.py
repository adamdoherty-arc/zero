"""Meeting search endpoint."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import select, func
import structlog

from app.db.models import MeetingTranscriptSegmentModel  # type: ignore
from app.infrastructure.database import get_session
from app.models.meeting import MeetingSearchResponse, MeetingSearchResult

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/")
async def search_meetings(
    q: str = Query(..., min_length=1),
    search_type: str = Query("hybrid"),
    limit: int = Query(20, ge=1, le=100),
    speaker: str | None = Query(default=None, description="Filter to a specific diarized speaker label"),
):
    from app.services.meeting_search_service import get_meeting_search_service
    search_svc = get_meeting_search_service()
    async with get_session() as db:
        # Speaker-aware path: if a speaker filter is set, narrow the
        # transcript segments first then merge results. v1 keeps the
        # filter in-Python until meeting_search_service grows native
        # speaker support.
        results = await search_svc.search(q, db, search_type=search_type, limit=limit * 2 if speaker else limit)
        if speaker:
            spk_lc = speaker.lower()
            results = [
                r for r in results
                if str(r.get("speaker") or "").lower() == spk_lc
                or spk_lc in str(r.get("speaker") or "").lower()
            ][:limit]
        return MeetingSearchResponse(
            results=[MeetingSearchResult(**r) for r in results],
            total=len(results),
            query=q,
        )


@router.get("/speakers")
async def list_speakers(days: int = Query(90, ge=1, le=365)):
    """F-62 — distinct speaker labels seen across recent meetings.

    Returns a list of ``{speaker, segments}`` sorted by frequency so the
    UI dropdown can lead with the most-talkative attendees. Anonymous
    SPEAKER_XX labels are bucketed at the end so users see real names
    first."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    async with get_session() as db:
        rows = (
            await db.execute(
                select(
                    MeetingTranscriptSegmentModel.speaker,
                    func.count().label("n"),
                )
                .where(MeetingTranscriptSegmentModel.speaker.is_not(None))
                .group_by(MeetingTranscriptSegmentModel.speaker)
                .order_by(func.count().desc())
                .limit(50)
            )
        ).all()
    named: list[dict] = []
    anonymous: list[dict] = []
    for spk, n in rows:
        label = str(spk or "").strip()
        if not label:
            continue
        item = {"speaker": label, "segments": int(n)}
        if label.upper().startswith("SPEAKER_"):
            anonymous.append(item)
        else:
            named.append(item)
    return {"named": named, "anonymous": anonymous, "since_days": days}
