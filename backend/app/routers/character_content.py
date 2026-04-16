"""
Character Content API endpoints.
REST API for managing character profiles, research pipelines, carousel generation,
AI review, and human approval for TikTok character development posts.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
import structlog
from pydantic import BaseModel

from app.infrastructure.auth import require_auth
from app.models.character_content import (
    Character, CharacterCreate, CharacterUpdate,
    CharacterCarousel, CarouselCreate, CarouselUpdate,
    CharacterImage, CharacterImageCreate,
    CarouselApproval, CarouselRejection,
    BatchGenerateRequest, CharacterStats,
    ContentAngle, CharacterUniverse,
    ContentInspirationCreate, ContentInspiration,
    MusicTrack, MusicTrackCreate,
    StoryTemplate, StoryTemplateCreate,
    ResearchQueueStatus,
    PublishRequest, PublishStatus,
    EnhanceCharacterRequest, EnhanceCharacterResult,
    CarouselVersion,
    EnhanceCarouselRequest, EnhanceCarouselResponse,
    ApplyEnhanceRequest,
    CouncilVoteRequest, CouncilVoteResponse,
    ApplyCouncilWinnerRequest,
    RestoreVersionResponse,
    BackfillBannedHooksRequest, BackfillBannedHooksResult,
)
from app.services.character_content_service import get_character_content_service
from app.services.content_inspiration_service import get_content_inspiration_service
from app.services.story_template_service import get_story_template_service
from app.services.music_library_service import get_music_library_service


# ---------------------------------------------------------------------------
# Response models for endpoints that return dict/list without a dedicated model
# ---------------------------------------------------------------------------

class BatchResearchResponse(BaseModel):
    researched: int
    skipped: int
    errors: List[Dict[str, Any]] = []
    total_candidates: int


class SmartBatchResponse(BaseModel):
    generated: int
    top_scored: List[str] = []
    needs_work: List[str] = []
    errors: List[str] = []
    message: Optional[str] = None


class CancelResponse(BaseModel):
    status: str
    message: str


class DeleteResponse(BaseModel):
    status: str
    id: str


class RenderResponse(BaseModel):
    carousel_id: str
    slides: List[str]
    count: int


class MusicAssignResponse(BaseModel):
    status: str
    carousel_id: str
    track_id: str


class WinningPatterns(BaseModel):
    total_analyzed: int = 0
    hook_types: Dict[str, int] = {}
    storytelling_arcs: Dict[str, int] = {}
    patterns: List[Dict[str, Any]] = []
    avg_slide_count: float = 0.0


class SourceAnalytics(BaseModel):
    sources: List[Dict[str, Any]] = []
    total_fragments: int = 0


class TemplateAnalytics(BaseModel):
    templates: List[Dict[str, Any]] = []


class MusicAssignResult(BaseModel):
    carousel_id: str
    track: Dict[str, Any]


class GenerateCarouselRequest(BaseModel):
    angle: Optional[ContentAngle] = None
    story_template: Optional[str] = None
    multi_character_ids: Optional[List[str]] = None
    slide_count: int = 6


class GenerateSeriesRequest(BaseModel):
    angle: Optional[ContentAngle] = None
    story_template: Optional[str] = None
    parts: int = 3


class SmartBatchRequest(BaseModel):
    count: int = 12
    universe: Optional[CharacterUniverse] = None


class MultiCarouselRequest(BaseModel):
    character_ids: List[str]
    angle: Optional[ContentAngle] = None
    story_template: Optional[str] = None


class AnalyzeInspirationRequest(BaseModel):
    url: str


class DiscoverInspirationRequest(BaseModel):
    niche: str = "character facts carousel"


class AssignMusicRequest(BaseModel):
    track_id: str


class AddFactRequest(BaseModel):
    text: str
    category: str = "hidden_details"
    surprise_score: int = 5
    source: str = "manual"
    verified: bool = False


class ImageValidationResponse(BaseModel):
    total_checked: int
    validated: int
    invalidated: int


class ImagePurgeResponse(BaseModel):
    total_checked: int
    purged: int
    kept: int


class BulkReimageResponse(BaseModel):
    updated: int
    errors: int
    total: int


class BatchResearchRequest(BaseModel):
    universe: Optional[CharacterUniverse] = None
    limit: int = 24


router = APIRouter(dependencies=[Depends(require_auth)])
logger = structlog.get_logger()


# ============================================
# STATS & REVIEW QUEUE (before parameterized routes)
# ============================================

@router.get("/stats", response_model=CharacterStats)
async def get_stats():
    """Get character content pipeline statistics."""
    service = get_character_content_service()
    return await service.get_stats()


@router.get("/review-queue", response_model=List[CharacterCarousel])
async def get_review_queue(limit: int = Query(50, ge=1, le=200)):
    """Get carousels pending human review."""
    service = get_character_content_service()
    return await service.list_review_queue(limit=limit)


@router.post("/backfill-depth-scores", response_model=Dict[str, Any])
async def backfill_depth_scores():
    """Recalculate depth_score and relationship_map for all researched characters."""
    service = get_character_content_service()
    return await service.backfill_depth_scores()


@router.post("/seed", response_model=List[Character])
async def seed_characters():
    """Pre-populate with iconic characters (Marvel, DC, TV, Film)."""
    service = get_character_content_service()
    return await service.seed_characters()


@router.post("/batch-generate", response_model=List[CharacterCarousel])
async def batch_generate(data: BatchGenerateRequest):
    """Generate carousels for multiple characters."""
    service = get_character_content_service()
    return await service.batch_generate(data)


@router.post("/batch-research", response_model=BatchResearchResponse)
async def batch_research(data: BatchResearchRequest = Body(default=BatchResearchRequest())):
    """Research multiple unresearched characters sequentially."""
    service = get_character_content_service()
    universe_val = data.universe.value if data.universe else None
    return await service.batch_research(universe=universe_val, limit=data.limit)


# ============================================
# RESEARCH QUEUE (async with progress tracking)
# ============================================

@router.get("/research-queue", response_model=ResearchQueueStatus)
async def get_research_queue():
    """Get current research queue status with per-character progress."""
    service = get_character_content_service()
    return await service.get_research_queue_status()


@router.post("/research-queue/start", response_model=ResearchQueueStatus)
async def start_research_queue(data: BatchResearchRequest = Body(default=BatchResearchRequest())):
    """Start batch research with progress tracking."""
    service = get_character_content_service()
    universe_val = data.universe.value if data.universe else None
    return await service.start_batch_research_async(universe=universe_val, limit=data.limit)


@router.post("/research-queue/cancel", response_model=CancelResponse)
async def cancel_research_queue():
    """Cancel the running research queue."""
    service = get_character_content_service()
    return await service.cancel_research_queue()


@router.post("/research-queue/retry/{character_id}", response_model=ResearchQueueStatus)
async def retry_research_job(character_id: str):
    """Retry a failed or stuck research job for a specific character."""
    service = get_character_content_service()
    try:
        result = await service.retry_research_job(character_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================
# SMART BATCH & REVIEW
# ============================================

@router.post("/batch-smart", response_model=SmartBatchResponse)
async def smart_batch_generate(data: SmartBatchRequest = Body(default=SmartBatchRequest())):
    """Smart batch generation with priority scoring."""
    service = get_character_content_service()
    return await service.smart_batch_generate(count=data.count)


@router.get("/review-queue/smart", response_model=List[CharacterCarousel])
async def get_smart_review_queue(limit: int = Query(50, ge=1, le=200)):
    """Get priority-sorted review queue."""
    service = get_character_content_service()
    return await service.list_review_queue_smart(limit=limit)


# ============================================
# SERIES & MULTI-CHARACTER
# ============================================

class SeriesRequest(BaseModel):
    character_id: str
    angle: str = "hidden_truths"
    parts: int = 3
    story_template: Optional[str] = None

class MultiCharRequest(BaseModel):
    primary_character_id: str
    secondary_character_ids: List[str]
    angle: str = "vs_comparison"
    story_template: Optional[str] = None

@router.post("/generate-series", response_model=List[CharacterCarousel])
async def generate_series(data: SeriesRequest):
    """Generate a multi-part carousel series for one character."""
    service = get_character_content_service()
    return await service.generate_series(
        character_id=data.character_id,
        angle=data.angle,
        parts=data.parts,
        story_template=data.story_template,
    )

@router.post("/generate-multi-character", response_model=CharacterCarousel)
async def generate_multi_character(data: MultiCharRequest):
    """Generate a carousel featuring multiple characters (vs, hidden_connection)."""
    service = get_character_content_service()
    return await service.generate_multi_character_carousel(
        primary_character_id=data.primary_character_id,
        secondary_character_ids=data.secondary_character_ids,
        angle=data.angle,
        story_template=data.story_template,
    )


# ============================================
# RANKING CAROUSEL
# ============================================

class RankingRequest(BaseModel):
    theme: str = "most_powerful"
    universe: Optional[str] = None
    character_ids: Optional[List[str]] = None

@router.post("/generate-ranking", response_model=CharacterCarousel)
async def generate_ranking_carousel(data: RankingRequest):
    """Generate a multi-character ranking (Top 5) carousel."""
    service = get_character_content_service()
    return await service.generate_ranking_carousel(
        theme=data.theme,
        universe=data.universe,
        character_ids=data.character_ids,
    )

@router.get("/ranking-themes", response_model=Dict[str, str])
async def get_ranking_themes():
    """List available ranking themes."""
    from app.services.character_content_service import CharacterContentService
    return CharacterContentService.RANKING_THEMES


# ============================================
# TRENDING & INSPIRATIONS
# ============================================

@router.get("/trending", response_model=List[Dict[str, Any]])
async def get_trending_topics(limit: int = Query(10, ge=1, le=50)):
    """Get trending topics for content inspiration."""
    svc = get_content_inspiration_service()
    return await svc.get_trending_topics(limit)


@router.post("/inspirations/discover", response_model=List[ContentInspiration])
async def discover_inspirations(data: DiscoverInspirationRequest = Body(default=DiscoverInspirationRequest())):
    """Discover viral carousel creators."""
    service = get_content_inspiration_service()
    return await service.discover_carousel_creators(data.niche)


@router.get("/inspirations", response_model=List[ContentInspiration])
async def list_inspirations(limit: int = Query(50, ge=1, le=200)):
    """List analyzed content inspirations."""
    service = get_content_inspiration_service()
    return await service.list_inspirations(limit=limit)


@router.post("/inspirations/analyze", response_model=Optional[ContentInspiration])
async def analyze_inspiration(data: AnalyzeInspirationRequest):
    """Analyze a specific carousel URL for patterns."""
    service = get_content_inspiration_service()
    return await service.analyze_carousel_reference(data.url)


@router.get("/inspirations/patterns", response_model=WinningPatterns)
async def get_inspiration_patterns():
    """Get extracted winning patterns from all analyzed inspirations."""
    service = get_content_inspiration_service()
    return await service.extract_winning_patterns()


# ============================================
# STORY TEMPLATES
# ============================================

@router.get("/templates", response_model=List[StoryTemplate])
async def list_templates():
    """List all story templates."""
    service = get_story_template_service()
    return await service.list_templates()


@router.post("/templates", response_model=StoryTemplate)
async def create_template(data: StoryTemplateCreate):
    """Create a custom story template."""
    service = get_story_template_service()
    return await service.create_template(data)


@router.post("/templates/seed", response_model=List[StoryTemplate])
async def seed_templates():
    """Seed the 10 built-in story templates."""
    service = get_story_template_service()
    return await service.seed_templates()


# ============================================
# MUSIC LIBRARY
# ============================================

@router.get("/music", response_model=List[MusicTrack])
async def list_music(mood: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200)):
    """Browse music library by mood."""
    service = get_music_library_service()
    return await service.get_tracks(mood=mood, limit=limit)


@router.post("/music", response_model=MusicTrack)
async def add_music_track(data: MusicTrackCreate):
    """Add a track to the music library."""
    service = get_music_library_service()
    return await service.add_track(data)


@router.post("/music/seed", response_model=List[MusicTrack])
async def seed_music():
    """Seed the music library with curated tracks."""
    service = get_music_library_service()
    return await service.seed_music_library()


@router.get("/music/trending", response_model=List[Dict[str, Any]])
async def get_trending_music(niche: str = Query("character facts")):
    """Search for trending TikTok sounds."""
    service = get_music_library_service()
    return await service.search_trending_sounds(niche)


# ============================================
# ANALYTICS
# ============================================

@router.get("/analytics/sources", response_model=SourceAnalytics)
async def get_source_analytics():
    """Get research source effectiveness analytics."""
    service = get_character_content_service()
    return await service.get_source_analytics()


@router.get("/analytics/templates", response_model=TemplateAnalytics)
async def get_template_analytics():
    """Get template performance leaderboard."""
    service = get_story_template_service()
    return await service.get_template_leaderboard()


# ============================================
# CAROUSEL ROUTES (before character parameterized)
# ============================================

@router.get("/carousels", response_model=List[CharacterCarousel])
async def list_carousels(
    character_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all carousels with optional filters."""
    service = get_character_content_service()
    return await service.list_carousels(character_id=character_id, status=status, limit=limit)


