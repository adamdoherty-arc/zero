"""
Sprint data models.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SprintStatus(str, Enum):
    """Sprint lifecycle status."""
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Legion uses different status names
LEGION_TO_ZERO_STATUS: Dict[str, str] = {
    "planned": "planning",
    "active": "active",
    "completed": "completed",
    "blocked": "paused",
}

ZERO_TO_LEGION_STATUS: Dict[str, str] = {v: k for k, v in LEGION_TO_ZERO_STATUS.items()}


class Sprint(BaseModel):
    """Full sprint model."""

    id: str
    number: int
    name: str
    description: Optional[str] = None
    status: SprintStatus = SprintStatus.PLANNING
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    duration_days: int = 14
    goals: List[str] = Field(default_factory=list)
    total_points: int = 0
    completed_points: int = 0
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

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
