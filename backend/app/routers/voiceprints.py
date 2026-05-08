"""Voice fingerprint enrollment & management.

Endpoints:
- POST /api/voiceprints/enroll       multipart upload of a WAV + display_name
- POST /api/voiceprints/enroll-path  enrol from a server-side path (host_agent flow)
- GET  /api/voiceprints              list enrolled identities
- DELETE /api/voiceprints/{id}       remove an identity
- POST /api/voiceprints/match        debug: compute embedding from WAV and report best match
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.meeting import (
    VoiceprintEnrollResponse,
    VoiceprintMatchResult,
    VoiceprintResponse,
)
from app.services.voiceprint_service import (
    DEFAULT_MATCH_THRESHOLD,
    get_voiceprint_service,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


def _audio_duration_seconds(path: Path) -> float:
    """Best-effort WAV duration. Returns 0.0 on any failure."""
    try:
        import wave

        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate)
    except Exception:  # noqa: BLE001
        return 0.0


@router.post("/enroll", response_model=VoiceprintEnrollResponse)
async def enroll_voiceprint(
    audio: UploadFile = File(...),
    display_name: str = Form(...),
    is_primary: bool = Form(False),
):
    if not display_name.strip():
        raise HTTPException(status_code=400, detail="display_name required")

    suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = Path(tmp.name)

    try:
        return await _enroll_from_path(tmp_path, display_name.strip(), is_primary)
    finally:
        try:
            tmp_path.unlink()
        except Exception:  # noqa: BLE001
            pass


class _EnrollPathPayload:
    """Light wrapper so the endpoint can take JSON when called from host_agent."""


@router.post("/enroll-path", response_model=VoiceprintEnrollResponse)
async def enroll_voiceprint_from_path(
    audio_path: str = Form(...),
    display_name: str = Form(...),
    is_primary: bool = Form(False),
    source_meeting_id: Optional[str] = Form(None),
):
    path = Path(audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Audio not found: {audio_path}")
    return await _enroll_from_path(path, display_name.strip(), is_primary, source_meeting_id)


async def _enroll_from_path(
    audio_path: Path,
    display_name: str,
    is_primary: bool,
    source_meeting_id: Optional[str] = None,
) -> VoiceprintEnrollResponse:
    service = get_voiceprint_service()
    try:
        embedding = service.compute_embedding(audio_path)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("voiceprint_compute_failed")
        raise HTTPException(status_code=500, detail=f"Embedding failed: {exc}") from exc

    duration = _audio_duration_seconds(audio_path)
    row, replaced = await service.enroll(
        display_name=display_name,
        embedding=embedding,
        samples_seconds=duration,
        is_primary=is_primary,
        source_meeting_id=source_meeting_id,
    )
    return VoiceprintEnrollResponse(
        voiceprint=VoiceprintResponse.model_validate(row),
        replaced_existing=replaced,
    )


@router.get("", response_model=list[VoiceprintResponse])
async def list_voiceprints():
    service = get_voiceprint_service()
    rows = await service.list_all()
    return [VoiceprintResponse.model_validate(r) for r in rows]


@router.delete("/{voiceprint_id}")
async def delete_voiceprint(voiceprint_id: int):
    service = get_voiceprint_service()
    deleted = await service.delete(voiceprint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Voiceprint not found")
    return {"deleted": True, "id": voiceprint_id}


@router.post("/match", response_model=Optional[VoiceprintMatchResult])
async def match_voiceprint(
    audio: UploadFile = File(...),
    threshold: float = Form(DEFAULT_MATCH_THRESHOLD),
):
    suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        tmp_path = Path(tmp.name)
    try:
        service = get_voiceprint_service()
        embedding = service.compute_embedding(tmp_path)
        result = await service.match(embedding, threshold=threshold)
        if result is None:
            return None
        return VoiceprintMatchResult(display_name=result[0], similarity=result[1])
    finally:
        try:
            tmp_path.unlink()
        except Exception:  # noqa: BLE001
            pass
