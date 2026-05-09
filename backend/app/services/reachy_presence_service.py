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
import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload

logger = structlog.get_logger()


# Jobs that drive autonomous Reachy motion when ambient mode is enabled.
# Pomodoro is excluded: it's user-opt-in via its own start/stop endpoint and
# should not respawn just because ambient mode is re-enabled.
_AMBIENT_JOB_IDS = (
    "reachy_presence_beat",
    "reachy_idle_watcher",
    "reachy_hourly_chime",
)
_AMBIENT_STATE_PATH = Path("workspace/reachy/ambient_state.json")


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
# Rotated during meeting-mode quiet periods so Reachy looks attentive but
# not metronomic. The first item fires most often.
MEETING_FIDGETS = ("attentive1", "thoughtful1", "curious1", "attentive2")
MEETING_PERSONA_ID = "deep_work"


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
        # Meeting mode
        self._meeting_mode: bool = False
        self._meeting_id: Optional[str] = None
        self._meeting_task: Optional[asyncio.Task] = None
        self._meeting_started_at: Optional[datetime] = None
        # Persona to restore when meeting mode exits. Captured at start.
        self._pre_meeting_persona: Optional[str] = None
        # Reflects whether the most recent DoA probe returned cleanly.
        # False when meeting mode is off, or when the Reachy daemon DoA
        # endpoint is unreachable / erroring. Lets the UI surface a
        # "DoA unavailable" warning instead of looking silently broken.
        self._doa_available: bool = False
        # Ambient autonomy on/off (presence beat + idle watcher + hourly chime).
        # Persisted to disk so user preference survives restarts. Default ON
        # for first-run; respect saved value otherwise.
        self._ambient_enabled: bool = self._load_ambient_enabled()

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
        # Honour persisted ambient preference: pause the autonomous-motion jobs
        # immediately if the user previously turned them off. Pomodoro_tick is
        # not in _AMBIENT_JOB_IDS — it stays runnable and is gated by its own
        # active/inactive state inside the tick.
        if not self._ambient_enabled:
            for jid in _AMBIENT_JOB_IDS:
                try:
                    sched.pause_job(jid)
                except Exception as e:
                    logger.warning("reachy_ambient_pause_on_start_failed", job=jid, error=str(e))
        logger.info(
            "reachy_presence_started",
            jobs=self._job_ids,
            ambient_enabled=self._ambient_enabled,
        )

    # ------------------------------------------------------------------
    # Activity tracking — voice loop calls this on each input it handles
    # ------------------------------------------------------------------

    def mark_voice_activity(self) -> None:
        self._last_voice_activity = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Phase 7 — user attention state (Reachy presence ⨯ sight)
    # ------------------------------------------------------------------

    async def user_attention_state(self) -> dict:
        """
        Cross-reference Reachy's own signals (DoA angle, face detection) with
        the active SightProvider's last frame to describe where the user's
        attention actually is. Returns one of:
          {"label": "with_reachy" | "at_screen" | "moving" | "away", ...}

        Best-effort — returns `{"label": None, "reason": "..."}` if any
        signal is missing. Callers should treat a None label as "no data".
        """
        import time as _time
        try:
            from app.services.reachy_service import get_reachy_service
        except Exception as e:
            return {"label": None, "reason": f"reachy_service unavailable: {e}"}

        reachy_has_face = False
        reachy_recent = False
        reachy_angle: Optional[float] = None
        try:
            state = await get_reachy_service().get_full_state()
            if state and not state.get("error"):
                doa = state.get("doa") or {}
                reachy_angle = doa.get("angle")
                reachy_recent = bool(doa.get("speech_detected"))
        except Exception:
            pass

        try:
            # Reuse the existing detect-on-own-camera endpoint if available.
            from app.services.sight import get_sight_registry
            reg = get_sight_registry()
            reachy_prov = reg.get("reachy")
            if reachy_prov is not None:
                jpeg = await reachy_prov.get_latest_frame()
                if jpeg:
                    from app.services.reachy_vision_service import get_reachy_vision_service
                    det = get_reachy_vision_service().detect(jpeg, kind="face")
                    reachy_has_face = bool(det.get("detections"))
        except Exception:
            pass

        glasses_caption: Optional[str] = None
        try:
            from app.services.sight import get_sight_registry
            reg = get_sight_registry()
            glasses = reg.get("meta_rayban")
            if glasses is not None:
                gstatus = await glasses.status()
                if gstatus.active and gstatus.last_frame_ts and (_time.time() - gstatus.last_frame_ts) < 15.0:
                    gjpeg = await glasses.get_latest_frame()
                    if gjpeg:
                        from app.services.vision_vlm_service import get_vision_vlm_service
                        scene = await get_vision_vlm_service().describe_scene(gjpeg)
                        glasses_caption = (scene.get("caption") or "").lower()
        except Exception:
            pass

        # Decision tree:
        # 1. If Reachy sees a face close + recent speech → user with Reachy.
        # 2. Else if glasses caption references a screen / laptop → at_screen.
        # 3. Else if glasses caption mentions motion ("walking", "hallway") → moving.
        # 4. Else if neither source has fresh signal → away.
        label: Optional[str] = None
        reason = ""
        if reachy_has_face and reachy_recent:
            label = "with_reachy"
            reason = "Reachy sees face + recent speech"
        elif glasses_caption and any(k in glasses_caption for k in (
            "laptop", "computer", "monitor", "screen", "desk", "keyboard", "code",
        )):
            label = "at_screen"
            reason = "glasses caption suggests screen"
        elif glasses_caption and any(k in glasses_caption for k in (
            "walking", "hallway", "street", "outside", "kitchen", "standing",
        )):
            label = "moving"
            reason = "glasses caption suggests motion"
        elif not reachy_has_face and glasses_caption is None:
            label = "away"
            reason = "no fresh Reachy face + no glasses caption"

        return {
            "label": label,
            "reason": reason,
            "reachy_has_face": reachy_has_face,
            "reachy_doa_angle": reachy_angle,
            "glasses_caption_preview": glasses_caption[:100] if glasses_caption else None,
        }

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
        if not body_motion_allowed(surface="presence:pomodoro_start").get("allowed"):
            logger.info("reachy_pomodoro_start_blocked", reason="body_motion_locked")
            self._pomodoro = PomodoroState()
            return {
                **self.pomodoro_state(),
                **body_motion_locked_payload(surface="presence:pomodoro_start"),
            }
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

    async def pomodoro_stop(self, *, play_ack: bool = True) -> dict:
        was_active = self._pomodoro.active
        self._pomodoro = PomodoroState()
        if play_ack and was_active:
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
        now = datetime.now(timezone.utc).astimezone()
        if now.hour < 7 or now.hour >= 22:
            return  # quiet hours
        if self._pomodoro.active and self._pomodoro.phase == "focus":
            return
        if self._meeting_mode:
            return
        await self._play_safe("understanding1", kind="emotion")

    # ------------------------------------------------------------------
    # Presence beat — tiny gestures so the robot looks alive
    # ------------------------------------------------------------------

    async def _tick_presence_beat(self) -> None:
        if self._meeting_mode:
            return  # meeting loop is driving gestures
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

    # ------------------------------------------------------------------
    # Meeting mode (Wave 4)
    # ------------------------------------------------------------------

    def meeting_state(self) -> dict:
        elapsed = None
        if self._meeting_started_at:
            elapsed = (datetime.now(timezone.utc) - self._meeting_started_at).total_seconds()
        return {
            "active": self._meeting_mode,
            "meeting_id": self._meeting_id,
            "started_at": self._meeting_started_at.isoformat() if self._meeting_started_at else None,
            "elapsed_s": elapsed,
            "doa_available": self._doa_available if self._meeting_mode else False,
        }

    async def start_meeting_mode(self, meeting_id: Optional[str] = None) -> dict:
        """
        Enter meeting mode: a background task that every ~3 s pulls the
        daemon's DoA (direction-of-arrival) and points Reachy's head at the
        active speaker, plus a rotating fidget gesture during silence.

        Also swaps the voice-loop persona to ``deep_work`` — silent unless
        addressed, shortest possible reply — for the duration of the meeting.
        The original persona is restored on stop.

        Idempotent — calling twice just refreshes the meeting id.
        """
        if not body_motion_allowed(surface="presence:meeting_start").get("allowed"):
            logger.info("reachy_meeting_mode_blocked", reason="body_motion_locked", meeting_id=meeting_id)
            if self._meeting_mode:
                await self.stop_meeting_mode(play_ack=False)
            return {
                **self.meeting_state(),
                **body_motion_locked_payload(surface="presence:meeting_start"),
            }
        self._meeting_id = meeting_id
        self._meeting_started_at = datetime.now(timezone.utc)
        if self._meeting_mode and self._meeting_task and not self._meeting_task.done():
            return self.meeting_state()

        # Persona swap (best effort; never block the meeting on this).
        try:
            from app.services.voice_loop_service import get_voice_loop_service
            vs = get_voice_loop_service()
            current = vs.get_active_persona_id()
            if current and current != MEETING_PERSONA_ID:
                self._pre_meeting_persona = current
                vs.set_persona(MEETING_PERSONA_ID)
                logger.info(
                    "reachy_meeting_persona_swapped",
                    from_=current,
                    to=MEETING_PERSONA_ID,
                )
        except Exception as e:
            logger.debug("reachy_meeting_persona_swap_failed", error=str(e))

        self._meeting_mode = True
        await self._play_safe("welcoming1", kind="emotion")
        self._meeting_task = asyncio.create_task(self._meeting_loop())
        logger.info("reachy_meeting_mode_started", meeting_id=meeting_id)
        return self.meeting_state()

    async def stop_meeting_mode(self, *, play_ack: bool = True) -> dict:
        was_active = self._meeting_mode
        self._meeting_mode = False
        self._doa_available = False
        if self._meeting_task and not self._meeting_task.done():
            self._meeting_task.cancel()
            try:
                await self._meeting_task
            except (asyncio.CancelledError, Exception):
                pass
        self._meeting_task = None
        if play_ack and was_active:
            # Final ack — understanding2 = "I got it"
            await self._play_safe("understanding2", kind="emotion")

        # Restore pre-meeting persona if we swapped.
        if self._pre_meeting_persona:
            try:
                from app.services.voice_loop_service import get_voice_loop_service
                vs = get_voice_loop_service()
                vs.set_persona(self._pre_meeting_persona)
                logger.info(
                    "reachy_meeting_persona_restored",
                    to=self._pre_meeting_persona,
                )
            except Exception as e:
                logger.debug("reachy_meeting_persona_restore_failed", error=str(e))
            self._pre_meeting_persona = None

        logger.info("reachy_meeting_mode_stopped", meeting_id=self._meeting_id)
        state = self.meeting_state()
        self._meeting_id = None
        self._meeting_started_at = None
        return state

    async def _meeting_loop(self) -> None:
        """
        DoA-driven head tracking. Shape is intentionally simple: every POLL_S
        seconds, fetch DoA; if `speech_detected` and the angle has moved
        enough, call look_at with the angle projected onto unit-sphere x/y.

        Every ATTENTIVE_EVERY seconds, regardless of DoA, play `attentive1`
        to signal active listening.
        """
        import math
        POLL_S = 3.0
        ATTENTIVE_EVERY = 45.0
        last_angle: Optional[float] = None
        last_attentive = 0.0
        try:
            from app.services.reachy_service import get_reachy_service
            svc = get_reachy_service()
            while self._meeting_mode:
                try:
                    # Look-at-speaker via DoA
                    doa = await svc.get_doa()
                    self._doa_available = isinstance(doa, dict) and "angle" in doa
                    angle = doa.get("angle") if isinstance(doa, dict) else None
                    speech = doa.get("speech_detected") if isinstance(doa, dict) else False
                    if (
                        speech
                        and isinstance(angle, (int, float))
                        and body_motion_allowed(surface="presence:meeting_look_at").get("allowed")
                    ):
                        if last_angle is None or abs(angle - last_angle) > 0.15:
                            # Project onto unit-circle 1 m in front of the robot
                            x = math.cos(angle)
                            y = math.sin(angle)
                            await svc.look_at(x=x, y=y, z=0.0, duration=0.6)
                            last_angle = angle
                            self._last_gesture_at = datetime.now(timezone.utc)
                except Exception as e:
                    self._doa_available = False
                    logger.debug("reachy_meeting_doa_tick_failed", error=str(e))

                # Periodic attentiveness fidget, rotated so Reachy doesn't
                # look metronomic during long silences.
                now = datetime.now(timezone.utc).timestamp()
                if now - last_attentive > ATTENTIVE_EVERY:
                    last_attentive = now
                    try:
                        if body_motion_allowed(surface="presence:meeting_fidget").get("allowed"):
                            fidget = random.choice(MEETING_FIDGETS)
                            await svc.play_emotion(fidget)
                            self._last_gesture_at = datetime.now(timezone.utc)
                    except Exception:
                        pass

                await asyncio.sleep(POLL_S)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("reachy_meeting_loop_crashed", error=str(e))

    async def _play_safe(self, name: str, *, kind: str) -> None:
        """Play a clip but swallow errors so the scheduler stays clean."""
        if not body_motion_allowed(surface=f"presence:{kind}:{name}").get("allowed"):
            logger.debug("reachy_presence_play_blocked", clip=name, kind=kind, reason="body_motion_locked")
            return
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

    # ------------------------------------------------------------------
    # Ambient autonomy on/off
    # ------------------------------------------------------------------

    def _load_ambient_enabled(self) -> bool:
        try:
            if _AMBIENT_STATE_PATH.exists():
                data = json.loads(_AMBIENT_STATE_PATH.read_text(encoding="utf-8"))
                return bool(data.get("enabled", True))
        except Exception as e:
            logger.warning("reachy_ambient_state_load_failed", error=str(e))
        return True

    def _save_ambient_enabled(self, enabled: bool) -> None:
        try:
            _AMBIENT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _AMBIENT_STATE_PATH.write_text(
                json.dumps({"enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("reachy_ambient_state_save_failed", error=str(e))

    def ambient_state(self) -> dict:
        from app.services.scheduler_service import get_scheduler_service
        sched = get_scheduler_service().scheduler
        jobs = []
        for jid in _AMBIENT_JOB_IDS:
            j = sched.get_job(jid)
            if j is None:
                jobs.append({"id": jid, "registered": False, "next_run_time": None})
            else:
                jobs.append({
                    "id": jid,
                    "registered": True,
                    "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                })
        return {"enabled": self._ambient_enabled, "jobs": jobs}

    def ambient_start(self) -> dict:
        """Resume the autonomous-motion jobs (presence beat, idle watcher, hourly chime)."""
        if not body_motion_allowed(surface="presence:ambient_start").get("allowed"):
            logger.info("reachy_ambient_start_blocked", reason="body_motion_locked")
            state = self.ambient_stop()
            return {
                **state,
                **body_motion_locked_payload(surface="presence:ambient_start"),
            }
        from app.services.scheduler_service import get_scheduler_service
        sched = get_scheduler_service().scheduler
        for jid in _AMBIENT_JOB_IDS:
            try:
                sched.resume_job(jid)
            except Exception as e:
                logger.warning("reachy_ambient_resume_failed", job=jid, error=str(e))
        self._ambient_enabled = True
        self._save_ambient_enabled(True)
        logger.info("reachy_ambient_started", jobs=list(_AMBIENT_JOB_IDS))
        return self.ambient_state()

    def ambient_stop(self) -> dict:
        """Pause the autonomous-motion jobs. Persists across restarts."""
        from app.services.scheduler_service import get_scheduler_service
        sched = get_scheduler_service().scheduler
        for jid in _AMBIENT_JOB_IDS:
            try:
                sched.pause_job(jid)
            except Exception as e:
                logger.warning("reachy_ambient_pause_failed", job=jid, error=str(e))
        self._ambient_enabled = False
        self._save_ambient_enabled(False)
        logger.info("reachy_ambient_stopped", jobs=list(_AMBIENT_JOB_IDS))
        return self.ambient_state()


def get_reachy_presence_service() -> ReachyPresenceService:
    return ReachyPresenceService.get_instance()
