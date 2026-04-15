"""
Character Content Pipeline data models.
Models for character profiles, carousel posts, images, and content review.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class CharacterUniverse(str, Enum):
    MARVEL = "marvel"
    DC = "dc"
    STAR_WARS = "star_wars"
    LOTR = "lotr"
    HARRY_POTTER = "harry_potter"
    ANIME = "anime"
    TV = "tv"
    FILM = "film"
    GAMING = "gaming"
    OTHER = "other"


class CharacterStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ResearchStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    COMPLETED = "completed"
    FAILED = "failed"


class CarouselStatus(str, Enum):
    DRAFT = "draft"
    AI_REVIEWED = "ai_reviewed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"


class ContentAngle(str, Enum):
    HIDDEN_TRUTHS = "hidden_truths"
    POWER_SECRETS = "power_secrets"
    UNDERRATED_MOMENTS = "underrated_moments"
    ORIGIN_STORY = "origin_story"
    CHARACTER_EVOLUTION = "character_evolution"
    CONTROVERSIAL_TAKES = "controversial_takes"
    VS_COMPARISON = "vs_comparison"
    BEHIND_SCENES = "behind_scenes"
    FAN_THEORIES = "fan_theories"
    DARK_FACTS = "dark_facts"
    ACTOR_SECRETS = "actor_secrets"
    EASTER_EGGS = "easter_eggs"
    CROSSOVER_CONNECTIONS = "crossover_connections"
    WHAT_IF = "what_if"
    TIMELINE_DEEP_DIVE = "timeline_deep_dive"


class StoryTemplateType(str, Enum):
    SECRETS_REVEALED = "secrets_revealed"
    HIDDEN_CONNECTION = "hidden_connection"
    DARK_ORIGIN = "dark_origin"
    FAN_THEORY_DEEP_DIVE = "fan_theory_deep_dive"
    ACTOR_BEHIND_ROLE = "actor_behind_role"
    VERSUS_BREAKDOWN = "versus_breakdown"
    TIMELINE_TRAGEDY = "timeline_tragedy"
    WHAT_THEY_CHANGED = "what_they_changed"
    REAL_LIFE_INSPIRATION = "real_life_inspiration"
    DELETED_SCENES = "deleted_scenes"


class MusicMood(str, Enum):
    EPIC = "epic"
    DARK = "dark"
    EMOTIONAL = "emotional"
    MYSTERIOUS = "mysterious"
    DRAMATIC = "dramatic"
    HYPE = "hype"
    CHILL = "chill"


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------

class CharacterCreate(BaseModel):
    name: str
    universe: CharacterUniverse = CharacterUniverse.OTHER
    franchise: Optional[str] = None
    real_name: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    universe: Optional[CharacterUniverse] = None
    franchise: Optional[str] = None
    real_name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[CharacterStatus] = None


class Character(BaseModel):
    id: str
    name: str
    universe: str
    franchise: Optional[str] = None
    real_name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    research_data: Dict[str, Any] = Field(default_factory=dict)
    research_status: str = "pending"
    fact_bank: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    posts_created: int = 0
    total_views: int = 0
    total_likes: int = 0
    avg_engagement: float = 0.0
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_researched: Optional[datetime] = None
    research_sources: List[str] = Field(default_factory=list)
    relationship_map: Dict[str, Any] = Field(default_factory=dict)
    research_depth_score: float = 0.0
    content_themes: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Carousel
# ---------------------------------------------------------------------------

class CarouselSlide(BaseModel):
    slide_num: int
    text: str
    image_query: Optional[str] = None
    image_url: Optional[str] = None


class CarouselCreate(BaseModel):
    character_id: str
    angle: ContentAngle = ContentAngle.HIDDEN_TRUTHS
    story_template: Optional[str] = None
    multi_character_ids: Optional[List[str]] = None
    series_id: Optional[str] = None
    series_part: Optional[int] = None
    slide_count: int = 6


class CarouselUpdate(BaseModel):
    hook_text: Optional[str] = None
    slides: Optional[List[Dict[str, Any]]] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    music_mood: Optional[str] = None
    human_notes: Optional[str] = None


class AIReviewResult(BaseModel):
    hook_strength: float = 0.0
    fact_quality: float = 0.0
    engagement_potential: float = 0.0
    caption_quality: float = 0.0
    overall_score: float = 0.0
    suggestions: List[str] = Field(default_factory=list)
    fact_check_flags: List[str] = Field(default_factory=list)


class CharacterCarousel(BaseModel):
    id: str
    character_id: str
    character_name: Optional[str] = None
    angle: str
    title: Optional[str] = None
    hook_text: Optional[str] = None
    slides: List[Dict[str, Any]] = Field(default_factory=list)
    caption: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    music_mood: Optional[str] = None
    ai_review: Optional[Dict[str, Any]] = None
    ai_review_score: Optional[float] = None
    human_notes: Optional[str] = None
    status: str = "draft"
    content_queue_id: Optional[str] = None
    publish_url: Optional[str] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    engagement_rate: Optional[float] = None
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    story_template: Optional[str] = None
    series_id: Optional[str] = None
    series_part: Optional[int] = None
    multi_character_ids: List[str] = Field(default_factory=list)
    music_track: Optional[Dict[str, Any]] = None
    text_overlay_specs: List[Dict[str, Any]] = Field(default_factory=list)
    brain_context_used: Optional[Dict[str, Any]] = None
    generation_metadata: Dict[str, Any] = Field(default_factory=dict)
    publish_status: Optional[str] = None
    publish_platform: Optional[str] = None
    download_urls: Optional[List[str]] = None
    watermark_applied: bool = False


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

class CharacterImageCreate(BaseModel):
    character_id: str
    url: str
    source: str = "manual"
    is_primary: bool = False


class CharacterImage(BaseModel):
    id: str
    character_id: str
    url: str
    source: str = "manual"
    query_used: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_valid: bool = True
    is_primary: bool = False
    usage_count: int = 0
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Request / Response helpers
# ---------------------------------------------------------------------------

class PublishRequest(BaseModel):
    """Request to queue a carousel for publishing."""
    platform: str = "tiktok"
    schedule_at: Optional[datetime] = None
    caption_variant: Optional[str] = None


class PublishStatus(BaseModel):
    """Publishing status response."""
    carousel_id: str
    publish_status: Optional[str] = None
    publish_platform: Optional[str] = None
    published_at: Optional[datetime] = None
    publish_url: Optional[str] = None
    download_urls: Optional[List[str]] = None


class CarouselApproval(BaseModel):
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    human_notes: Optional[str] = None


class CarouselRejection(BaseModel):
    reason: str
    human_notes: Optional[str] = None


class BatchGenerateRequest(BaseModel):
    universe: Optional[CharacterUniverse] = None
    character_ids: Optional[List[str]] = None
    angle: Optional[ContentAngle] = None
    count: int = 5
    story_template: Optional[str] = None
    use_brain: bool = True


class CharacterStats(BaseModel):
    total_characters: int = 0
    characters_researched: int = 0
    total_carousels: int = 0
    carousels_by_status: Dict[str, int] = Field(default_factory=dict)
    total_published: int = 0
    total_views: int = 0
    total_likes: int = 0
    avg_engagement_rate: float = 0.0
    top_characters: List[Dict[str, Any]] = Field(default_factory=list)
    top_angles: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Research & Relationships
# ---------------------------------------------------------------------------

class ResearchFragment(BaseModel):
    """Research fragment from multi-source research."""
    id: str
    character_id: str
    source: str  # fandom_wiki, reddit, tvtropes, imdb, quotes
    content: str
    url: Optional[str] = None
    relevance_score: float = 0.5
    fragment_type: str = "lore"  # lore, fan_theory, behind_scenes, trivia, relationship, quote
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class CharacterRelationship(BaseModel):
    """Relationship between two characters."""
    id: str
    character_a_id: str
    character_b_id: str
    relationship_type: str  # ally, enemy, mentor, rival, family, lover, complicated
    description: Optional[str] = None
    strength: float = 0.5  # 0-1 how strong the connection
    source: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Content Inspiration
# ---------------------------------------------------------------------------

class ContentInspiration(BaseModel):
    """Inspiration from viral creator analysis."""
    id: str
    platform: str  # tiktok, instagram
    source_url: Optional[str] = None
    creator_handle: Optional[str] = None
    content_type: Optional[str] = None  # character_facts, comparison, story, quiz
    hook_text: Optional[str] = None
    slide_count: Optional[int] = None
    structure_analysis: Optional[Dict[str, Any]] = None
    engagement_metrics: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    patterns_extracted: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "pending"
    created_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None


class ContentInspirationCreate(BaseModel):
    platform: str = "tiktok"
    source_url: str
    creator_handle: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

class MusicTrack(BaseModel):
    """Music track for carousel content."""
    id: str
    name: str
    artist: Optional[str] = None
    mood: str  # epic, dark, emotional, mysterious, dramatic, hype, chill
    energy_level: Optional[str] = None  # low, medium, high
    genre: Optional[str] = None
    tiktok_sound_id: Optional[str] = None
    tiktok_sound_url: Optional[str] = None
    is_trending: bool = False
    trending_score: float = 0.0
    use_count: int = 0
    avg_engagement: float = 0.0
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class MusicTrackCreate(BaseModel):
    name: str
    artist: Optional[str] = None
    mood: str = "epic"
    energy_level: Optional[str] = None
    genre: Optional[str] = None
    tiktok_sound_id: Optional[str] = None
    tiktok_sound_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Story Templates
# ---------------------------------------------------------------------------

class StoryTemplate(BaseModel):
    """Reusable story template for carousel generation."""
    id: str
    name: str
    template_type: str
    description: Optional[str] = None
    slide_structure: List[Dict[str, Any]] = Field(default_factory=list)
    prompt_template: str = ""
    example_hook: Optional[str] = None
    suitable_angles: List[str] = Field(default_factory=list)
    suitable_universes: List[str] = Field(default_factory=list)
    times_used: int = 0
    avg_score: float = 0.0
    is_active: bool = True
    created_at: Optional[datetime] = None


class StoryTemplateCreate(BaseModel):
    name: str
    template_type: str
    description: Optional[str] = None
    slide_structure: List[Dict[str, Any]]
    prompt_template: str
    example_hook: Optional[str] = None
    suitable_angles: List[str] = Field(default_factory=list)
    suitable_universes: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Text Overlay
# ---------------------------------------------------------------------------

class TextOverlaySpec(BaseModel):
    """Text overlay specification per carousel slide."""
    slide_num: int
    text_position: str = "center"  # top, center, bottom
    font_weight: str = "bold"  # normal, bold, black
    font_style: str = "sans"  # sans, serif, handwritten
    max_chars_per_line: int = 30
    background_overlay: float = 0.4  # 0-1 opacity behind text
    text_color: str = "#FFFFFF"
    text_shadow: bool = True
    emoji_placement: Optional[str] = None  # before, after, none


# ---------------------------------------------------------------------------
# Research Job Tracking
# ---------------------------------------------------------------------------

class ResearchJobStatus(str, Enum):
    QUEUED = "queued"
    RESEARCHING = "researching"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchJobStep(BaseModel):
    """A single step in the research pipeline."""
    name: str  # e.g. "searxng_search", "wiki_scrape", "deep_research", "synthesis", "facts", "images"
    status: str = "pending"  # pending, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_summary: Optional[str] = None
    error: Optional[str] = None


class ResearchJob(BaseModel):
    """Tracks progress of a character research job."""
    id: str
    character_id: str
    character_name: str
    universe: str
    status: str = "queued"
    steps: List[ResearchJobStep] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    facts_found: int = 0
    images_found: int = 0
    sources_used: List[str] = Field(default_factory=list)
    depth_score: float = 0.0


class ResearchQueueStatus(BaseModel):
    """Overall research queue status."""
    total_jobs: int = 0
    queued: int = 0
    researching: int = 0
    completed: int = 0
    failed: int = 0
    current_character: Optional[str] = None
    current_step: Optional[str] = None
    jobs: List[ResearchJob] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    estimated_completion: Optional[str] = None
