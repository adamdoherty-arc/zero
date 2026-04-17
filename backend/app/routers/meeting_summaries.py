"""Meeting summary endpoints."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, delete
import structlog

from app.db.models import MeetingSummaryModel, MeetingTranscriptSegmentModel, MeetingModel
from app.infrastructure.database import get_session
from app.models.meeting import SummaryResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/{meeting_id}")
async def get_summary(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(
            select(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
        )
        summary = result.scalar_one_or_none()
        if not summary:
            raise HTTPException(404, "Summary not found")
        return SummaryResponse.model_validate(summary)


@router.post("/{meeting_id}/generate")
async def generate_summary(meeting_id: str):
    async with get_session() as db:
        # Get transcript
        seg_result = await db.execute(
            select(MeetingTranscriptSegmentModel)
            .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
            .order_by(MeetingTranscriptSegmentModel.start_time)
        )
        segments = seg_result.scalars().all()
        if not segments:
            raise HTTPException(400, "No transcript segments found")

        meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")

        transcript_lines = [f"[{seg.speaker or 'Speaker'}]: {seg.text}" for seg in segments]
        transcript_text = "\n".join(transcript_lines)

        from app.services.meeting_summary_service import get_meeting_summary_service
        import uuid, time
        from app.infrastructure.config import get_settings

        summary_svc = get_meeting_summary_service()
        t0 = time.time()
        summary_data = await summary_svc.summarize(transcript_text, meeting_title=meeting.title)
        elapsed = int((time.time() - t0) * 1000)

        # Delete existing
        await db.execute(delete(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id))

        summary = MeetingSummaryModel(
            id=uuid.uuid4().hex,
            meeting_id=meeting_id,
            summary_text=summary_data["summary_text"],
            key_topics=summary_data.get("key_topics", []),
            action_items=summary_data.get("action_items", []),
            decisions=summary_data.get("decisions", []),
            model_used=get_settings().ollama_model,
            generation_time_ms=elapsed,
        )
        db.add(summary)
        await db.commit()
        await db.refresh(summary)
        return SummaryResponse.model_validate(summary)
