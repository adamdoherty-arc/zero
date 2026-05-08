"""
Media Content Router.

REST API for TV show and movie content management.
Handles CRUD for media titles, research, carousel generation,
character linking, TMDB search, and image management.
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
import structlog

from app.infrastructure.auth import require_auth
from app.models.media_content import (
    MediaTitle, MediaTitleCreate, MediaTitleUpdate,
    MediaCarouselCreate, MediaContentAngle, MediaStoryTemplate,
    CharacterMediaLink, CharacterMediaLinkCreate,
    MediaImage, MediaImageCreate,
    MediaStats, TMDBSearchResult,
    MediaBatchGenerateRequest,
)
from app.models.character_content import (
    CharacterCarousel, CarouselUpdate,
    CarouselApproval, CarouselRejection,
)

logger = structlog.get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


def _get_service():
    from app.services.media_content_service import get_media_content_service
    return get_media_content_service()


def _get_character_service():
    from app.services.character_content_service import get_character_content_service
    return get_character_content_service()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=MediaStats)
async def get_stats():
    """Get media content statistics."""
    svc = _get_service()
    return await svc.get_stats()


# ---------------------------------------------------------------------------
# TMDB Search
# ---------------------------------------------------------------------------

@router.get("/search-tmdb", response_model=List[TMDBSearchResult])
async def search_tmdb(
    q: str = Query(..., min_length=1),
    media_type: Optional[str] = Query(None),
):
    """Search TMDB for titles to import."""
    svc = _get_service()
    return await svc.search_tmdb(q, media_type)


# ---------------------------------------------------------------------------
# Media Title CRUD
# ---------------------------------------------------------------------------

@router.get("/titles", response_model=List[MediaTitle])
async def list_titles(
    media_type: Optional[str] = Query(None),
    universe: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    research_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List media titles with optional filters."""
    svc = _get_service()
    return await svc.list_media_titles(
        media_type=media_type,
        universe=universe,
        status=status,
        research_status=research_status,
        limit=limit,
        offset=offset,
    )


