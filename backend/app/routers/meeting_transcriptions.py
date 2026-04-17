"""Meeting transcription endpoints."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, delete
import structlog

from app.db.models import MeetingTranscriptSegmentModel, MeetingModel
from app.infrastructure.database import get_session
from app.models.meeting import TranscriptResponse, TranscriptSegmentResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/{meeting_id}")
async def get_transcript(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(
            select(MeetingTranscriptSegmentModel)
            .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
            .order_by(MeetingTranscriptSegmentModel.start_time)
        )
        segments = result.scalars().all()
        return TranscriptResponse(
            meeting_id=meeting_id,
            segments=[TranscriptSegmentResponse.model_validate(s) for s in segments],
            total_segments=len(segments),
        )


@router.post("/{meeting_id}/retranscribe")
async def retranscribe(meeting_id: str):
    async with get_session() as db:
        meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        meeting.status = "processing"
        await db.commit()

    # Run pipeline in background
    import asyncio
    from app.services.meeting_recording_service import _run_processing_pipeline
    asyncio.create_task(_run_processing_pipeline(meeting_id))
    return {"status": "retranscription_started", "meeting_id": meeting_id}
