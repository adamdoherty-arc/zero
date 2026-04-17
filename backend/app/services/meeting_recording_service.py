"""Meeting recording orchestration: start/stop, meeting management, pipeline trigger."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MeetingModel, MeetingRecordingModel
from app.infrastructure.config import get_settings, get_recordings_path
from app.infrastructure.database import get_session
logger = structlog.get_logger(__name__)

_audio_capture = None


def get_audio_capture():
    global _audio_capture
    if _audio_capture is None:
        from app.services.meeting_audio_capture import AudioCapture
        settings = get_settings()
        _audio_capture = AudioCapture(sample_rate=settings.sample_rate)
    return _audio_capture


async def start_recording(db: AsyncSession, meeting_id: str | None = None,
                          title: str | None = None, source: str = "mixed") -> dict:
    capture = get_audio_capture()
    if capture.is_recording:
        raise RuntimeError("Already recording")

    if meeting_id:
        result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
        meeting = result.scalar_one_or_none()
        if not meeting:
            raise ValueError(f"Meeting {meeting_id} not found")
        meeting.status = "recording"
    else:
        meeting = MeetingModel(
            id=uuid.uuid4().hex,
            title=title or f"Recording {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            start_time=datetime.now(timezone.utc),
            status="recording",
        )
        db.add(meeting)

    await db.commit()
    await db.refresh(meeting)

    recordings_dir = get_recordings_path()
    recordings_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{meeting.id}_{timestamp}.wav"
    output_path = recordings_dir / filename

    recording = MeetingRecordingModel(
        id=uuid.uuid4().hex,
        meeting_id=meeting.id,
        file_path=str(output_path),
        format="wav",
        sample_rate=get_settings().sample_rate,
        channels=1,
        source=source,
    )
    db.add(recording)
    await db.commit()

    capture.start(output_path, source=source)
    return {"meeting_id": meeting.id, "recording_id": recording.id, "file_path": str(output_path)}


async def stop_recording(db: AsyncSession) -> dict | None:
    capture = get_audio_capture()
    if not capture.is_recording:
        return None

    duration = capture.duration_seconds
    output_path = capture.stop()
    if output_path is None:
        return None

    file_size = output_path.stat().st_size if output_path.exists() else 0

    result = await db.execute(
        select(MeetingRecordingModel).where(MeetingRecordingModel.file_path == str(output_path))
    )
    recording = result.scalar_one_or_none()
    if recording:
        recording.duration_seconds = duration
        recording.file_size_bytes = file_size

        meeting_result = await db.execute(select(MeetingModel).where(MeetingModel.id == recording.meeting_id))
        meeting = meeting_result.scalar_one_or_none()
        if meeting:
            meeting.status = "processing"
            meeting.end_time = datetime.now(timezone.utc)
            meeting.duration_seconds = int(duration)

        await db.commit()

        meeting_id = recording.meeting_id
        asyncio.create_task(_run_processing_pipeline(meeting_id))

        return {
            "meeting_id": meeting_id, "recording_id": recording.id,
            "duration_seconds": duration, "file_path": str(output_path), "file_size_bytes": file_size,
        }
    return None


async def _run_processing_pipeline(meeting_id: str) -> None:
    try:
        from app.services.meeting_processing_pipeline import process_meeting_recording
        async with get_session() as db:
            await process_meeting_recording(meeting_id, db)
            logger.info("meeting_pipeline_complete", meeting_id=meeting_id)
    except Exception as e:
        logger.error("meeting_pipeline_failed", meeting_id=meeting_id, error=str(e))
        try:
            async with get_session() as db:
                result = await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
                meeting = result.scalar_one_or_none()
                if meeting:
                    meeting.status = "failed"
                    await db.commit()
        except Exception:
            logger.error("failed_to_mark_meeting_failed", meeting_id=meeting_id)


def get_recording_status() -> dict:
    capture = get_audio_capture()
    return {
        "is_recording": capture.is_recording,
        "duration_seconds": capture.duration_seconds,
        "audio_levels": capture.audio_levels if capture.is_recording else None,
    }
