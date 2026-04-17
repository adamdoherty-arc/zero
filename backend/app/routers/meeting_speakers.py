"""Meeting speaker mapping endpoints."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, delete
import structlog

from app.db.models import MeetingSpeakerMappingModel
from app.infrastructure.database import get_session
from app.models.meeting import SpeakerMappingResponse, SpeakerMappingUpdate

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/{meeting_id}/speakers")
async def list_speakers(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(
            select(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        mappings = result.scalars().all()
        return [SpeakerMappingResponse.model_validate(m) for m in mappings]


@router.put("/{meeting_id}/speakers")
async def update_speakers(meeting_id: str, mappings: list[SpeakerMappingUpdate]):
    async with get_session() as db:
        # Delete existing
        await db.execute(
            delete(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        for m in mappings:
            db.add(MeetingSpeakerMappingModel(
                meeting_id=meeting_id,
                speaker_label=m.speaker_label,
                display_name=m.display_name,
            ))
        await db.commit()
        # Return updated
        result = await db.execute(
            select(MeetingSpeakerMappingModel).where(MeetingSpeakerMappingModel.meeting_id == meeting_id)
        )
        return [SpeakerMappingResponse.model_validate(m) for m in result.scalars().all()]
