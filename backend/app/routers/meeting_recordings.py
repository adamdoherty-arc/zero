"""Meeting recording start/stop/status endpoints."""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import structlog

from app.infrastructure.database import get_session
from app.models.meeting import RecordingStartRequest, RecordingStatusResponse, RecordingMetadataResponse
from app.services.meeting_recording_service import start_recording, stop_recording, get_recording_status
from app.db.models import MeetingRecordingModel
from sqlalchemy import select

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/start")
async def start_recording_endpoint(request: RecordingStartRequest):
    async with get_session() as db:
        try:
            result = await start_recording(db, meeting_id=request.meeting_id, title=request.title, source=request.source)
            return result
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/stop")
async def stop_recording_endpoint():
    async with get_session() as db:
        result = await stop_recording(db)
        if result is None:
            raise HTTPException(400, "No active recording")
        return result


@router.get("/status")
async def recording_status():
    return get_recording_status()


@router.get("/capabilities")
async def recording_capabilities():
    """Check whether audio recording backends are available."""
    has_numpy_sf = False
    has_system_audio = False
    has_mic = False
    try:
        import numpy  # noqa: F401
        import soundfile  # noqa: F401
        has_numpy_sf = True
    except ImportError:
        pass
    try:
        import pyaudiowpatch  # noqa: F401
        has_system_audio = True
    except ImportError:
        pass
    try:
        import sounddevice  # noqa: F401
        has_mic = True
    except ImportError:
        pass
    can_record = has_numpy_sf and (has_system_audio or has_mic)
    return {
        "can_record": can_record,
        "has_system_audio": has_system_audio,
        "has_mic": has_mic,
        "message": None if can_record else (
            "Audio recording requires pyaudiowpatch (system audio) or sounddevice (microphone). "
            "These are not installed in the Docker container. Run Zero on the host for recording."
        ),
    }


@router.get("/{meeting_id}")
async def get_recording_metadata(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(
            select(MeetingRecordingModel).where(MeetingRecordingModel.meeting_id == meeting_id)
        )
        recording = result.scalar_one_or_none()
        if not recording:
            raise HTTPException(404, "Recording not found")
        return RecordingMetadataResponse(
            meeting_id=recording.meeting_id,
            duration_seconds=recording.duration_seconds,
            file_size_bytes=recording.file_size_bytes,
            format=recording.format,
            sample_rate=recording.sample_rate,
            channels=recording.channels,
        )


@router.get("/{meeting_id}/audio")
async def serve_audio(meeting_id: str):
    async with get_session() as db:
        result = await db.execute(
            select(MeetingRecordingModel).where(MeetingRecordingModel.meeting_id == meeting_id)
        )
        recording = result.scalar_one_or_none()
        if not recording:
            raise HTTPException(404, "Recording not found")

        audio_path = Path(recording.file_path)
        if not audio_path.exists():
            raise HTTPException(404, "Audio file not found on disk")

        from fastapi.responses import FileResponse
        return FileResponse(
            path=str(audio_path),
            media_type="audio/wav",
            filename=audio_path.name,
        )
