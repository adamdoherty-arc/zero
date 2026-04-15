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
    carousel = await service.update_carousel(carousel_id, data)
    if not carousel:
        raise HTTPException(status_code=404, detail="Carousel not found")
    return carousel


@router.post("/carousels/{carousel_id}/review", response_model=CharacterCarousel)
async def ai_review_carousel(carousel_id: str):
    """Trigger AI review of a carousel."""
    service = get_character_content_service()
    try:
        return await service.ai_review_carousel(carousel_id)
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


# ============================================
# CHARACTER IMAGES
# ============================================

@router.get("/{character_id}/images", response_model=List[CharacterImage])
async def list_character_images(character_id: str):
    """List sourced images for a character."""
    service = get_character_content_service()
    return await service.list_images(character_id)


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
