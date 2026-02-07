"""
Calendar API endpoints for Google Calendar integration.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import structlog

from app.models.calendar import (
    CalendarEvent, EventSummary, Calendar, EventCreate, EventUpdate,
    CalendarSyncStatus, TodaySchedule, TaskToEventRequest, EventDateTime,
    EventReminder
)
from app.services.calendar_service import get_calendar_service
from app.services.task_service import get_task_service

router = APIRouter()
logger = structlog.get_logger()


# ============================================================================
# OAuth Endpoints
# ============================================================================

@router.get("/auth/url")
async def get_auth_url(
    redirect_uri: Optional[str] = Query(default=None)
):
    """Get Google Calendar OAuth authorization URL."""
    service = get_calendar_service()

    if not service.has_client_config():
        raise HTTPException(
            status_code=400,
            detail="Calendar OAuth not configured. Set up client credentials first."
        )

    uri = redirect_uri or "http://localhost:18792/api/calendar/auth/callback"
    return service.get_auth_url(uri)


@router.get("/auth/callback")
async def auth_callback(
    code: str = Query(...),
    state: str = Query(...)
):
    """Handle OAuth callback from Google."""
    service = get_calendar_service()

    try:
        result = service.handle_callback(code, state)
        return {
            "status": "success",
            "message": "Google Calendar connected successfully",
            "email_address": result.get("email_address")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("calendar_auth_callback_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.post("/auth/config")
async def set_client_config(config: Dict[str, Any]):
    """Set Google Calendar OAuth client configuration."""
    service = get_calendar_service()

    if "installed" not in config and "web" not in config:
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials format"
        )

    service.set_client_config(config)
    return {"status": "configured"}


@router.post("/disconnect")
async def disconnect_calendar():
    """Disconnect Google Calendar account."""
    service = get_calendar_service()
    service.disconnect()
    return {"status": "disconnected"}


# ============================================================================
# Calendar Operations
# ============================================================================

@router.get("/status", response_model=CalendarSyncStatus)
async def get_status():
    """Get calendar sync status."""
    service = get_calendar_service()
    return service.get_sync_status()


@router.post("/sync")
async def sync_calendar(
    days_ahead: int = Query(default=30, ge=7, le=90)
):
    """Sync calendar events from Google Calendar."""
    service = get_calendar_service()

    if not service.has_valid_tokens():
        raise HTTPException(
            status_code=401,
            detail="Calendar not connected. Complete OAuth flow first."
        )

    try:
        result = await service.sync_events(days_ahead)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("calendar_sync_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.get("/calendars", response_model=List[Calendar])
async def list_calendars():
    """List available calendars."""
    service = get_calendar_service()

    if not service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Calendar not connected")

    return await service.get_calendars()


@router.get("/events", response_model=List[EventSummary])
async def list_events(
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200)
):
    """List calendar events with optional date range filter."""
    service = get_calendar_service()
    return await service.list_events(start_date, end_date, limit)


@router.get("/events/{event_id}", response_model=CalendarEvent)
async def get_event(event_id: str):
    """Get a specific calendar event."""
    service = get_calendar_service()
    event = await service.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/events", response_model=CalendarEvent)
async def create_event(event_data: EventCreate):
    """Create a new calendar event."""
    service = get_calendar_service()

    if not service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Calendar not connected")

    try:
        return await service.create_event(event_data)
    except Exception as e:
        logger.error("event_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create event: {str(e)}")


@router.patch("/events/{event_id}", response_model=CalendarEvent)
async def update_event(event_id: str, updates: EventUpdate):
    """Update a calendar event."""
    service = get_calendar_service()

    if not service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Calendar not connected")

    event = await service.update_event(event_id, updates)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/events/{event_id}")
async def delete_event(event_id: str):
    """Delete a calendar event."""
    service = get_calendar_service()

    if not service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Calendar not connected")

    success = await service.delete_event(event_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete event")
    return {"status": "deleted"}


@router.get("/today", response_model=TodaySchedule)
async def get_today_schedule():
    """Get today's schedule."""
    service = get_calendar_service()
    return await service.get_today_schedule()


@router.post("/events/from-task", response_model=CalendarEvent)
async def create_event_from_task(request: TaskToEventRequest):
    """Create a calendar event from a task."""
    calendar_service = get_calendar_service()
    task_service = get_task_service()

    if not calendar_service.has_valid_tokens():
        raise HTTPException(status_code=401, detail="Calendar not connected")

    task = await task_service.get_task(request.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Calculate end time if not provided
    end = request.end
    if not end and request.start.date_time:
        end_dt = request.start.date_time + timedelta(minutes=request.duration_minutes)
        end = EventDateTime(date_time=end_dt, timezone=request.start.timezone)
    elif not end and request.start.date:
        end = EventDateTime(date=request.start.date)

    # Build event data
    event_data = EventCreate(
        summary=f"[Task] {task.title}",
        description=f"{task.description or ''}\n\n---\nTask ID: {task.id}\nStatus: {task.status}\nPriority: {task.priority}",
        start=request.start,
        end=end,
        reminders=[EventReminder(method="popup", minutes=15)] if request.add_reminders else []
    )

    event = await calendar_service.create_event(event_data)

    logger.info("task_to_event_created", task_id=task.id, event_id=event.id)

    return event