@router.post("/titles", response_model=MediaTitle, status_code=201)
async def create_title(data: MediaTitleCreate):
    """Create a new media title."""
    svc = _get_service()
    try:
        return await svc.create_media_title(data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/titles/{media_title_id}", response_model=MediaTitle)
async def get_title(media_title_id: str):
    """Get a media title by ID."""
    svc = _get_service()
    try:
        return await svc.get_media_title(media_title_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/titles/{media_title_id}", response_model=MediaTitle)
async def update_title(media_title_id: str, data: MediaTitleUpdate):
    """Update a media title."""
    svc = _get_service()
    try:
        return await svc.update_media_title(media_title_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/titles/{media_title_id}", status_code=204)
async def delete_title(media_title_id: str):
    """Delete a media title."""
    svc = _get_service()
    try:
        await svc.delete_media_title(media_title_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

@router.post("/titles/{media_title_id}/research", response_model=MediaTitle)
async def research_title(media_title_id: str):
    """Trigger research pipeline for a media title."""
    svc = _get_service()
    try:
        return await svc.research_media_title(media_title_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch-research")
async def batch_research(media_title_ids: List[str]):
    """Research multiple media titles."""
    svc = _get_service()
    results = {"researched": [], "errors": []}
    for tid in media_title_ids:
        try:
            await svc.research_media_title(tid)
            results["researched"].append(tid)
        except Exception as e:
            results["errors"].append({"id": tid, "error": str(e)})
    return results


# ---------------------------------------------------------------------------
# Admin: TMDB cast sync
# ---------------------------------------------------------------------------

@router.post("/admin/sync-cast")
async def admin_sync_cast(
    media_title_id: Optional[str] = Query(None),
    all: bool = Query(False),
    universe: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=500),
    dry_run: bool = Query(False),
    top_n: int = Query(15, ge=1, le=50),
):
    """Pull TMDB cast credits and populate ``character_media_titles``.

    Top-billed cast members (TMDB order < 5) without an existing character
    auto-create a pending-status stub. Cameos (order >= 5) are skipped
    unless they match an existing character. Idempotent — re-running adds
    no duplicate junction rows.
    """
    from app.services.media_cast_sync_service import get_media_cast_sync_service
    svc = get_media_cast_sync_service()
    if not svc.is_configured:
        raise HTTPException(
            status_code=503,
            detail="TMDB not configured (set ZERO_TMDB_READ_ACCESS_TOKEN or ZERO_TMDB_API_KEY)",
        )
    if all:
        return await svc.sync_all_cast(
            universe=universe, media_type=media_type,
            limit=limit, dry_run=dry_run,
        )
    if not media_title_id:
        raise HTTPException(
            status_code=400,
            detail="Provide media_title_id or all=true",
        )
    return await svc.sync_cast_for_title(
        media_title_id, top_n=top_n, dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Carousel Generation
# ---------------------------------------------------------------------------

@router.post("/titles/{media_title_id}/generate", response_model=CharacterCarousel)
async def generate_carousel(media_title_id: str, data: MediaCarouselCreate):
    """Generate a carousel for a media title."""
    data.media_title_id = media_title_id
    svc = _get_service()
    try:
        return await svc.generate_carousel(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/carousels", response_model=List[CharacterCarousel])
async def list_carousels(
    media_title_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    angle: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List media carousels."""
    svc = _get_service()
    return await svc.list_carousels(
        media_title_id=media_title_id,
        status=status,
        angle=angle,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Carousel operations (delegate to character content service for shared ops)
# ---------------------------------------------------------------------------

@router.get("/carousels/{carousel_id}", response_model=CharacterCarousel)
async def get_carousel(carousel_id: str):
    """Get a media carousel by ID."""
    char_svc = _get_character_service()
    try:
        return await char_svc.get_carousel(carousel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/carousels/{carousel_id}", response_model=CharacterCarousel)
async def update_carousel(carousel_id: str, data: CarouselUpdate):
    """Update a media carousel."""
    char_svc = _get_character_service()
    try:
        return await char_svc.update_carousel(carousel_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/review", response_model=CharacterCarousel)
async def review_carousel(carousel_id: str):
    """Trigger AI review for a media carousel."""
    char_svc = _get_character_service()
    try:
        return await char_svc.ai_review_carousel(carousel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/approve", response_model=CharacterCarousel)
async def approve_carousel(carousel_id: str, data: CarouselApproval):
    """Approve a media carousel."""
    char_svc = _get_character_service()
    try:
        return await char_svc.approve_carousel(carousel_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/reject", response_model=CharacterCarousel)
async def reject_carousel(carousel_id: str, data: CarouselRejection):
    """Reject a media carousel."""
    char_svc = _get_character_service()
    try:
        return await char_svc.reject_carousel(carousel_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Character Linking
# ---------------------------------------------------------------------------

@router.get("/titles/{media_title_id}/characters", response_model=List[CharacterMediaLink])
async def list_linked_characters(media_title_id: str):
    """List characters linked to a media title."""
    svc = _get_service()
    return await svc.list_linked_characters(media_title_id)


@router.post("/titles/{media_title_id}/characters", response_model=CharacterMediaLink, status_code=201)
async def link_character(media_title_id: str, data: CharacterMediaLinkCreate):
    """Link a character to a media title."""
    data.media_title_id = media_title_id
    svc = _get_service()
    try:
        return await svc.link_character(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/titles/{media_title_id}/characters/{character_id}", status_code=204)
async def unlink_character(media_title_id: str, character_id: str):
    """Unlink a character from a media title."""
    svc = _get_service()
    try:
        await svc.unlink_character(media_title_id, character_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

@router.get("/titles/{media_title_id}/images", response_model=List[MediaImage])
async def list_images(media_title_id: str):
    """List images for a media title."""
    svc = _get_service()
    return await svc.list_images(media_title_id)


@router.post("/titles/{media_title_id}/images", response_model=MediaImage, status_code=201)
async def add_image(media_title_id: str, data: MediaImageCreate):
    """Add an image to a media title."""
    data.media_title_id = media_title_id
    svc = _get_service()
    return await svc.add_image(data)


@router.delete("/titles/{media_title_id}/images/{image_id}", status_code=204)
async def delete_image(media_title_id: str, image_id: str):
    """Delete an image."""
    svc = _get_service()
    try:
        await svc.delete_image(media_title_id, image_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

@router.post("/seed", response_model=List[MediaTitle])
async def seed_titles(
    count: int = Query(10, ge=1, le=50),
    media_type: str = Query("movie"),
):
    """Import popular titles from TMDB."""
    svc = _get_service()
    try:
        return await svc.seed_from_tmdb(count=count, media_type=media_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Angles & Templates (reference data)
# ---------------------------------------------------------------------------

@router.get("/angles")
async def list_angles():
    """List available media content angles."""
    return [{"value": a.value, "label": a.value.replace("_", " ").title()} for a in MediaContentAngle]


@router.get("/templates")
async def list_templates():
    """List available media story templates."""
    return [{"value": t.value, "label": t.value.replace("_", " ").title()} for t in MediaStoryTemplate]


# ---------------------------------------------------------------------------
# Character's media (convenience endpoint)
# ---------------------------------------------------------------------------

@router.get("/characters/{character_id}/media", response_model=List[CharacterMediaLink])
async def list_character_media(character_id: str):
    """List media titles linked to a character."""
    svc = _get_service()
    return await svc.list_media_for_character(character_id)
