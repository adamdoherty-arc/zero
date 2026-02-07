"""
Sprint data models.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SprintStatus(str, Enum):
    """Sprint lifecycle status."""
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SprintCreate(BaseModel):
    """Schema for creating a new sprint."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    duration_days: int = Field(default=14, ge=1, le=90)
    goals: List[str] = Field(default_factory=list)


class SprintUpdate(BaseModel):
    """Schema for updating a sprint."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[SprintStatus] = None
    goals: Optional[List[str]] = None
    end_date: Optional[datetime] = None


class Sprint(BaseModel):
    """Full sprint model."""
    model_config = ConfigDict(populate_by_name=True)

    id: str
    number: int
    name: str
    description: Optional[str] = None
    status: SprintStatus = SprintStatus.PLANNING
    start_date: Optional[datetime] = Field(None, alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")
    duration_days: int = Field(14, alias="durationDays")
    goals: List[str] = Field(default_factory=list)
    total_points: int = Field(0, alias="totalPoints")
    completed_points: int = Field(0, alias="completedPoints")
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")

    @property
    def progress_percent(self) -> float:
        """Calculate sprint progress percentage."""
        if self.total_points == 0:
            return 0.0
        return round((self.completed_points / self.total_points) * 100, 1)

    @property
    def days_remaining(self) -> Optional[int]:
        """Calculate days remaining in sprint."""
        if not self.end_date:
            return None
        delta = self.end_date - datetime.utcnow()
        return max(0, delta.days)

