"""
Reference Video models for TikTok video inspiration / copy feature.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ReferenceVideoCreate(BaseModel):
    """Create a reference video from a TikTok URL."""
    tiktok_url: str = Field(..., min_length=5)
    product_id: Optional[str] = None


class ReferenceVideoUpdate(BaseModel):
    """Update reference video fields."""
    product_id: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    style_notes: Optional[str] = None
    status: Optional[str] = None


class ReferenceVideo(BaseModel):
    """Full reference video model."""
    id: str
    tiktok_url: str
    product_id: Optional[str] = None

    # oEmbed metadata
    title: Optional[str] = None
    author_name: Optional[str] = None
    author_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    caption: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)

    # Engagement metrics
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None

    # LLM analysis
    hook_analysis: Optional[str] = None
    structure_analysis: Optional[str] = None
    style_notes: Optional[str] = None
    content_type: Optional[str] = None
    estimated_duration: Optional[int] = None

    # Generated script link
    generated_script_id: Optional[str] = None

    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    analyzed_at: Optional[datetime] = None
