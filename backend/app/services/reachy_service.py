"""
Reachy Mini robot integration service.

Async REST client for the Reachy Mini desktop daemon. The daemon is spawned
by the Pollen Robotics Reachy Mini Desktop App (Tauri + Python FastAPI
sidecar) and listens on :8000 by default. On a Docker host set
REACHY_API_URL=http://host.docker.internal:8000 so calls cross the bridge.

API surface mirrors the daemon's OpenAPI (v1.6.4 at time of writing):
  - /api/daemon/status                   daemon liveness + version
  - /api/state/full                      head pose, body yaw, antennas, doa
  - /api/state/doa                       direction of arrival only
  - /api/move/goto                       move head + antennas + body
  - /api/move/set_target                 continuous target stream
  - /api/move/stop                       cancel a move by uuid
  - /api/move/running                    whether a move is in flight
  - /api/move/play/wake_up               canned animation
  - /api/move/play/goto_sleep            canned animation
  - /api/media/sounds                    list uploaded sounds
  - /api/media/sounds/upload             upload a WAV
  - /api/media/sounds/{name}  [DELETE]   remove a sound
  - /api/media/play_sound                play uploaded sound by name
  - /api/media/stop_sound                stop current playback
  - /api/media/acquire | /api/media/release  exclusive media lock
  - /api/media/status                    available/released/no_media
  - /api/volume/current | /api/volume/set                speaker volume
  - /api/volume/microphone/current | /set                mic volume
  - /api/volume/test-sound               play built-in chime
  - /api/motors/status | /set_mode/{mode}                motor control
  - /api/camera/specs                    camera metadata (no capture endpoint)

The legacy `move_head`, `look_at`, `set_antennas`, `say`, etc. public methods
are preserved as convenience wrappers over the new endpoint set so existing
callers (routers, voice loop) continue to work.
"""

from __future__ import annotations

import asyncio
import io
import math
import os
import time
import uuid as uuid_mod
from collections import deque
from typing import Any, Deque, Iterable, Optional

import httpx
import structlog


# Ring buffer of the last N motions the robot played. Populated by
# play_emotion / play_dance / play_motion so the UI can show a "recent
# activity" strip without us having to persist anything. Ephemeral on
# purpose — clears on process restart.
_RECENT_MOTION_CAP = 20
_recent_motions: Deque[dict] = deque(maxlen=_RECENT_MOTION_CAP)
# Daemon request concurrency: previously 8, which let head-tracking +
# voice-gesture wobbler + look_at + dance fire-and-forget all 4 hit the
# daemon's motion queue simultaneously and back it up — visible as jitter,
# and on weak actuators (stewart_3) as overload. Serialize at the Zero
# boundary so the daemon's motor controller smoothly blends one move at a
# time. Bump back up via env var only if you measure a real latency gap.
_DAEMON_REQUEST_CONCURRENCY = max(1, int(os.getenv("ZERO_REACHY_DAEMON_REQUEST_CONCURRENCY", "1")))
_DAEMON_MAX_CONNECTIONS = max(
    _DAEMON_REQUEST_CONCURRENCY + 4,
    int(os.getenv("ZERO_REACHY_DAEMON_MAX_CONNECTIONS", "16")),
)
_daemon_request_semaphore = asyncio.Semaphore(_DAEMON_REQUEST_CONCURRENCY)

NEUTRAL_HEAD_POSE: dict[str, float] = {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0,
    "roll": 0.0,
    "pitch": 0.0,
    "yaw": 0.0,
}
NEUTRAL_ANTENNAS: tuple[float, float] = (0.0, 0.0)


def _record_motion(name: str, kind: str, source: str = "direct") -> None:
    _recent_motions.appendleft(
        {
            "name": name,
            "kind": kind,
            "source": source,
            "ts": time.time(),
        }
    )


def get_recent_motions(limit: int = 10) -> list[dict]:
    return list(_recent_motions)[: max(1, min(limit, _RECENT_MOTION_CAP))]


