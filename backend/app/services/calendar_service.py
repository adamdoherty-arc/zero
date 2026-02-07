"""
Google Calendar service for calendar operations.
"""

import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime, timedelta
import structlog

from app.models.calendar import (
    CalendarEvent, EventSummary, Calendar, EventCreate, EventUpdate,
    EventStatus, EventVisibility, EventDateTime, EventAttendee,
    EventReminder, EventResponseStatus, CalendarSyncStatus, TodaySchedule
)

logger = structlog.get_logger()

# OAuth scopes for Google Calendar
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


class CalendarService:
    """Service for Google Calendar operations."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.calendar_path = self.workspace_path / "calendar"
        self.calendar_path.mkdir(parents=True, exist_ok=True)
        self.credentials_file = self.calendar_path / "calendar_credentials.json"
        self.tokens_file = self.calendar_path / "calendar_tokens.json"
        self.cache_file = self.calendar_path / "events_cache.json"
        self.sync_file = self.calendar_path / "sync_status.json"
        self._service = None
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage files exist."""
        if not self.cache_file.exists():
            self.cache_file.write_text(json.dumps({"events": [], "last_sync": None}))
        if not self.sync_file.exists():
            self.sync_file.write_text(json.dumps({
                "connected": False,
                "email_address": None,
                "last_sync": None,
                "calendars_count": 0,
                "upcoming_events_count": 0,
                "sync_errors": []
            }))

    def _load_google_modules(self):
        """Lazy load Google OAuth modules."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.oauth2.credentials import Credentials
            return InstalledAppFlow, Credentials
        except ImportError:
            raise RuntimeError(
                "Google OAuth libraries not installed. "
                "Install with: pip install google-auth google-auth-oauthlib google-api-python-client"
            )

    def has_client_config(self) -> bool:
        """Check if OAuth client config exists."""
        return self.credentials_file.exists()

    def set_client_config(self, config: Dict[str, Any]):
        """Set OAuth client configuration."""
        self.credentials_file.write_text(json.dumps(config, indent=2))
        logger.info("calendar_client_config_saved")

    def has_valid_tokens(self) -> bool:
        """Check if valid tokens exist (from Gmail OAuth service)."""
        from app.services.gmail_oauth_service import get_gmail_oauth_service
        
        gmail_oauth = get_gmail_oauth_service()
        return gmail_oauth.has_valid_tokens()

    def get_auth_url(self, redirect_uri: str = "http://localhost:18792/api/calendar/auth/callback") -> Dict[str, str]:
        """Get OAuth authorization URL."""
        if not self.has_client_config():
            raise ValueError("Calendar client config not found")

        InstalledAppFlow, _ = self._load_google_modules()

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=CALENDAR_SCOPES,
            redirect_uri=redirect_uri
        )

        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )

        # Save state
        state_file = self.calendar_path / "oauth_state.json"
        state_file.write_text(json.dumps({
            "state": state,
            "redirect_uri": redirect_uri,
            "created_at": datetime.utcnow().isoformat()
        }))

        return {"auth_url": auth_url, "state": state}

    def handle_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Handle OAuth callback."""
        state_file = self.calendar_path / "oauth_state.json"
        if not state_file.exists():
            raise ValueError("OAuth state not found")

        saved_state = json.loads(state_file.read_text())
        if saved_state.get("state") != state:
            raise ValueError("OAuth state mismatch")

        redirect_uri = saved_state.get("redirect_uri")
        InstalledAppFlow, _ = self._load_google_modules()

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_file),
            scopes=CALENDAR_SCOPES,
            redirect_uri=redirect_uri
        )

        flow.fetch_token(code=code)
        creds = flow.credentials
        self.tokens_file.write_text(creds.to_json())
        state_file.unlink()

        # Get user email
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds)
        calendar = service.calendars().get(calendarId="primary").execute()

        return {
            "status": "connected",
            "email_address": calendar.get("id", "unknown")
        }

    def _get_credentials(self):
        """Get valid OAuth credentials from Gmail OAuth service."""
        from app.services.gmail_oauth_service import get_gmail_oauth_service, GOOGLE_SCOPES
        
        gmail_oauth = get_gmail_oauth_service()
        
        # Check if Gmail OAuth has valid tokens
        if not gmail_oauth.has_valid_tokens():
            return None
        
        # Get credentials from Gmail OAuth service
        _, Credentials = self._load_google_modules()
        tokens_file = gmail_oauth.tokens_file
        
        if not tokens_file.exists():
            return None
        
        # IMPORTANT: Use GOOGLE_SCOPES (not CALENDAR_SCOPES) because tokens were issued with unified scopes
        creds = Credentials.from_authorized_user_file(str(tokens_file), GOOGLE_SCOPES)
        
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            # Save refreshed tokens back to Gmail OAuth service
            tokens_file.write_text(creds.to_json())
        
        return creds if creds.valid else None

    def _get_service(self):
        """Get authenticated Calendar API service."""
        if self._service:
            return self._service

        creds = self._get_credentials()
        if not creds:
            raise RuntimeError("Calendar not connected")

        from googleapiclient.discovery import build
        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def _load_cache(self) -> Dict[str, Any]:
        """Load events cache."""
        try:
            return json.loads(self.cache_file.read_text())
        except Exception:
            return {"events": [], "last_sync": None}

    def _save_cache(self, cache: Dict[str, Any]):
        """Save events cache."""
        self.cache_file.write_text(json.dumps(cache, indent=2, default=str))

    def _load_sync_status(self) -> CalendarSyncStatus:
        """Load sync status."""
        try:
            return CalendarSyncStatus(**json.loads(self.sync_file.read_text()))
        except Exception:
            return CalendarSyncStatus()

    def _save_sync_status(self, status: CalendarSyncStatus):
        """Save sync status."""
        self.sync_file.write_text(json.dumps(status.model_dump(), indent=2, default=str))

    def get_sync_status(self) -> CalendarSyncStatus:
        """Get current sync status."""
        status = self._load_sync_status()
        status.connected = self.has_valid_tokens()
        return status

    def disconnect(self):
        """Disconnect calendar."""
        if self.tokens_file.exists():
            self.tokens_file.unlink()
        self._service = None
        logger.info("calendar_disconnected")

    def _parse_event_datetime(self, dt_data: Dict) -> EventDateTime:
        """Parse Google Calendar datetime object."""
        if "dateTime" in dt_data:
            return EventDateTime(
                date_time=datetime.fromisoformat(dt_data["dateTime"].replace("Z", "+00:00")),
                timezone=dt_data.get("timeZone")
            )
        elif "date" in dt_data:
            return EventDateTime(date=dt_data["date"])
        return EventDateTime()

    def _event_to_model(self, event: Dict) -> CalendarEvent:
        """Convert API event to model."""
        start = self._parse_event_datetime(event.get("start", {}))
        end = self._parse_event_datetime(event.get("end", {}))
        is_all_day = start.date is not None

        attendees = [
            EventAttendee(
                email=a.get("email", ""),
                display_name=a.get("displayName"),
                response_status=EventResponseStatus(a.get("responseStatus", "needsAction")),
                is_organizer=a.get("organizer", False),
                is_self=a.get("self", False)
            )
            for a in event.get("attendees", [])
        ]

        reminders = []
        if event.get("reminders", {}).get("useDefault"):
            reminders = [EventReminder(method="popup", minutes=10)]
        else:
            for r in event.get("reminders", {}).get("overrides", []):
                reminders.append(EventReminder(method=r.get("method", "popup"), minutes=r.get("minutes", 10)))

        return CalendarEvent(
            id=event["id"],
            calendar_id=event.get("calendarId", "primary"),
            summary=event.get("summary", "(No Title)"),
            description=event.get("description"),
            location=event.get("location"),
            start=start,
            end=end,
            status=EventStatus(event.get("status", "confirmed")),
            visibility=EventVisibility(event.get("visibility", "default")),
            html_link=event.get("htmlLink"),
            hangout_link=event.get("hangoutLink"),
            attendees=attendees,
            reminders=reminders,
            recurrence=event.get("recurrence"),
            recurring_event_id=event.get("recurringEventId"),
            is_all_day=is_all_day,
            created_at=datetime.fromisoformat(event["created"].replace("Z", "+00:00")) if event.get("created") else None,
            updated_at=datetime.fromisoformat(event["updated"].replace("Z", "+00:00")) if event.get("updated") else None
        )

    async def sync_events(self, days_ahead: int = 30) -> Dict[str, Any]:
        """Sync calendar events."""
        service = self._get_service()

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        try:
            results = service.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=250,
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            events = [self._event_to_model(e).model_dump() for e in results.get("items", [])]

            cache = {"events": events, "last_sync": datetime.utcnow().isoformat()}
            self._save_cache(cache)

            # Get calendars count
            calendars = service.calendarList().list().execute()

            status = CalendarSyncStatus(
                connected=True,
                email_address=results.get("summary"),
                last_sync=datetime.utcnow(),
                calendars_count=len(calendars.get("items", [])),
                upcoming_events_count=len(events)
            )
            self._save_sync_status(status)

            return {
                "status": "success",
                "synced_at": datetime.utcnow().isoformat(),
                "events_count": len(events)
            }

        except Exception as e:
            logger.error("calendar_sync_failed", error=str(e))
            raise

    async def list_events(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50
    ) -> List[EventSummary]:
        """List events from cache."""
        cache = self._load_cache()
        events = cache.get("events", [])

        # Filter by date range
        if start_date:
            events = [e for e in events if self._event_start_datetime(e) >= start_date]
        if end_date:
            events = [e for e in events if self._event_start_datetime(e) <= end_date]

        # Convert to summaries
        return [
            EventSummary(
                id=e["id"],
                summary=e["summary"],
                start=EventDateTime(**e["start"]),
                end=EventDateTime(**e["end"]),
                location=e.get("location"),
                is_all_day=e.get("is_all_day", False),
                status=EventStatus(e.get("status", "confirmed")),
                has_attendees=len(e.get("attendees", [])) > 0,
                html_link=e.get("html_link")
            )
            for e in events[:limit]
        ]

    def _event_start_datetime(self, event: Dict) -> datetime:
        """Get event start as datetime."""
        start = event.get("start", {})
        if start.get("date_time"):
            return datetime.fromisoformat(start["date_time"].replace("Z", "+00:00")).replace(tzinfo=None)
        elif start.get("date"):
            return datetime.strptime(start["date"], "%Y-%m-%d")
        return datetime.utcnow()

    def _event_end_datetime(self, event: Dict) -> datetime:
        """Get event end as datetime."""
        end = event.get("end", {})
        if end.get("date_time"):
            return datetime.fromisoformat(end["date_time"].replace("Z", "+00:00")).replace(tzinfo=None)
        elif end.get("date"):
            return datetime.strptime(end["date"], "%Y-%m-%d") + timedelta(days=1)
        start = self._event_start_datetime(event)
        return start + timedelta(hours=1)

    def _detect_conflicts(self, events: List[Dict]) -> List[Dict[str, Any]]:
        """Detect overlapping events in a list."""
        timed = []
        for e in events:
            if e.get("is_all_day"):
                continue
            timed.append({
                "id": e["id"],
                "summary": e.get("summary", ""),
                "start": self._event_start_datetime(e),
                "end": self._event_end_datetime(e),
            })
        timed.sort(key=lambda x: x["start"])

        conflicts = []
        for i in range(len(timed)):
            for j in range(i + 1, len(timed)):
                if timed[j]["start"] < timed[i]["end"]:
                    conflicts.append({
                        "event_a": timed[i]["summary"],
                        "event_b": timed[j]["summary"],
                        "overlap_start": timed[j]["start"].strftime("%H:%M"),
                        "overlap_end": min(timed[i]["end"], timed[j]["end"]).strftime("%H:%M"),
                    })
                else:
                    break
        return conflicts

    def _calculate_free_slots(self, events: List[Dict], work_start: int = 9, work_end: int = 17) -> List[Dict[str, str]]:
        """Calculate free time slots during work hours."""
        today = datetime.utcnow().date()
        day_start = datetime(today.year, today.month, today.day, work_start)
        day_end = datetime(today.year, today.month, today.day, work_end)

        busy = []
        for e in events:
            if e.get("is_all_day"):
                continue
            s = self._event_start_datetime(e)
            en = self._event_end_datetime(e)
            if s < day_end and en > day_start:
                busy.append((max(s, day_start), min(en, day_end)))
        busy.sort()

        # Merge overlapping busy periods
        merged = []
        for s, en in busy:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], en))
            else:
                merged.append((s, en))

        # Find gaps
        slots = []
        cursor = day_start
        for s, en in merged:
            if cursor < s:
                slots.append({
                    "start": cursor.strftime("%H:%M"),
                    "end": s.strftime("%H:%M"),
                    "duration_minutes": str(int((s - cursor).total_seconds() / 60)),
                })
            cursor = en
        if cursor < day_end:
            slots.append({
                "start": cursor.strftime("%H:%M"),
                "end": day_end.strftime("%H:%M"),
                "duration_minutes": str(int((day_end - cursor).total_seconds() / 60)),
            })
        return slots

    async def suggest_meeting_time(
        self,
        duration_minutes: int = 30,
        preferences: Optional[Dict[str, Any]] = None,
        work_start: int = 9,
        work_end: int = 17,
    ) -> List[Dict[str, Any]]:
        """Suggest optimal meeting times using free slot analysis and AI ranking.

        Args:
            duration_minutes: Required meeting duration
            preferences: Optional dict with keys like 'prefer_morning', 'avoid_after_lunch'
            work_start: Work day start hour
            work_end: Work day end hour

        Returns:
            List of suggested time slots with reasoning
        """
        cache = self._load_cache()
        events = cache.get("events", [])
        today = datetime.utcnow().date()
        today_events = [e for e in events if self._event_start_datetime(e).date() == today]

        free_slots = self._calculate_free_slots(today_events, work_start, work_end)

        # Filter slots that are long enough
        valid_slots = [
            s for s in free_slots
            if int(s.get("duration_minutes", 0)) >= duration_minutes
        ]

        if not valid_slots:
            return [{"slot": None, "reason": "No free slots available for the requested duration"}]

        # Use AI to rank slots based on preferences
        try:
            ranked = await self._ai_rank_slots(valid_slots, duration_minutes, preferences or {})
            return ranked
        except Exception as e:
            logger.warning("ai_slot_ranking_failed", error=str(e))
            # Fallback: return slots sorted by start time
            return [
                {"slot": s, "reason": "Available slot", "score": 1.0 - i * 0.1}
                for i, s in enumerate(valid_slots[:3])
            ]

    async def _ai_rank_slots(
        self,
        slots: List[Dict[str, str]],
        duration_minutes: int,
        preferences: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Use Ollama to rank time slots by preference."""
        from app.infrastructure.config import get_settings
        import httpx

        settings = get_settings()

        slot_descriptions = "\n".join(
            f"- {s['start']} to {s['end']} ({s.get('duration_minutes', '?')} min available)"
            for s in slots
        )
        pref_text = ", ".join(f"{k}: {v}" for k, v in preferences.items()) if preferences else "none specified"

        prompt = (
            f"I need to schedule a {duration_minutes}-minute meeting today.\n"
            f"Available slots:\n{slot_descriptions}\n"
            f"Preferences: {pref_text}\n\n"
            f"Rank the top 3 best slots. For each, give: slot start time, end time, and a brief reason.\n"
            f"Respond as JSON array: [{{'start': 'HH:MM', 'end': 'HH:MM', 'reason': '...', 'score': 0.0-1.0}}]"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/chat/completions",
                json={
                    "model": settings.ollama_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

            # Try to parse JSON from response
            import json as _json
            # Find JSON array in response
            start_idx = content.find("[")
            end_idx = content.rfind("]") + 1
            if start_idx >= 0 and end_idx > start_idx:
                ranked = _json.loads(content[start_idx:end_idx])
                return ranked[:3]

        # Fallback
        return [{"slot": s, "reason": "Available", "score": 0.5} for s in slots[:3]]

    async def smart_reschedule(
        self, event_id: str, reason: str = ""
    ) -> List[Dict[str, Any]]:
        """Find alternative time slots when an event needs rescheduling.

        Args:
            event_id: ID of the event to reschedule
            reason: Why it needs rescheduling

        Returns:
            List of alternative time slot suggestions
        """
        event = await self.get_event(event_id)
        if not event:
            return [{"error": f"Event {event_id} not found"}]

        # Calculate event duration
        start = self._event_start_datetime({"start": {"date_time": event.start.date_time.isoformat() if event.start.date_time else None}})
        end = self._event_end_datetime({"end": {"date_time": event.end.date_time.isoformat() if event.end.date_time else None}})
        duration_minutes = int((end - start).total_seconds() / 60)

        # Find alternative slots
        suggestions = await self.suggest_meeting_time(
            duration_minutes=duration_minutes,
            preferences={"reason_for_reschedule": reason},
        )

        return suggestions

    async def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        """Get event by ID."""
        cache = self._load_cache()
        for e in cache.get("events", []):
            if e["id"] == event_id:
                return CalendarEvent(**e)
        return None

    async def create_event(self, event_data: EventCreate) -> CalendarEvent:
        """Create a new calendar event."""
        service = self._get_service()

        body = {
            "summary": event_data.summary,
            "description": event_data.description,
            "location": event_data.location,
            "start": {},
            "end": {},
            "visibility": event_data.visibility.value,
        }

        # Set start
        if event_data.start.date_time:
            body["start"]["dateTime"] = event_data.start.date_time.isoformat()
            if event_data.start.timezone:
                body["start"]["timeZone"] = event_data.start.timezone
        elif event_data.start.date:
            body["start"]["date"] = event_data.start.date

        # Set end
        if event_data.end.date_time:
            body["end"]["dateTime"] = event_data.end.date_time.isoformat()
            if event_data.end.timezone:
                body["end"]["timeZone"] = event_data.end.timezone
        elif event_data.end.date:
            body["end"]["date"] = event_data.end.date

        # Add attendees
        if event_data.attendees:
            body["attendees"] = [{"email": email} for email in event_data.attendees]

        # Add reminders
        if event_data.reminders:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": r.method, "minutes": r.minutes} for r in event_data.reminders]
            }

        # Add recurrence
        if event_data.recurrence:
            body["recurrence"] = event_data.recurrence

        result = service.events().insert(calendarId="primary", body=body).execute()

        logger.info("calendar_event_created", event_id=result["id"])
        return self._event_to_model(result)

    async def update_event(self, event_id: str, updates: EventUpdate) -> Optional[CalendarEvent]:
        """Update a calendar event."""
        service = self._get_service()

        # Get existing event
        try:
            existing = service.events().get(calendarId="primary", eventId=event_id).execute()
        except Exception:
            return None

        # Apply updates
        if updates.summary:
            existing["summary"] = updates.summary
        if updates.description is not None:
            existing["description"] = updates.description
        if updates.location is not None:
            existing["location"] = updates.location
        if updates.status:
            existing["status"] = updates.status.value
        if updates.start:
            if updates.start.date_time:
                existing["start"] = {"dateTime": updates.start.date_time.isoformat()}
            elif updates.start.date:
                existing["start"] = {"date": updates.start.date}
        if updates.end:
            if updates.end.date_time:
                existing["end"] = {"dateTime": updates.end.date_time.isoformat()}
            elif updates.end.date:
                existing["end"] = {"date": updates.end.date}

        result = service.events().update(calendarId="primary", eventId=event_id, body=existing).execute()

        logger.info("calendar_event_updated", event_id=event_id)
        return self._event_to_model(result)

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event."""
        service = self._get_service()

        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            logger.info("calendar_event_deleted", event_id=event_id)
            return True
        except Exception as e:
            logger.error("calendar_event_delete_failed", event_id=event_id, error=str(e))
            return False

    async def get_calendars(self) -> List[Calendar]:
        """Get list of calendars."""
        service = self._get_service()

        results = service.calendarList().list().execute()
        return [
            Calendar(
                id=cal["id"],
                summary=cal.get("summary", ""),
                description=cal.get("description"),
                timezone=cal.get("timeZone", "UTC"),
                is_primary=cal.get("primary", False),
                background_color=cal.get("backgroundColor"),
                foreground_color=cal.get("foregroundColor")
            )
            for cal in results.get("items", [])
        ]

    async def get_events_multi(
        self,
        calendar_ids: List[str],
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate events from multiple calendars.

        Args:
            calendar_ids: List of calendar IDs to query
            time_min: Start of time range (default: now)
            time_max: End of time range (default: 7 days from now)

        Returns:
            List of events from all specified calendars, sorted by start time
        """
        service = self._get_service()

        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=7)

        all_events = []
        for cal_id in calendar_ids:
            try:
                results = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min.isoformat() + "Z",
                    timeMax=time_max.isoformat() + "Z",
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=100,
                ).execute()

                for event in results.get("items", []):
                    event["_calendar_id"] = cal_id
                    all_events.append(event)

            except Exception as e:
                logger.warning("multi_calendar_fetch_failed", calendar_id=cal_id, error=str(e))

        # Sort by start time
        all_events.sort(key=lambda e: e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")))

        logger.info("multi_calendar_events_fetched", calendars=len(calendar_ids), events=len(all_events))
        return all_events

    async def get_today_schedule(self) -> TodaySchedule:
        """Get today's schedule."""
        cache = self._load_cache()
        events = cache.get("events", [])

        today = datetime.utcnow().date()
        today_events = []

        for e in events:
            event_date = self._event_start_datetime(e).date()
            if event_date == today:
                today_events.append(EventSummary(
                    id=e["id"],
                    summary=e["summary"],
                    start=EventDateTime(**e["start"]),
                    end=EventDateTime(**e["end"]),
                    location=e.get("location"),
                    is_all_day=e.get("is_all_day", False),
                    status=EventStatus(e.get("status", "confirmed")),
                    has_attendees=len(e.get("attendees", [])) > 0,
                    html_link=e.get("html_link")
                ))

        today_raw = [e for e in events if self._event_start_datetime(e).date() == today]
        conflicts = self._detect_conflicts(today_raw)
        free_slots = self._calculate_free_slots(today_raw)

        return TodaySchedule(
            date=today.isoformat(),
            events=today_events,
            total_events=len(today_events),
            has_conflicts=len(conflicts) > 0,
            free_slots=free_slots
        )

    async def sync_events_to_notion(
        self,
        days_ahead: int = 7,
        notion_database_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sync upcoming calendar events to a Notion database.

        Args:
            days_ahead: Number of days to sync
            notion_database_id: Target Notion database ID

        Returns:
            Dict with sync results
        """
        try:
            from app.services.notion_service import get_notion_service
        except ImportError:
            return {"synced": 0, "error": "Notion service not available"}

        notion = get_notion_service()
        if notion is None:
            return {"synced": 0, "error": "Notion not configured"}

        cache = self._load_cache()
        events = cache.get("events", [])

        now = datetime.utcnow()
        cutoff = now + timedelta(days=days_ahead)

        upcoming = []
        for e in events:
            try:
                start = self._event_start_datetime(e)
                if now <= start <= cutoff:
                    upcoming.append(e)
            except Exception:
                continue

        if not upcoming:
            return {"synced": 0, "message": "No upcoming events to sync"}

        try:
            results = await notion.sync_calendar_events_to_notion(
                events=upcoming,
                database_id=notion_database_id,
            )
            return {"synced": len(results), "events": [e.get("summary", "?") for e in upcoming]}
        except Exception as e:
            logger.error("calendar_notion_sync_failed", error=str(e))
            return {"synced": 0, "error": str(e)}


@lru_cache()
def get_calendar_service() -> CalendarService:
    """Get singleton CalendarService instance."""
    return CalendarService()
