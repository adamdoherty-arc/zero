"""Face fingerprint enrollment + management. Feature-52.

Endpoints (mirror voiceprints):
- POST   /api/faceprints/enroll        multipart upload of a face JPEG + display_name
- POST   /api/faceprints/enroll-meeting enrol the dominant face cluster from a meeting
- GET    /api/faceprints               list enrolled identities
- DELETE /api/faceprints/{id}          remove an identity
- POST   /api/faceprints/match         debug: match an uploaded crop, return best identity
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.meeting_face_service import (
    DEFAULT_MATCH_THRESHOLD,
    compute_embedding,
    extract_faces_from_meeting,
    get_faceprint_service,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


class FaceprintResponse(BaseModel):
    id: int
    display_name: str
    sample_count: int
    is_primary: bool
    source_meeting_id: Optional[str]
    face_crop_path: Optional[str]
    created_at: datetime


class FaceprintEnrollResponse(BaseModel):
    id: int
    display_name: str
    is_primary: bool
    replaced_existing: bool
    sample_count: int


class FaceprintMatchResult(BaseModel):
    matched: bool
    display_name: Optional[str] = None
    similarity: Optional[float] = None
    threshold: float


def _to_response(row) -> FaceprintResponse:
    return FaceprintResponse(
        id=row.id,
        display_name=row.display_name,
        sample_count=row.sample_count,
        is_primary=row.is_primary,
        source_meeting_id=row.source_meeting_id,
        face_crop_path=row.face_crop_path,
        created_at=row.created_at or datetime.now(timezone.utc),
    )


@router.post("/enroll", response_model=FaceprintEnrollResponse)
async def enroll_faceprint(
    face: UploadFile = File(...),
    display_name: str = Form(...),
    is_primary: bool = Form(False),
):
    if not display_name.strip():
        raise HTTPException(status_code=400, detail="display_name required")

    suffix = Path(face.filename or "face.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await face.read())
        tmp_path = Path(tmp.name)

    try:
        embedding = compute_embedding(tmp_path)
        if embedding is None:
            raise HTTPException(
                500,
                "Face embedding failed -- mediapipe + PIL + imagehash must be installed",
            )
        svc = get_faceprint_service()
        row, replaced = await svc.enroll(
            display_name=display_name.strip(),
            embedding=embedding,
            face_crop_path=None,
            sample_count=1,
            is_primary=is_primary,
        )
        return FaceprintEnrollResponse(
            id=row.id,
            display_name=row.display_name,
            is_primary=row.is_primary,
            replaced_existing=replaced,
            sample_count=row.sample_count,
        )
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


@router.post("/enroll-meeting", response_model=FaceprintEnrollResponse)
async def enroll_from_meeting(
    meeting_id: str = Form(...),
    display_name: str = Form(...),
    cluster_index: int = Form(0),
    is_primary: bool = Form(False),
):
    """Pick the largest face cluster from a meeting's captured frames and
    enroll it under display_name. cluster_index=0 means biggest cluster."""
    from app.infrastructure.config import get_workspace_path

    frames_dir = get_workspace_path("meetings") / meeting_id / "frames"
    clusters = extract_faces_from_meeting(meeting_id, frames_dir)
    if not clusters:
        raise HTTPException(404, "No face clusters found for that meeting")

    clusters.sort(key=lambda c: len(c.frames), reverse=True)
    if cluster_index >= len(clusters):
        raise HTTPException(404, f"cluster_index {cluster_index} out of range (have {len(clusters)})")
    cluster = clusters[cluster_index]
    # Use the dominant face crop from the cluster as a reference image on disk.
    dominant = max(
        (f for f in cluster.frames if f.face_crop_path),
        key=lambda f: 1,
        default=None,
    )
    crop_path = str(dominant.face_crop_path) if dominant and dominant.face_crop_path else None
    svc = get_faceprint_service()
    row, replaced = await svc.enroll(
        display_name=display_name.strip(),
        embedding=cluster.centroid.astype("float32"),
        face_crop_path=crop_path,
        sample_count=len(cluster.frames),
        is_primary=is_primary,
        source_meeting_id=meeting_id,
    )
    return FaceprintEnrollResponse(
        id=row.id,
        display_name=row.display_name,
        is_primary=row.is_primary,
        replaced_existing=replaced,
        sample_count=row.sample_count,
    )


@router.get("", response_model=list[FaceprintResponse])
async def list_faceprints():
    rows = await get_faceprint_service().list_all()
    return [_to_response(r) for r in rows]


@router.delete("/{faceprint_id}")
async def delete_faceprint(faceprint_id: int):
    ok = await get_faceprint_service().delete(faceprint_id)
    if not ok:
        raise HTTPException(404, "Faceprint not found")
    return {"deleted": True, "id": faceprint_id}


@router.post("/match", response_model=FaceprintMatchResult)
async def match_face(face: UploadFile = File(...)):
    suffix = Path(face.filename or "face.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await face.read())
        tmp_path = Path(tmp.name)
    try:
        embedding = compute_embedding(tmp_path)
        if embedding is None:
            raise HTTPException(500, "Embedding failed")
        svc = get_faceprint_service()
        m = await svc.match(embedding)
        if m is None:
            return FaceprintMatchResult(matched=False, threshold=DEFAULT_MATCH_THRESHOLD)
        return FaceprintMatchResult(
            matched=True,
            display_name=m[0],
            similarity=m[1],
            threshold=DEFAULT_MATCH_THRESHOLD,
        )
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
