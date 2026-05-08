"""
Sight API — wearable-agnostic vision endpoints.

  GET  /sight/providers            list providers + statuses + active id
  GET  /sight/active               status of the currently-active provider
  POST /sight/select               {"provider": "reachy"} — switch active
  GET  /sight/{id}/status          detailed status
  GET  /sight/{id}/frame.jpg       single latest JPEG
  GET  /sight/{id}/mjpeg           live stream (multipart/x-mixed-replace)
  POST /sight/{id}/ingest          multipart file upload — push providers
  POST /sight/{id}/audio-chunk     base64 PCM16 + sample_rate — push providers
  POST /sight/{id}/notify          push a TTS / text hint back to wearer

Same-origin URLs so `<img src>` works without token gymnastics.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import structlog

from app.services.sight import get_sight_registry

logger = structlog.get_logger()
router = APIRouter()


class SelectRequest(BaseModel):
    provider: str = Field(..., description="Provider id, e.g. 'reachy', 'meta_rayban'")


class AudioChunkRequest(BaseModel):
    pcm16_b64: str = Field(..., description="Base64-encoded PCM16 samples")
    sample_rate: int = Field(16000, ge=8000, le=48000)


class NotifyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.get("/providers")
async def list_providers():
    reg = get_sight_registry()
    statuses = await reg.list_statuses()
    return {
        "active": reg.get_active_id(),
        "eyes_off": reg.eyes_off,
        "providers": [s.to_dict() for s in statuses],
    }


class EyesOffRequest(BaseModel):
    eyes_off: bool = Field(..., description="True to disable every provider; False to re-enable.")


@router.get("/eyes-off")
async def get_eyes_off():
    reg = get_sight_registry()
    return {"eyes_off": reg.eyes_off}


@router.post("/eyes-off")
async def set_eyes_off(request: EyesOffRequest):
    """
    Global privacy kill switch. When ON, no provider returns frames, no
    push buffer accepts ingests, and in-memory rings are purged.
    """
    reg = get_sight_registry()
    result = await reg.set_eyes_off(request.eyes_off)
    return result


@router.get("/active")
async def active_status():
    reg = get_sight_registry()
    prov = reg.get_active()
    if prov is None:
        raise HTTPException(503, "No active sight provider")
    status = await prov.status()
    return status.to_dict()


@router.post("/select")
async def select_provider(request: SelectRequest):
    reg = get_sight_registry()
    ok = await reg.set_active(request.provider)
    if not ok:
        raise HTTPException(404, f"Unknown provider {request.provider!r}")
    return {"active": reg.get_active_id()}


@router.get("/{provider_id}/status")
async def provider_status(provider_id: str):
    reg = get_sight_registry()
    prov = reg.get(provider_id)
    if prov is None:
        raise HTTPException(404, f"Unknown provider {provider_id!r}")
    status = await prov.status()
    return status.to_dict()


@router.get("/{provider_id}/frame.jpg")
async def provider_frame(provider_id: str):
    reg = get_sight_registry()
    prov = reg.get(provider_id)
    if prov is None:
        raise HTTPException(404, f"Unknown provider {provider_id!r}")
    jpeg = await prov.get_latest_frame()
    if not jpeg:
        raise HTTPException(503, "No frame available")
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/{provider_id}/mjpeg")
async def provider_mjpeg(provider_id: str):
    reg = get_sight_registry()
    prov = reg.get(provider_id)
    if prov is None:
        raise HTTPException(404, f"Unknown provider {provider_id!r}")
    return StreamingResponse(
        prov.mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=sight-frame",
    )


@router.post("/{provider_id}/ingest")
async def provider_ingest(provider_id: str, file: UploadFile = File(...)):
    reg = get_sight_registry()
    prov = reg.get(provider_id)
    if prov is None:
        raise HTTPException(404, f"Unknown provider {provider_id!r}")
    data = await file.read()
    try:
        await prov.ingest_frame(data)
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
    return {"bytes": len(data), "provider": provider_id}


@router.post("/{provider_id}/audio-chunk")
async def provider_audio(provider_id: str, request: AudioChunkRequest):
    reg = get_sight_registry()
    prov = reg.get(provider_id)
    if prov is None:
        raise HTTPException(404, f"Unknown provider {provider_id!r}")
    try:
        await prov.ingest_audio_chunk(request.pcm16_b64, request.sample_rate)
    except NotImplementedError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/{provider_id}/notify")
async def provider_notify(provider_id: str, request: NotifyRequest):
    reg = get_sight_registry()
    prov = reg.get(provider_id)
    if prov is None:
        raise HTTPException(404, f"Unknown provider {provider_id!r}")
    ok = await prov.push_notification(request.text)
    return {"delivered": ok, "provider": provider_id}