@router.post("/carousels/backfill-banned-hooks", response_model=BackfillBannedHooksResult)
async def backfill_banned_hooks(
    data: BackfillBannedHooksRequest = Body(default_factory=BackfillBannedHooksRequest),
):
    """Scan non-published carousels for banned hook patterns and rewrite them.

    Registered before parameterized `/carousels/{carousel_id}` to avoid route
    collision.
    """
    service = get_character_content_service()
    return await service.backfill_banned_hooks(data, created_by="backfill-endpoint")


@router.get("/carousels/{carousel_id}", response_model=CharacterCarousel)
async def get_carousel(carousel_id: str):
    """Get a specific carousel."""
    service = get_character_content_service()
    carousel = await service.get_carousel(carousel_id)
    if not carousel:
        raise HTTPException(status_code=404, detail="Carousel not found")
    return carousel


@router.patch("/carousels/{carousel_id}", response_model=CharacterCarousel)
async def update_carousel(carousel_id: str, data: CarouselUpdate):
    """Edit carousel content (human edits)."""
    service = get_character_content_service()
    carousel = await service.update_carousel(
        carousel_id,
        data,
        created_by="human",
        snapshot_source="manual_edit",
    )
    if not carousel:
        raise HTTPException(status_code=404, detail="Carousel not found")
    return carousel


