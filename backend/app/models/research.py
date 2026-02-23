"""
Research Agent data models.
Models for autonomous web research, findings tracking, and self-improvement.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class ResearchTopicStatus(str, Enum):
    """Status of a research topic."""
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class FindingStatus(str, Enum):
    """Status of a research finding."""
    NEW = "new"
    REVIEWED = "reviewed"
    ACTIONABLE = "actionable"
    TASK_CREATED = "task_created"
    DISMISSED = "dismissed"


class FindingCategory(str, Enum):
    """Category of a research finding."""
    TOOL = "tool"
    PATTERN = "pattern"
    TECHNIQUE = "technique"
    PROJECT = "project"
    ARTICLE = "article"
    REPO = "repo"
    OTHER = "other"


class ResearchTopicCreate(BaseModel):
    """Schema for creating a research topic."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    search_queries: List[str] = Field(default_factory=list)
    aspects: List[str] = Field(default_factory=list)
    category_tags: List[str] = Field(default_factory=list)
    frequency: str = Field("daily", pattern="^(daily|weekly)$")
    category_id: Optional[str] = None


class ResearchTopicUpdate(BaseModel):
    """Schema for updating a research topic."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    search_queries: Optional[List[str]] = None
    aspects: Optional[List[str]] = None
    category_tags: Optional[List[str]] = None
    status: Optional[ResearchTopicStatus] = None
    frequency: Optional[str] = Field(None, pattern="^(daily|weekly)$")


class ResearchTopic(BaseModel):
    """Full research topic model."""
    id: str
    name: str
    description: Optional[str] = None
    search_queries: List[str] = Field(default_factory=list)
    aspects: List[str] = Field(default_factory=list)
    category_tags: List[str] = Field(default_factory=list)
    status: ResearchTopicStatus = ResearchTopicStatus.ACTIVE
    frequency: str = "daily"
    last_researched_at: Optional[datetime] = None
    findings_count: int = 0
    relevance_score: float = Field(50.0, ge=0, le=100)
    category_id: Optional[str] = None


class ResearchFinding(BaseModel):
    """A single research discovery."""
    id: str
    topic_id: str = ""
    title: str
    url: str
    snippet: str = ""
    source_engine: Optional[str] = None
    category: FindingCategory = FindingCategory.OTHER
    status: FindingStatus = FindingStatus.NEW

    # Scoring
    relevance_score: float = Field(50.0, ge=0, le=100)
    novelty_score: float = Field(50.0, ge=0, le=100)
    actionability_score: float = Field(50.0, ge=0, le=100)
    composite_score: float = Field(50.0, ge=0, le=100)

    # LLM analysis
    llm_summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    suggested_task: Optional[str] = None

    # Linking
    linked_task_id: Optional[str] = None
    category_id: Optional[str] = None
    fired_rule_ids: List[str] = Field(default_factory=list)

    # Timestamps
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None


class ResearchCycleResult(BaseModel):
    """Result of a single research cycle."""
    cycle_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    topics_researched: int = 0
    total_results: int = 0
    new_findings: int = 0
    duplicate_filtered: int = 0
    high_value_findings: int = 0
    tasks_created: int = 0
    errors: List[str] = Field(default_factory=list)


class ResearchStats(BaseModel):
    """Statistics about the research pipeline."""
    total_topics: int
    active_topics: int
    total_findings: int
    findings_this_week: int
    tasks_created_total: int
    tasks_created_this_week: int
    avg_relevance_score: float
    top_finding: Optional[str] = None
    last_cycle_at: Optional[datetime] = None


class FeedbackEntry(BaseModel):
    """Tracks user feedback for self-improvement."""
    finding_id: str
    action: str  # useful, not_useful, created_task, dismissed
    timestamp: datetime
    topic_id: Optional[str] = None
