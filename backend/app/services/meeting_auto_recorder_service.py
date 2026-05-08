"""
Meeting auto-recorder.

Tracks which calendar events the user has flagged for automatic recording.
The scheduler's reachy_calendar_nudge job consults `due_starts(now)` /
`due_stops(now)` once per minute and triggers start/stop on the recording
service.

State is persisted to a JSON file at workspace/meetings/auto_record.json so
restarts don't lose flags. There's no DB migration to keep this slice small
and reversible — promote to a real table once the feature stabilises.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class MeetingAutoRecorderService:
    """Per-event opt-in auto-record registry."""

    def __init__(self, workspace_path: str = "workspace") -> None:
        self._path = Path(workspace_path) / "meetings" / "auto_record.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._state: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except Exception as e:
            logger.warning("auto_record_state_load_failed", error=str(e))
            return {}

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._state, indent=2, default=str))
        except Exception as e:
            logger.warning("auto_record_state_save_failed", error=str(e))

    async def mark(
        self,
        *,
        calendar_event_id: str,
        meeting_id: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        title: Optional[str] = None,
    ) -> None:
        """Flag a calendar event for auto-record."""
        async with self._lock:
            self._state[calendar_event_id] = {
                "calendar_event_id": calendar_event_id,
                "meeting_id": meeting_id,
                "start_time": start_time.astimezone(timezone.utc).isoformat(),
                "end_time": end_time.astimezone(timezone.utc).isoformat() if end_time else None,
                "title": title,
                "started": False,
                "stopped": False,
            }
            self._save()
            logger.info("auto_record_marked", event_id=calendar_event_id, meeting_id=meeting_id)

    async def unmark(self, calendar_event_id: str) -> bool:
        async with self._lock:
            if calendar_event_id in self._state:
                del self._state[calendar_event_id]
                self._save()
                logger.info("auto_record_unmarked", event_id=calendar_event_id)
                return True
        return False

    async def is_marked(self, calendar_event_id: str) -> bool:
        return calendar_event_id in self._state

    async def list_marked(self) -> list[dict]:
        return list(self._state.values())

    async def due_starts(self, now: datetime, window_seconds: int = 60) -> list[dict]:
        """Entries whose start_time is within ±window_seconds of now and not yet started."""
        results: list[dict] = []
        for entry in self._state.values():
            if entry.get("started"):
                continue
            start = self._parse_dt(entry.get("start_time"))
            if start is None:
                continue
            delta = abs((start - now).total_seconds())
            if delta <= window_seconds:
                results.append(entry)
        return results

    async def due_stops(self, now: datetime, grace_seconds: int = 30) -> list[dict]:
        """Entries already started whose end_time has passed (now >= end + grace)."""
        results: list[dict] = []
        for entry in self._state.values():
            if not entry.get("started") or entry.get("stopped"):
                continue
            end = self._parse_dt(entry.get("end_time"))
            if end is None:
                continue
            if (now - end).total_seconds() >= grace_seconds:
                results.append(entry)
        return results

    async def mark_started(self, calendar_event_id: str) -> None:
        async with self._lock:
            entry = self._state.get(calendar_event_id)
            if entry:
                entry["started"] = True
                entry["started_at"] = datetime.now(timezone.utc).isoformat()
                self._save()

    async def mark_stopped(self, calendar_event_id: str) -> None:
        async with self._lock:
            entry = self._state.get(calendar_event_id)
            if entry:
                entry["stopped"] = True
                entry["stopped_at"] = datetime.now(timezone.utc).isoformat()
                self._save()

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None


@lru_cache()
def get_meeting_auto_recorder_service() -> MeetingAutoRecorderService:
    return MeetingAutoRecorderService()
