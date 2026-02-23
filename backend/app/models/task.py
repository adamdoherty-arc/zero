"""
Task data models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task workflow status."""
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    TESTING = "testing"
    DONE = "done"
    BLOCKED = "blocked"


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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
