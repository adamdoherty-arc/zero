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
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: Optional[str] = None
    search_queries: List[str] = Field(default_factory=list, alias="searchQueries")
    aspects: List[str] = Field(default_factory=list)
    category_tags: List[str] = Field(default_factory=list, alias="categoryTags")
    status: ResearchTopicStatus = ResearchTopicStatus.ACTIVE
    frequency: str = "daily"
    last_researched_at: Optional[datetime] = Field(None, alias="lastResearchedAt")
    findings_count: int = Field(0, alias="findingsCount")
    relevance_score: float = Field(50.0, ge=0, le=100, alias="relevanceScore")


class ResearchFinding(BaseModel):
    """A single research discovery."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    topic_id: str = Field(alias="topicId")
    title: str
    url: str
    snippet: str = ""
    source_engine: Optional[str] = Field(None, alias="sourceEngine")
    category: FindingCategory = FindingCategory.OTHER
    status: FindingStatus = FindingStatus.NEW

    # Scoring
    relevance_score: float = Field(50.0, ge=0, le=100, alias="relevanceScore")
    novelty_score: float = Field(50.0, ge=0, le=100, alias="noveltyScore")
    actionability_score: float = Field(50.0, ge=0, le=100, alias="actionabilityScore")
    composite_score: float = Field(50.0, ge=0, le=100, alias="compositeScore")

    # LLM analysis
    llm_summary: Optional[str] = Field(None, alias="llmSummary")
    tags: List[str] = Field(default_factory=list)
    suggested_task: Optional[str] = Field(None, alias="suggestedTask")

    # Linking
    linked_task_id: Optional[str] = Field(None, alias="linkedTaskId")

    # Timestamps
    discovered_at: datetime = Field(default_factory=datetime.utcnow, alias="discoveredAt")
    reviewed_at: Optional[datetime] = Field(None, alias="reviewedAt")


class ResearchCycleResult(BaseModel):
    """Result of a single research cycle."""
    model_config = ConfigDict(populate_by_name=True)

    cycle_id: str = Field(alias="cycleId")
    started_at: datetime = Field(alias="startedAt")
    completed_at: Optional[datetime] = Field(None, alias="completedAt")
    topics_researched: int = Field(0, alias="topicsResearched")
    total_results: int = Field(0, alias="totalResults")
    new_findings: int = Field(0, alias="newFindings")
    duplicate_filtered: int = Field(0, alias="duplicateFiltered")
    high_value_findings: int = Field(0, alias="highValueFindings")
    tasks_created: int = Field(0, alias="tasksCreated")
    errors: List[str] = Field(default_factory=list)


class ResearchStats(BaseModel):
    """Statistics about the research pipeline."""
    model_config = ConfigDict(populate_by_name=True)

    total_topics: int = Field(alias="totalTopics")
    active_topics: int = Field(alias="activeTopics")
    total_findings: int = Field(alias="totalFindings")
    findings_this_week: int = Field(alias="findingsThisWeek")
    tasks_created_total: int = Field(alias="tasksCreatedTotal")
    tasks_created_this_week: int = Field(alias="tasksCreatedThisWeek")
    avg_relevance_score: float = Field(alias="avgRelevanceScore")
    top_finding: Optional[str] = Field(None, alias="topFinding")
    last_cycle_at: Optional[datetime] = Field(None, alias="lastCycleAt")


class FeedbackEntry(BaseModel):
    """Tracks user feedback for self-improvement."""
    model_config = ConfigDict(populate_by_name=True)

    finding_id: str = Field(alias="findingId")
    action: str  # useful, not_useful, created_task, dismissed
    timestamp: datetime
    topic_id: Optional[str] = Field(None, alias="topicId")
