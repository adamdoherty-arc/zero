"""
Persona → signature intro sequence mapping.

When the user switches personas, Reachy can play a user-authored motion
sequence as an "intro" — e.g. switching to coach triggers a thoughtful1 +
head_tilt_roll chain. This service owns the persona→sequence map,
persisted as JSON so it survives restarts.

Kept separate from reachy_personas.py (which holds the immutable
persona catalog) because this mapping is user-editable state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

INTROS_PATH = Path("workspace") / "reachy" / "persona_intros.json"


class ReachyPersonaIntrosService:
    _instance: Optional["ReachyPersonaIntrosService"] = None

    def __init__(self) -> None:
        self._map: dict[str, int] = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "ReachyPersonaIntrosService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        try:
            if not INTROS_PATH.exists():
                return
            raw = json.loads(INTROS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._map = {
                    str(k): int(v)
                    for k, v in raw.items()
                    if isinstance(v, (int, float))
                }
        except Exception as e:
            logger.warning("persona_intros_load_failed", error=str(e))

    def _save(self) -> None:
        try:
            INTROS_PATH.parent.mkdir(parents=True, exist_ok=True)
            INTROS_PATH.write_text(json.dumps(self._map, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("persona_intros_save_failed", error=str(e))

    # ------------------------------------------------------------------

    def get(self, persona_id: str) -> Optional[int]:
        return self._map.get(persona_id)

    def all(self) -> dict[str, int]:
        return dict(self._map)

    def set(self, persona_id: str, sequence_id: int) -> None:
        self._map[persona_id] = int(sequence_id)
        self._save()
        logger.info("persona_intro_set", persona=persona_id, sequence_id=sequence_id)

    def clear(self, persona_id: str) -> bool:
        if persona_id in self._map:
            del self._map[persona_id]
            self._save()
            logger.info("persona_intro_cleared", persona=persona_id)
            return True
        return False


def get_reachy_persona_intros_service() -> ReachyPersonaIntrosService:
    return ReachyPersonaIntrosService.get_instance()
