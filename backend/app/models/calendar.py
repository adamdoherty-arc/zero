"""
Calendar data models for ZERO.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class EventStatus(str, Enum):
    """Calendar event status."""
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class EventVisibility(str, Enum):
    """Event visibility."""
    DEFAULT = "default"
    PUBLIC = "public"
    PRIVATE = "private"


class EventResponseStatus(str, Enum):
    """Attendee response status."""
    NEEDS_ACTION = "needsAction"
    DECLINED = "declined"
    TENTATIVE = "tentative"
    ACCEPTED = "accepted"


class EventDateTime(BaseModel):
    """Event date/time with optional timezone."""
    date_time: Optional[datetime] = None  # For timed events
    date: Optional[str] = None  # For all-day events (YYYY-MM-DD)
    timezone: Optional[str] = None


class EventAttendee(BaseModel):
    """Calendar event attendee."""
    email: str
    display_name: Optional[str] = None
    response_status: EventResponseStatus = EventResponseStatus.NEEDS_ACTION
    is_organizer: bool = False
    is_self: bool = False


class EventReminder(BaseModel):
    """Event reminder."""
    method: str = "popup"  # popup, email
    minutes: int = 10


class CalendarEvent(BaseModel):
    """Full calendar event model."""
    id: str
    calendar_id: str = "primary"
    summary: str
    description: Optional[str] = None
    location: Optional[str] = None
    start: EventDateTime
    end: EventDateTime
    status: EventStatus = EventStatus.CONFIRMED
    visibility: EventVisibility = EventVisibility.DEFAULT
    html_link: Optional[str] = None
    hangout_link: Optional[str] = None
    attendees: List[EventAttendee] = Field(default_factory=list)
    reminders: List[EventReminder] = Field(default_factory=list)
    recurrence: Optional[List[str]] = None
    recurring_event_id: Optional[str] = None
    is_all_day: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EventSummary(BaseModel):
    """Lightweight event summary for lists."""
    id: str
    summary: str
    start: EventDateTime
    end: EventDateTime
    location: Optional[str] = None
    is_all_day: bool = False
    status: EventStatus = EventStatus.CONFIRMED
    has_attendees: bool = False
    html_link: Optional[str] = None


class EventCreate(BaseModel):
    """Schema for creating a calendar event."""
    summary: str = Field(..., min_length=1)
    description: Optional[str] = None
    location: Optional[str] = None
    start: EventDateTime
    end: EventDateTime
    attendees: List[str] = Field(default_factory=list)  # List of email addresses
    reminders: List[EventReminder] = Field(default_factory=list)
    visibility: EventVisibility = EventVisibility.DEFAULT
    recurrence: Optional[List[str]] = None


class EventUpdate(BaseModel):
    """Schema for updating a calendar event."""
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start: Optional[EventDateTime] = None
    end: Optional[EventDateTime] = None
    status: Optional[EventStatus] = None


class Calendar(BaseModel):
    """Calendar metadata."""
    id: str
    summary: str
    description: Optional[str] = None
    timezone: str = "UTC"
    is_primary: bool = False
    background_color: Optional[str] = None
    foreground_color: Optional[str] = None


class CalendarSyncStatus(BaseModel):
    """Calendar sync status."""
    connected: bool = False
    email_address: Optional[str] = None
    last_sync: Optional[datetime] = None
    calendars_count: int = 0
    upcoming_events_count: int = 0
    sync_errors: List[str] = Field(default_factory=list)


class TodaySchedule(BaseModel):
    """Today's schedule summary."""
    date: str
    events: List[EventSummary] = Field(default_factory=list)
    total_events: int = 0
    has_conflicts: bool = False
    free_slots: List[Dict[str, str]] = Field(default_factory=list)


class TaskToEventRequest(BaseModel):
    """Request to create calendar event from task."""
    task_id: str
    start: EventDateTime
    end: Optional[EventDateTime] = None
    duration_minutes: int = 60
    add_reminders: bool = True
