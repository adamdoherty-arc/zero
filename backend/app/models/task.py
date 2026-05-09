"""
Task data models.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task workflow status."""
    BACKLOG = "backlog"
    TODO = "todo"
    ON_HOLD = "on_hold"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    TESTING = "testing"
    DONE = "done"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


class TaskCategory(str, Enum):
    """Task category/type."""
    BUG = "bug"
    FEATURE = "feature"
    ENHANCEMENT = "enhancement"
    CHORE = "chore"
    DOCUMENTATION = "documentation"


class TaskPriority(str, Enum):
    """Task priority level."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskSource(str, Enum):
    """Source of task creation."""
    MANUAL = "MANUAL"
    QA_DETECTED = "QA_DETECTED"
    ERROR_LOG = "ERROR_LOG"
    ENHANCEMENT_ENGINE = "ENHANCEMENT_ENGINE"
    USER_REPORTED = "USER_REPORTED"
    TODO_SCAN = "TODO_SCAN"


class TaskCreate(BaseModel):
    """Schema for creating a new task."""
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    sprint_id: Optional[str] = None
    project_id: Optional[str] = None
    category: TaskCategory = TaskCategory.FEATURE
    priority: TaskPriority = TaskPriority.MEDIUM
    points: Optional[int] = Field(None, ge=0, le=100)
    source: TaskSource = TaskSource.MANUAL
    source_reference: Optional[str] = None
    blocked_reason: Optional[str] = None
    domain: Optional[str] = None
    owner_agent: Optional[str] = None
    due_at: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None
    risk_level: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")
    approval_state: Optional[str] = Field(None, pattern="^(none|pending|approved|rejected|expired)$")
    approval_id: Optional[str] = None
    tags: Optional[list[str]] = None
    links: Optional[list[dict[str, Any]]] = None
    sort_order: Optional[int] = None
    estimate_points: Optional[int] = Field(None, ge=0, le=100)
    parent_task_id: Optional[str] = None


class TaskUpdate(BaseModel):
    """Schema for updating a task."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    sprint_id: Optional[str] = None
    project_id: Optional[str] = None
    status: Optional[TaskStatus] = None
    category: Optional[TaskCategory] = None
    priority: Optional[TaskPriority] = None
    points: Optional[int] = Field(None, ge=0, le=100)
    blocked_reason: Optional[str] = None
    domain: Optional[str] = None
    owner_agent: Optional[str] = None
    due_at: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None
    risk_level: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")
    approval_state: Optional[str] = Field(None, pattern="^(none|pending|approved|rejected|expired)$")
    approval_id: Optional[str] = None
    tags: Optional[list[str]] = None
    links: Optional[list[dict[str, Any]]] = None
    sort_order: Optional[int] = None
    estimate_points: Optional[int] = Field(None, ge=0, le=100)
    parent_task_id: Optional[str] = None


class TaskMove(BaseModel):
    """Schema for moving task to new status."""
    status: TaskStatus
    reason: Optional[str] = None


class Task(BaseModel):
    """Full task model."""

    id: str
    sprint_id: Optional[str] = None
    project_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.BACKLOG
    category: TaskCategory = TaskCategory.FEATURE
    priority: TaskPriority = TaskPriority.MEDIUM
    points: Optional[int] = None
    source: TaskSource = TaskSource.MANUAL
    source_reference: Optional[str] = None
    blocked_reason: Optional[str] = None
    domain: Optional[str] = None
    owner_agent: Optional[str] = None
    due_at: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None
    risk_level: Optional[str] = None
    approval_state: Optional[str] = None
    approval_id: Optional[str] = None
    tags: Optional[list[str]] = Field(default_factory=list)
    links: Optional[list[dict[str, Any]]] = Field(default_factory=list)
    sort_order: Optional[int] = None
    estimate_points: Optional[int] = None
    parent_task_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class CompanyTaskEvent(BaseModel):
    """Audit event for company work-item activity."""

    id: str
    task_id: str
    event_type: str
    actor: str = "system"
    summary: Optional[str] = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CompanyWorkItemReview(BaseModel):
    """Dashboard review packet for a company work item."""

    id: str
    task_id: str
    score: int = Field(0, ge=0, le=100)
    recommendation: str = "keep"
    summary: Optional[str] = None
    missing_info: list[str] = Field(default_factory=list)
    action_steps: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    automation_plan: dict[str, Any] = Field(default_factory=dict)
    source_links: list[dict[str, Any]] = Field(default_factory=list)
    reviewed_by: str = "zero-company-operator"
    operator_run_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class CompanyDashboardReviewSummary(BaseModel):
    """Overall Company OS dashboard readiness review."""

    overall_score: int = Field(0, ge=0, le=100)
    status: str = "not_reviewed"
    tasks_reviewed: int = 0
    critical_blockers: int = 0
    missing_info_count: int = 0
    archived_count: int = 0
    category_scores: dict[str, int] = Field(default_factory=dict)
    recommendation_counts: dict[str, int] = Field(default_factory=dict)
    weakest_tasks: list[dict[str, Any]] = Field(default_factory=list)
    reviews: list[CompanyWorkItemReview] = Field(default_factory=list)
    last_run: Optional[dict[str, Any]] = None
    what_zero_did_last: list[dict[str, Any]] = Field(default_factory=list)


class CompanyAgentQuestion(BaseModel):
    """Question a company agent needs Adam to answer."""

    id: str
    question: str
    context: dict[str, Any] = Field(default_factory=dict)
    answer_type: str = "text"
    options: list[Any] = Field(default_factory=list)
    priority: str = "medium"
    status: str = "open"
    asked_by_agent: str = "ceo"
    task_id: Optional[str] = None
    agent_task_id: Optional[str] = None
    operator_run_id: Optional[str] = None
    source: str = "company_agent"
    answer: Optional[str] = None
    answered_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    answered_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CompanyAgentQuestionAnswer(BaseModel):
    """Answer or dismissal payload for a company-agent question."""

    answer: str = Field(..., min_length=1)
    answered_by: str = Field(default="dashboard", max_length=100)
