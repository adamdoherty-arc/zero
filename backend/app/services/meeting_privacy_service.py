"""Per-meeting privacy flag.

When the user says "Hey Zero, this is private" (or hits the UI button),
the active meeting is added to ``workspace/meetings/private_meetings.json``.
Downstream services check ``is_private(meeting_id)`` before:

  - Generating a summary
  - Indexing the transcript into the RAG / vector store
  - Drafting follow-up emails
  - Surfacing the meeting in cross-meeting search

The recording itself stays on disk (so the user can replay it locally),
but it does not propagate into any other system.

This is intentionally a simple JSON file rather than a DB column to
avoid an Alembic migration just for a privacy bit. A migration can come
later as part of a wider "meeting flags" cleanup.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


class MeetingPrivacyService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "private_meetings.json"
        self._lock = threading.RLock()

    def _load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("meeting_privacy_load_failed", error=str(exc))
            return {}

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def mark_private(self, meeting_id: str, *, source: str = "voice") -> None:
        with self._lock:
            data = self._load()
            data[meeting_id] = {
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
            }
            self._save(data)
        logger.info("meeting_privacy_marked", meeting_id=meeting_id, source=source)

    def clear(self, meeting_id: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(meeting_id, None) is not None:
                self._save(data)

    def is_private(self, meeting_id: str | None) -> bool:
        if not meeting_id:
            return False
        return meeting_id in self._load()

    def list_private(self) -> list[str]:
        return list(self._load().keys())


@lru_cache()
def get_meeting_privacy_service() -> MeetingPrivacyService:
    return MeetingPrivacyService()
