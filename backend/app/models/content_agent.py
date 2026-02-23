"""
Content Agent data models.
Models for content topic management, examples, rules, generation, and performance tracking.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class ContentStyle(str, Enum):
    """Style of content to generate."""
    EDUCATIONAL = "educational"
    ENTERTAINMENT = "entertainment"
    REVIEW = "review"
    TRENDING = "trending"
    CHALLENGE = "challenge"
    LIFESTYLE = "lifestyle"
    TUTORIAL = "tutorial"


class ContentTopicStatus(str, Enum):
    """Status of a content topic."""
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ContentTopicCreate(BaseModel):
    """Schema for creating a content topic."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    niche: str = Field("general", max_length=100)
    platform: str = Field("tiktok", pattern="^(tiktok|instagram|youtube_shorts|general)$")
    tiktok_product_id: Optional[str] = None
    content_style: Optional[ContentStyle] = None
    target_audience: Optional[str] = None
    tone_guidelines: Optional[str] = None
    hashtag_strategy: List[str] = Field(default_factory=list)


class ContentTopicUpdate(BaseModel):
    """Schema for updating a content topic."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[ContentTopicStatus] = None
    niche: Optional[str] = Field(None, max_length=100)
    platform: Optional[str] = Field(None, pattern="^(tiktok|instagram|youtube_shorts|general)$")
    content_style: Optional[ContentStyle] = None
    target_audience: Optional[str] = None
    tone_guidelines: Optional[str] = None
    hashtag_strategy: Optional[List[str]] = None


class ContentTopic(BaseModel):
    """Full content topic model."""
    id: str
    name: str
    description: Optional[str] = None
    niche: str = "general"
    platform: str = "tiktok"
    tiktok_product_id: Optional[str] = None

    # Rules (LLM-generated and user-refined)
    rules: List[dict] = Field(default_factory=list)

    # Content parameters
    content_style: Optional[ContentStyle] = None
    target_audience: Optional[str] = None
    tone_guidelines: Optional[str] = None
    hashtag_strategy: List[str] = Field(default_factory=list)

    # Performance
    status: ContentTopicStatus = ContentTopicStatus.ACTIVE
    examples_count: int = 0
    avg_performance_score: float = 0.0
    content_generated_count: int = 0

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class ContentExampleCreate(BaseModel):
    """Schema for adding a content example."""
    topic_id: str
    title: Optional[str] = None
    caption: Optional[str] = None
    script: Optional[str] = None
    url: Optional[str] = None
    platform: str = Field("tiktok", pattern="^(tiktok|instagram|youtube_shorts|general)$")
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    source: str = Field("manual", pattern="^(manual|scraped|generated|imported)$")


class ContentExample(BaseModel):
    """Full content example model."""
    id: str
    topic_id: str
    title: Optional[str] = None
    caption: Optional[str] = None
    script: Optional[str] = None
    url: Optional[str] = None
    platform: str = "tiktok"
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    performance_score: float = 50.0
    source: str = "manual"
    rule_contributions: List[str] = Field(default_factory=list)
    added_at: datetime = Field(default_factory=datetime.utcnow)


class RuleGenerateRequest(BaseModel):
    """Request to generate rules for a content topic."""
    topic_id: str
    focus: Optional[str] = None


class RuleUpdateRequest(BaseModel):
    """Request to update a specific rule."""
    topic_id: str
    rule_id: str
    text: str


class ContentGenerateRequest(BaseModel):
    """Request to generate content via AIContentTools."""
    topic_id: str
    persona_id: Optional[str] = None
    count: int = Field(1, ge=1, le=10)
    content_type: str = Field("video", pattern="^(video|image|carousel|story|reel)$")
    extra_prompt: Optional[str] = None


class ContentGenerateResponse(BaseModel):
    """Response from content generation."""
    job_ids: List[str] = Field(default_factory=list)
    act_generation_ids: List[str] = Field(default_factory=list)
    topic_id: str
    status: str = "queued"


class ContentPerformanceRecord(BaseModel):
    """Performance record for generated content."""
    id: str
    topic_id: str
    tiktok_product_id: Optional[str] = None
    act_generation_id: Optional[str] = None
    act_persona_id: Optional[str] = None
    platform: str = "tiktok"
    content_type: str = "video"
    caption: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)

    # Metrics
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    engagement_rate: float = 0.0
    performance_score: float = 0.0

    feedback_processed: bool = False
    posted_at: Optional[datetime] = None
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAgentStats(BaseModel):
    """Statistics about the content agent."""
    total_topics: int = 0
    active_topics: int = 0
    total_examples: int = 0
    total_content_generated: int = 0
    avg_performance: float = 0.0
    top_performing_topic: Optional[str] = None
    rules_count: int = 0
    last_improvement_at: Optional[datetime] = None
