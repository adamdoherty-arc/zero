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
        self._client: Optional[httpx.AsyncClient] = None
        self._active_move_uuid: Optional[str] = None
        self._tts_sound_prefix = "zero_tts_"

    @classmethod
    def get_instance(cls) -> "ReachyService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
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
    ) -> dict:
        """
        Make a request to the daemon with graceful error handling. Returns the
        parsed JSON body on success, or a dict carrying an `error` key when the
        robot is unreachable or the request fails.
        """
        url = f"{self._base_url}{path}"
        try:
            client = self._get_client()
            resp = await client.request(
                method,
                url,
                json=json,
                params=params,
                files=files,
                data=data,
                timeout=timeout,
            )
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return {"ok": True, "content_type": resp.headers.get("content-type")}
        except httpx.ConnectError:
            logger.warning("reachy_connection_failed", url=url)
            return {"error": "Robot not connected", "connected": False}
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            logger.warning(
                "reachy_request_failed",
                url=url,
                status=e.response.status_code,
                body=body,
            )
            return {
                "error": f"Request failed: {e.response.status_code}",
                "status": e.response.status_code,
                "detail": body,
                "connected": True,
            }
        except Exception as e:
            logger.error("reachy_request_error", url=url, error=str(e))
            return {"error": str(e), "connected": False}

    # ------------------------------------------------------------------
    # Connection / status
    # ------------------------------------------------------------------

    async def is_connected(self) -> bool:
        """True iff the daemon is reachable AND reports state == 'running'."""
        res = await self._request("GET", "/api/daemon/status", timeout=3.0)
        return res.get("state") == "running"

    async def get_daemon_status(self) -> dict:
        """Raw /api/daemon/status body (version, state, backend_status, etc.)."""
        return await self._request("GET", "/api/daemon/status", timeout=3.0)

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
        return await self._request("GET", "/api/state/full", params=params)

    async def get_doa(self) -> dict:
        """Direction-of-arrival: {angle: float (radians), speech_detected: bool}."""
        return await self._request("GET", "/api/state/doa", timeout=3.0)

    # legacy alias
    async def get_audio_direction(self) -> dict:
        return await self.get_doa()

    def get_status_info(self) -> dict:
        """Static config info (does not contact the robot)."""
        return {"base_url": self._base_url}

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
    ) -> dict:
        """POST /api/move/set_target (continuous target, no duration)."""
        payload: dict[str, Any] = {}
        if head_pose is not None:
            payload["head_pose"] = head_pose
        if antennas is not None:
            payload["antennas"] = list(antennas)
        if body_yaw is not None:
            payload["body_yaw"] = body_yaw
        return await self._request("POST", "/api/move/set_target", json=payload)

    async def stop_move(self, move_uuid: Optional[str] = None) -> dict:
        """POST /api/move/stop."""
        move_uuid = move_uuid or self._active_move_uuid
        if not move_uuid:
            return {"error": "no active move uuid to stop"}
        return await self._request("POST", "/api/move/stop", json={"uuid": move_uuid})

    async def is_moving(self) -> dict:
        return await self._request("GET", "/api/move/running")

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
        head_pose = {
            "x": 0.0, "y": 0.0, "z": 0.0,
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
    # captured by the host_agent (on the Windows host, port 18794), which
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
            host_agent = os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18794").rstrip("/")

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
