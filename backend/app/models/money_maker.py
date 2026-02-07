"""
Money Maker data models.
Models for generating, researching, and tracking money-making ideas.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class IdeaStatus(str, Enum):
    """Status of a money-making idea."""
    NEW = "new"
    RESEARCHING = "researching"
    VALIDATED = "validated"
    PURSUING = "pursuing"
    PARKED = "parked"
    REJECTED = "rejected"
    COMPLETED = "completed"


class IdeaCategory(str, Enum):
    """Category of money-making idea."""
    SAAS = "saas"
    CONTENT = "content"
    FREELANCE = "freelance"
    CONSULTING = "consulting"
    AFFILIATE = "affiliate"
    PRODUCT = "product"
    AUTOMATION = "automation"
    OTHER = "other"


class TimeToROI(str, Enum):
    """Expected time to return on investment."""
    IMMEDIATE = "immediate"   # < 1 week
    SHORT = "short"           # 1-4 weeks
    MEDIUM = "medium"         # 1-3 months
    LONG = "long"             # 3-12 months
    VERY_LONG = "very_long"   # 12+ months


class MoneyIdeaCreate(BaseModel):
    """Schema for creating a new money idea."""
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    category: IdeaCategory = IdeaCategory.OTHER
    revenue_potential: float = Field(0, ge=0, description="Estimated monthly revenue potential in dollars")
    effort_score: float = Field(50, ge=0, le=100, description="Effort required (0=easy, 100=hard)")
    time_to_roi: TimeToROI = TimeToROI.MEDIUM
    first_steps: List[str] = Field(default_factory=list)
    resources_needed: List[str] = Field(default_factory=list)


class MoneyIdeaUpdate(BaseModel):
    """Schema for updating a money idea."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    category: Optional[IdeaCategory] = None
    status: Optional[IdeaStatus] = None
    revenue_potential: Optional[float] = Field(None, ge=0)
    effort_score: Optional[float] = Field(None, ge=0, le=100)
    time_to_roi: Optional[TimeToROI] = None
    market_validation: Optional[float] = Field(None, ge=0, le=100)
    competition_score: Optional[float] = Field(None, ge=0, le=100)
    skill_match: Optional[float] = Field(None, ge=0, le=100)
    research_notes: Optional[str] = None
    market_size: Optional[str] = None
    competitors: Optional[List[str]] = None
    first_steps: Optional[List[str]] = None
    resources_needed: Optional[List[str]] = None


class MoneyIdeaAction(BaseModel):
    """Schema for idea actions (pursue, park, reject)."""
    reason: Optional[str] = None
    sprint_id: Optional[str] = None


class MoneyIdea(BaseModel):
    """Full money idea model."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    description: Optional[str] = None
    category: IdeaCategory = IdeaCategory.OTHER
    status: IdeaStatus = IdeaStatus.NEW

    # Scoring (0-100 scale, except revenue_potential which is dollars)
    revenue_potential: float = Field(0, ge=0, alias="revenuePotential", description="Estimated monthly revenue in dollars")
    effort_score: float = Field(50, ge=0, le=100, alias="effortScore", description="Effort required (0=easy, 100=hard)")
    time_to_roi: TimeToROI = Field(TimeToROI.MEDIUM, alias="timeToRoi")
    market_validation: float = Field(50, ge=0, le=100, alias="marketValidation", description="Market demand validation score")
    competition_score: float = Field(50, ge=0, le=100, alias="competitionScore", description="Competition level (0=none, 100=saturated)")
    skill_match: float = Field(50, ge=0, le=100, alias="skillMatch", description="How well idea matches your skills")

    # Computed viability score
    viability_score: float = Field(0, ge=0, le=100, alias="viabilityScore")

    # Research data
    research_notes: Optional[str] = Field(None, alias="researchNotes")
    market_size: Optional[str] = Field(None, alias="marketSize")
    competitors: List[str] = Field(default_factory=list)
    resources_needed: List[str] = Field(default_factory=list, alias="resourcesNeeded")
    first_steps: List[str] = Field(default_factory=list, alias="firstSteps")

    # Tracking
    source: str = "llm_generated"
    rejection_reason: Optional[str] = Field(None, alias="rejectionReason")
    park_reason: Optional[str] = Field(None, alias="parkReason")
    linked_task_ids: List[str] = Field(default_factory=list, alias="linkedTaskIds")

    # Timestamps
    generated_at: datetime = Field(default_factory=datetime.utcnow, alias="generatedAt")
    last_researched_at: Optional[datetime] = Field(None, alias="lastResearchedAt")
    status_changed_at: Optional[datetime] = Field(None, alias="statusChangedAt")


class MoneyMakerStats(BaseModel):
    """Statistics about the money maker pipeline."""
    total_ideas: int = Field(alias="totalIdeas")
    by_status: dict = Field(alias="byStatus")
    by_category: dict = Field(alias="byCategory")
    top_viability_score: float = Field(alias="topViabilityScore")
    avg_viability_score: float = Field(alias="avgViabilityScore")
    ideas_this_week: int = Field(alias="ideasThisWeek")
    researched_this_week: int = Field(alias="researchedThisWeek")
