"""
Reachy Radio mode.

Two cleanly-separated pieces, so callers can use either or both:

1. ``analyze_bpm(audio_bytes)`` — runs ``librosa.beat.beat_track`` on a short
   audio sample (any format librosa reads — MP3, WAV, OGG, FLAC) and returns
   the detected tempo.
2. ``start(bpm, dances=[...])`` / ``stop()`` — background task that plays a
   random dance from ``dances`` every ``beats_per_dance / bpm * 60`` seconds
   via the daemon's recorded-move library. No audio playback is attempted
   server-side; the daemon / user supplies the music.

This lets you:
  * Point a phone at a speaker, hit "analyze", get the BPM.
  * Start radio mode with that BPM and Reachy dances along to whatever is
    playing in the room.
  * Or pass BPM manually (e.g. from a Spotify now-playing integration) for
    perfectly beat-locked dances with no audio analysis.
"""

from __future__ import annotations

import asyncio
import io
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload

logger = structlog.get_logger()


# Reasonable defaults pulled from the dances we already ship (Wave 1).
DEFAULT_DANCE_ROTATION: tuple[str, ...] = (
    "simple_nod",
    "side_to_side_sway",
    "head_tilt_roll",
    "groovy_sway_and_roll",
    "pendulum_swing",
    "yeah_nod",
    "uh_huh_tilt",
    "polyrhythm_combo",
    "headbanger_combo",
)


@dataclass
class RadioState:
    active: bool = False
    bpm: float = 0.0
    beats_per_dance: int = 8
    dances: tuple[str, ...] = DEFAULT_DANCE_ROTATION
    started_at: Optional[datetime] = None
    dances_played: int = 0
    current_dance: Optional[str] = None
    task: Optional[asyncio.Task] = None


class ReachyRadioService:
    _instance: Optional["ReachyRadioService"] = None

    def __init__(self) -> None:
        self._state = RadioState()

    @classmethod
    def get_instance(cls) -> "ReachyRadioService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        s = self._state
        elapsed = None
        if s.started_at:
            elapsed = (datetime.now(timezone.utc) - s.started_at).total_seconds()
        return {
            "active": s.active,
            "bpm": s.bpm,
            "beats_per_dance": s.beats_per_dance,
            "dances": list(s.dances),
            "current_dance": s.current_dance,
            "dances_played": s.dances_played,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "elapsed_s": elapsed,
        }

    # ------------------------------------------------------------------
    # BPM detection (librosa)
    # ------------------------------------------------------------------

    def analyze_bpm(self, audio_bytes: bytes) -> dict:
        if not audio_bytes:
            return {"available": False, "reason": "empty_audio"}
        try:
            import librosa  # type: ignore[import-not-found]
            import numpy as np
            import soundfile as sf
        except Exception as e:
            return {"available": False, "reason": f"librosa/soundfile not installed: {e}"}
        try:
            data, sr = sf.read(io.BytesIO(audio_bytes), always_2d=False)
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            data = data.astype("float32")
            tempo_raw, beats = librosa.beat.beat_track(y=data, sr=sr)
            tempo = float(np.asarray(tempo_raw).flatten()[0]) if np.size(tempo_raw) else 0.0
            return {
                "available": True,
                "bpm": tempo,
                "beat_count": int(len(beats)),
                "duration_s": float(len(data) / sr),
                "sample_rate": int(sr),
            }
        except Exception as e:
            logger.warning("radio_bpm_analysis_failed", error=str(e))
            return {"available": True, "error": str(e)}

    # ------------------------------------------------------------------
    # Radio mode dance dispatcher
    # ------------------------------------------------------------------

    async def start(
        self,
        *,
        bpm: float,
        beats_per_dance: int = 8,
        dances: Optional[list[str]] = None,
    ) -> dict:
        if not body_motion_allowed(surface="radio:start").get("allowed"):
            return body_motion_locked_payload(surface="radio:start")
        if self._state.active:
            await self.stop()
        bpm = max(40.0, min(200.0, float(bpm)))
        dance_pool = tuple(dances) if dances else DEFAULT_DANCE_ROTATION
        self._state = RadioState(
            active=True,
            bpm=bpm,
            beats_per_dance=max(2, min(32, int(beats_per_dance))),
            dances=dance_pool,
            started_at=datetime.now(timezone.utc),
        )
        self._state.task = asyncio.create_task(self._loop())
        logger.info("reachy_radio_started", bpm=bpm, dances=len(dance_pool))
        return self.status()

    async def stop(self) -> dict:
        s = self._state
        s.active = False
        if s.task and not s.task.done():
            s.task.cancel()
            try:
                await s.task
            except (asyncio.CancelledError, Exception):
                pass
        s.task = None
        s.current_dance = None
        logger.info("reachy_radio_stopped")
        return self.status()

    async def _loop(self) -> None:
        from app.services.reachy_service import get_reachy_service
        svc = get_reachy_service()
        try:
            while self._state.active:
                if not body_motion_allowed(surface="radio:loop").get("allowed"):
                    logger.info("reachy_radio_blocked", reason="body_motion_locked")
                    self._state.active = False
                    self._state.current_dance = None
                    return
                dance_duration_s = (self._state.beats_per_dance * 60.0) / max(1.0, self._state.bpm)
                clip = random.choice(self._state.dances)
                self._state.current_dance = clip
                try:
                    if await svc.is_connected():
                        await svc.play_dance(clip)
                    self._state.dances_played += 1
                except Exception as e:
                    logger.debug("reachy_radio_dispatch_failed", clip=clip, error=str(e))
                await asyncio.sleep(max(0.5, dance_duration_s))
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("reachy_radio_loop_crashed", error=str(e))


def get_reachy_radio_service() -> ReachyRadioService:
    return ReachyRadioService.get_instance()
