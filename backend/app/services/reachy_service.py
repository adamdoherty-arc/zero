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
import uuid as uuid_mod
from typing import Any, Iterable, Optional

import httpx
import structlog

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

    async def play_emotion(self, emotion: str) -> dict:
        """
        Play a canned emotion animation. Accepts canonical names (``cheerful1``),
        aliases (``happy``), or free-form LLM tags (``thank you``). Returns a
        descriptive error + the list of known emotions if resolution fails.
        """
        clip = resolve_motion(emotion, kind="emotion")
        if not clip:
            return {
                "error": f"unknown emotion: {emotion}",
                "known": [c.name for c in EMOTION_CLIPS],
            }
        return await self._play_clip_with_fallback(
            clip, extra_datasets=EMOTIONS_DATASET_FALLBACKS
        )

    async def play_dance(self, dance: str) -> dict:
        """Play a canned dance move from the dances library."""
        clip = resolve_motion(dance, kind="dance")
        if not clip:
            return {
                "error": f"unknown dance: {dance}",
                "known": [c.name for c in DANCE_CLIPS],
            }
        return await self._play_clip_with_fallback(clip)

    async def play_motion(self, name: str, *, kind: Optional[MotionKind] = None) -> dict:
        """
        Play any clip (emotion or dance) by name or alias. Caller may constrain
        `kind` to force one library.
        """
        clip = resolve_motion(name, kind=kind) if kind else resolve_motion(name)
        if not clip:
            return {"error": f"unknown motion: {name}"}
        extras = EMOTIONS_DATASET_FALLBACKS if clip.kind == "emotion" else ()
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

    async def say(self, text: str, *, cleanup: bool = True) -> dict:
        """
        Speak `text` through the Reachy speaker.

        Pipeline: TTSService.synthesize -> upload WAV -> play_sound.
        If `cleanup` is true, the uploaded sound is deleted in the background
        after a short delay so the daemon's sound library does not bloat.
        """
        try:
            tts = get_tts_service()
            audio_bytes = await tts.synthesize(text)
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

    async def get_camera_specs(self) -> dict:
        return await self._request("GET", "/api/camera/specs")

    def get_stream_url(self, *, fmt: str = "webrtc") -> str:
        """
        Return the URL the frontend should hit to consume Reachy's live
        camera feed. The desktop app exposes the feed on :8443 via WebRTC;
        Zero serves the URL verbatim so browsers can connect directly.
        """
        # Daemon is e.g. http://host:8000 -> feed is on the same host :8443
        parsed = self._base_url.rstrip("/").split("//", 1)
        scheme = parsed[0] + "//" if len(parsed) > 1 else ""
        host_and_port = parsed[-1].split("/", 1)[0]
        host = host_and_port.split(":", 1)[0]
        if fmt == "webrtc":
            return f"https://{host}:8443/webrtc"
        return f"{scheme}{host}:8443"

    async def capture_image(self) -> bytes:
        """
        Camera capture is not exposed by the daemon's REST API. Frames come
        through the desktop app's WebRTC channel on :8443. Returning empty
        bytes keeps legacy callers from crashing; they should check for the
        empty result.
        """
        logger.debug(
            "reachy_capture_image_unavailable",
            hint="Daemon exposes only /api/camera/specs; frames live on WebRTC :8443",
        )
        return b""


def get_reachy_service() -> ReachyService:
    return ReachyService.get_instance()
