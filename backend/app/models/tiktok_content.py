"""
TikTok Content Pipeline data models.
Models for faceless video scripts, content generation queue, and template management.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class VideoTemplateType(str, Enum):
    """Available faceless video template types."""
    VOICEOVER_BROLL = "voiceover_broll"
    TEXT_OVERLAY_SHOWCASE = "text_overlay_showcase"
    BEFORE_AFTER = "before_after"
    LISTICLE_TOPN = "listicle_topn"
    PROBLEM_SOLUTION = "problem_solution"
    PHOTO_CAROUSEL = "photo_carousel"


class VideoScriptStatus(str, Enum):
    """Status of a video script."""
    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    GENERATED = "generated"
    FAILED = "failed"


class ContentQueueStatus(str, Enum):
    """Status of a content queue item."""
    QUEUED = "queued"
    SCRIPT_READY = "script_ready"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoScriptCreate(BaseModel):
    """Request to generate a video script."""
    product_id: str
    template_type: VideoTemplateType = VideoTemplateType.VOICEOVER_BROLL


class VideoScriptUpdate(BaseModel):
    """Editable fields of a video script."""
    hook_text: Optional[str] = None
    body_sections: Optional[List[Dict[str, Any]]] = None
    cta_text: Optional[str] = None
    text_overlays: Optional[List[str]] = None
    voiceover_script: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: Optional[VideoScriptStatus] = None


class VideoScript(BaseModel):
    """Full video script model."""
    id: str
    product_id: str
    topic_id: Optional[str] = None
    template_type: VideoTemplateType
    hook_text: str = ""
    body_sections: List[Dict[str, Any]] = Field(default_factory=list)
    cta_text: str = ""
    text_overlays: List[str] = Field(default_factory=list)
    voiceover_script: str = ""
    duration_seconds: int = 30
    status: VideoScriptStatus = VideoScriptStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    generated_at: Optional[datetime] = None


class PublishStatus(str, Enum):
    """Status of content publishing."""
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"


class ContentQueueItem(BaseModel):
    """An item in the content generation queue."""
    id: str
    script_id: str
    product_id: str
    generation_type: str = "text_to_video"
    act_job_id: Optional[str] = None
    act_generation_id: Optional[str] = None
    status: ContentQueueStatus = ContentQueueStatus.QUEUED
    error_message: Optional[str] = None
    # Publishing fields
    publish_status: Optional[str] = None
    publish_platform: Optional[str] = None
    publish_url: Optional[str] = None
    published_at: Optional[datetime] = None
    publish_error: Optional[str] = None
    caption: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    # Content format & video
    video_url: Optional[str] = None
    content_format: str = "video"
    carousel_data: Optional[Dict[str, Any]] = None
    # Manual posting & performance
    manually_published_url: Optional[str] = None
    performance_views: Optional[int] = None
    performance_likes: Optional[int] = None
    performance_comments: Optional[int] = None
    performance_shares: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class PublishRequest(BaseModel):
    """Request to publish content."""
    platform: str = "tiktok"
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    schedule_time: Optional[datetime] = None


class ContentApproval(BaseModel):
    """Request to approve content for publishing."""
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None


class ContentQueueStats(BaseModel):
    """Statistics about the content generation queue."""
    total_queued: int = 0
    generating: int = 0
    completed: int = 0
    failed: int = 0
    total_scripts: int = 0
    scripts_by_template: Dict[str, int] = Field(default_factory=dict)


class VideoTemplateInfo(BaseModel):
    """Description of a faceless video template."""
    type: VideoTemplateType
    name: str
    description: str
    duration: int
    sections: List[str]
