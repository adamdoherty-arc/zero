"""Meeting CRUD endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func, delete
import structlog

from app.db.models import (
    MeetingModel, MeetingRecordingModel, MeetingTranscriptSegmentModel,
    MeetingSummaryModel, MeetingSpeakerMappingModel,
)
from app.infrastructure.database import get_session
from app.models.meeting import (
    MeetingCreate, MeetingUpdate, MeetingResponse, MeetingListResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/")
async def list_meetings(
    status: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    async with get_session() as db:
        query = select(MeetingModel)
        if status:
            query = query.where(MeetingModel.status == status)
        if search:
            query = query.where(MeetingModel.title.ilike(f"%{search}%"))
        query = query.order_by(MeetingModel.start_time.desc())

        # Count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        # Paginate
        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        meetings = result.scalars().all()

        return MeetingListResponse(
            meetings=[MeetingResponse.model_validate(m) for m in meetings],
            total=total,
        )


@router.post("/", status_code=201)
async def create_meeting(data: MeetingCreate):
    async with get_session() as db:
        meeting = MeetingModel(
            id=uuid.uuid4().hex,
            title=data.title,
            start_time=data.start_time,
            end_time=data.end_time,
            participants=data.participants or [],
            calendar_event_id=data.calendar_event_id,
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        return MeetingResponse.model_validate(meeting)


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        return MeetingResponse.model_validate(meeting)


@router.patch("/{meeting_id}")
async def update_meeting(meeting_id: str, data: MeetingUpdate):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(meeting, field, value)
        meeting.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(meeting)
        return MeetingResponse.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        # Delete vectors
        try:
            from app.services.meeting_vector_service import get_meeting_vector_service
            await get_meeting_vector_service().delete_meeting_vectors(meeting_id, db)
        except Exception:
            pass
        await db.delete(meeting)
        await db.commit()


@router.get("/{meeting_id}/export")
async def export_meeting(meeting_id: str, format: str = Query("markdown")):
    async with get_session() as db:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise HTTPException(404, "Meeting not found")

        # Get transcript
        seg_result = await db.execute(
            select(MeetingTranscriptSegmentModel)
            .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
            .order_by(MeetingTranscriptSegmentModel.start_time)
        )
        segments = seg_result.scalars().all()

        # Get summary
        sum_result = await db.execute(
            select(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
        )
        summary = sum_result.scalar_one_or_none()

        # Get speaker mappings
        spk_result = await db.execute(
            select(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        speaker_map = {s.speaker_label: s.display_name for s in spk_result.scalars().all()}

        # Build markdown
        lines = [f"# {meeting.title}", f"**Date:** {meeting.start_time.strftime('%Y-%m-%d %H:%M')}"]
        if meeting.duration_seconds:
            lines.append(f"**Duration:** {meeting.duration_seconds // 60}m {meeting.duration_seconds % 60}s")
        lines.append("")

        if summary:
            lines.append("## Summary")
            lines.append(summary.summary_text)
            lines.append("")
            if summary.key_topics:
                lines.append("### Key Topics")
                for topic in summary.key_topics:
                    lines.append(f"- {topic}")
                lines.append("")
            if summary.action_items:
                lines.append("### Action Items")
                for item in summary.action_items:
                    if isinstance(item, dict):
                        lines.append(f"- [ ] {item.get('description', '')} (Owner: {item.get('owner', 'Unassigned')})")
                    else:
                        lines.append(f"- [ ] {item}")
                lines.append("")

        if segments:
            lines.append("## Transcript")
            for seg in segments:
                speaker = speaker_map.get(seg.speaker, seg.speaker) or "Speaker"
                mins = int(seg.start_time // 60)
                secs = int(seg.start_time % 60)
                lines.append(f"**[{mins:02d}:{secs:02d}] {speaker}:** {seg.text}")
            lines.append("")

        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content="\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{meeting.title}.md"'},
        )
