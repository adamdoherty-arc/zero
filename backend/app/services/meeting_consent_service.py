"""Consent guard for meeting auto-record.

Reads ``workspace/meetings/consent_policy.json`` and resolves whether a
given calendar event should auto-record without asking, ask first, or
never record. Lets the user keep "record everything by default" without
landing on a legal landmine (two-party-consent jurisdictions, external
attendees, sensitive titles).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

import structlog

from app.infrastructure.config import get_workspace_path

logger = structlog.get_logger(__name__)


ConsentDecision = Literal["allow", "ask", "deny"]


@dataclass
class ConsentResult:
    decision: ConsentDecision
    reason: str
    confirm_window_seconds: int = 30


class MeetingConsentService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("meetings")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "consent_policy.json"
        self._lock = threading.RLock()
        self._cached: dict[str, Any] | None = None

    def _policy(self) -> dict[str, Any]:
        with self._lock:
            if self._cached is not None:
                return self._cached
            if not self._path.exists():
                self._cached = self._default_policy()
                self._path.write_text(
                    json.dumps(self._cached, indent=2), encoding="utf-8"
                )
                return self._cached
            try:
                self._cached = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("consent_policy_load_failed", error=str(exc))
                self._cached = self._default_policy()
            return self._cached

    def reload(self) -> None:
        with self._lock:
            self._cached = None

    def _default_policy(self) -> dict[str, Any]:
        return {
            "version": 1,
            "default_record_for_solo": True,
            "default_record_for_internal": True,
            "default_record_for_external": "ask",
            "internal_domains": [],
            "always_record_titles": [],
            "never_record_titles": [],
            "confirm_window_seconds": 30,
        }

    def evaluate(
        self,
        *,
        title: str | None,
        attendees: Iterable[str] | None = None,
        organizer_email: str | None = None,
    ) -> ConsentResult:
        pol = self._policy()
        confirm_window = int(pol.get("confirm_window_seconds", 30))
        title_norm = (title or "").strip().lower()
        for never in pol.get("never_record_titles", []):
            if never.lower() in title_norm:
                return ConsentResult(
                    "deny",
                    f"title matches never-record rule: {never!r}",
                    confirm_window,
                )
        for always in pol.get("always_record_titles", []):
            if always.lower() in title_norm:
                return ConsentResult(
                    "allow",
                    f"title matches always-record rule: {always!r}",
                    confirm_window,
                )
        atts = [a for a in (attendees or []) if a]
        if not atts:
            decision = "allow" if pol.get("default_record_for_solo", True) else "ask"
            return ConsentResult(decision, "solo / no attendees", confirm_window)

        internal_domains = {d.lower() for d in pol.get("internal_domains", [])}

        def _is_internal(email: str) -> bool:
            if "@" not in email:
                return False
            return email.rsplit("@", 1)[1].strip().lower() in internal_domains

        all_internal = all(_is_internal(a) for a in atts)
        if all_internal:
            decision = "allow" if pol.get("default_record_for_internal", True) else "ask"
            return ConsentResult(decision, "all attendees internal", confirm_window)

        choice = pol.get("default_record_for_external", "ask")
        if choice not in {"allow", "ask", "deny"}:
            choice = "ask"
        return ConsentResult(
            choice, "external attendee on invite", confirm_window
        )


@lru_cache()
def get_meeting_consent_service() -> MeetingConsentService:
    return MeetingConsentService()
