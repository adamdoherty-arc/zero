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


def get_audio_capture(
    *,
    mic_device_index: int | None = None,
    system_device_index: int | None = None,
):
    """
    Return the singleton AudioCapture, (re)configuring device selection if the
    caller passes new device indices. Creating a new instance is the only way
    to swap devices because pyaudiowpatch streams are bound at construction.
    """
    global _audio_capture
    from app.services.meeting_audio_capture import AudioCapture, find_default_mic_index
    settings = get_settings()

    if mic_device_index is None:
        mic_device_index = find_default_mic_index(
            preferred_name=settings.preferred_mic_device_name,
            prefer_reachy=True,
        )

    needs_new = (
        _audio_capture is None
        or (not _audio_capture.is_recording and (
            _audio_capture.mic_device_index != mic_device_index
            or _audio_capture.system_device_index != system_device_index
        ))
    )
    if needs_new:
        _audio_capture = AudioCapture(
            sample_rate=settings.sample_rate,
            mic_device_index=mic_device_index,
            system_device_index=system_device_index,
        )
    return _audio_capture


async def start_recording(
    db: AsyncSession,
    meeting_id: str | None = None,
    title: str | None = None,
    source: str = "mixed",
    mic_device_index: int | None = None,
    system_device_index: int | None = None,
) -> dict:
    settings = get_settings()
    capture = get_audio_capture(
        mic_device_index=mic_device_index,
        system_device_index=system_device_index,
    )
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
        sample_rate=settings.sample_rate,
        channels=1,
        source=source,
    )
    db.add(recording)
    await db.commit()

    capture.start(output_path, source=source)

    # Persist the device name AFTER capture.start populates it from the live stream.
    if capture.mic_device_name:
        recording.mic_device_name = capture.mic_device_name
        await db.commit()

    if settings.reachy_tts_confirmations:
        asyncio.create_task(_reachy_say_quiet("Recording started"))

    # Wave 4: flip Reachy into meeting mode so it looks at the active speaker
    # via DoA and plays periodic attentive gestures.
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        asyncio.create_task(get_reachy_presence_service().start_meeting_mode(meeting.id))
    except Exception:
        pass

    return {
        "meeting_id": meeting.id,
        "recording_id": recording.id,
        "file_path": str(output_path),
        "mic_device_name": capture.mic_device_name,
    }


async def stop_recording(db: AsyncSession) -> dict | None:
    settings = get_settings()
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

        if settings.reachy_tts_confirmations:
            asyncio.create_task(_reachy_say_quiet("Meeting saved"))

        # Wave 4: leave meeting mode and play an acknowledgement gesture.
        try:
            from app.services.reachy_presence_service import get_reachy_presence_service
            asyncio.create_task(get_reachy_presence_service().stop_meeting_mode())
        except Exception:
            pass

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
        if get_settings().reachy_tts_confirmations:
            asyncio.create_task(_reachy_say_quiet("Summary ready"))
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


async def _reachy_say_quiet(text: str) -> None:
    """Fire-and-forget Reachy TTS. Never raises; just logs on failure."""
    try:
        from app.services.reachy_service import get_reachy_service
        service = get_reachy_service()
        if not await service.is_connected():
            return
        await service.say(text)
    except Exception as e:
        logger.debug("reachy_tts_skipped", text=text, error=str(e))


def get_recording_status() -> dict:
    capture = get_audio_capture()
    return {
        "is_recording": capture.is_recording,
        "duration_seconds": capture.duration_seconds,
        "audio_levels": capture.audio_levels if capture.is_recording else None,
        "mic_device_name": capture.mic_device_name,
    }
