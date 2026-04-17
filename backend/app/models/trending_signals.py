"""Trending signals: release calendar + viral trend Pydantic models."""

from datetime import date, datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TrendSource(str, Enum):
    TMDB_UPCOMING = "tmdb_upcoming"
    TMDB_NOW_PLAYING = "tmdb_now_playing"
    TMDB_ON_THE_AIR = "tmdb_on_the_air"
    TMDB_AIRING_TODAY = "tmdb_airing_today"
    TMDB_TRENDING_MOVIE = "tmdb_trending_movie"
    TMDB_TRENDING_TV = "tmdb_trending_tv"
    TVMAZE_SCHEDULE = "tvmaze_schedule"
    REDDIT_RISING = "reddit_rising"
    GOOGLE_TRENDS = "google_trends"
    SEARXNG_PULSE = "searxng_pulse"


class SignalType(str, Enum):
    RELEASE = "release"
    TRENDING = "trending"
    VIRAL = "viral"


class TrendingSignal(BaseModel):
    id: str
    source: str
    signal_type: str
    title: str
    franchise: Optional[str] = None
    universe: Optional[str] = None
    media_type: Optional[str] = None
    release_date: Optional[date] = None
    signal_strength: float
    score_reasoning: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    external_id: Optional[str] = None
    linked_character_ids: List[str] = Field(default_factory=list)
    linked_media_title_ids: List[str] = Field(default_factory=list)
    processed_at: Optional[datetime] = None
    triggered_content_at: Optional[datetime] = None
    discovered_at: datetime
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TrendingSignalSummary(BaseModel):
    """Lightweight shape for list views."""
    id: str
    source: str
    signal_type: str
    title: str
    franchise: Optional[str] = None
    media_type: Optional[str] = None
    release_date: Optional[date] = None
    signal_strength: float
    linked_character_count: int = 0
    linked_media_title_count: int = 0
    triggered_content_at: Optional[datetime] = None
    discovered_at: datetime


class UpcomingRelease(BaseModel):
    """Release-calendar view. Shows what's dropping + who's already prepped."""
    signal_id: str
    title: str
    franchise: Optional[str] = None
    media_type: Optional[str] = None
    release_date: date
    days_until: int
    signal_strength: float
    linked_character_ids: List[str] = Field(default_factory=list)
    linked_media_title_ids: List[str] = Field(default_factory=list)
    triggered_content_at: Optional[datetime] = None


class TrendRefreshResponse(BaseModel):
    triggered: List[str]
    errors: Dict[str, str] = Field(default_factory=dict)


class TrendLinkResponse(BaseModel):
    signal_id: str
    linked_character_ids: List[str]
    linked_media_title_ids: List[str]
    created_media_title_id: Optional[str] = None
