"""Meeting concurrency queue.

When two calendar events overlap, today's auto-record path swallows the
``RuntimeError`` from ``start_recording`` because a previous capture is
still live. That silently drops the second meeting. This service keeps
a tiny queue at ``workspace/meetings/concurrency_queue.json`` so the
auto-stop tick can drain a queued meeting into the now-free recorder.

Lifecycle from the scheduler perspective:

    auto_record start  →  is_recording? yes → enqueue(event)
                                            → publish meeting.conflict
                       →  is_recording? no  → start as usual
    auto_record stop   →  drain_for_capture(now)
                       →  for each queued whose window is still open:
                            start its recording, drop from queue
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


class MeetingConcurrencyService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "concurrency_queue.json"
        self._lock = threading.RLock()

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("concurrency_queue_load_failed", error=str(exc))
            return []

    def _save(self, data: list[dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def enqueue(
        self,
        *,
        meeting_id: str,
        event_id: str,
        title: str | None,
        end_time: datetime | str | None,
        reason: str = "concurrent_recording",
    ) -> None:
        end_iso = end_time.isoformat() if isinstance(end_time, datetime) else end_time
        entry = {
            "meeting_id": meeting_id,
            "calendar_event_id": event_id,
            "title": title,
            "end_time": end_iso,
            "reason": reason,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            queue = self._load()
            # Dedupe by event_id; replace if already queued.
            queue = [q for q in queue if q.get("calendar_event_id") != event_id]
            queue.append(entry)
            self._save(queue)
        logger.info(
            "meeting_concurrency_enqueued",
            meeting_id=meeting_id,
            event_id=event_id,
            reason=reason,
        )

    def drain_due(self, now: datetime) -> list[dict[str, Any]]:
        """Return queued entries whose end_time is still in the future.
        Removes both fresh-and-drained entries AND expired ones from the
        on-disk queue."""
        with self._lock:
            queue = self._load()
            fresh: list[dict[str, Any]] = []
            keep_in_queue: list[dict[str, Any]] = []
            for entry in queue:
                end_iso = entry.get("end_time")
                still_in_window = False
                if end_iso:
                    try:
                        end_dt = datetime.fromisoformat(str(end_iso))
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                        # Need at least 30s of meeting left to bother starting.
                        still_in_window = (end_dt - now).total_seconds() > 30
                    except Exception:
                        still_in_window = False
                if still_in_window:
                    fresh.append(entry)
                else:
                    logger.info(
                        "meeting_concurrency_expired_in_queue",
                        meeting_id=entry.get("meeting_id"),
                        event_id=entry.get("calendar_event_id"),
                    )
            # Drained entries leave the queue; expired entries also leave.
            self._save(keep_in_queue)
        return fresh

    def list_queued(self) -> list[dict[str, Any]]:
        return self._load()


@lru_cache()
def get_meeting_concurrency_service() -> MeetingConcurrencyService:
    return MeetingConcurrencyService()
