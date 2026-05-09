"""
Record user-authored Reachy Mini moves without the on-device SDK.

Upstream ``reachy_mini_toolbox/moves/recorder.py`` uses ``ReachyMini()`` which
opens a direct USB handle to the motors — that's fine on-robot but useless
from Zero's Docker container. This module polls the daemon's REST state API
instead: every ~20 ms it snapshots head pose + body yaw + antennas, and on
stop writes a JSON trajectory compatible with the daemon's own
``recorded-move-dataset`` format so replay goes through the same
``set_target`` pipe Zero already uses.

Workflow:
1. ``POST /reachy/moves/record/start``  with {library, name, description}
   → enables torque-release on the motors (user-puppets the head) and begins
     the poll loop.
2. User moves Reachy by hand.
3. ``POST /reachy/moves/record/stop``
   → writes ``workspace/reachy/user_moves/{library}/{name}.json``.
4. ``POST /reachy/moves/user/{library}/{name}/play``
   → streams the trajectory back as set_target calls. 50 Hz is good enough
     for the small pose deltas these recordings typically capture.

The same JSON shape the daemon's ``/api/move/play/recorded-move-dataset/..``
uses, so these files could in principle be uploaded to HF as a user's
personal move library.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload

logger = structlog.get_logger()


USER_MOVES_ROOT = Path("workspace") / "reachy" / "user_moves"
DEFAULT_LIBRARY = "user"
RECORD_HZ = 50
REPLAY_HZ = 50


@dataclass
class RecordingState:
    active: bool = False
    library: str = DEFAULT_LIBRARY
    name: str = ""
    description: str = ""
    started_at: Optional[datetime] = None
    frame_count: int = 0
    task: Optional[asyncio.Task] = None
    frames: list[dict] = field(default_factory=list)
    times: list[float] = field(default_factory=list)


class ReachyMoveRecorder:
    _instance: Optional["ReachyMoveRecorder"] = None

    def __init__(self) -> None:
        self._state = RecordingState()
        self._replay_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "ReachyMoveRecorder":
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
            "recording": s.active,
            "library": s.library,
            "name": s.name,
            "description": s.description,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "elapsed_s": elapsed,
            "frame_count": s.frame_count,
            "replaying": self._replay_task is not None and not self._replay_task.done(),
        }

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def start(self, *, library: str, name: str, description: str = "") -> dict:
        if not body_motion_allowed(surface="move_recorder:start").get("allowed"):
            return body_motion_locked_payload(surface="move_recorder:start")
        if self._state.active:
            return {"error": "recording_already_active", **self.status()}
        if not name.replace("_", "").replace("-", "").isalnum():
            return {"error": "invalid_name", "hint": "use [A-Za-z0-9_-]+"}

        from app.services.reachy_service import get_reachy_service

        svc = get_reachy_service()
        if not await svc.is_connected():
            return {"error": "robot_not_connected"}

        # Release torque so the user can move the head by hand. 'compliant' is
        # the daemon's standard name for this mode; fall back to 'disabled' if
        # the daemon is old.
        mode_res = await svc.set_motor_mode("compliant")
        if mode_res.get("error"):
            mode_res = await svc.set_motor_mode("disabled")
        if mode_res.get("error"):
            return {"error": "motor_release_failed", "detail": mode_res.get("error")}

        self._state = RecordingState(
            active=True,
            library=library or DEFAULT_LIBRARY,
            name=name,
            description=description,
            started_at=datetime.now(timezone.utc),
        )
        self._state.task = asyncio.create_task(self._poll_loop())
        logger.info("reachy_record_started", name=name, library=library)
        return self.status()

    async def _poll_loop(self) -> None:
        from app.services.reachy_service import get_reachy_service

        svc = get_reachy_service()
        interval = 1.0 / RECORD_HZ
        t0 = time.monotonic()
        try:
            while self._state.active:
                loop_start = time.monotonic()
                try:
                    snap = await svc.get_full_state()
                    if snap.get("error"):
                        await asyncio.sleep(interval)
                        continue
                    pose = snap.get("head_pose") or {}
                    antennas = snap.get("antenna_positions") or snap.get("antennas") or [0.0, 0.0]
                    body_yaw = snap.get("body_yaw", 0.0)
                    self._state.times.append(loop_start - t0)
                    self._state.frames.append({
                        "head": {
                            "x": pose.get("x", 0.0),
                            "y": pose.get("y", 0.0),
                            "z": pose.get("z", 0.0),
                            "roll": pose.get("roll", 0.0),
                            "pitch": pose.get("pitch", 0.0),
                            "yaw": pose.get("yaw", 0.0),
                        },
                        "antennas": list(antennas),
                        "body_yaw": float(body_yaw),
                        "check_collision": True,
                    })
                    self._state.frame_count += 1
                except Exception as e:
                    logger.debug("reachy_record_tick_failed", error=str(e))
                # Pace the loop
                dt = time.monotonic() - loop_start
                await asyncio.sleep(max(0.0, interval - dt))
        except asyncio.CancelledError:
            raise

    async def stop(self) -> dict:
        if not self._state.active:
            return {"error": "not_recording"}

        s = self._state
        s.active = False
        if s.task and not s.task.done():
            s.task.cancel()
            try:
                await s.task
            except (asyncio.CancelledError, Exception):
                pass
        s.task = None

        # Default to disabled after recording. Re-enabling torque has been the
        # most dangerous post-recording transition on unstable hardware.
        try:
            from app.services.reachy_service import get_reachy_service
            await get_reachy_service().set_motor_mode("disabled")
        except Exception as e:
            logger.debug("reachy_record_motor_disable_failed", error=str(e))

        # Persist
        library_dir = USER_MOVES_ROOT / s.library
        library_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "description": s.description or f"User-recorded move: {s.name}",
            "time": s.times,
            "set_target_data": s.frames,
            "recorded_at": s.started_at.isoformat() if s.started_at else None,
            "source": "zero_reachy_move_recorder",
            "frame_rate_hz": RECORD_HZ,
        }
        path = library_dir / f"{s.name}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        info = {
            **self.status(),
            "saved_to": str(path),
            "frames": len(s.frames),
            "duration_s": s.times[-1] if s.times else 0,
        }
        # Reset state but keep a snapshot in status()
        self._state = RecordingState(
            library=s.library,
            name=s.name,
            frame_count=0,
        )
        logger.info("reachy_record_saved", path=str(path), frames=len(s.frames))
        return info

    # ------------------------------------------------------------------
    # Library enumeration / deletion
    # ------------------------------------------------------------------

    def list_moves(self) -> list[dict]:
        if not USER_MOVES_ROOT.exists():
            return []
        out: list[dict] = []
        for library_dir in sorted(USER_MOVES_ROOT.iterdir()):
            if not library_dir.is_dir():
                continue
            for json_path in sorted(library_dir.glob("*.json")):
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                out.append({
                    "library": library_dir.name,
                    "name": json_path.stem,
                    "description": data.get("description", ""),
                    "duration_s": data.get("time", [0])[-1] if data.get("time") else 0,
                    "frame_count": len(data.get("set_target_data", [])),
                    "recorded_at": data.get("recorded_at"),
                })
        return out

    def delete_move(self, library: str, name: str) -> dict:
        path = USER_MOVES_ROOT / library / f"{name}.json"
        if not path.exists():
            return {"error": "not_found"}
        path.unlink()
        return {"deleted": str(path)}

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    async def play(self, library: str, name: str) -> dict:
        if not body_motion_allowed(surface=f"move_recorder:play:{library}/{name}").get("allowed"):
            return body_motion_locked_payload(surface=f"move_recorder:play:{library}/{name}")
        path = USER_MOVES_ROOT / library / f"{name}.json"
        if not path.exists():
            return {"error": "not_found", "path": str(path)}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"error": "parse_failed", "detail": str(e)}

        times = data.get("time", [])
        frames = data.get("set_target_data", [])
        if not frames:
            return {"error": "empty_recording"}

        if self._replay_task and not self._replay_task.done():
            self._replay_task.cancel()

        self._replay_task = asyncio.create_task(self._replay_loop(times, frames))
        return {"replaying": True, "frames": len(frames), "duration_s": times[-1] if times else 0}

    async def _replay_loop(self, times: list[float], frames: list[dict]) -> None:
        from app.services.reachy_service import get_reachy_service

        svc = get_reachy_service()
        # Downsample to REPLAY_HZ so we don't hammer the daemon with a 100 Hz
        # stream if the recording was captured at a higher rate.
        target_dt = 1.0 / REPLAY_HZ
        start = time.monotonic()
        last_sent = -math.inf
        try:
            for t, frame in zip(times, frames):
                if not body_motion_allowed(surface="move_recorder:replay_loop").get("allowed"):
                    logger.info("reachy_replay_blocked", reason="body_motion_locked")
                    return
                if time.monotonic() - last_sent < target_dt:
                    # still within a send window — sleep until the next frame time
                    pass
                wait_for = t - (time.monotonic() - start)
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                head = frame.get("head") or {}
                antennas = frame.get("antennas") or [0.0, 0.0]
                body_yaw = frame.get("body_yaw", 0.0)
                try:
                    await svc.set_target(
                        head_pose=head,
                        antennas=antennas,
                        body_yaw=body_yaw,
                    )
                    last_sent = time.monotonic()
                except Exception as e:
                    logger.debug("reachy_replay_tick_failed", error=str(e))
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("reachy_replay_crashed", error=str(e))


def get_reachy_move_recorder() -> ReachyMoveRecorder:
    return ReachyMoveRecorder.get_instance()
