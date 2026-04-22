"""
Home Assistant → Reachy gesture watcher.

Polls HA every ``ZERO_HA_POLL_SECONDS`` (default 15s) for a configured set of
entity ids and fires a Reachy emotion clip when any of them change state.

Mapping is loaded from ``ZERO_HA_GESTURE_MAP`` as a JSON string, or from
``workspace/home_assistant/gesture_map.json`` if present. Shape:

    {
      "binary_sensor.doorbell":         {"state": "on",  "emotion": "welcoming1"},
      "alarm_control_panel.home":       {"state": "triggered", "emotion": "surprised1"},
      "person.adam":                    {"state": "home", "emotion": "cheerful1"},
      "sensor.kitchen_motion":          {"state": "on",  "emotion": "attentive1", "cooldown_s": 120}
    }

Each rule optionally carries ``cooldown_s`` (default 60) to prevent repeat
fires when the sensor flickers. Entities not in the map are ignored.

Register with Zero's main scheduler via ``start()`` in main.py lifespan.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


DEFAULT_MAP_PATH = Path("workspace/home_assistant/gesture_map.json")
DEFAULT_POLL_SECONDS = 15


class HomeAssistantWatcher:
    _instance: Optional["HomeAssistantWatcher"] = None

    def __init__(self) -> None:
        self._started = False
        self._last_states: dict[str, str] = {}
        self._last_fired_at: dict[str, float] = {}
        self._map: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> "HomeAssistantWatcher":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._load_map()
        if not self._map:
            logger.info("ha_watcher_skipped_no_map")
            return
        try:
            from app.services.scheduler_service import get_scheduler_service
            sched = get_scheduler_service().scheduler
            interval = int(os.environ.get("ZERO_HA_POLL_SECONDS", DEFAULT_POLL_SECONDS))
            sched.add_job(
                self._tick,
                trigger="interval",
                seconds=max(5, interval),
                id="ha_gesture_watcher",
                name="HA → Reachy gesture watcher",
                replace_existing=True,
            )
            self._started = True
            logger.info("ha_watcher_started", entities=list(self._map.keys()), interval=interval)
        except Exception as e:
            logger.warning("ha_watcher_start_failed", error=str(e))

    def _load_map(self) -> None:
        raw = os.environ.get("ZERO_HA_GESTURE_MAP")
        if raw:
            try:
                self._map = json.loads(raw)
                return
            except Exception as e:
                logger.warning("ha_gesture_map_env_malformed", error=str(e))
        if DEFAULT_MAP_PATH.exists():
            try:
                self._map = json.loads(DEFAULT_MAP_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("ha_gesture_map_file_malformed", path=str(DEFAULT_MAP_PATH), error=str(e))

    def get_map(self) -> dict[str, dict[str, Any]]:
        return dict(self._map)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        from app.services.home_assistant_service import get_home_assistant_service
        from app.services.reachy_service import get_reachy_service

        ha = get_home_assistant_service()
        if not ha.configured:
            return

        now = time.monotonic()
        for entity_id, rule in self._map.items():
            try:
                state = await ha.get_state(entity_id)
                if state.get("error"):
                    continue
                current = state.get("state")
                target = rule.get("state")
                if target is None or current != target:
                    # Record state but don't fire on non-matching transitions
                    self._last_states[entity_id] = current or ""
                    continue
                prev = self._last_states.get(entity_id)
                cooldown = float(rule.get("cooldown_s", 60))
                last_fired = self._last_fired_at.get(entity_id, 0.0)
                if prev == target:
                    continue  # already in target state; wait for a change
                if now - last_fired < cooldown:
                    continue  # cooling down
                emotion = rule.get("emotion")
                dance = rule.get("dance")
                if not (emotion or dance):
                    continue
                svc = get_reachy_service()
                if not await svc.is_connected():
                    continue
                if emotion:
                    await svc.play_emotion(emotion)
                if dance:
                    await svc.play_dance(dance)
                self._last_states[entity_id] = target
                self._last_fired_at[entity_id] = now
                logger.info("ha_gesture_fired", entity=entity_id, state=target, emotion=emotion, dance=dance)
            except Exception as e:
                logger.debug("ha_gesture_tick_failed", entity=entity_id, error=str(e))


def get_ha_watcher() -> HomeAssistantWatcher:
    return HomeAssistantWatcher.get_instance()