# ============================================
# CAROUSEL ENHANCE / COUNCIL / VERSIONS
# ============================================

@router.post("/carousels/{carousel_id}/enhance", response_model=EnhanceCarouselResponse)
async def enhance_carousel(carousel_id: str, data: EnhanceCarouselRequest):
    """Generate N rewrite variants for a carousel field using the chosen LLM.

    Does NOT apply any variant. Use `/enhance/apply` to commit a chosen one.
    """
    service = get_character_content_service()
    try:
        return await service.enhance_carousel_piece(carousel_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/enhance/apply", response_model=CharacterCarousel)
async def apply_carousel_enhance(carousel_id: str, data: ApplyEnhanceRequest):
    """Apply a selected enhancement variant and snapshot the prior state."""
    service = get_character_content_service()
    try:
        result = await service.apply_enhance_variant(
            carousel_id, data, created_by="human", source="enhance"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Carousel not found")
    return result


@router.post("/carousels/{carousel_id}/council-vote", response_model=CouncilVoteResponse)
async def carousel_council_vote(carousel_id: str, data: CouncilVoteRequest):
    """Generate variants across providers and let the Council vote on them.

    Returns the winning variant + per-role votes + reasoning. Does NOT apply.
    """
    service = get_character_content_service()
    try:
        return await service.run_council_on_carousel(carousel_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/carousels/{carousel_id}/council-vote/apply", response_model=CharacterCarousel
)
async def apply_council_winner(carousel_id: str, data: ApplyCouncilWinnerRequest):
    """Apply the Council's winning variant and snapshot the prior state."""
    service = get_character_content_service()
    try:
        result = await service.apply_enhance_variant(
            carousel_id,
            ApplyEnhanceRequest(
                target=data.target,
                slide_num=data.slide_num,
                text=data.text,
                provider="council",
                model=data.decision_id or "council",
            ),
            created_by="council",
            source="council_vote",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Carousel not found")
    return result


@router.get("/carousels/{carousel_id}/versions", response_model=List[CarouselVersion])
async def list_carousel_versions(
    carousel_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """List carousel versions (newest first)."""
    service = get_character_content_service()
    try:
        return await service.list_carousel_versions(carousel_id, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/carousels/{carousel_id}/versions/{version_id}/restore",
    response_model=RestoreVersionResponse,
)
async def restore_carousel_version(
    carousel_id: str,
    version_id: str,
    force: bool = Query(False, description="Allow restoring over published carousels"),
):
    """Restore a previous carousel version.

    Snapshots the current state as `restore` before overwriting. Blocks
    restoring over `published` carousels unless `force=true`.
    """
    service = get_character_content_service()
    try:
        result = await service.restore_carousel_version(
            carousel_id, version_id, force=force, created_by="human"
        )
    except ValueError as e:
        msg = str(e)
        if "published" in msg.lower():
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=404, detail=msg)
    if result is None:
        raise HTTPException(status_code=404, detail="Carousel not found")
    return result


@router.post("/carousels/{carousel_id}/review", response_model=CharacterCarousel)
async def ai_review_carousel(carousel_id: str):
    """Trigger AI review of a carousel."""
    service = get_character_content_service()
    try:
        return await service.ai_review_carousel(carousel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/reimage", response_model=CharacterCarousel)
async def reimage_carousel(carousel_id: str):
    """Re-run the 3-tier image matcher across ALL slides of a carousel.

    Uses the character's existing image pool. Does not source new images.
    """
    service = get_character_content_service()
    try:
        return await service.reimage_carousel(carousel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class SlideReimageRequest(BaseModel):
    query: Optional[str] = None


@router.post(
    "/carousels/{carousel_id}/slides/{slide_index}/reimage",
    response_model=CharacterCarousel,
)
async def reimage_slide(
    carousel_id: str,
    slide_index: int,
    data: SlideReimageRequest = Body(default_factory=SlideReimageRequest),
):
    """Refresh a single slide's image.

    Optional body `{"query": "..."}` overrides the matcher keyword.
    """
    service = get_character_content_service()
    try:
        return await service.reimage_slide(carousel_id, slide_index, data.query)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/carousels/{carousel_id}/reimage-with-fresh-sources",
    response_model=CharacterCarousel,
)
async def reimage_carousel_with_fresh_sources(carousel_id: str):
    """Expand the character image pool via fresh SearXNG sourcing, then reimage all slides."""
    service = get_character_content_service()
    try:
        return await service.reimage_carousel_with_fresh_sources(carousel_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/approve", response_model=CharacterCarousel)
async def approve_carousel(carousel_id: str, data: CarouselApproval = None):
    """Human approve a carousel for publishing."""
    service = get_character_content_service()
    try:
        return await service.approve_carousel(carousel_id, data or CarouselApproval())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/reject", response_model=CharacterCarousel)
async def reject_carousel(carousel_id: str, data: CarouselRejection):
    """Human reject a carousel."""
    service = get_character_content_service()
    try:
        return await service.reject_carousel(carousel_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/{carousel_id}/music", response_model=MusicAssignResult)
async def assign_music(carousel_id: str, data: AssignMusicRequest):
    """Assign or change music track for a carousel."""
    service = get_music_library_service()
    return await service.assign_track_to_carousel(carousel_id, data.track_id)


@router.post("/carousels/{carousel_id}/render", response_model=RenderResponse)
async def render_carousel(carousel_id: str):
    """Render carousel slides as 1080x1350 PNG images ready for TikTok."""
    from app.services.carousel_renderer_service import get_carousel_renderer

    content_service = get_character_content_service()
    carousel = await content_service.get_carousel(carousel_id)
    if not carousel:
        raise HTTPException(status_code=404, detail="Carousel not found")

    # Get character image for background
    char = await content_service.get_character(carousel.character_id)
    image_url = char.image_url if char else None
    image_urls = char.image_urls if char else []

    renderer = get_carousel_renderer()
    result = await renderer.render_carousel(
        carousel_id=carousel_id,
        slides=carousel.slides,
        text_overlay_specs=carousel.text_overlay_specs,
        character_image_url=image_url,
        character_image_urls=image_urls,
    )
    return result


@router.get("/carousels/{carousel_id}/rendered", response_model=RenderResponse)
async def get_rendered_slides(carousel_id: str):
    """Get list of rendered slide image paths for a carousel."""
    from app.services.carousel_renderer_service import get_carousel_renderer

    renderer = get_carousel_renderer()
    paths = await renderer.list_rendered(carousel_id)
    if not paths:
        raise HTTPException(status_code=404, detail="No rendered slides found. Call POST /render first.")
    return {"carousel_id": carousel_id, "slides": paths, "count": len(paths)}


# ============================================
# PUBLISHING PIPELINE
# ============================================

@router.post("/carousels/{carousel_id}/queue-publish", response_model=PublishStatus)
async def queue_for_publishing(carousel_id: str, req: PublishRequest = Body(default=PublishRequest())):
    """Queue an approved carousel for publishing."""
    svc = get_character_content_service()
    try:
        return await svc.queue_for_publishing(carousel_id, req.platform, req.schedule_at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/carousels/{carousel_id}/publish", response_model=PublishStatus)
async def publish_carousel(carousel_id: str):
    """Publish a queued carousel (renders + exports)."""
    svc = get_character_content_service()
    try:
        return await svc.publish_carousel(carousel_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/carousels/{carousel_id}/download", response_model=List[str])
async def get_download_urls(carousel_id: str):
    """Get rendered slide download URLs for manual upload."""
    svc = get_character_content_service()
    return await svc.get_download_urls(carousel_id)


@router.post("/carousels/{carousel_id}/caption-variants", response_model=List[str])
async def generate_caption_variants(carousel_id: str, count: int = Query(3, ge=1, le=10)):
    """Generate A/B caption variants for a carousel."""
    svc = get_character_content_service()
    try:
        return await svc.generate_caption_variants(carousel_id, count)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/carousels/{carousel_id}/export/{platform}", response_model=List[str])
async def export_for_platform(carousel_id: str, platform: str):
    """Export carousel in platform-specific format."""
    svc = get_character_content_service()
    return await svc.export_for_platform(carousel_id, platform)


# ============================================
# CHARACTER CRUD
# ============================================

@router.post("/", response_model=Character)
async def create_character(data: CharacterCreate):
    """Create a new character profile."""
    service = get_character_content_service()
    return await service.create_character(data)


@router.get("/", response_model=List[Character])
async def list_characters(
    universe: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    research_status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List characters with optional filters."""
    service = get_character_content_service()
    return await service.list_characters(
        universe=universe, status=status,
        research_status=research_status, limit=limit,
    )


@router.get("/{character_id}", response_model=Character)
async def get_character(character_id: str):
    """Get a character's full profile including research data and fact bank."""
    service = get_character_content_service()
    char = await service.get_character(character_id)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    return char


@router.patch("/{character_id}", response_model=Character)
async def update_character(character_id: str, data: CharacterUpdate):
    """Update character details."""
    service = get_character_content_service()
    char = await service.update_character(character_id, data)
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    return char


@router.delete("/{character_id}", response_model=DeleteResponse)
async def delete_character(character_id: str):
    """Delete a character and all associated content."""
    service = get_character_content_service()
    deleted = await service.delete_character(character_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"status": "deleted", "id": character_id}


# ============================================
# CHARACTER RESEARCH
# ============================================

@router.post("/{character_id}/research", response_model=Character)
async def research_character(character_id: str):
    """Start the research pipeline for a character (runs in background)."""
    service = get_character_content_service()
    try:
        return await service.research_character(character_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{character_id}/enhance", response_model=EnhanceCharacterResult)
async def enhance_character(
    character_id: str,
    data: EnhanceCharacterRequest = Body(default_factory=EnhanceCharacterRequest),
):
    """Deep-enhance a character: refresh research, top up images, regenerate weak carousels.

    Returns a summary of facts/images/carousels changed.
    """
    service = get_character_content_service()
    try:
        summary = await service.enhance_character(
            character_id,
            refresh_research=data.refresh_research,
            add_images=data.add_images,
            regenerate_weak_carousels=data.regenerate_weak_carousels,
            weak_threshold=data.weak_threshold,
        )
        return summary
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================
# CHARACTER IMAGES
# ============================================

@router.get("/{character_id}/images", response_model=List[CharacterImage])
async def list_character_images(
    character_id: str,
    include_invalid: bool = Query(False),
):
    """List sourced images for a character. Excludes broken/invalid images by default."""
    service = get_character_content_service()
    return await service.list_images(character_id, include_invalid=include_invalid)


@router.post("/{character_id}/images", response_model=CharacterImage)
async def add_character_image(character_id: str, data: CharacterImageCreate):
    """Add an image manually for a character."""
    data.character_id = character_id
    service = get_character_content_service()
    return await service.add_image(data)


@router.post("/{character_id}/source-images", response_model=List[CharacterImage])
async def source_images(character_id: str):
    """Re-run image search for a character with fresh queries."""
    service = get_character_content_service()
    try:
        return await service.source_images_on_demand(character_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/images/validate-all", response_model=ImageValidationResponse)
async def validate_all_images(limit: int = Query(100, ge=1, le=500)):
    """Validate all unvalidated character images. Checks URLs, extracts dimensions, marks broken ones invalid."""
    service = get_character_content_service()
    return await service.validate_all_images(limit=limit)


@router.post("/images/purge-broken", response_model=ImagePurgeResponse)
async def purge_broken_images(limit: int = Query(200, ge=1, le=1000)):
    """Auto-delete broken image URLs and add them to the character blocklist."""
    service = get_character_content_service()
    return await service.purge_broken_images(limit=limit)


@router.post("/{character_id}/images/{image_id}/approve", response_model=CharacterImage)
async def approve_image(character_id: str, image_id: str):
    """Mark an image as approved (good quality)."""
    service = get_character_content_service()
    try:
        return await service.approve_image(character_id, image_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{character_id}/images/{image_id}/reject", response_model=CharacterImage)
async def reject_image(character_id: str, image_id: str, reason: str = Query("")):
    """Mark an image as rejected. Sets is_valid=False to exclude from future carousel use."""
    service = get_character_content_service()
    try:
        return await service.reject_image(character_id, image_id, reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{character_id}/images/{image_id}")
async def delete_image(character_id: str, image_id: str):
    """Delete an image and block its URL from re-import."""
    service = get_character_content_service()
    try:
        return await service.delete_image(character_id, image_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carousels/bulk-reimage", response_model=BulkReimageResponse)
async def bulk_reimage_carousels(
    status: Optional[str] = Query("draft"),
    limit: int = Query(20, ge=1, le=100),
):
    """Re-source and re-assign images for existing carousels using improved pipeline."""
    service = get_character_content_service()
    return await service.bulk_reimage_carousels(status=status, limit=limit)


# ============================================
# FACT MANAGEMENT
# ============================================

@router.post("/{character_id}/facts", response_model=Character)
async def add_fact(character_id: str, data: AddFactRequest):
    """Add a single fact to a character's fact bank."""
    service = get_character_content_service()
    fact = data.model_dump()
    try:
        return await service.add_fact(character_id, fact)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{character_id}/facts/{fact_index}", response_model=Character)
async def update_fact(character_id: str, fact_index: int, data: AddFactRequest):
    """Update a fact in a character's fact bank by index."""
    service = get_character_content_service()
    fact = data.model_dump()
    try:
        return await service.update_fact(character_id, fact_index, fact)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# CAROUSEL GENERATION
# ============================================

@router.post("/{character_id}/carousel", response_model=CharacterCarousel)
async def generate_carousel(character_id: str, data: GenerateCarouselRequest = Body(default=GenerateCarouselRequest())):
    """Generate a new carousel post for a character."""
    create_data = CarouselCreate(
        character_id=character_id,
        angle=data.angle or ContentAngle.HIDDEN_TRUTHS,
        story_template=data.story_template,
        multi_character_ids=data.multi_character_ids,
        slide_count=data.slide_count,
    )
    service = get_character_content_service()
    try:
        return await service.generate_carousel(create_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# SERIES GENERATION
# ============================================

@router.post("/{character_id}/carousel/series", response_model=List[CharacterCarousel])
async def generate_series(character_id: str, data: GenerateSeriesRequest = Body(default=GenerateSeriesRequest())):
    """Generate a multi-part carousel series for a character."""
    service = get_character_content_service()
    try:
        return await service.generate_carousel_series(
            character_id=character_id,
            story_template=data.story_template,
            parts=data.parts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# CHARACTER AUTOPILOT (Phase 024)
# ============================================

class AutopilotStats(BaseModel):
    autopilot_enabled: bool
    characters_discovered_24h: int
    carousels_auto_approved_24h: int
    gaps_filled_24h: int
    minimax_spend_today_usd: float
    minimax_daily_cap_usd: float
    minimax_pct_of_cap: float
    approved_queued_count: int
    human_review_queue_count: int
    priority_characters: int
    probation_characters: int


class AutopilotAction(BaseModel):
    id: int
    job_name: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class AutopilotToggleRequest(BaseModel):
    enabled: bool


class AutopilotToggleResponse(BaseModel):
    autopilot_enabled: bool


class AutonomousToggleResponse(BaseModel):
    character_id: str
    autonomous_disabled: bool


class AutopilotTriggerResponse(BaseModel):
    job: str
    status: str
    result: Dict[str, Any] = {}


class HumanReviewQueueItem(BaseModel):
    carousel_id: str
    character_id: str
    character_name: Optional[str] = None
    priority_tier: Optional[str] = None
    final_review_score: Optional[float] = None
    hook_text: Optional[str] = None
    angle: Optional[str] = None
    created_at: Optional[str] = None


@router.get("/autopilot/stats", response_model=AutopilotStats)
async def autopilot_stats():
    """24h autopilot KPIs plus today's MiniMax spend."""
    from datetime import date, datetime, timedelta, timezone
    from sqlalchemy import select, func as sql_func

    from app.db.models import (
        CharacterModel,
        CharacterCarouselModel,
        LlmDailySpendModel,
        SchedulerAuditLogModel,
    )
    from app.infrastructure.config import get_settings
    from app.infrastructure.database import get_session

    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    today = date.today()

    async with get_session() as session:
        discovered = (await session.execute(
            select(sql_func.count()).select_from(CharacterModel)
            .where(CharacterModel.created_at >= since)
            .where(CharacterModel.discovery_source.is_not(None))
        )).scalar() or 0

        auto_approved = (await session.execute(
            select(sql_func.count()).select_from(CharacterCarouselModel)
            .where(CharacterCarouselModel.auto_approved_at >= since)
        )).scalar() or 0

        gap_rows = (await session.execute(
            select(SchedulerAuditLogModel)
            .where(SchedulerAuditLogModel.job_name == "character_gap_audit")
            .where(SchedulerAuditLogModel.created_at >= since)
        )).scalars().all()
        gaps_filled = sum(1 for r in gap_rows if r.status == "success")

        spend_row = await session.get(LlmDailySpendModel, ("minimax", today))
        spend_usd = float(spend_row.spend_usd) if spend_row else 0.0

        approved_queued = (await session.execute(
            select(sql_func.count()).select_from(CharacterCarouselModel)
            .where(CharacterCarouselModel.status == "approved")
            .where(CharacterCarouselModel.publish_status == "queued")
        )).scalar() or 0

        human_queue = (await session.execute(
            select(sql_func.count()).select_from(CharacterCarouselModel)
            .where(CharacterCarouselModel.status == "review")
            .where(CharacterCarouselModel.final_review_score.is_not(None))
            .where(CharacterCarouselModel.final_review_score < settings.character_auto_approve_threshold)
            .where(CharacterCarouselModel.final_review_score >= 75.0)
        )).scalar() or 0

        priority_n = (await session.execute(
            select(sql_func.count()).select_from(CharacterModel)
            .where(CharacterModel.priority_tier == "priority")
        )).scalar() or 0

        probation_n = (await session.execute(
            select(sql_func.count()).select_from(CharacterModel)
            .where(CharacterModel.priority_tier == "probation")
        )).scalar() or 0

    cap = float(settings.character_minimax_daily_cap_usd or 0.0)
    pct = round((spend_usd / cap) * 100.0, 2) if cap > 0 else 0.0

    return AutopilotStats(
        autopilot_enabled=bool(settings.character_autopilot_enabled),
        characters_discovered_24h=int(discovered),
        carousels_auto_approved_24h=int(auto_approved),
        gaps_filled_24h=int(gaps_filled),
        minimax_spend_today_usd=round(spend_usd, 4),
        minimax_daily_cap_usd=cap,
        minimax_pct_of_cap=pct,
        approved_queued_count=int(approved_queued),
        human_review_queue_count=int(human_queue),
        priority_characters=int(priority_n),
        probation_characters=int(probation_n),
    )


@router.get("/autopilot/actions", response_model=List[AutopilotAction])
async def autopilot_actions(limit: int = Query(20, ge=1, le=200)):
    """Recent autopilot scheduler runs for observability."""
    from sqlalchemy import select

    from app.db.models import SchedulerAuditLogModel
    from app.infrastructure.database import get_session

    character_jobs = [
        "character_discovery",
        "character_discovery_refvideos",
        "character_gap_audit",
        "character_hook_audit",
        "character_auto_approval",
        "character_publish_backlog",
        "character_research_refresh",
        "character_auto_publish",
        "character_content_generation",
        "character_performance_sync",
        "character_content_learning",
    ]

    async with get_session() as session:
        rows = (await session.execute(
            select(SchedulerAuditLogModel)
            .where(SchedulerAuditLogModel.job_name.in_(character_jobs))
            .order_by(SchedulerAuditLogModel.created_at.desc())
            .limit(limit)
        )).scalars().all()

    return [
        AutopilotAction(
            id=r.id,
            job_name=r.job_name,
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            status=r.status,
            duration_seconds=r.duration_seconds,
            error=r.error,
        )
        for r in rows
    ]


@router.get("/autopilot/human-queue", response_model=List[HumanReviewQueueItem])
async def autopilot_human_queue(limit: int = Query(20, ge=1, le=100)):
    """Carousels scoring 75-84 that need a human decision, priority tier first."""
    from sqlalchemy import select, case

    from app.db.models import CharacterModel, CharacterCarouselModel
    from app.infrastructure.config import get_settings
    from app.infrastructure.database import get_session

    settings = get_settings()
    tier_order = case(
        (CharacterModel.priority_tier == "priority", 0),
        (CharacterModel.priority_tier == "standard", 1),
        (CharacterModel.priority_tier == "probation", 2),
        else_=3,
    )

    async with get_session() as session:
        rows = (await session.execute(
            select(CharacterCarouselModel, CharacterModel)
            .join(CharacterModel, CharacterCarouselModel.character_id == CharacterModel.id)
            .where(CharacterCarouselModel.status == "review")
            .where(CharacterCarouselModel.final_review_score.is_not(None))
            .where(CharacterCarouselModel.final_review_score >= 75.0)
            .where(CharacterCarouselModel.final_review_score < settings.character_auto_approve_threshold)
            .order_by(tier_order.asc(), CharacterCarouselModel.final_review_score.desc())
            .limit(limit)
        )).all()

    return [
        HumanReviewQueueItem(
            carousel_id=c.id,
            character_id=c.character_id,
            character_name=ch.name,
            priority_tier=ch.priority_tier,
            final_review_score=c.final_review_score,
            hook_text=c.hook_text,
            angle=c.angle,
            created_at=c.created_at.isoformat() if c.created_at else None,
        )
        for c, ch in rows
    ]


@router.post("/autopilot/toggle", response_model=AutopilotToggleResponse)
async def autopilot_toggle(data: AutopilotToggleRequest):
    """Global kill-switch for all character autopilot jobs."""
    from app.infrastructure.config import get_settings

    settings = get_settings()
    settings.character_autopilot_enabled = bool(data.enabled)
    return AutopilotToggleResponse(autopilot_enabled=settings.character_autopilot_enabled)


@router.post("/autopilot/trigger/{job}", response_model=AutopilotTriggerResponse)
async def autopilot_trigger(job: str):
    """Manually trigger an autopilot job. Useful for testing without waiting for cron."""
    from app.services.character_content_service import get_character_content_service

    svc = get_character_content_service()

    result: Dict[str, Any] = {}
    try:
        if job == "character_auto_approval":
            n = await svc.auto_approve_eligible(limit=50)
            result = {"auto_approved": n}
        elif job == "character_publish_backlog":
            result = await svc.ensure_publish_backlog(target=6)
        elif job == "character_gap_audit":
            result = await svc.run_gap_audit_cycle(max_characters=20)
        elif job == "character_discovery":
            from app.services.character_discovery_service import get_character_discovery_service
            disc = get_character_discovery_service()
            result = await disc.run_all_sources()
        elif job == "character_discovery_refvideos":
            from app.services.character_discovery_service import get_character_discovery_service
            disc = get_character_discovery_service()
            n = await disc.discover_from_reference_videos(limit=5)
            result = {"promoted": n}
        elif job == "character_hook_audit":
            from app.services.character_hook_service import get_character_hook_service
            hook_svc = get_character_hook_service()
            result = await hook_svc.audit_weak_hooks(threshold=6.0, limit=20)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown autopilot job: {job}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("autopilot_trigger_failed", job=job, error=str(e))
        return AutopilotTriggerResponse(job=job, status="error", result={"error": str(e)})

    return AutopilotTriggerResponse(job=job, status="ok", result=result)


@router.post("/{character_id}/autonomous/toggle", response_model=AutonomousToggleResponse)
async def autonomous_toggle(character_id: str):
    """Per-character kill-switch. Flips the autonomous_disabled flag."""
    from sqlalchemy import select

    from app.db.models import CharacterModel
    from app.infrastructure.database import get_session

    async with get_session() as session:
        row = await session.get(CharacterModel, character_id)
        if not row:
            raise HTTPException(status_code=404, detail="character not found")
        row.autonomous_disabled = not bool(row.autonomous_disabled)
        await session.commit()
        disabled = bool(row.autonomous_disabled)

    return AutonomousToggleResponse(character_id=character_id, autonomous_disabled=disabled)


@router.get("/autopilot/budget", response_model=Dict[str, Any])
async def autopilot_budget():
    """Per-provider daily spend vs caps for all LLM providers."""
    from datetime import date
    from sqlalchemy import select

    from app.db.models import LlmDailySpendModel
    from app.infrastructure.config import get_settings
    from app.infrastructure.database import get_session

    settings = get_settings()
    today = date.today()

    async with get_session() as session:
        rows = (await session.execute(
            select(LlmDailySpendModel).where(LlmDailySpendModel.day == today)
        )).scalars().all()

    providers = {r.provider: float(r.spend_usd or 0.0) for r in rows}
    minimax_spend = providers.get("minimax", 0.0)
    minimax_cap = float(settings.character_minimax_daily_cap_usd or 0.0)

    return {
        "date": today.isoformat(),
        "providers": providers,
        "minimax": {
            "spend_usd": round(minimax_spend, 4),
            "cap_usd": minimax_cap,
            "pct_of_cap": round((minimax_spend / minimax_cap) * 100.0, 2) if minimax_cap > 0 else 0.0,
            "exceeded": minimax_cap > 0 and minimax_spend >= minimax_cap,
        },
    }


# --- Activity feed (what has been found / what is researching / what is being built) ---

class DiscoveredCharacter(BaseModel):
    id: str
    name: str
    universe: Optional[str] = None
    discovery_source: Optional[str] = None
    discovery_hits: int = 0
    research_status: Optional[str] = None
    priority_tier: Optional[str] = None
    created_at: Optional[str] = None
    evidence_summary: Optional[str] = None


class ResearchingCharacter(BaseModel):
    id: str
    name: str
    universe: Optional[str] = None
    research_status: str
    research_depth_score: float = 0.0
    fact_count: int = 0
    image_count: int = 0
    last_researched: Optional[str] = None


class RecentCarousel(BaseModel):
    id: str
    character_id: str
    character_name: Optional[str] = None
    angle: Optional[str] = None
    hook_text: Optional[str] = None
    status: str
    final_review_score: Optional[float] = None
    auto_approved: Optional[bool] = None
    created_at: Optional[str] = None


class AutopilotActivity(BaseModel):
    recently_discovered: List[DiscoveredCharacter]
    currently_researching: List[ResearchingCharacter]
    recent_carousels: List[RecentCarousel]
    counts: Dict[str, int]


@router.get("/autopilot/activity", response_model=AutopilotActivity)
async def autopilot_activity(limit: int = Query(10, ge=1, le=50)):
    """What the autopilot has found, is researching, and is building right now."""
    from sqlalchemy import select, func as sa_func

    from app.db.models import CharacterModel, CharacterCarouselModel, CharacterImageModel
    from app.infrastructure.database import get_session

    async with get_session() as session:
        # Recently discovered (has a discovery_source)
        disc_result = await session.execute(
            select(CharacterModel)
            .where(CharacterModel.discovery_source.is_not(None))
            .order_by(CharacterModel.created_at.desc())
            .limit(limit)
        )
        disc_rows = list(disc_result.scalars().all())

        # Currently researching or pending research
        res_result = await session.execute(
            select(CharacterModel)
            .where(CharacterModel.research_status.in_(["researching", "pending"]))
            .order_by(CharacterModel.updated_at.desc().nulls_last(), CharacterModel.created_at.desc())
            .limit(limit)
        )
        res_rows = list(res_result.scalars().all())

        # Recent carousels (any status) with character name
        car_result = await session.execute(
            select(CharacterCarouselModel, CharacterModel.name)
            .join(CharacterModel, CharacterModel.id == CharacterCarouselModel.character_id, isouter=True)
            .order_by(CharacterCarouselModel.created_at.desc())
            .limit(limit)
        )
        car_rows = list(car_result.all())

        # Image counts for researching characters
        img_counts: Dict[str, int] = {}
        if res_rows:
            img_rows = (await session.execute(
                select(CharacterImageModel.character_id, sa_func.count(CharacterImageModel.id))
                .where(CharacterImageModel.character_id.in_([r.id for r in res_rows]))
                .group_by(CharacterImageModel.character_id)
            )).all()
            img_counts = {cid: int(cnt) for cid, cnt in img_rows}

        # High-level counts
        total_discovered = (await session.execute(
            select(sa_func.count(CharacterModel.id)).where(CharacterModel.discovery_source.is_not(None))
        )).scalar() or 0
        total_researching = (await session.execute(
            select(sa_func.count(CharacterModel.id)).where(CharacterModel.research_status == "researching")
        )).scalar() or 0
        total_pending = (await session.execute(
            select(sa_func.count(CharacterModel.id)).where(CharacterModel.research_status == "pending")
        )).scalar() or 0
        total_in_progress_carousels = (await session.execute(
            select(sa_func.count(CharacterCarouselModel.id))
            .where(CharacterCarouselModel.status.in_(["draft", "review", "pending_review", "ai_reviewed"]))
        )).scalar() or 0

    def _evidence_summary(ev: Optional[dict]) -> Optional[str]:
        if not ev or not isinstance(ev, dict):
            return None
        # Common evidence keys produced by discovery services
        for key in ("reason", "source_url", "subreddit", "trending_week", "rank"):
            val = ev.get(key)
            if val:
                return f"{key}: {val}"
        try:
            first = next(iter(ev.items()))
            return f"{first[0]}: {first[1]}"
        except Exception:
            return None

    recently_discovered = [
        DiscoveredCharacter(
            id=r.id,
            name=r.name,
            universe=r.universe,
            discovery_source=r.discovery_source,
            discovery_hits=int(r.discovery_hits or 0),
            research_status=r.research_status,
            priority_tier=r.priority_tier,
            created_at=r.created_at.isoformat() if r.created_at else None,
            evidence_summary=_evidence_summary(r.discovery_evidence),
        )
        for r in disc_rows
    ]

    currently_researching = [
        ResearchingCharacter(
            id=r.id,
            name=r.name,
            universe=r.universe,
            research_status=r.research_status,
            research_depth_score=float(r.research_depth_score or 0.0),
            fact_count=len(r.fact_bank or []),
            image_count=img_counts.get(r.id, 0),
            last_researched=r.last_researched.isoformat() if r.last_researched else None,
        )
        for r in res_rows
    ]

    recent_carousels = []
    for car, char_name in car_rows:
        ai_review = car.ai_review or {}
        score = ai_review.get("final_review_score") if isinstance(ai_review, dict) else None
        recent_carousels.append(RecentCarousel(
            id=car.id,
            character_id=car.character_id,
            character_name=char_name,
            angle=car.angle,
            hook_text=(car.hook_text or "")[:140] if car.hook_text else None,
            status=car.status,
            final_review_score=float(score) if isinstance(score, (int, float)) else None,
            auto_approved=bool(car.auto_approved) if car.auto_approved is not None else None,
            created_at=car.created_at.isoformat() if car.created_at else None,
        ))

    return AutopilotActivity(
        recently_discovered=recently_discovered,
        currently_researching=currently_researching,
        recent_carousels=recent_carousels,
        counts={
            "total_discovered": int(total_discovered),
            "total_researching": int(total_researching),
            "total_pending_research": int(total_pending),
            "total_in_progress_carousels": int(total_in_progress_carousels),
        },
    )
