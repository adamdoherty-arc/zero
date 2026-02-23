"""
TikTok Shop Research Agent data models.
Models for product discovery, market opportunity scoring, and content idea generation.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class TikTokProductStatus(str, Enum):
    """Status of a TikTok Shop product."""
    DISCOVERED = "discovered"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RESEARCHED = "researched"
    CONTENT_PLANNED = "content_planned"
    ACTIVE = "active"
    PAUSED = "paused"
    REJECTED = "rejected"


class TikTokProductType(str, Enum):
    """Type of TikTok Shop product opportunity."""
    AFFILIATE = "affiliate"
    DROPSHIP = "dropship"
    OWN = "own"
    UNKNOWN = "unknown"


class TikTokProductCreate(BaseModel):
    """Schema for creating a TikTok product."""
    name: str = Field(..., min_length=1, max_length=500)
    category: str = Field("general", max_length=100)
    niche: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    source_url: Optional[str] = None
    marketplace_url: Optional[str] = None
    product_type: TikTokProductType = TikTokProductType.UNKNOWN
    tags: List[str] = Field(default_factory=list)
    price_range_min: Optional[float] = None
    price_range_max: Optional[float] = None
    commission_rate: Optional[float] = None
    source_article_title: Optional[str] = None
    source_article_url: Optional[str] = None
    is_extracted: bool = False
    why_trending: Optional[str] = None
    estimated_price_range: Optional[str] = None
    image_url: Optional[str] = None
    supplier_url: Optional[str] = None
    sourcing_method: Optional[str] = None


class TikTokProductUpdate(BaseModel):
    """Schema for updating a TikTok product."""
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    status: Optional[TikTokProductStatus] = None
    niche: Optional[str] = Field(None, max_length=100)
    category: Optional[str] = Field(None, max_length=100)
    product_type: Optional[TikTokProductType] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    supplier_url: Optional[str] = None
    supplier_name: Optional[str] = None
    sourcing_method: Optional[str] = None
    sourcing_notes: Optional[str] = None
    success_rating: Optional[float] = None


class TikTokProduct(BaseModel):
    """Full TikTok product model."""
    id: str
    name: str
    category: str = "general"
    niche: Optional[str] = None
    description: Optional[str] = None
    source_url: Optional[str] = None
    source_engine: Optional[str] = None
    marketplace_url: Optional[str] = None
    product_type: TikTokProductType = TikTokProductType.UNKNOWN

    # Scoring
    trend_score: float = Field(50.0, ge=0, le=100)
    competition_score: float = Field(50.0, ge=0, le=100)
    margin_score: float = Field(50.0, ge=0, le=100)
    opportunity_score: float = Field(50.0, ge=0, le=100)

    # Market data
    price_range_min: Optional[float] = None
    price_range_max: Optional[float] = None
    estimated_monthly_sales: Optional[int] = None
    competitor_count: Optional[int] = None
    commission_rate: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    llm_analysis: Optional[str] = None
    content_ideas: List[dict] = Field(default_factory=list)

    # Status & linking
    status: TikTokProductStatus = TikTokProductStatus.DISCOVERED
    linked_content_topic_id: Optional[str] = None
    linked_legion_task_id: Optional[str] = None

    # Approval tracking
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    # LLM extraction metadata
    source_article_title: Optional[str] = None
    source_article_url: Optional[str] = None
    is_extracted: bool = False
    why_trending: Optional[str] = None
    estimated_price_range: Optional[str] = None

    # Images
    image_url: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)

    # Success rating
    success_rating: Optional[float] = Field(None, ge=0, le=100)
    success_factors: dict = Field(default_factory=dict)

    # Sourcing
    supplier_url: Optional[str] = None
    supplier_name: Optional[str] = None
    sourcing_method: Optional[str] = None
    sourcing_notes: Optional[str] = None
    sourcing_links: List[dict] = Field(default_factory=list)
    listing_steps: List[str] = Field(default_factory=list)

    # Timestamps
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    last_researched_at: Optional[datetime] = None


class TikTokResearchCycleResult(BaseModel):
    """Result of a TikTok Shop research cycle."""
    cycle_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    products_discovered: int = 0
    products_researched: int = 0
    high_opportunity_count: int = 0
    content_topics_created: int = 0
    tasks_created: int = 0
    errors: List[str] = Field(default_factory=list)


class TikTokProductApproval(BaseModel):
    """Schema for batch approve/reject operations."""
    product_ids: List[str] = Field(..., min_length=1)
    rejection_reason: Optional[str] = None


class TikTokShopStats(BaseModel):
    """Statistics about the TikTok Shop research pipeline."""
    total_products: int = 0
    active_products: int = 0
    discovered_products: int = 0
    pending_approval_products: int = 0
    approved_products: int = 0
    avg_opportunity_score: float = 0.0
    top_niches: List[str] = Field(default_factory=list)
    products_this_week: int = 0
    content_topics_linked: int = 0
    last_research_at: Optional[datetime] = None
