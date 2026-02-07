"""
Proactive assistant data models for ZERO.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ReminderStatus(str, Enum):
    """Reminder status."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    COMPLETED = "completed"


class ReminderRecurrence(str, Enum):
    """Reminder recurrence patterns."""
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"  # Uses cron expression


class NotificationChannel(str, Enum):
    """Notification delivery channels."""
    UI = "ui"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class Reminder(BaseModel):
    """Reminder model."""
    id: str
    title: str
    description: Optional[str] = None
    trigger_at: datetime
    recurrence: ReminderRecurrence = ReminderRecurrence.ONCE
    cron_expression: Optional[str] = None  # For custom recurrence
    channels: List[NotificationChannel] = Field(default_factory=lambda: [NotificationChannel.UI])
    status: ReminderStatus = ReminderStatus.ACTIVE
    snooze_until: Optional[datetime] = None
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    last_triggered_at: Optional[datetime] = None


class ReminderCreate(BaseModel):
    """Schema for creating a reminder."""
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    trigger_at: datetime
    recurrence: ReminderRecurrence = ReminderRecurrence.ONCE
    cron_expression: Optional[str] = None
    channels: List[NotificationChannel] = Field(default_factory=lambda: [NotificationChannel.UI])
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ReminderUpdate(BaseModel):
    """Schema for updating a reminder."""
    title: Optional[str] = None
    description: Optional[str] = None
    trigger_at: Optional[datetime] = None
    recurrence: Optional[ReminderRecurrence] = None
    cron_expression: Optional[str] = None
    channels: Optional[List[NotificationChannel]] = None
    status: Optional[ReminderStatus] = None


class BriefingSection(BaseModel):
    """A section of the daily briefing."""
    title: str
    icon: str = ""
    items: List[str] = Field(default_factory=list)
    priority: int = 0


class DailyBriefing(BaseModel):
    """Daily briefing summary."""
    date: str
    greeting: str
    weather: Optional[str] = None
    sections: List[BriefingSection] = Field(default_factory=list)
    calendar_summary: Optional[str] = None
    task_summary: Optional[str] = None
    email_summary: Optional[str] = None
    project_health_summary: Optional[str] = None  # From Legion
    reminders_due: List[Reminder] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class Notification(BaseModel):
    """Notification model."""
    id: str
    title: str
    message: str
    channel: NotificationChannel = NotificationChannel.UI
    read: bool = False
    action_url: Optional[str] = None
    source: Optional[str] = None  # reminder, email, task, etc.
    source_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Suggestion(BaseModel):
    """AI-generated suggestion."""
    id: str
    type: str  # task, note, reminder, etc.
    title: str
    description: str
    confidence: float = 0.0
    action: Optional[str] = None  # API endpoint to execute suggestion
    action_data: Optional[Dict[str, Any]] = None
    accepted: Optional[bool] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AssistantStatus(BaseModel):
    """Overall assistant status."""
    scheduler_running: bool = False
    last_briefing_at: Optional[datetime] = None
    pending_reminders: int = 0
    unread_notifications: int = 0
    active_jobs: List[str] = Field(default_factory=list)