def _extract_running_move_uuids(value: Any) -> list[str]:
    """Collect daemon move UUIDs from the shapes returned by /api/move/running."""
    found: list[str] = []

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            if node and node not in found:
                found.append(node)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            for key in ("uuid", "id", "move_uuid"):
                val = node.get(key)
                if isinstance(val, str) and val and val not in found:
                    found.append(val)
            for key in ("running", "moves", "active", "items", "value"):
                if key in node:
                    _walk(node.get(key))

    _walk(value)
    return found


def _looks_like_robot_state(value: dict) -> bool:
    if not isinstance(value, dict) or value.get("error"):
        return False
    return any(
        key in value
        for key in (
            "head_pose",
            "body_yaw",
            "antenna_positions",
            "antennas_position",
            "control_mode",
            "doa",
        )
    )


def _looks_like_daemon_status(value: dict) -> bool:
    if not isinstance(value, dict) or value.get("error") or value.get("connected") is False:
        return False
    return any(
        key in value
        for key in (
            "backend_status",
            "state",
            "type",
            "version",
        )
    )

from app.services.reachy_motion_library import (
    ALL_CLIPS,
    DANCE_CLIPS,
    DANCES_DATASET,
    EMOTION_CLIPS,
    EMOTIONS_DATASET,
    EMOTIONS_DATASET_FALLBACKS,
    MotionClip,
    MotionKind,
    get_clip,
    resolve_motion,
)
from app.services.tts_service import get_tts_service

logger = structlog.get_logger()

DEFAULT_REACHY_URL = "http://localhost:8000"

# Legacy shape kept for backward compatibility with callers that imported
# EMOTION_MOVES directly (routers, voice loop). New code should use the
# catalog in reachy_motion_library.
EMOTION_MOVES: dict[str, tuple[str, str]] = {
    clip.name: (clip.dataset, clip.name) for clip in EMOTION_CLIPS
}


