"""
Centralized activity log for all autonomous actions.
Stores timestamped events in workspace/engine/activity_log.json.
Feeds the frontend activity feed and morning briefing.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from app.infrastructure.config import get_workspace_path
from app.infrastructure.storage import JsonStorage

logger = structlog.get_logger()

MAX_EVENTS = 1000


class ActivityLogService:
    """Unified activity log for all autonomous actions."""

    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("engine"))
        self._log_file = "activity_log.json"
        self._lock = asyncio.Lock()

    async def log_event(
        self,
        event_type: str,
        project: str,
        title: str,
        details: Optional[Dict[str, Any]] = None,
        source: str = "engine",
        status: str = "info",
    ) -> Dict[str, Any]:
        """Append an activity event to the log."""
        event = {
            "event_id": f"EVT-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "project": project,
            "title": title,
            "details": details or {},
            "source": source,
            "status": status,
        }

        async with self._lock:
            data = await self._storage.read(self._log_file)
            events = data.get("events", [])
            events.append(event)
            # Keep only the last MAX_EVENTS
            if len(events) > MAX_EVENTS:
                events = events[-MAX_EVENTS:]
            await self._storage.write(self._log_file, {"events": events})

        logger.info(
            "activity_logged",
            event_type=event_type,
            project=project,
            title=title,
            status=status,
        )
        return event

    async def get_events(
        self,
        limit: int = 50,
        project: Optional[str] = None,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Query events with optional filters."""
        data = await self._storage.read(self._log_file)
        events = data.get("events", [])

        # Apply filters
        if project:
            events = [e for e in events if e.get("project") == project]
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type]
        if source:
            events = [e for e in events if e.get("source") == source]
        if since:
            cutoff = since.isoformat()
            events = [e for e in events if e.get("timestamp", "") >= cutoff]

        # Return most recent first
        events.reverse()
        return events[:limit]

    async def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get activity summary for the last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        events = await self.get_events(limit=MAX_EVENTS, since=cutoff)

        by_type: Dict[str, int] = {}
        by_project: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        files_changed = 0
        improvements_completed = 0

        for event in events:
            et = event.get("event_type", "unknown")
            by_type[et] = by_type.get(et, 0) + 1

            proj = event.get("project", "unknown")
            by_project[proj] = by_project.get(proj, 0) + 1

            st = event.get("status", "info")
            by_status[st] = by_status.get(st, 0) + 1

            details = event.get("details", {})
            if details.get("file_written"):
                files_changed += 1
            if et == "execute_complete" and st == "success":
                improvements_completed += 1

        return {
            "total_events": len(events),
            "hours": hours,
            "by_type": by_type,
            "by_project": by_project,
            "by_status": by_status,
            "files_changed": files_changed,
            "improvements_completed": improvements_completed,
        }


@lru_cache()
def get_activity_log_service() -> ActivityLogService:
    return ActivityLogService()
