"""
Proactive assistant API endpoints.
Provides daily briefings, reminders, notifications, and AI suggestions.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime
import structlog

from app.models.assistant import (
    Reminder, ReminderCreate, ReminderUpdate, ReminderStatus,
    DailyBriefing, Notification, NotificationChannel, AssistantStatus
)
from app.services.briefing_service import get_briefing_service
from app.services.reminder_service import get_reminder_service
from app.services.notification_service import get_notification_service
from app.services.scheduler_service import get_scheduler_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================================================
# Briefing Endpoints
# ============================================================================

@router.get("/briefing", response_model=DailyBriefing)
async def get_briefing(refresh: bool = Query(default=False)):
    """
    Get the daily briefing.

    Includes calendar events, tasks, emails, and reminders for today.
    Set refresh=true to regenerate the briefing.
    """
    service = get_briefing_service()

    if not refresh:
        existing = await service.get_latest_briefing()
        if existing:
            return existing

    return await service.generate_briefing()


# ============================================================================
# Reminder Endpoints
# ============================================================================

@router.get("/reminders", response_model=List[Reminder])
async def list_reminders(
    status: Optional[ReminderStatus] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100)
):
    """List reminders with optional status filter."""
    service = get_reminder_service()
    return await service.list_reminders(status, limit)


@router.get("/reminders/upcoming", response_model=List[Reminder])
async def get_upcoming_reminders(
    hours: int = Query(default=24, ge=1, le=168)
):
    """Get reminders due within the specified hours."""
    service = get_reminder_service()
    return await service.get_upcoming_reminders(hours)


@router.get("/reminders/{reminder_id}", response_model=Reminder)
async def get_reminder(reminder_id: str):
    """Get a reminder by ID."""
    service = get_reminder_service()
    reminder = await service.get_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.post("/reminders", response_model=Reminder)
async def create_reminder(data: ReminderCreate):
    """Create a new reminder."""
    service = get_reminder_service()

    # Validate trigger time is in the future
    if data.trigger_at < datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="Trigger time must be in the future"
        )

    return await service.create_reminder(data)


@router.patch("/reminders/{reminder_id}", response_model=Reminder)
async def update_reminder(reminder_id: str, updates: ReminderUpdate):
    """Update a reminder."""
    service = get_reminder_service()
    reminder = await service.update_reminder(reminder_id, updates)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str):
    """Delete a reminder."""
    service = get_reminder_service()
    success = await service.delete_reminder(reminder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"status": "deleted"}


@router.post("/reminders/{reminder_id}/snooze", response_model=Reminder)
async def snooze_reminder(
    reminder_id: str,
    minutes: int = Query(default=15, ge=1, le=1440)
):
    """Snooze a reminder for the specified minutes."""
    service = get_reminder_service()
    reminder = await service.snooze_reminder(reminder_id, minutes)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.post("/reminders/{reminder_id}/dismiss", response_model=Reminder)
async def dismiss_reminder(reminder_id: str):
    """Dismiss a reminder."""
    service = get_reminder_service()
    reminder = await service.dismiss_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.post("/reminders/{reminder_id}/complete", response_model=Reminder)
async def complete_reminder(reminder_id: str):
    """Mark a reminder as completed."""
    service = get_reminder_service()
    reminder = await service.complete_reminder(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.get("/reminders/stats")
async def get_reminder_stats():
    """Get reminder statistics."""
    service = get_reminder_service()
    return await service.get_stats()


# ============================================================================
# Notification Endpoints
# ============================================================================

@router.get("/notifications", response_model=List[Notification])
async def list_notifications(
    unread_only: bool = Query(default=False),
    channel: Optional[NotificationChannel] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100)
):
    """List notifications with optional filters."""
    service = get_notification_service()
    return await service.list_notifications(unread_only, channel, limit)


@router.get("/notifications/count")
async def get_notification_count():
    """Get count of unread notifications."""
    service = get_notification_service()
    count = await service.get_unread_count()
    return {"unread_count": count}


@router.get("/notifications/{notification_id}", response_model=Notification)
async def get_notification(notification_id: str):
    """Get a notification by ID."""
    service = get_notification_service()
    notification = await service.get_notification(notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


@router.post("/notifications/{notification_id}/read", response_model=Notification)
async def mark_notification_read(notification_id: str):
    """Mark a notification as read."""
    service = get_notification_service()
    notification = await service.mark_as_read(notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


@router.post("/notifications/read-all")
async def mark_all_notifications_read():
    """Mark all notifications as read."""
    service = get_notification_service()
    count = await service.mark_all_as_read()
    return {"status": "success", "marked_count": count}


@router.delete("/notifications/{notification_id}")
async def delete_notification(notification_id: str):
    """Delete a notification."""
    service = get_notification_service()
    success = await service.delete_notification(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "deleted"}


@router.delete("/notifications")
async def clear_notifications():
    """Clear all notifications."""
    service = get_notification_service()
    count = await service.clear_all()
    return {"status": "success", "deleted_count": count}


# ============================================================================
# Status Endpoint
# ============================================================================

@router.get("/status", response_model=AssistantStatus)
async def get_assistant_status():
    """Get overall assistant status."""
    briefing_service = get_briefing_service()
    reminder_service = get_reminder_service()
    notification_service = get_notification_service()
    scheduler_service = get_scheduler_service()

    briefing = await briefing_service.get_latest_briefing()
    reminder_stats = await reminder_service.get_stats()
    unread_count = await notification_service.get_unread_count()
    scheduler_status = scheduler_service.get_status()

    return AssistantStatus(
        scheduler_running=scheduler_status.get("running", False),
        last_briefing_at=briefing.generated_at if briefing else None,
        pending_reminders=reminder_stats.get("active", 0),
        unread_notifications=unread_count,
        active_jobs=[job.get("name", job.get("id")) for job in scheduler_status.get("jobs", [])]
    )