class ReachyService:
    """Async REST client for the Reachy Mini daemon."""

    _instance: Optional["ReachyService"] = None

    def __init__(self) -> None:
        # Honor ZERO_REACHY_API_URL (docker-compose env with Settings env_prefix),
        # REACHY_API_URL (legacy / non-containerized), then the default.
        self._base_url = (
            os.getenv("ZERO_REACHY_API_URL")
            or os.getenv("REACHY_API_URL")
            or DEFAULT_REACHY_URL
        ).rstrip("/")
        self._host_agent_url = (
            os.getenv("ZERO_HOST_AGENT_URL")
            or os.getenv("HOST_AGENT_URL")
            or "http://host.docker.internal:18796"
        ).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._active_move_uuid: Optional[str] = None
        self._tts_sound_prefix = "zero_tts_"
        self._daemon_status_cache: dict[str, Any] | None = None
        self._daemon_status_cache_at = 0.0
        self._daemon_status_cache_ttl_s = max(
            0.0,
            float(os.getenv("ZERO_REACHY_DAEMON_STATUS_CACHE_SECONDS", "1.0")),
        )

    @classmethod
    def get_instance(cls) -> "ReachyService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(
                    max_connections=_DAEMON_MAX_CONNECTIONS,
                    max_keepalive_connections=0,
                ),
                headers={"Connection": "close"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Low-level request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        timeout: float = 10.0,
        quiet: bool = False,
    ) -> dict:
        """
        Make a request to the daemon with graceful error handling. Returns the
        parsed JSON body on success, or a dict carrying an `error` key when the
        robot is unreachable or the request fails.
        """
        url = f"{self._base_url}{path}"
        try:
            client = self._get_client()
            request = client.request(
                method,
                url,
                json=json,
                params=params,
                files=files,
                data=data,
                timeout=httpx.Timeout(
                    timeout,
                    connect=min(timeout, 2.0),
                    pool=min(timeout, 0.75),
                ),
            )
            async with _daemon_request_semaphore:
                resp = await request
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return {"ok": True, "content_type": resp.headers.get("content-type")}
        except httpx.ConnectError:
            if quiet:
                logger.debug("reachy_connection_failed", url=url)
            else:
                logger.warning("reachy_connection_failed", url=url)
            return {"error": "Robot not connected", "connected": False}
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            log = logger.debug if quiet else logger.warning
            log("reachy_request_failed", url=url, status=e.response.status_code, body=body)
            return {
                "error": f"Request failed: {e.response.status_code}",
                "status": e.response.status_code,
                "detail": body,
                "connected": True,
            }
        except Exception as e:
            log = logger.debug if quiet else logger.error
            error = str(e) or type(e).__name__
            log("reachy_request_error", url=url, error=error, error_type=type(e).__name__)
            return {"error": error, "connected": False}

    async def _host_agent_request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = 2.0,
        quiet: bool = True,
    ) -> dict:
        """Short, isolated call to host_agent for supervisor-only fallbacks."""
        if not self._host_agent_url:
            return {"error": "host_agent not configured", "connected": False}
        url = f"{self._host_agent_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                headers={"Connection": "close"},
            ) as client:
                resp = await client.request(method, url)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return {"ok": True, "content_type": resp.headers.get("content-type")}
        except Exception as e:
            log = logger.debug if quiet else logger.warning
            error = str(e) or type(e).__name__
            log("reachy_host_agent_request_error", url=url, error=error, error_type=type(e).__name__)
            return {"error": error, "connected": False}

    # ------------------------------------------------------------------
    # Connection / status
    # ------------------------------------------------------------------

    async def is_connected(self) -> bool:
        """True iff the daemon is running and the robot state API responds."""
        state = await self.get_full_state(timeout=3.0)
        return _looks_like_robot_state(state)

    async def get_daemon_status(
        self,
        *,
        timeout: float = 1.0,
        supervisor_timeout: float = 0.75,
        quiet: bool = False,
    ) -> dict:
        """Raw /api/daemon/status body (version, state, backend_status, etc.)."""
        if self._daemon_status_cache and self._daemon_status_cache_ttl_s > 0:
            age = time.monotonic() - self._daemon_status_cache_at
            if age <= self._daemon_status_cache_ttl_s:
                cached = dict(self._daemon_status_cache)
                cached["cached_recent"] = True
                cached["cache_age_seconds"] = round(age, 3)
                return cached

        direct = await self._request("GET", "/api/daemon/status", timeout=timeout, quiet=quiet)
        if _looks_like_daemon_status(direct):
            payload = {
                **direct,
                "via": direct.get("via") or "direct",
                "daemon_route": "direct",
                "daemon_direct_reachable": True,
                "status_stale": False,
            }
            self._daemon_status_cache = dict(payload)
            self._daemon_status_cache_at = time.monotonic()
            return payload

        supervisor = await self._host_agent_request(
            "GET",
            "/daemon/status",
            timeout=supervisor_timeout,
            quiet=quiet,
        )
        if supervisor.get("running"):
            backend_status = direct.get("backend_status") if isinstance(direct, dict) else None
            if not isinstance(backend_status, dict):
                backend_status = {
                    "ready": None,
                    "motor_control_mode": None,
                    "detail": (
                        "Daemon process is running under host_agent; direct "
                        "status route is retrying."
                    ),
                }
            payload = {
                "type": "daemon_status",
                "state": "running",
                "connected": True,
                "via": "host_agent_supervisor",
                "daemon_route": "host_agent_supervisor",
                "daemon_direct_reachable": False,
                "status_stale": True,
                "direct_error": direct.get("error") if isinstance(direct, dict) else None,
                "supervisor": supervisor,
                "backend_status": backend_status,
            }
            self._daemon_status_cache = dict(payload)
            self._daemon_status_cache_at = time.monotonic()
            return payload
        return {
            **(direct if isinstance(direct, dict) else {}),
            "connected": False,
            "via": "direct_error",
            "daemon_route": "direct",
            "daemon_direct_reachable": False,
            "status_stale": True,
        }

    async def health_check(self) -> dict:
        return await self._request("POST", "/health-check", timeout=3.0)

    async def get_full_state(
        self,
        *,
        with_head_pose: bool = True,
        with_body_yaw: bool = True,
        with_antenna_positions: bool = True,
        with_doa: bool = True,
        with_head_joints: bool = False,
        with_target_head_pose: bool = False,
        use_pose_matrix: bool = False,
        timeout: float = 10.0,
        quiet: bool = False,
    ) -> dict:
        params = {
            "with_head_pose": with_head_pose,
            "with_body_yaw": with_body_yaw,
            "with_antenna_positions": with_antenna_positions,
            "with_doa": with_doa,
            "with_head_joints": with_head_joints,
            "with_target_head_pose": with_target_head_pose,
            "use_pose_matrix": use_pose_matrix,
        }
        return await self._request("GET", "/api/state/full", params=params, timeout=timeout, quiet=quiet)

    async def get_doa(self) -> dict:
        """Direction-of-arrival: {angle: float (radians), speech_detected: bool}."""
        return await self._request("GET", "/api/state/doa", timeout=3.0)

    # legacy alias
    async def get_audio_direction(self) -> dict:
        return await self.get_doa()

    def get_status_info(self) -> dict:
        """Static config info (does not contact the robot)."""
        return {"base_url": self._base_url, "host_agent_url": self._host_agent_url}

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    async def goto(
        self,
        *,
        head_pose: Optional[dict] = None,
        antennas: Optional[Iterable[float]] = None,
        body_yaw: Optional[float] = None,
        duration: float = 1.0,
        interpolation: Optional[str] = None,
    ) -> dict:
        """
        POST /api/move/goto.

        Args:
            head_pose: {x, y, z, roll, pitch, yaw} in the XYZRPY convention.
                       Angles in radians per daemon convention.
            antennas: 2-tuple of (left_angle_rad, right_angle_rad).
            body_yaw: body rotation in radians.
            duration: seconds.
            interpolation: optional InterpolationTechnique string.
        """
        payload: dict[str, Any] = {"duration": duration}
        if head_pose is not None:
            payload["head_pose"] = head_pose
        if antennas is not None:
            antennas_list = list(antennas)
            if len(antennas_list) != 2:
                raise ValueError("antennas must be a 2-element iterable")
            payload["antennas"] = antennas_list
        if body_yaw is not None:
            payload["body_yaw"] = body_yaw
        if interpolation:
            payload["interpolation"] = interpolation
        res = await self._request("POST", "/api/move/goto", json=payload)
        if "uuid" in res:
            self._active_move_uuid = res["uuid"]
        return res

    async def set_target(
        self,
        *,
        head_pose: Optional[dict] = None,
        antennas: Optional[Iterable[float]] = None,
        body_yaw: Optional[float] = None,
        timeout: float = 10.0,
    ) -> dict:
        """POST /api/move/set_target (continuous target, no duration)."""
        payload: dict[str, Any] = {}
        if head_pose is not None:
            payload["head_pose"] = head_pose
        if antennas is not None:
            payload["antennas"] = list(antennas)
        if body_yaw is not None:
            payload["body_yaw"] = body_yaw
        return await self._request("POST", "/api/move/set_target", json=payload, timeout=timeout)

    async def stop_move(self, move_uuid: Optional[str] = None) -> dict:
        """POST /api/move/stop."""
        move_uuid = move_uuid or self._active_move_uuid
        if not move_uuid:
            return {"ok": True, "stopped": False, "detail": "No active daemon move uuid to stop."}
        result = await self._request("POST", "/api/move/stop", json={"uuid": move_uuid})
        detail = f"{result.get('detail', '')} {result.get('error', '')}".lower()
        stale_uuid = (
            result.get("status") in {404, 500}
            and "not found" in detail
            and "move" in detail
        )
        if stale_uuid:
            if move_uuid == self._active_move_uuid:
                self._active_move_uuid = None
            return {
                "ok": True,
                "stopped": False,
                "stale_uuid": True,
                "uuid": move_uuid,
                "detail": "Daemon had already finished or forgotten that move.",
                "daemon": result,
            }
        if "error" not in result and move_uuid == self._active_move_uuid:
            self._active_move_uuid = None
        return result

    async def stop_all_moves(self) -> dict:
        """Best-effort cancel for every daemon-reported motion source."""
        running = await self.is_moving()
        uuids = _extract_running_move_uuids(running)

        # The daemon is the source of truth for active moves. ``_active_move_uuid``
        # often points at a short neutral/goto move that already completed, and
        # trying to stop that stale UUID produces a scary 500 even though the
        # robot is still. Only fall back to the local UUID when the running-move
        # probe itself failed.
        running_probe_failed = isinstance(running, dict) and bool(running.get("error"))
        if running_probe_failed and self._active_move_uuid and self._active_move_uuid not in uuids:
            uuids.append(self._active_move_uuid)

        stops: list[dict[str, Any]] = []
        for uuid in uuids:
            res = await self.stop_move(uuid)
            stops.append({"uuid": uuid, "ok": "error" not in res, "result": res})

        if not uuids:
            self._active_move_uuid = None
            return {
                "ok": True,
                "running": running,
                "uuids": [],
                "stops": [],
                "detail": "No daemon move was running.",
            }

        ok = all(stop.get("ok") for stop in stops)
        if ok:
            self._active_move_uuid = None
        return {"ok": ok, "running": running, "uuids": uuids, "stops": stops}

    async def is_moving(self) -> dict:
        return await self._request("GET", "/api/move/running")

    async def settle_neutral(self, *, duration: float = 1.0) -> dict:
        """Move to a calm neutral posture without playing a canned animation."""
        return await self.goto(
            head_pose=dict(NEUTRAL_HEAD_POSE),
            antennas=NEUTRAL_ANTENNAS,
            body_yaw=0.0,
            duration=duration,
        )

    async def wake_up(self) -> dict:
        return await self._request("POST", "/api/move/play/wake_up")

    async def goto_sleep(self) -> dict:
        return await self._request("POST", "/api/move/play/goto_sleep")

    async def play_recorded_move(self, dataset: str, move_name: str) -> dict:
        return await self._request(
            "POST",
            f"/api/move/play/recorded-move-dataset/{dataset}/{move_name}",
        )

    # --- Convenience wrappers (preserved API for existing callers) ---

    async def move_head(
        self,
        *,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        duration: float = 1.0,
    ) -> dict:
        """Move head to a target orientation. Angles in degrees (converted)."""
        state = await self.get_full_state(
            with_body_yaw=False,
            with_antenna_positions=False,
            with_doa=False,
            timeout=2.0,
            quiet=True,
        )
        current_pose = state.get("head_pose") if isinstance(state, dict) else None
        current_pose = current_pose if isinstance(current_pose, dict) else {}
        head_pose = {
            "x": float(current_pose.get("x", 0.0) or 0.0),
            "y": float(current_pose.get("y", 0.0) or 0.0),
            "z": float(current_pose.get("z", 0.0) or 0.0),
            "roll": math.radians(roll),
            "pitch": math.radians(pitch),
            "yaw": math.radians(yaw),
        }
        return await self.goto(head_pose=head_pose, duration=duration)

    async def look_at(
        self,
        *,
        x: float,
        y: float,
        z: float,
        duration: float = 1.0,
    ) -> dict:
        """
        Aim the head at a 3D point. Computes yaw (horizontal) and pitch
        (vertical) from the target relative to the robot's head origin.
        """
        yaw = math.atan2(y, x)
        pitch = -math.atan2(z, math.sqrt(x * x + y * y))
        head_pose = {
            "x": 0.0, "y": 0.0, "z": 0.0,
            "roll": 0.0, "pitch": pitch, "yaw": yaw,
        }
        return await self.goto(head_pose=head_pose, duration=duration)

    async def set_antennas(
        self,
        *,
        left_angle: float = 0.0,
        right_angle: float = 0.0,
        duration: float = 0.5,
    ) -> dict:
        """Set antenna positions in degrees (converted to radians)."""
        return await self.goto(
            antennas=(math.radians(left_angle), math.radians(right_angle)),
            duration=duration,
        )

    async def _play_clip_with_fallback(
        self, clip: MotionClip, *, extra_datasets: Iterable[str] = ()
    ) -> dict:
        """
        Try the clip's dataset first, then any fallback dataset names. Returns
        the last response so the caller sees the real error when nothing works.
        """
        tried = [clip.dataset, *extra_datasets]
        last: dict = {}
        for dataset in tried:
            last = await self.play_recorded_move(dataset, clip.name)
            # daemon returns {"error": "..."} on 4xx/5xx or transport failures
            if not last.get("error"):
                return {**last, "clip": clip.name, "dataset": dataset, "kind": clip.kind}
            status = last.get("status")
            # 404 means wrong dataset name — try the next fallback.
            if status and status != 404:
                break
        return {
            **last,
            "clip": clip.name,
            "dataset_tried": tried,
            "kind": clip.kind,
        }

    async def _maybe_play_sequence(self, name: str) -> Optional[dict]:
        """If `name` matches a user-defined sequence, play it and return the
        result. Returns None when no sequence matches (caller falls back to
        hardcoded clip resolution)."""
        try:
            # Imported lazily to avoid a circular import (sequence service ->
            # reachy_service via playback).
            from app.services.reachy_sequence_service import (
                get_reachy_sequence_service,
            )
            svc = get_reachy_sequence_service()
            match = await svc.resolve(name)
            if not match:
                return None
            result = await svc.play_sequence(match["id"], reachy_service=self)
            return {**result, "is_sequence": True}
        except Exception as e:
            # Never let sequence resolution failures break the hardcoded path.
            logger.warning("sequence_resolve_failed", name=name, error=str(e))
            return None

    async def play_emotion(self, emotion: str) -> dict:
        """
        Play a canned emotion animation. Accepts canonical names (``cheerful1``),
        aliases (``happy``), or free-form LLM tags (``thank you``). Returns a
        descriptive error + the list of known emotions if resolution fails.

        User-defined sequences share the same namespace — a sequence named
        ``happy_greeting`` (or with that alias) is played in full when the
        caller passes it here.
        """
        seq_result = await self._maybe_play_sequence(emotion)
        if seq_result is not None:
            _record_motion(emotion, "sequence")
            return seq_result
        clip = resolve_motion(emotion, kind="emotion")
        if not clip:
            return {
                "error": f"unknown emotion: {emotion}",
                "known": [c.name for c in EMOTION_CLIPS],
            }
        _record_motion(clip.name, "emotion")
        return await self._play_clip_with_fallback(
            clip, extra_datasets=EMOTIONS_DATASET_FALLBACKS
        )

    async def play_dance(self, dance: str) -> dict:
        """Play a canned dance move from the dances library (or a matching sequence)."""
        seq_result = await self._maybe_play_sequence(dance)
        if seq_result is not None:
            _record_motion(dance, "sequence")
            return seq_result
        clip = resolve_motion(dance, kind="dance")
        if not clip:
            return {
                "error": f"unknown dance: {dance}",
                "known": [c.name for c in DANCE_CLIPS],
            }
        _record_motion(clip.name, "dance")
        return await self._play_clip_with_fallback(clip)

    async def play_motion(self, name: str, *, kind: Optional[MotionKind] = None) -> dict:
        """
        Play any clip (emotion or dance) by name or alias. Sequences share the
        same namespace. Caller may constrain `kind` to force one library; that
        constraint only applies to the hardcoded clip fallback.
        """
        seq_result = await self._maybe_play_sequence(name)
        if seq_result is not None:
            _record_motion(name, "sequence")
            return seq_result
        clip = resolve_motion(name, kind=kind) if kind else resolve_motion(name)
        if not clip:
            return {"error": f"unknown motion: {name}"}
        extras = EMOTIONS_DATASET_FALLBACKS if clip.kind == "emotion" else ()
        _record_motion(clip.name, clip.kind)
        return await self._play_clip_with_fallback(clip, extra_datasets=extras)

    # ------------------------------------------------------------------
    # Media / audio output
    # ------------------------------------------------------------------

    async def acquire_media(self) -> dict:
        return await self._request("POST", "/api/media/acquire")

    async def release_media(self) -> dict:
        return await self._request("POST", "/api/media/release")

    async def media_status(self) -> dict:
        return await self._request("GET", "/api/media/status")

    async def list_sounds(self) -> dict:
        return await self._request("GET", "/api/media/sounds")

    async def upload_sound(self, filename: str, audio_bytes: bytes) -> dict:
        """Upload a WAV file to the daemon's sound library."""
        files = {"file": (filename, io.BytesIO(audio_bytes), "audio/wav")}
        return await self._request(
            "POST",
            "/api/media/sounds/upload",
            files=files,
            timeout=30.0,
        )

    async def delete_sound(self, filename: str) -> dict:
        return await self._request("DELETE", f"/api/media/sounds/{filename}")

    async def play_sound(self, filename: str) -> dict:
        return await self._request(
            "POST",
            "/api/media/play_sound",
            json={"file": filename},
        )

    async def stop_sound(self) -> dict:
        return await self._request("POST", "/api/media/stop_sound")

    async def test_sound(self) -> dict:
        """Play the daemon's built-in test chime (no upload required)."""
        return await self._request("POST", "/api/volume/test-sound")

    async def get_volume(self) -> dict:
        return await self._request("GET", "/api/volume/current")

    async def set_volume(self, volume: int) -> dict:
        volume = max(0, min(100, int(volume)))
        return await self._request("POST", "/api/volume/set", json={"volume": volume})

    async def get_mic_volume(self) -> dict:
        return await self._request("GET", "/api/volume/microphone/current")

    async def set_mic_volume(self, volume: int) -> dict:
        volume = max(0, min(100, int(volume)))
        return await self._request(
            "POST",
            "/api/volume/microphone/set",
            json={"volume": volume},
        )

    # ------------------------------------------------------------------
    # High-level: synthesize + play + cleanup
    # ------------------------------------------------------------------

    async def play_audio_bytes(
        self,
        audio_bytes: bytes,
        *,
        cleanup: bool = True,
        label: str = "audio",
    ) -> dict:
        """
        Upload already-synthesized WAV bytes to the daemon and play them on
        Reachy's speaker. Skips the TTS step — use this when the caller has
        the audio in hand already (e.g. the voice loop or persona preview)
        to avoid double-synthesizing.
        """
        if not audio_bytes:
            return {"error": "no audio bytes", "label": label}
        filename = f"{self._tts_sound_prefix}{uuid_mod.uuid4().hex[:12]}.wav"
        upload_res = await self.upload_sound(filename, audio_bytes)
        if upload_res.get("error"):
            return {"error": upload_res.get("error"), "label": label, "stage": "upload"}
        play_res = await self.play_sound(filename)
        if play_res.get("error"):
            if cleanup:
                asyncio.create_task(self._deferred_delete(filename, delay_s=1.0))
            return {"error": play_res.get("error"), "label": label, "stage": "play"}
        if cleanup:
            # Best-effort cleanup. Heuristic based on audio size (16 kHz mono
            # 16-bit → 32 kB/s). Clamp [2, 30] s.
            approx_seconds = len(audio_bytes) / 32_000.0
            delay = max(2.0, min(30.0, approx_seconds + 1.0))
            asyncio.create_task(self._deferred_delete(filename, delay_s=delay))
        return {"label": label, "file": filename, "audio_size": len(audio_bytes)}

    async def say(
        self,
        text: str,
        *,
        cleanup: bool = True,
        voice_override: Optional[str] = None,
    ) -> dict:
        """
        Speak `text` through the Reachy speaker.

        Pipeline: TTSService.synthesize -> upload WAV -> play_sound.
        If `cleanup` is true, the uploaded sound is deleted in the background
        after a short delay so the daemon's sound library does not bloat.
        `voice_override` forces an edge-tts voice for this utterance only
        (e.g. switching to a different voice when reading email content).
        """
        try:
            tts = get_tts_service()
            audio_bytes = await tts.synthesize(text, voice_override=voice_override)
        except RuntimeError as e:
            logger.warning("reachy_say_tts_failed", error=str(e))
            return {"error": f"tts failed: {e}", "text": text}

        filename = f"{self._tts_sound_prefix}{uuid_mod.uuid4().hex[:12]}.wav"
        upload_res = await self.upload_sound(filename, audio_bytes)
        if upload_res.get("error"):
            return {"error": upload_res.get("error"), "text": text, "stage": "upload"}

        play_res = await self.play_sound(filename)
        if play_res.get("error"):
            if cleanup:
                asyncio.create_task(self._deferred_delete(filename, delay_s=1.0))
            return {"error": play_res.get("error"), "text": text, "stage": "play"}

        if cleanup:
            # Let the sound finish playing before we delete. Rough heuristic:
            # 0.12s per character, clamped to [2, 30] seconds. The daemon does
            # not tell us playback duration, so this is a best-effort cleanup.
            delay = max(2.0, min(30.0, 0.12 * len(text) + 1.0))
            asyncio.create_task(self._deferred_delete(filename, delay_s=delay))

        return {"text": text, "file": filename, "audio_size": len(audio_bytes)}

    async def _deferred_delete(self, filename: str, *, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            await self.delete_sound(filename)
        except Exception as e:
            logger.debug("reachy_deferred_delete_failed", filename=filename, error=str(e))

    # ------------------------------------------------------------------
    # Motors
    # ------------------------------------------------------------------

    async def get_motor_status(self) -> dict:
        return await self._request("GET", "/api/motors/status")

    async def set_motor_mode(self, mode: str) -> dict:
        """mode is one of MotorControlMode values (e.g. 'enabled', 'disabled')."""
        return await self._request("POST", f"/api/motors/set_mode/{mode}")

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------
    #
    # The daemon itself only exposes /api/camera/specs. Live frames are
    # captured by the host_agent (on the Windows host), which
    # owns the USB device via OpenCV. Zero proxies the MJPEG stream and the
    # single-frame endpoint through its own API so browsers see a same-origin
    # URL — see backend/app/routers/reachy.py for the proxy routes.

    async def get_camera_specs(self) -> dict:
        return await self._request("GET", "/api/camera/specs")

    def get_stream_url(self, *, fmt: str = "mjpeg") -> str:
        """Browser-facing URL for the live camera feed (served by Zero, proxied to host_agent)."""
        if fmt == "mjpeg":
            return "/api/reachy/camera/mjpeg"
        if fmt == "frame":
            return "/api/reachy/camera/frame.jpg"
        # Back-compat: callers that passed "webrtc" still get something usable.
        return "/api/reachy/camera/mjpeg"

    async def capture_image(self) -> bytes:
        """
        Fetch a single JPEG from the host_agent camera worker.
        Returns empty bytes if the host_agent / camera is unavailable so
        callers can fail gracefully (checked via `len(...) == 0`).
        """
        from app.infrastructure.config import get_settings

        settings = get_settings()
        host_agent = (getattr(settings, "host_agent_url", None) or "").rstrip("/")
        if not host_agent:
            host_agent = os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18796").rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{host_agent}/camera/frame.jpg")
            if resp.status_code == 200:
                return resp.content
            logger.info(
                "reachy_capture_image_host_agent_status",
                status=resp.status_code,
                host_agent=host_agent,
            )
        except Exception as e:
            logger.info("reachy_capture_image_host_agent_unreachable", error=str(e), host_agent=host_agent)
        return b""


def get_reachy_service() -> ReachyService:
    return ReachyService.get_instance()
