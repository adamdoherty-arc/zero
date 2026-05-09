"""
Reachy face tracking controller.

The realtime ``head_tracking`` tool used to return success without starting
any motion. This service owns the real loop: read the active Reachy camera
frame, detect a face, and send small bounded head pose adjustments.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class HeadTrackingConfig:
    # Smooth tracking: 6.7 Hz update rate (was 1.3 Hz). Combined with the
    # 5-frame EMA below this gives continuous-looking head motion instead of
    # the prior step-then-pause cadence.
    interval_s: float = 0.15
    face_deadzone: float = 0.05
    yaw_gain_deg: float = 14.0
    pitch_gain_deg: float = 10.0
    max_step_yaw_deg: float = 3.0
    max_step_pitch_deg: float = 2.5
    min_move_delta_deg: float = 0.3
    min_face_width: float = 0.05
    min_face_height: float = 0.065
    min_face_area: float = 0.004
    # Move duration matches the cycle so successive goto calls overlap
    # smoothly without queueing on the daemon.
    duration_s: float = 0.18
    yaw_limit_deg: float = 75.0
    pitch_up_limit_deg: float = -30.0
    pitch_down_limit_deg: float = 35.0
    ema_window: int = 5


class ReachyHeadTrackingService:
    _instance: Optional["ReachyHeadTrackingService"] = None

    def __init__(self) -> None:
        self._config = HeadTrackingConfig()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._enabled_at: float | None = None
        self._iterations = 0
        self._detections = 0
        self._moves = 0
        self._last_detection: dict[str, Any] | None = None
        self._last_move: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_scan_at: float | None = None
        self._last_move_at: float | None = None
        self._face_xy_history: Deque[tuple[float, float]] = deque(
            maxlen=max(1, self._config.ema_window)
        )

    @classmethod
    def get_instance(cls) -> "ReachyHeadTrackingService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            self._enabled_at = self._enabled_at or time.time()
            first = await self._scan_once()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="reachy-head-tracking")
            return self.status(extra={"first_scan": first})

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            task = self._task
            self._task = None
            self._enabled_at = None
            self._face_xy_history.clear()
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return self.status(extra={"stopped": True})

    def status(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        running = bool(self._task and not self._task.done())
        face_visible = self._last_detection is not None and self._last_error is None
        moving_recently = bool(self._last_move_at and (time.time() - self._last_move_at) <= 3.0)
        state = (
            "tracking"
            if running and face_visible and moving_recently
            else "centered"
            if running and face_visible
            else "scanning"
            if running
            else "stopped"
        )
        detail = (
            "Following the detected face."
            if state == "tracking"
            else "Face is centered; no head move needed."
            if state == "centered"
            else self._last_error
            or "Scanning for a face in the Reachy camera frame."
            if state == "scanning"
            else "Head tracking is stopped."
        )
        payload: dict[str, Any] = {
            "running": running,
            "state": state,
            "detail": detail,
            "enabled_at": self._enabled_at,
            "iterations": self._iterations,
            "detections": self._detections,
            "moves": self._moves,
            "last_scan_at": self._last_scan_at,
            "last_move_at": self._last_move_at,
            "last_detection": self._last_detection,
            "last_move": self._last_move,
            "last_error": self._last_error,
        }
        if extra:
            payload.update(extra)
        return payload

    async def step(self) -> dict[str, Any]:
        return await self._scan_once()

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._config.interval_s)
                async with self._lock:
                    await self._scan_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("reachy_head_tracking_loop_failed")

    async def _scan_once(self) -> dict[str, Any]:
        self._iterations += 1
        self._last_scan_at = time.time()
        try:
            from app.services.reachy_service import get_reachy_service
            from app.services.reachy_vision_service import get_reachy_vision_service

            vision = get_reachy_vision_service()
            analysis = await vision.analyze_latest(kind="face", provider_id="reachy")
            detections = [
                item
                for item in analysis.get("detections") or []
                if isinstance(item, dict) and item.get("kind") == "face"
            ]
            detections = [item for item in detections if self._is_usable_face(item)]
            if not detections:
                reason = analysis.get("reason") or "No usable face detected in the current Reachy camera frame."
                self._last_error = str(reason)
                self._last_detection = None
                return {
                    "ok": False,
                    "state": "scanning",
                    "detail": self._last_error,
                    "analysis": analysis,
                }

            face = max(detections, key=lambda item: float(item.get("width", 0.0)) * float(item.get("height", 0.0)))
            self._detections += 1
            self._last_detection = face
            self._last_error = None

            raw_x = float(face.get("x", 0.5))
            raw_y = float(face.get("y", 0.5))
            self._face_xy_history.append((raw_x, raw_y))
            n = len(self._face_xy_history)
            if n > 0:
                smoothed_x = sum(p[0] for p in self._face_xy_history) / n
                smoothed_y = sum(p[1] for p in self._face_xy_history) / n
                face = {
                    **face,
                    "x": smoothed_x,
                    "y": smoothed_y,
                    "raw_x": raw_x,
                    "raw_y": raw_y,
                    "ema_n": n,
                }

            svc = get_reachy_service()
            state = await svc.get_full_state(
                with_doa=False,
                with_head_joints=False,
                timeout=2.0,
                quiet=True,
            )
            pose = state.get("head_pose") if isinstance(state, dict) else None
            if not isinstance(pose, dict):
                self._last_error = "Face detected, but Reachy head pose is unavailable."
                return {"ok": False, "state": "blocked", "detail": self._last_error, "detection": face}

            x = float(face.get("x", 0.5))
            y = float(face.get("y", 0.5))
            error_x = x - 0.5
            error_y = y - 0.5
            if abs(error_x) < self._config.face_deadzone and abs(error_y) < self._config.face_deadzone:
                return {"ok": True, "state": "centered", "detail": "Face is already centered.", "detection": face}

            current_yaw = float(pose.get("yaw", 0.0) or 0.0)
            current_pitch = float(pose.get("pitch", 0.0) or 0.0)
            yaw_step = -self._clamp(error_x * self._config.yaw_gain_deg, self._config.max_step_yaw_deg)
            pitch_step = self._clamp(error_y * self._config.pitch_gain_deg, self._config.max_step_pitch_deg)
            if abs(yaw_step) < self._config.min_move_delta_deg and abs(pitch_step) < self._config.min_move_delta_deg:
                return {"ok": True, "state": "centered", "detail": "Face offset is below movement threshold.", "detection": face}

            target_yaw = self._clamp(
                math.degrees(current_yaw) + yaw_step,
                self._config.yaw_limit_deg,
            )
            target_pitch = max(
                self._config.pitch_up_limit_deg,
                min(self._config.pitch_down_limit_deg, math.degrees(current_pitch) + pitch_step),
            )
            head_pose = {
                "x": float(pose.get("x", 0.0) or 0.0),
                "y": float(pose.get("y", 0.0) or 0.0),
                "z": float(pose.get("z", 0.0) or 0.0),
                "roll": float(pose.get("roll", 0.0) or 0.0),
                "pitch": math.radians(target_pitch),
                "yaw": math.radians(target_yaw),
            }
            move = await svc.goto(head_pose=head_pose, duration=self._config.duration_s)
            if move.get("error"):
                self._last_error = str(move.get("error"))
                return {"ok": False, "state": "move_failed", "detail": self._last_error, "detection": face, "move": move}

            self._moves += 1
            self._last_move_at = time.time()
            self._last_move = {
                "yaw_step_deg": yaw_step,
                "pitch_step_deg": pitch_step,
                "target_yaw_deg": target_yaw,
                "target_pitch_deg": target_pitch,
                "result": move,
            }
            return {"ok": True, "state": "tracking", "detail": "Moved toward detected face.", "detection": face, "move": self._last_move}
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("reachy_head_tracking_scan_failed")
            return {"ok": False, "state": "error", "detail": self._last_error}

    @staticmethod
    def _clamp(value: float, limit: float) -> float:
        return max(-limit, min(limit, value))

    def _is_usable_face(self, detection: dict[str, Any]) -> bool:
        width = float(detection.get("width", 0.0) or 0.0)
        height = float(detection.get("height", 0.0) or 0.0)
        return (
            width >= self._config.min_face_width
            and height >= self._config.min_face_height
            and (width * height) >= self._config.min_face_area
        )


def get_reachy_head_tracking_service() -> ReachyHeadTrackingService:
    return ReachyHeadTrackingService.get_instance()
