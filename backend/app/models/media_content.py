"""
TV & Movie Content Pipeline data models.
Models for media titles (TV shows, movies), carousel posts, and content review.
Shares carousel infrastructure with character content pipeline.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MediaType(str, Enum):
    TV_SHOW = "tv_show"
    MOVIE = "movie"


class MediaContentAngle(str, Enum):
    PLOT_HOLES = "plot_holes"
    BEST_EPISODES = "best_episodes"
    SHOWRUNNER_SECRETS = "showrunner_secrets"
    CASTING_STORIES = "casting_stories"
    DELETED_SCENES = "deleted_scenes"
    FAN_THEORIES = "fan_theories"
    SEQUEL_PREDICTIONS = "sequel_predictions"
    BOX_OFFICE_ANALYSIS = "box_office_analysis"
    CINEMATOGRAPHY = "cinematography"
    SOUNDTRACK_BREAKDOWN = "soundtrack_breakdown"
    SEASON_RANKING = "season_ranking"
    HIDDEN_DETAILS = "hidden_details"
    PRODUCTION_DISASTERS = "production_disasters"
    CULTURAL_IMPACT = "cultural_impact"
    ADAPTATION_CHANGES = "adaptation_changes"
    CONTROVERSIAL_DECISIONS = "controversial_decisions"


class MediaStoryTemplate(str, Enum):
    EPISODE_BREAKDOWN = "episode_breakdown"
    SEASON_ARC_ANALYSIS = "season_arc_analysis"
    DIRECTORS_VISION = "directors_vision"
    BEHIND_THE_SCENES = "behind_the_scenes"
    CAST_CHEMISTRY = "cast_chemistry"
    FRANCHISE_TIMELINE = "franchise_timeline"
    REMAKE_COMPARISON = "remake_comparison"
    BOX_OFFICE_BATTLE = "box_office_battle"
    GENRE_EVOLUTION = "genre_evolution"
    CLIFFHANGER_RANKING = "cliffhanger_ranking"
    ICONIC_SCENES = "iconic_scenes"
    WRITERS_ROOM = "writers_room"


class MediaRoleType(str, Enum):
    LEAD = "lead"
    SUPPORTING = "supporting"
    RECURRING = "recurring"
    GUEST = "guest"
    CAMEO = "cameo"


class MediaShowStatus(str, Enum):
    AIRING = "airing"
    ENDED = "ended"
    CANCELLED = "cancelled"
    UPCOMING = "upcoming"


# ---------------------------------------------------------------------------
# Media Title
# ---------------------------------------------------------------------------

class MediaTitleCreate(BaseModel):
    title: str
    media_type: MediaType = MediaType.MOVIE
    year: Optional[int] = None
    end_year: Optional[int] = None
    genre: List[str] = Field(default_factory=list)
    franchise: Optional[str] = None
    universe: Optional[str] = "other"
    synopsis: Optional[str] = None
    tagline: Optional[str] = None
    # TV-specific
    season_count: Optional[int] = None
    episode_count: Optional[int] = None
    network: Optional[str] = None
    show_status: Optional[str] = None
    # Movie-specific
    runtime_minutes: Optional[int] = None
    budget_usd: Optional[int] = None
    box_office_usd: Optional[int] = None
    mpaa_rating: Optional[str] = None
    # External IDs
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class MediaTitleUpdate(BaseModel):
    title: Optional[str] = None
    media_type: Optional[MediaType] = None
    year: Optional[int] = None
    end_year: Optional[int] = None
    genre: Optional[List[str]] = None
    franchise: Optional[str] = None
    universe: Optional[str] = None
    synopsis: Optional[str] = None
    tagline: Optional[str] = None
    season_count: Optional[int] = None
    episode_count: Optional[int] = None
    network: Optional[str] = None
    show_status: Optional[str] = None
    runtime_minutes: Optional[int] = None
    budget_usd: Optional[int] = None
    box_office_usd: Optional[int] = None
    mpaa_rating: Optional[str] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


class MediaTitle(BaseModel):
    id: str
    media_type: str
    title: str
    year: Optional[int] = None
    end_year: Optional[int] = None
    genre: List[str] = Field(default_factory=list)
    franchise: Optional[str] = None
    universe: Optional[str] = "other"
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    synopsis: Optional[str] = None
    tagline: Optional[str] = None
    # TV-specific
    season_count: Optional[int] = None
    episode_count: Optional[int] = None
    network: Optional[str] = None
    show_status: Optional[str] = None
    # Movie-specific
    runtime_minutes: Optional[int] = None
    budget_usd: Optional[int] = None
    box_office_usd: Optional[int] = None
    mpaa_rating: Optional[str] = None
    # Research
    research_data: Dict[str, Any] = Field(default_factory=dict)
    research_status: str = "pending"
    fact_bank: List[Dict[str, Any]] = Field(default_factory=list)
    research_sources: List[str] = Field(default_factory=list)
    research_depth_score: float = 0.0
    content_themes: List[str] = Field(default_factory=list)
    # External IDs
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # Stats
    carousels_created: int = 0
    total_views: int = 0
    total_likes: int = 0
    avg_engagement: float = 0.0
    # Meta
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_researched: Optional[datetime] = None
    # Linked characters count (populated on read)
    character_count: int = 0


# ---------------------------------------------------------------------------
# Character-Media Link
# ---------------------------------------------------------------------------

class CharacterMediaLinkCreate(BaseModel):
    character_id: str
    media_title_id: str
    role_name: Optional[str] = None
    role_type: MediaRoleType = MediaRoleType.SUPPORTING
    actor_name: Optional[str] = None
    seasons_appeared: List[int] = Field(default_factory=list)
    notes: Optional[str] = None


class CharacterMediaLink(BaseModel):
    id: str
    character_id: str
    media_title_id: str
    character_name: Optional[str] = None
    media_title_name: Optional[str] = None
    role_name: Optional[str] = None
    role_type: str = "supporting"
    actor_name: Optional[str] = None
    seasons_appeared: List[int] = Field(default_factory=list)
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    # Deep-link fields populated by list_linked_characters / appears_in joins.
    # Optional so older callers and serializers stay compatible.
    character_image_url: Optional[str] = None
    character_status: Optional[str] = None
    media_type: Optional[str] = None
    media_year: Optional[int] = None
    media_poster_url: Optional[str] = None
    media_franchise: Optional[str] = None
    media_universe: Optional[str] = None


# ---------------------------------------------------------------------------
# Media Carousel (extends character carousel with media context)
# ---------------------------------------------------------------------------

class MediaCarouselCreate(BaseModel):
    media_title_id: str
    angle: MediaContentAngle = MediaContentAngle.HIDDEN_DETAILS
    story_template: Optional[str] = None
    character_id: Optional[str] = None  # optional: tie to a specific character
    slide_count: int = 6
    hook_style: Optional[str] = None
    content_format: Optional[str] = None


# ---------------------------------------------------------------------------
# Media Image
# ---------------------------------------------------------------------------

class MediaImageCreate(BaseModel):
    media_title_id: str
    url: str
    source: str = "manual"
    is_primary: bool = False


class MediaImage(BaseModel):
    id: str
    media_title_id: str
    url: str
    source: str = "manual"
    query_used: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_valid: bool = True
    is_primary: bool = False
    usage_count: int = 0
    quality_score: float = 0.0
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    is_approved: Optional[bool] = None
    feedback_reason: Optional[str] = None
    validated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Media Research Fragment
# ---------------------------------------------------------------------------

class MediaResearchFragment(BaseModel):
    id: str
    media_title_id: str
    source: str
    content: str
    url: Optional[str] = None
    relevance_score: float = 0.5
    fragment_type: str = "trivia"  # trivia, production, behind_scenes, review, cast, plot, quote
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class MediaStats(BaseModel):
    total_titles: int = 0
    tv_shows: int = 0
    movies: int = 0
    titles_researched: int = 0
    total_carousels: int = 0
    carousels_by_status: Dict[str, int] = Field(default_factory=dict)
    total_published: int = 0
    total_views: int = 0
    total_likes: int = 0
    avg_engagement_rate: float = 0.0
    top_titles: List[Dict[str, Any]] = Field(default_factory=list)
    top_angles: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Research Job Tracking (mirrors character research)
# ---------------------------------------------------------------------------

class MediaResearchJob(BaseModel):
    id: str
    media_title_id: str
    title: str
    media_type: str
    status: str = "queued"
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    facts_found: int = 0
    images_found: int = 0
    sources_used: List[str] = Field(default_factory=list)
    depth_score: float = 0.0
    eta_seconds: Optional[int] = None


# ---------------------------------------------------------------------------
# Batch / Seed
# ---------------------------------------------------------------------------

class MediaBatchGenerateRequest(BaseModel):
    media_type: Optional[MediaType] = None
    media_title_ids: Optional[List[str]] = None
    angle: Optional[MediaContentAngle] = None
    count: int = 5
    story_template: Optional[str] = None
    hook_style: Optional[str] = None
    content_format: Optional[str] = None


class TMDBSearchResult(BaseModel):
    tmdb_id: int
    title: str
    media_type: str
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    vote_average: Optional[float] = None
    already_imported: bool = False
