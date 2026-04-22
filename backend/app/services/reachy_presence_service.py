"""
Reachy Mini presence / ambient-behaviour scheduler.

Registers recurring jobs against Zero's main AsyncIOScheduler that keep
Reachy Mini behaving like a companion instead of a mute desk ornament:

  * pomodoro    — 25 min work, 5 min break. Reachy plays `thoughtful1` at
                  the start of each focus block and `cheerful1` (+ a short
                  `yeah_nod` dance) at each break. Opt-in: start via
                  POST /reachy/presence/pomodoro/start.
  * idle_watcher — every 10 min, if the voice loop has not processed any
                  input, play a low-energy gesture (tired1 / boredom1 /
                  sleep1, rotated) so the robot looks alive.
  * hourly_chime — on the hour, small `understanding1` nod. Disabled at
                  night (22:00–07:00 local).
  * presence_beat — every 3 min, if the robot is connected and idle for
                   >90 s, play a tiny random dance (side_glance_flick,
                   side_to_side_sway) to signal attention.

All jobs no-op when the Reachy daemon is unreachable. Nothing breaks the
scheduler if the robot is offline.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


@dataclass
class PomodoroState:
    active: bool = False
    phase: str = "idle"  # "focus" | "break" | "idle"
    started_at: Optional[datetime] = None
    focus_minutes: int = 25
    break_minutes: int = 5
    cycle_index: int = 0


IDLE_GESTURES = ("tired1", "boredom1", "sleep1", "thoughtful1")
PRESENCE_BEATS = ("side_glance_flick", "side_to_side_sway", "simple_nod")


class ReachyPresenceService:
    """Ambient-behaviour orchestrator for Reachy Mini."""

    _instance: Optional["ReachyPresenceService"] = None

    def __init__(self) -> None:
        self._started = False
        self._pomodoro = PomodoroState()
        self._last_voice_activity: Optional[datetime] = None
        self._last_gesture_at: Optional[datetime] = None
        # Job ids so we can cancel/requery.
        self._job_ids: list[str] = []

    @classmethod
    def get_instance(cls) -> "ReachyPresenceService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Attach ambient jobs to the main scheduler. Idempotent."""
        if self._started:
            return
        from app.services.scheduler_service import get_scheduler_service

        sched = get_scheduler_service().scheduler
        # Register with replace_existing so reloads don't pile up.
        sched.add_job(
            self._tick_pomodoro,
            trigger="interval",
            minutes=1,
            id="reachy_pomodoro_tick",
            name="Reachy pomodoro tick",
            replace_existing=True,
        )
        sched.add_job(
            self._tick_idle,
            trigger="interval",
            minutes=10,
            id="reachy_idle_watcher",
            name="Reachy idle watcher",
            replace_existing=True,
        )
        sched.add_job(
            self._tick_hourly_chime,
            trigger="cron",
            minute=0,
            id="reachy_hourly_chime",
            name="Reachy hourly chime",
            replace_existing=True,
        )
        sched.add_job(
            self._tick_presence_beat,
            trigger="interval",
            minutes=3,
            id="reachy_presence_beat",
            name="Reachy presence beat",
            replace_existing=True,
        )
        self._job_ids = [
            "reachy_pomodoro_tick",
            "reachy_idle_watcher",
            "reachy_hourly_chime",
            "reachy_presence_beat",
        ]
        self._started = True
        logger.info("reachy_presence_started", jobs=self._job_ids)

    # ------------------------------------------------------------------
    # Activity tracking — voice loop calls this on each input it handles
    # ------------------------------------------------------------------

    def mark_voice_activity(self) -> None:
        self._last_voice_activity = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Pomodoro
    # ------------------------------------------------------------------

    def pomodoro_state(self) -> dict:
        s = self._pomodoro
        elapsed = None
        if s.started_at:
            elapsed = (datetime.now(timezone.utc) - s.started_at).total_seconds()
        return {
            "active": s.active,
            "phase": s.phase,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "elapsed_s": elapsed,
            "focus_minutes": s.focus_minutes,
            "break_minutes": s.break_minutes,
            "cycle_index": s.cycle_index,
        }

    async def pomodoro_start(self, focus_minutes: int = 25, break_minutes: int = 5) -> dict:
        self._pomodoro = PomodoroState(
            active=True,
            phase="focus",
            started_at=datetime.now(timezone.utc),
            focus_minutes=max(5, min(90, focus_minutes)),
            break_minutes=max(1, min(30, break_minutes)),
            cycle_index=1,
        )
        await self._play_safe("thoughtful1", kind="emotion")
        logger.info("reachy_pomodoro_started", focus=focus_minutes, break_=break_minutes)
        return self.pomodoro_state()

    async def pomodoro_stop(self) -> dict:
        self._pomodoro = PomodoroState()
        await self._play_safe("understanding1", kind="emotion")
        logger.info("reachy_pomodoro_stopped")
        return self.pomodoro_state()

    async def _tick_pomodoro(self) -> None:
        s = self._pomodoro
        if not s.active or not s.started_at:
            return
        elapsed_min = (datetime.now(timezone.utc) - s.started_at).total_seconds() / 60.0
        target = s.focus_minutes if s.phase == "focus" else s.break_minutes
        if elapsed_min + 0.5 < target:
            return
        # phase flip
        if s.phase == "focus":
            s.phase = "break"
            s.started_at = datetime.now(timezone.utc)
            await self._play_safe("cheerful1", kind="emotion")
            await asyncio.sleep(1.0)
            await self._play_safe("yeah_nod", kind="dance")
            logger.info("reachy_pomodoro_phase", phase="break", cycle=s.cycle_index)
        else:
            s.phase = "focus"
            s.cycle_index += 1
            s.started_at = datetime.now(timezone.utc)
            await self._play_safe("thoughtful1", kind="emotion")
            logger.info("reachy_pomodoro_phase", phase="focus", cycle=s.cycle_index)

    # ------------------------------------------------------------------
    # Idle watcher
    # ------------------------------------------------------------------

    async def _tick_idle(self) -> None:
        last = self._last_voice_activity
        idle_for = (datetime.now(timezone.utc) - last).total_seconds() if last else None
        # Only react if we've been totally quiet for >= 20 minutes and the
        # robot is connected. Boredom should not interrupt pomodoro.
        if self._pomodoro.active:
            return
        if idle_for is None or idle_for < 20 * 60:
            return
        # Don't spam: skip if we played a gesture in the last 15 minutes.
        if self._gesture_recent(seconds=15 * 60):
            return
        clip = random.choice(IDLE_GESTURES)
        await self._play_safe(clip, kind="emotion")

    # ------------------------------------------------------------------
    # Hourly chime
    # ------------------------------------------------------------------

    async def _tick_hourly_chime(self) -> None:
        now = datetime.now().astimezone()
        if now.hour < 7 or now.hour >= 22:
            return  # quiet hours
        if self._pomodoro.active and self._pomodoro.phase == "focus":
            return
        await self._play_safe("understanding1", kind="emotion")

    # ------------------------------------------------------------------
    # Presence beat — tiny gestures so the robot looks alive
    # ------------------------------------------------------------------

    async def _tick_presence_beat(self) -> None:
        if self._pomodoro.active and self._pomodoro.phase == "focus":
            return
        if self._gesture_recent(seconds=90):
            return
        last = self._last_voice_activity
        if last and (datetime.now(timezone.utc) - last).total_seconds() < 60:
            return  # active conversation, leave it alone
        if random.random() > 0.4:
            return  # ~40% probability per tick to avoid metronome feel
        clip = random.choice(PRESENCE_BEATS)
        await self._play_safe(clip, kind="dance")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gesture_recent(self, *, seconds: int) -> bool:
        if not self._last_gesture_at:
            return False
        return (datetime.now(timezone.utc) - self._last_gesture_at).total_seconds() < seconds

    async def _play_safe(self, name: str, *, kind: str) -> None:
        """Play a clip but swallow errors so the scheduler stays clean."""
        try:
            from app.services.reachy_service import get_reachy_service
            svc = get_reachy_service()
            if not await svc.is_connected():
                return
            if kind == "dance":
                await svc.play_dance(name)
            else:
                await svc.play_emotion(name)
            self._last_gesture_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.debug("reachy_presence_play_failed", clip=name, kind=kind, error=str(e))


def get_reachy_presence_service() -> ReachyPresenceService:
    return ReachyPresenceService.get_instance()
