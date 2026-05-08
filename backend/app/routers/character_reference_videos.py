"""
Character Reference Videos API.

TikTok videos ingested from the user's phone for character content development.
Share sheet ("Send to Zero") hits `POST /ingest-simple` with just a URL; a
scheduler poller downloads, transcribes, and analyzes each video.
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.infrastructure.auth import require_auth, require_auth_flex
from app.models.character_reference_video import (
    ApplyFactsRequest,
    ApplyFactsResponse,
    AssignCharacterRequest,
    CharacterReferenceVideo,
    CharacterReferenceVideoCreate,
    CharacterReferenceVideoUpdate,
    DeleteResponse,
    IngestSimpleRequest,
    IngestSimpleResponse,
    PromoteResponse,
    PromoteToCharacterRequest,
    RefVideoIntent,
    RefVideoStatus,
)
from app.services.character_reference_video_service import (
    get_character_reference_video_service,
)

router = APIRouter(dependencies=[Depends(require_auth)])
# Separate router for file-serving endpoints: browsers can't set Authorization
# headers on <img>/<video> tags, so these endpoints accept ?token= as well.
file_router = APIRouter(dependencies=[Depends(require_auth_flex)])
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Create / ingest
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=CharacterReferenceVideo,
    status_code=status.HTTP_201_CREATED,
)
async def create_reference_video(
    data: CharacterReferenceVideoCreate,
) -> CharacterReferenceVideo:
    """Full create used by the UI.

    The row is inserted with `status=pending`; the scheduler poller will
    download, transcribe, and analyze it shortly.
    """
    service = get_character_reference_video_service()
    return await service.create(data)


@router.post(
    "/ingest-simple",
    response_model=IngestSimpleResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_simple(
    request: Request,
    body: Optional[IngestSimpleRequest] = Body(None),
    url_q: Optional[str] = Query(None, alias="url"),
) -> IngestSimpleResponse:
    """Minimal ingest for the Android share intent.

    Accepts any of:
      - JSON body `{"url": "..."}` or `{"text": "..."}`
      - Plain-text body (share sheet sometimes posts raw text)
      - Query string `?url=...`

    Returns 202 immediately so the share sheet never hits its 5s timeout.
    The scheduler picks up the row and processes it asynchronously.
    """
    url = (body.url if body else None) or url_q
    text = (body.text if body else None)

    # Plain-text fallback: try to read the raw body if JSON didn't parse into fields
    if not url and not text:
        try:
            raw = await request.body()
            raw_str = raw.decode("utf-8", errors="replace").strip()
            if raw_str:
                text = raw_str
        except Exception as e:  # noqa: BLE001
            logger.debug("ingest_simple_body_read_failed", error=str(e))

    if not url and not text:
        raise HTTPException(
            status_code=400,
            detail="Provide a 'url' or 'text' (JSON body, query param, or plain-text body)",
        )

    service = get_character_reference_video_service()
    try:
        created = await service.ingest_simple(url=url, text=text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("cref_ingest_simple", id=created.id, url=created.tiktok_url)
    return IngestSimpleResponse(
        id=created.id,
        status=created.status,
        tiktok_url=created.tiktok_url,
    )


# ---------------------------------------------------------------------------
# List / get
# ---------------------------------------------------------------------------


@router.get("/", response_model=List[CharacterReferenceVideo])
async def list_reference_videos(
    character_id: Optional[str] = Query(None),
    intent: Optional[RefVideoIntent] = Query(None),
    status_filter: Optional[RefVideoStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[CharacterReferenceVideo]:
    service = get_character_reference_video_service()
    return await service.list(
        character_id=character_id,
        intent=intent.value if intent else None,
        status=status_filter.value if status_filter else None,
        limit=limit,
        offset=offset,
    )


@router.get("/{ref_id}", response_model=CharacterReferenceVideo)
async def get_reference_video(ref_id: str) -> CharacterReferenceVideo:
    service = get_character_reference_video_service()
    ref = await service.get(ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="reference video not found")
    return ref


@file_router.get("/{ref_id}/file/{kind}")
async def get_reference_file(ref_id: str, kind: str):
    """Serve video / thumbnail / audio with auth.

    We don't mount StaticFiles because auth must gate access. FileResponse
    streams the file directly.
    """
    if kind not in ("video", "thumbnail", "audio"):
        raise HTTPException(status_code=400, detail="kind must be video|thumbnail|audio")

    service = get_character_reference_video_service()
    ref = await service.get(ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="reference video not found")

    path_str = {
        "video": ref.video_path,
        "thumbnail": ref.thumbnail_path,
        "audio": ref.audio_path,
    }[kind]
    if not path_str:
        raise HTTPException(status_code=404, detail=f"{kind} not available yet")

    # Resolve against workspace root so legacy cwd-relative paths still work.
    from app.services.character_reference_video_service import resolve_reference_path

    path = resolve_reference_path(path_str)
    if not path or not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{kind} file missing on disk (stored={path_str!r}, resolved={str(path) if path else 'None'!r})",
        )

    media_types = {
        "video": "video/mp4",
        "thumbnail": "image/jpeg",
        "audio": "audio/mp4",
    }
    return FileResponse(
        path=str(path),
        media_type=media_types[kind],
        filename=path.name,
    )


# ---------------------------------------------------------------------------
# Update / actions
# ---------------------------------------------------------------------------


@router.patch("/{ref_id}", response_model=CharacterReferenceVideo)
async def update_reference_video(
    ref_id: str,
    data: CharacterReferenceVideoUpdate,
) -> CharacterReferenceVideo:
    service = get_character_reference_video_service()
    updated = await service.update(
        ref_id,
        intent=data.intent,
        character_id=data.character_id,
        notes=data.notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="reference video not found")
    return updated


@router.post("/{ref_id}/analyze", response_model=CharacterReferenceVideo)
async def analyze_reference_video(ref_id: str) -> CharacterReferenceVideo:
    service = get_character_reference_video_service()
    updated = await service.analyze(ref_id)
    if not updated:
        raise HTTPException(status_code=404, detail="reference video not found")
    return updated


@router.post("/{ref_id}/assign-character", response_model=CharacterReferenceVideo)
async def assign_character(
    ref_id: str,
    data: AssignCharacterRequest,
) -> CharacterReferenceVideo:
    service = get_character_reference_video_service()
    try:
        updated = await service.assign_character(ref_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="reference video not found")
    return updated


@router.post("/{ref_id}/apply-facts", response_model=ApplyFactsResponse)
async def apply_facts(
    ref_id: str,
    data: ApplyFactsRequest = Body(default=ApplyFactsRequest()),
) -> ApplyFactsResponse:
    service = get_character_reference_video_service()
    try:
        return await service.apply_facts(ref_id, fact_indexes=data.fact_indexes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ref_id}/promote-to-character", response_model=PromoteResponse)
async def promote_to_character(
    ref_id: str,
    data: PromoteToCharacterRequest = Body(default=PromoteToCharacterRequest()),
) -> PromoteResponse:
    service = get_character_reference_video_service()
    try:
        return await service.promote_to_character(
            ref_id,
            name=data.name,
            universe=data.universe,
            franchise=data.franchise,
            description=data.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{ref_id}/retry", response_model=CharacterReferenceVideo)
async def retry_reference_video(ref_id: str) -> CharacterReferenceVideo:
    service = get_character_reference_video_service()
    ref = await service.retry(ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="reference video not found")
    return ref


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/{ref_id}", response_model=DeleteResponse)
async def delete_reference_video(ref_id: str) -> DeleteResponse:
    service = get_character_reference_video_service()
    ok = await service.delete(ref_id)
    if not ok:
        raise HTTPException(status_code=404, detail="reference video not found")
    return DeleteResponse(status="deleted", id=ref_id)


# ---------------------------------------------------------------------------
# Diagnostic: manual poll (normally handled by scheduler)
# ---------------------------------------------------------------------------


class ProcessResponse(BaseModel):
    processed: int


@router.post("/process-pending", response_model=ProcessResponse)
async def process_pending_now(
    batch_size: int = Query(5, ge=1, le=20),
) -> ProcessResponse:
    """Manually trigger one processor tick. The scheduler runs this every minute."""
    service = get_character_reference_video_service()
    n = await service.process_pending(batch_size=batch_size)
    return ProcessResponse(processed=n)
