"""Superhuman v2 opt-in store + driver gate.

Stores per-meeting opt-in flags at workspace/meetings/superhuman_optin.json
so the scheduler can decide whether to spawn the meeting-agent (Playwright)
or fall back to passive loopback capture at meeting start time.

Real-driver toggle is the env var ``ZERO_MEETING_AGENT_REAL_DRIVER``; this
service just exposes the boolean and stores the per-event flag. The actual
join-leave automation lives in ``meeting_agent_service.py``.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


class MeetingSuperhumanService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "superhuman_optin.json"
        self._lock = threading.RLock()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("superhuman_optin_load_failed", error=str(exc))
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def real_driver_enabled(self) -> bool:
        val = os.getenv("ZERO_MEETING_AGENT_REAL_DRIVER", "false").strip().lower()
        return val in {"1", "true", "yes", "on"}

    async def opt_in(self, *, meeting_id: str, join_url: str, title: str | None) -> None:
        with self._lock:
            data = self._load()
            data[meeting_id] = {
                "join_url": join_url,
                "title": title,
                "opted_in_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save(data)
        logger.info(
            "superhuman_opt_in",
            meeting_id=meeting_id,
            join_url=join_url,
            real_driver=self.real_driver_enabled(),
        )

    async def opt_out(self, meeting_id: str) -> None:
        with self._lock:
            data = self._load()
            data.pop(meeting_id, None)
            self._save(data)
        logger.info("superhuman_opt_out", meeting_id=meeting_id)

    async def status(self, meeting_id: str) -> dict[str, Any]:
        data = self._load()
        entry = data.get(meeting_id)
        return {
            "meeting_id": meeting_id,
            "send_zero": bool(entry),
            "real_driver": self.real_driver_enabled(),
            **(entry or {}),
        }

    async def is_opted_in(self, meeting_id: str) -> bool:
        return meeting_id in self._load()

    async def list_opt_ins(self) -> dict[str, dict[str, Any]]:
        return self._load()


@lru_cache()
def get_meeting_superhuman_service() -> MeetingSuperhumanService:
    return MeetingSuperhumanService()
