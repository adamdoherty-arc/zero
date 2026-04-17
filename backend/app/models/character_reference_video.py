"""
Character Reference Video models.

TikTok videos captured from the user's phone and ingested into Zero for
character content development: style inspiration, fact extraction, or character discovery.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class RefVideoIntent(str, Enum):
    inbox = "inbox"
    inspiration = "inspiration"
    facts = "facts"
    discovery = "discovery"


class RefVideoStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    downloaded = "downloaded"
    transcribing = "transcribing"
    analyzing = "analyzing"
    ready = "ready"
    failed = "failed"


class StyleAnalysis(BaseModel):
    hook: Optional[str] = None
    structure: Optional[str] = None
    pacing: Optional[str] = None
    visual_style: Optional[str] = None
    transitions: Optional[str] = None
    estimated_engagement: Optional[str] = None


class ExtractedFact(BaseModel):
    text: str
    category: Optional[str] = None
    surprise_score: Optional[float] = None
    source_timecode: Optional[str] = None


class ProposedCharacter(BaseModel):
    name: Optional[str] = None
    universe: Optional[str] = None
    franchise: Optional[str] = None
    description: Optional[str] = None
    seed_facts: List[ExtractedFact] = Field(default_factory=list)


class CharacterReferenceVideoCreate(BaseModel):
    """Full create request."""
    tiktok_url: str = Field(..., min_length=5)
    character_id: Optional[str] = None
    intent: RefVideoIntent = RefVideoIntent.inbox
    notes: Optional[str] = None


class IngestSimpleRequest(BaseModel):
    """Minimal ingest used by Android share-intent shortcut."""
    url: Optional[str] = None
    text: Optional[str] = None


class IngestSimpleResponse(BaseModel):
    id: str
    status: RefVideoStatus
    tiktok_url: str


class CharacterReferenceVideoUpdate(BaseModel):
    intent: Optional[RefVideoIntent] = None
    character_id: Optional[str] = None
    notes: Optional[str] = None


class AssignCharacterRequest(BaseModel):
    character_id: str


class ApplyFactsRequest(BaseModel):
    fact_indexes: Optional[List[int]] = None  # None means apply all


class PromoteToCharacterRequest(BaseModel):
    name: Optional[str] = None
    universe: Optional[str] = None
    franchise: Optional[str] = None
    description: Optional[str] = None


class CharacterReferenceVideo(BaseModel):
    id: str
    tiktok_url: str
    tiktok_video_id: Optional[str] = None
    character_id: Optional[str] = None
    intent: RefVideoIntent = RefVideoIntent.inbox
    status: RefVideoStatus = RefVideoStatus.pending
    error_message: Optional[str] = None
    retry_count: int = 0

    title: Optional[str] = None
    author_name: Optional[str] = None
    author_url: Optional[str] = None
    caption: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    views: Optional[int] = None
    likes: Optional[int] = None

    video_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    audio_path: Optional[str] = None
    file_size_bytes: Optional[int] = None

    transcript: Optional[str] = None
    transcript_language: Optional[str] = None
    transcribed_at: Optional[datetime] = None

    style_analysis: Optional[StyleAnalysis] = None
    extracted_facts: Optional[List[ExtractedFact]] = None
    proposed_character: Optional[ProposedCharacter] = None
    analyzed_at: Optional[datetime] = None

    notes: Optional[str] = None
    promoted_character_id: Optional[str] = None
    applied_fact_count: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class DeleteResponse(BaseModel):
    status: str
    id: str


class PromoteResponse(BaseModel):
    reference_video_id: str
    character_id: str
    status: str


class ApplyFactsResponse(BaseModel):
    reference_video_id: str
    character_id: str
    applied_count: int
    total_fact_bank_size: int
