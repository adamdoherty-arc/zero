"""
Reachy persona state — interaction counts + optional auto-rotation.

Pure layer on top of reachy_personas.PERSONAS. Tracks (per-persona):
  * interactions — every time the voice loop consumed a turn
  * emotions_fired — gesture markers actually dispatched
  * last_used_at
  * last_switched_at

Optional rotation config (env or workspace JSON):
  {
    "rotate_after_interactions": 20,
    "rotation": ["companion", "explorer", "narrator"]
  }
If present, every N interactions the service quietly rotates to the next
persona in the list. Off by default — personas are sticky unless the user
switches via the UI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

STATE_PATH = Path("workspace") / "reachy" / "persona_state.json"
CONFIG_PATH = Path("workspace") / "reachy" / "persona_rotation.json"


@dataclass
class PersonaStats:
    interactions: int = 0
    emotions_fired: int = 0
    dances_fired: int = 0
    last_used_at: Optional[str] = None


@dataclass
class PersonaState:
    stats: dict[str, PersonaStats] = field(default_factory=dict)
    last_switched_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "stats": {k: v.__dict__ for k, v in self.stats.items()},
            "last_switched_at": self.last_switched_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PersonaState":
        out = cls()
        out.last_switched_at = d.get("last_switched_at")
        for k, v in (d.get("stats") or {}).items():
            out.stats[k] = PersonaStats(**v)
        return out


class ReachyPersonaStateService:
    _instance: Optional["ReachyPersonaStateService"] = None

    def __init__(self) -> None:
        self._state = self._load_state()
        self._rotation = self._load_rotation_config()

    @classmethod
    def get_instance(cls) -> "ReachyPersonaStateService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> PersonaState:
        try:
            if STATE_PATH.exists():
                return PersonaState.from_dict(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            logger.warning("persona_state_load_failed", error=str(e))
        return PersonaState()

    def _save_state(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(self._state.to_dict(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("persona_state_save_failed", error=str(e))

    def _load_rotation_config(self) -> dict:
        raw = os.environ.get("ZERO_REACHY_PERSONA_ROTATION")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _stats_for(self, persona_id: str) -> PersonaStats:
        if persona_id not in self._state.stats:
            self._state.stats[persona_id] = PersonaStats()
        return self._state.stats[persona_id]

    def record_interaction(self, persona_id: str, *, gestures: int = 0, dances: int = 0) -> Optional[str]:
        """
        Bump counters for the given persona. Returns the id of a new persona
        to switch to if rotation is configured and threshold crossed,
        otherwise None.
        """
        s = self._stats_for(persona_id)
        s.interactions += 1
        s.emotions_fired += max(0, gestures)
        s.dances_fired += max(0, dances)
        s.last_used_at = datetime.now(timezone.utc).isoformat()

        suggested: Optional[str] = None
        threshold = int(self._rotation.get("rotate_after_interactions", 0) or 0)
        rotation = list(self._rotation.get("rotation") or [])
        if threshold > 0 and len(rotation) >= 2 and s.interactions % threshold == 0:
            try:
                idx = rotation.index(persona_id)
            except ValueError:
                idx = -1
            suggested = rotation[(idx + 1) % len(rotation)]
            self._state.last_switched_at = datetime.now(timezone.utc).isoformat()

        self._save_state()
        return suggested

    def get_stats(self) -> dict:
        return {
            "last_switched_at": self._state.last_switched_at,
            "rotation": self._rotation,
            "personas": {
                k: {
                    "interactions": v.interactions,
                    "emotions_fired": v.emotions_fired,
                    "dances_fired": v.dances_fired,
                    "last_used_at": v.last_used_at,
                }
                for k, v in sorted(self._state.stats.items())
            },
        }

    def reset(self, persona_id: Optional[str] = None) -> dict:
        if persona_id:
            self._state.stats.pop(persona_id, None)
        else:
            self._state.stats.clear()
            self._state.last_switched_at = None
        self._save_state()
        return self.get_stats()


def get_reachy_persona_state() -> ReachyPersonaStateService:
    return ReachyPersonaStateService.get_instance()
