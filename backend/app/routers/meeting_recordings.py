"""Meeting recording start/stop/status endpoints.

When ZERO_HOST_AGENT_URL is configured, start/stop/status are forwarded to the
Zero Host Audio Agent — a small FastAPI service that runs on the Windows host
outside Docker so it can access pyaudiowpatch / sounddevice and the Reachy
Mini USB microphone. When unset, the endpoints fall back to the in-process
AudioCapture service (only useful when Zero's backend itself runs on the host).
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path
import httpx
import structlog

from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.models.meeting import (
    RecordingStartRequest,
    RecordingStatusResponse,
    RecordingMetadataResponse,
    AudioDevicesResponse,
)
from app.services.meeting_recording_service import start_recording, stop_recording, get_recording_status
from app.db.models import MeetingRecordingModel
from sqlalchemy import select

router = APIRouter()
logger = structlog.get_logger(__name__)


def _host_agent_url() -> str | None:
    url = get_settings().host_agent_url
    return url.rstrip("/") if url else None


async def _forward(method: str, path: str, *, json: dict | None = None) -> dict:
    """Forward to the host agent. Raises HTTPException on network or status failure."""
    base = _host_agent_url()
    if not base:
        raise HTTPException(503, "No host agent configured (ZERO_HOST_AGENT_URL unset)")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, f"{base}{path}", json=json)
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, resp.text)
            return resp.json() if resp.content else {}
    except httpx.RequestError as e:
        logger.warning("host_agent_unreachable", url=base, error=str(e))
        raise HTTPException(502, f"Host agent unreachable: {e}")


@router.get("/devices", response_model=AudioDevicesResponse)
async def list_devices():
    """
    Enumerate audio input devices visible to the recorder. When a host agent is
    configured this lists devices visible ON THE HOST (including Reachy Mini
    USB mic). Otherwise falls back to whatever the backend process can see.
    """
    if _host_agent_url():
        return await _forward("GET", "/devices")
    from app.services.meeting_audio_capture import list_audio_devices
    return list_audio_devices()


@router.post("/start")
async def start_recording_endpoint(request: RecordingStartRequest):
    if _host_agent_url():
        return await _forward("POST", "/record/start", json=request.model_dump(exclude_none=True))
    async with get_session() as db:
        try:
            return await start_recording(
                db,
                meeting_id=request.meeting_id,
                title=request.title,
                source=request.source,
                mic_device_index=request.mic_device_index,
                system_device_index=request.system_device_index,
            )
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/stop")
async def stop_recording_endpoint():
    if _host_agent_url():
        return await _forward("POST", "/record/stop")
    async with get_session() as db:
        result = await stop_recording(db)
        if result is None:
            raise HTTPException(400, "No active recording")
        return result


@router.get("/status")
async def recording_status():
    if _host_agent_url():
        return await _forward("GET", "/record/status")
    return get_recording_status()


@router.get("/capabilities")
async def recording_capabilities():
    """
    Report whether a real audio backend is reachable. When the host agent is
    configured, probe it. Otherwise inspect this process for pyaudiowpatch /
    sounddevice availability.
    """
    base = _host_agent_url()
    if base:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base}/health")
                ok = resp.status_code == 200
                return {
                    "can_record": ok,
                    "via": "host_agent",
                    "host_agent_url": base,
                    "message": None if ok else f"Host agent returned {resp.status_code}",
                }
        except httpx.RequestError as e:
            return {
                "can_record": False,
                "via": "host_agent",
                "host_agent_url": base,
                "message": f"Host agent unreachable: {e}",
            }

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
        "via": "local",
        "has_system_audio": has_system_audio,
        "has_mic": has_mic,
        "message": None if can_record else (
            "Audio recording requires pyaudiowpatch (system audio) or sounddevice (microphone). "
            "These are not installed in the Docker container. Configure ZERO_HOST_AGENT_URL to "
            "point at a Zero Host Audio Agent running on the host, or run Zero backend on the host."
        ),
    }


@router.post("/{meeting_id}/process")
async def process_meeting(meeting_id: str):
    """
    Kick off the Whisper transcription + diarization + summary pipeline for
    a meeting whose audio has already been recorded (e.g. via the host agent).
    Runs in the background; returns immediately.
    """
    import asyncio
    from app.services.meeting_processing_pipeline import process_meeting_recording

    async def _run():
        try:
            async with get_session() as db:
                await process_meeting_recording(meeting_id, db)
            # TTS: "Summary ready" after pipeline completes
            settings = get_settings()
            if settings.reachy_tts_confirmations:
                try:
                    from app.services.reachy_service import get_reachy_service
                    service = get_reachy_service()
                    if await service.is_connected():
                        await service.say("Summary ready")
                except Exception as e:
                    logger.debug("reachy_say_summary_ready_failed", error=str(e))
        except Exception as e:
            logger.error("meeting_pipeline_failed", meeting_id=meeting_id, error=str(e))
            try:
                from sqlalchemy import update
                from app.db.models import MeetingModel
                async with get_session() as db:
                    await db.execute(
                        update(MeetingModel).where(MeetingModel.id == meeting_id).values(status="failed")
                    )
                    await db.commit()
            except Exception:
                pass

    asyncio.create_task(_run())
    return {"meeting_id": meeting_id, "status": "processing_started"}


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
            mic_device_name=getattr(recording, "mic_device_name", None),
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
