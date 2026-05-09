"""
Realtime session orchestrator.

Gluecode between:
- A browser WebSocket (the client that holds the microphone + speaker).
- One provider handler (``OpenAIRealtimeHandler`` or ``GeminiLiveHandler``).
- Zero's ``reachy_service`` for motion tool-calling.

Wire protocol (client <-> Zero over WebSocket, JSON frames either way):

    Client → Zero:
      {"type": "start", "backend": "openai"|"gemini", "api_key": "...",
       "model": "...", "voice": "...", "profile": "companion"}
      {"type": "audio", "audio_b64": "<pcm16 mono>",
       "rate": 24000 | 16000}        # rate must match backend; converter-free
      {"type": "text", "text": "hello"}
      {"type": "commit_audio"}
      {"type": "cancel_response"}
      {"type": "stop"}

    Zero → Client:
      {"type": "session.ready", "model": "...", "voice": "..."}
      {"type": "audio.delta", "format": "pcm16", "rate": 24000, "audio_b64": "..."}
      {"type": "audio.done"}
      {"type": "transcript.partial", "role": "user", "content": "..."}
      {"type": "transcript", "role": "user"|"assistant", "content": "..."}
      {"type": "tool.start"|"tool.end", "tool_name": "...", ...}
      {"type": "usage", "cost_usd": 0.01, "cumulative_usd": 0.07}
      {"type": "error", "message": "..."}
      {"type": "session.closed"}
"""

from __future__ import annotations

import asyncio
import base64
import math
import os
import time
import weakref
from typing import Any, Optional, Union

import httpx
import structlog
import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.infrastructure.config import get_settings
from app.services.reachy_realtime.common import (
    BACKEND_GEMINI,
    BACKEND_LOCAL,
    BACKEND_OPENAI,
    MotionDispatcher,
    ToolDependencies,
    normalize_backend,
    resolve_model,
)
from app.services.reachy_realtime.gemini_handler import GeminiLiveHandler
from app.services.reachy_realtime.head_wobbler import AsyncHeadWobbler, Offsets
from app.services.reachy_realtime.local_handler import LocalRealtimeHandler
from app.services.reachy_realtime.openai_handler import OpenAIRealtimeHandler

logger = structlog.get_logger()


Handler = Union[OpenAIRealtimeHandler, GeminiLiveHandler, LocalRealtimeHandler]
_ACTIVE_SESSIONS: "weakref.WeakSet[RealtimeSession]" = weakref.WeakSet()
_HOST_MIC_ECHO_SUPPRESS_TAIL_S = 0.75
_SPEAKER_READY_TIMEOUT_S = float(os.getenv("ZERO_REACHY_SPEAKER_READY_TIMEOUT_S", "10.0"))
_SPEAKER_PRESTART_TIMEOUT_S = float(os.getenv("ZERO_REACHY_SPEAKER_PRESTART_TIMEOUT_S", "25.0"))
_SPEAKER_RETRY_COOLDOWN_S = float(os.getenv("ZERO_REACHY_SPEAKER_RETRY_COOLDOWN_S", "15.0"))
_SPEAKER_WRITE_TIMEOUT_S = float(os.getenv("ZERO_REACHY_SPEAKER_WRITE_TIMEOUT_S", "0.35"))
_SESSION_STALL_S = float(os.getenv("ZERO_REACHY_REALTIME_STALL_S", "45.0"))
_SESSION_HEALTH_EMIT_INTERVAL_S = float(os.getenv("ZERO_REACHY_REALTIME_HEALTH_EMIT_INTERVAL_S", "0.75"))
_INPUT_NO_SIGNAL_RMS = float(os.getenv("ZERO_REACHY_INPUT_NO_SIGNAL_RMS", "0.00005"))
_INPUT_NO_SIGNAL_PEAK = float(os.getenv("ZERO_REACHY_INPUT_NO_SIGNAL_PEAK", "0.0002"))
_INPUT_ACTIVE_RMS = float(os.getenv("ZERO_REACHY_INPUT_ACTIVE_RMS", "0.003"))
_INPUT_ACTIVE_PEAK = float(os.getenv("ZERO_REACHY_INPUT_ACTIVE_PEAK", "0.015"))
_INPUT_NO_SIGNAL_GRACE_S = float(os.getenv("ZERO_REACHY_INPUT_NO_SIGNAL_GRACE_S", "6.0"))
_INPUT_WARNING_INTERVAL_S = float(os.getenv("ZERO_REACHY_INPUT_WARNING_INTERVAL_S", "5.0"))


def _user_facing_mic_error(message: str, *, source: str = "reachy_mic") -> str:
    """Keep raw Windows device probes in logs, not in the live UI."""
    raw = str(message or "").strip()
    lowered = raw.lower()
    if (
        "no usable microphone stream" in lowered
        or "digital silence" in lowered
        or "no audio frames received" in lowered
    ):
        if source == "reachy_mic":
            return (
                "Reachy microphone is connected, but Windows is delivering "
                "digital silence/no audio frames. Use Computer mic for this "
                "session, then replug or repair the Reachy audio device."
            )
        return "Computer microphone opened, but no usable audio frames reached Zero."
    return raw or "Microphone input is unavailable."


def _now() -> float:
    return time.time()


def _phase_from_event(event: dict[str, Any]) -> str | None:
    etype = str(event.get("type") or "")
    role = str(event.get("role") or "")
    if etype == "session.phase":
        phase = str(event.get("phase") or "")
        return phase or None
    if etype in ("input.ready", "session.ready"):
        return "listening"
    if etype in ("user.speech_started", "user.interrupt"):
        return "listening"
    if etype == "user.speech_stopped":
        return "transcribing"
    if etype == "transcript.partial" and role == "user":
        return "transcribing"
    if etype == "transcript" and role == "user":
        return "thinking"
    if etype == "tool.start":
        return "moving"
    if etype == "audio.delta" or (etype in ("transcript.partial", "transcript") and role == "assistant"):
        return "speaking"
    if etype == "audio.done":
        return "listening"
    if etype == "session.closed":
        return "idle"
    if etype == "error":
        return "stalled"
    return None


def _resample_pcm16(pcm: bytes, *, from_rate: int, to_rate: int) -> bytes:
    """Resample mono PCM16 frames with linear interpolation."""
    if not pcm or from_rate == to_rate:
        return pcm
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2")
    if samples.size == 0:
        return pcm
    target_len = max(1, int(round(samples.size * float(to_rate) / float(from_rate))))
    if target_len == samples.size:
        return pcm
    source_x = np.arange(samples.size, dtype=np.float32)
    target_x = np.linspace(0, samples.size - 1, target_len, dtype=np.float32)
    resampled = np.interp(target_x, source_x, samples.astype(np.float32))
    return np.clip(resampled, -32768, 32767).astype("<i2").tobytes()


def _pcm16_stats_norm(pcm: bytes) -> dict[str, float]:
    """Return normalized RMS/peak for PCM16 frames without raising."""
    if not pcm:
        return {"rms": 0.0, "peak": 0.0}
    try:
        import numpy as np

        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        if samples.size == 0:
            return {"rms": 0.0, "peak": 0.0}
        rms = float(np.sqrt(np.mean(samples * samples))) / 32768.0
        peak = float(np.max(np.abs(samples))) / 32768.0
        return {"rms": rms, "peak": peak}
    except Exception:
        return {"rms": 0.0, "peak": 0.0}


def _classify_input_level(rms: float, peak: float) -> str:
    """Classify whether mic frames contain usable signal, not just bytes."""
    if rms <= _INPUT_NO_SIGNAL_RMS and peak <= _INPUT_NO_SIGNAL_PEAK:
        return "no_signal"
    if rms >= _INPUT_ACTIVE_RMS or peak >= _INPUT_ACTIVE_PEAK:
        return "ok"
    return "waiting_for_speech"


def realtime_motion_snapshot() -> dict[str, Any]:
    """Return live realtime sessions that can currently move the robot body."""
    sessions = list(_ACTIVE_SESSIONS)
    motion_active = [s for s in sessions if s.motion_active]
    body_motion_enabled = [s for s in sessions if s.body_motion_enabled]
    input_ready = [s for s in sessions if s.input_ready]
    health = [s.health_snapshot() for s in sessions]
    primary = health[-1] if health else {}
    return {
        "active_sessions": len(sessions),
        "motion_active_sessions": len(motion_active),
        "body_motion_enabled_sessions": len(body_motion_enabled),
        "input_ready_sessions": len(input_ready),
        "input_sources": [s.input_source for s in sessions],
        "active": bool(motion_active),
        "body_motion_enabled": bool(body_motion_enabled),
        "sessions": health,
        "session_phase": primary.get("session_phase", "idle"),
        "stalled_reason": primary.get("stalled_reason"),
        "input_health": primary.get("input_health") or _default_input_health(),
        "output_health": primary.get("output_health") or _default_output_health(),
    }


async def suspend_all_realtime_motion(reason: str = "settle") -> dict[str, Any]:
    """Pause realtime body/head motion without closing live voice sessions."""
    sessions = list(_ACTIVE_SESSIONS)
    results = [await session.suspend_motion(reason=reason) for session in sessions]
    return {
        "active_sessions": len(sessions),
        "suspended": sum(1 for result in results if result.get("motion_was_active")),
        "results": results,
    }


def _default_input_health() -> dict[str, Any]:
    return {
        "source": "unknown",
        "ready": False,
        "rms": 0.0,
        "peak": 0.0,
        "empty_stt_count": 0,
        "confidence_state": "unknown",
        "last_signal_at": None,
        "last_frame_at": None,
        "suggested_action": None,
        "last_error": None,
    }


def _default_output_health() -> dict[str, Any]:
    return {
        "sink": "unknown",
        "ready": False,
        "queued_ms": 0,
        "last_error": None,
    }


def realtime_session_snapshot() -> dict[str, Any]:
    sessions = [s.health_snapshot() for s in list(_ACTIVE_SESSIONS)]
    primary = sessions[-1] if sessions else {}
    return {
        "active_sessions": len(sessions),
        "sessions": sessions,
        "session_phase": primary.get("session_phase", "idle"),
        "stalled_reason": primary.get("stalled_reason"),
        "input_health": primary.get("input_health") or _default_input_health(),
        "output_health": primary.get("output_health") or _default_output_health(),
    }


async def recover_all_realtime_sessions(reason: str = "manual") -> dict[str, Any]:
    sessions = list(_ACTIVE_SESSIONS)
    results = [await session.recover(reason=reason) for session in sessions]
    return {
        "ok": True,
        "active_sessions": len(sessions),
        "recovered": sum(1 for result in results if result.get("ok")),
        "results": results,
        **realtime_session_snapshot(),
    }


def build_motion_dispatcher() -> MotionDispatcher:
    """Wrap ``reachy_service`` so the tool surface matches ``MotionDispatcher``.

    All calls are best-effort: if the daemon is offline, ``reachy_service``
    returns ``{"error": "Robot not connected"}`` — tools forward that straight
    to the model, which then narrates the failure.
    """
    from app.services.reachy_motion_library import DANCE_CLIPS, EMOTION_CLIPS
    from app.services.reachy_service import get_reachy_service

    svc = get_reachy_service()

    async def _move_head(**kwargs) -> dict:
        return await svc.move_head(**kwargs)

    async def _play_emotion(name: str) -> dict:
        return await svc.play_emotion(name)

    async def _play_dance(name: str) -> dict:
        return await svc.play_dance(name)

    async def _stop_move(**_kwargs) -> dict:
        return await svc.stop_move()

    def _list_emotions() -> list[str]:
        return [c.name for c in EMOTION_CLIPS]

    def _list_dances() -> list[str]:
        return [c.name for c in DANCE_CLIPS]

    async def _capture_image() -> bytes:
        return await svc.capture_image()  # returns b"" when unavailable

    async def _set_head_tracking(enabled: bool) -> dict:
        from app.services.reachy_head_tracking_service import get_reachy_head_tracking_service

        tracker = get_reachy_head_tracking_service()
        if enabled:
            return await tracker.start()
        return await tracker.stop()

    return MotionDispatcher(
        move_head=_move_head,
        play_emotion=_play_emotion,
        play_dance=_play_dance,
        stop_move=_stop_move,
        list_emotions=_list_emotions,
        list_dances=_list_dances,
        capture_image=_capture_image,
        set_head_tracking=_set_head_tracking,
    )


def _build_tool_deps(*, body_motion_enabled: bool, profile_id: str | None = None) -> ToolDependencies:
    return ToolDependencies(
        motion=build_motion_dispatcher(),
        extra={"body_motion_enabled": body_motion_enabled, "profile_id": profile_id or ""},
    )


def _build_wobbler_apply() -> callable:
    """Return an ``apply_offsets`` coroutine bound to ``reachy_service``.

    The daemon's continuous-target endpoint is ``/api/move/set_target``. We
    only hit it when the composite offset changes meaningfully (> ~0.3 deg
    or > 1 mm on any axis) so a 20 Hz sway loop doesn't become a 20 Hz
    daemon-call storm — most hops during quiet audio are near-zero and can
    be coalesced.

    A circuit breaker trips when the daemon is unreachable: after
    ``BREAKER_TRIP_FAILURES`` consecutive "Robot not connected" responses we
    pause dispatch for ``BREAKER_COOLDOWN_S``. This stops the 20 Hz warn-log
    firehose that would otherwise fill ``docker logs`` when you realtime-chat
    without the daemon up.
    """
    from app.services.reachy_service import get_reachy_service

    svc = get_reachy_service()
    state = {
        "last": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        "last_sent_at": 0.0,
        "consecutive_failures": 0,
        "tripped_until": 0.0,
    }
    DEG_THRESH = math.radians(0.3)
    MM_THRESH = 0.001
    MAX_SKIP_S = 0.25
    BREAKER_TRIP_FAILURES = 3
    BREAKER_COOLDOWN_S = 10.0

    async def _apply(offsets: Offsets) -> None:
        now = time.monotonic()
        if now < state["tripped_until"]:
            return
        last = state["last"]
        changed = any(
            (abs(a - b) > (DEG_THRESH if i >= 3 else MM_THRESH))
            for i, (a, b) in enumerate(zip(offsets, last))
        )
        if not changed and (now - state["last_sent_at"]) < MAX_SKIP_S:
            return
        state["last"] = offsets
        state["last_sent_at"] = now
        x, y, z, roll, pitch, yaw = offsets
        try:
            res = await svc.set_target(
                head_pose={
                    "x": float(x), "y": float(y), "z": float(z),
                    "roll": float(roll), "pitch": float(pitch), "yaw": float(yaw),
                },
            )
        except Exception as e:
            logger.debug("head_wobbler_set_target_raised", error=str(e))
            res = {"error": str(e)}
        if isinstance(res, dict) and res.get("error"):
            state["consecutive_failures"] += 1
            if state["consecutive_failures"] >= BREAKER_TRIP_FAILURES:
                state["tripped_until"] = now + BREAKER_COOLDOWN_S
                logger.info(
                    "head_wobbler_breaker_tripped",
                    cooldown_s=BREAKER_COOLDOWN_S,
                    error=res.get("error"),
                )
        else:
            state["consecutive_failures"] = 0

    return _apply


class ReachySpeakerSink:
    """Forwards assistant PCM frames to host_agent's /speaker/stream WS so
    the assistant's voice comes out of the Reachy USB speaker, not the
    user's PC. host_agent owns the sounddevice OutputStream because it
    runs on the Windows host (Docker containers can't see USB audio).

    All failures are logged and swallowed — speaker forwarding must never
    take down the realtime session.
    """

    def __init__(self, host_agent_url: str) -> None:
        # host_agent_url is something like "http://host.docker.internal:18796".
        # Convert to ws:// for the streaming endpoint.
        self.http_url = host_agent_url.rstrip("/")
        url = self.http_url
        if url.startswith("https://"):
            url = "wss://" + url[len("https://"):]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://"):]
        elif not url.startswith(("ws://", "wss://")):
            url = "ws://" + url
        self.url = f"{url}/speaker/stream"
        self._ws: Optional[Any] = None
        self._send_lock = asyncio.Lock()
        self._closed = False
        self._connected_rate: Optional[int] = None
        self._ready_info: dict[str, Any] = {}
        self.last_error: Optional[str] = None

    async def connect(self, *, rate: int) -> bool:
        """Open the WS and send the start handshake. Returns True on success."""
        try:
            await self._prestart(rate=rate)
            self._ws = await asyncio.wait_for(
                websockets.connect(self.url, max_size=None, ping_interval=20),
                timeout=8.0,
            )
            await self._ws.send(_json_dumps({"type": "start", "rate": rate}))
            raw = await asyncio.wait_for(self._ws.recv(), timeout=_SPEAKER_READY_TIMEOUT_S)
            ready = _json_loads(raw) if isinstance(raw, str) else {}
            if ready.get("type") == "error":
                raise RuntimeError(str(ready.get("message") or "speaker stream failed"))
            if ready.get("type") != "ready":
                raise RuntimeError("speaker stream did not become ready")
            self._connected_rate = rate
            self._ready_info = ready
            logger.info("reachy_speaker_sink_connected", url=self.url, rate=rate, device=ready.get("device_name"))
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e!r}"
            logger.warning(
                "reachy_speaker_sink_connect_failed",
                url=self.url,
                error=str(e),
                error_type=type(e).__name__,
                error_repr=repr(e),
            )
            try:
                if self._ws is not None:
                    await self._ws.close()
            except Exception:
                pass
            self._ws = None
            return False

    async def _prestart(self, *, rate: int) -> None:
        """Warm the host speaker process so the WS handshake can return quickly."""
        try:
            async with httpx.AsyncClient(timeout=_SPEAKER_PRESTART_TIMEOUT_S) as client:
                await client.post(f"{self.http_url}/speaker/start", json={"rate": rate})
        except Exception as e:
            logger.debug("reachy_speaker_prestart_failed", error=str(e), url=self.http_url)

    def info(self) -> dict[str, Any]:
        return dict(self._ready_info)

    async def write_pcm(self, pcm_bytes: bytes, rate: int) -> None:
        if self._closed or self._ws is None or not pcm_bytes:
            return
        async with self._send_lock:
            try:
                # Binary frame is the cheapest path — host_agent decodes it
                # straight into the queue without a JSON round-trip. Rate is
                # fixed at the start handshake; if a different rate arrives
                # we send it as a JSON audio frame so host_agent can adjust.
                if rate == self._connected_rate:
                    await self._ws.send(pcm_bytes)
                else:
                    await self._ws.send(_json_dumps({
                        "type": "audio",
                        "audio_b64": base64.b64encode(pcm_bytes).decode("ascii"),
                        "rate": rate,
                    }))
            except Exception as e:
                logger.debug("reachy_speaker_sink_write_failed", error=str(e))
                self._ws = None

    async def flush(self) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            try:
                await self._ws.send(_json_dumps({"type": "flush"}))
            except Exception:
                pass

    async def close(self) -> None:
        self._closed = True
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            await ws.send(_json_dumps({"type": "stop"}))
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass


def _json_dumps(obj: dict) -> str:
    import json
    return json.dumps(obj)


def _json_loads(text: str) -> dict:
    import json
    value = json.loads(text)
    return value if isinstance(value, dict) else {}


class RealtimeSession:
    """Owns one active handler + WebSocket, dies when either side closes."""

    def __init__(self, ws: WebSocket, *, enable_head_wobble: bool = False) -> None:
        self.ws = ws
        self.handler: Optional[Handler] = None
        self._handler_task: Optional[asyncio.Task[None]] = None
        self._wobbler: Optional[AsyncHeadWobbler] = None
        self._enable_head_wobble = enable_head_wobble
        self._body_motion_enabled = False
        self._speaker_sink: Optional[ReachySpeakerSink] = None
        self._speaker_sink_task: Optional[asyncio.Task[None]] = None
        self._speaker_sink_enabled = False
        self._speaker_sink_url: Optional[str] = None
        self._speaker_sink_rate = 24000
        self._speaker_sink_retry_after = 0.0
        self._host_mic_task: Optional[asyncio.Task[None]] = None
        self._host_mic_ws: Optional[Any] = None
        self._host_mic_ready = False
        self._input_muted = False
        self._suppress_host_mic_until = 0.0
        self._input_source = "browser"
        # Last-known session shape — preserved across hot-swaps so the
        # frontend can swap backends without re-sending profile / api_keys.
        self._current_profile: Optional[str] = None
        self._current_backend: Optional[str] = None
        self._cached_openai_key: Optional[str] = None
        self._cached_gemini_key: Optional[str] = None
        self._current_phase = "idle"
        self._stalled_reason: Optional[str] = None
        self._last_user_audio_at: Optional[float] = None
        self._last_input_frame_at: Optional[float] = None
        self._last_input_signal_at: Optional[float] = None
        self._last_transcript_at: Optional[float] = None
        self._last_assistant_audio_at: Optional[float] = None
        self._last_health_emit_at = 0.0
        self._input_no_signal_since: Optional[float] = None
        self._last_input_warning_at = 0.0
        self._tool_count = 0
        self._input_health: dict[str, Any] = _default_input_health()
        self._output_health: dict[str, Any] = _default_output_health()

    async def run(self) -> None:
        await self.ws.accept()
        _ACTIVE_SESSIONS.add(self)
        try:
            await self._run_loop()
        except WebSocketDisconnect:
            pass
        finally:
            _ACTIVE_SESSIONS.discard(self)
            await self._cleanup()

    async def _run_loop(self) -> None:
        while True:
            try:
                msg = await self.ws.receive_json()
            except WebSocketDisconnect:
                return
            except Exception as e:
                logger.debug("realtime_bad_frame", error=str(e))
                continue

            mtype = msg.get("type")
            if mtype == "start":
                await self._handle_start(msg)
            elif mtype == "swap_backend":
                await self._handle_swap_backend(msg)
            elif mtype == "audio":
                await self._handle_audio(msg)
            elif mtype == "text":
                if self.handler:
                    await self.handler.send_text(str(msg.get("text", "")))
            elif mtype == "commit_audio":
                if self.handler:
                    await self.handler.commit_audio()
            elif mtype == "cancel_response":
                if self.handler:
                    await self.handler.cancel_response()
            elif mtype == "set_body_motion":
                await self.set_body_motion_enabled(bool(msg.get("enabled")))
            elif mtype == "set_input_muted":
                self._input_muted = bool(msg.get("muted"))
                await self._safe_send({
                    "type": "input_muted",
                    "muted": self._input_muted,
                    "source": self._input_source,
                })
            elif mtype == "set_input_source":
                await self.set_input_source(str(msg.get("source") or "browser"))
            elif mtype == "stop":
                await self._safe_send({"type": "session.closed"})
                return

    @property
    def body_motion_enabled(self) -> bool:
        return self._body_motion_enabled

    @property
    def motion_active(self) -> bool:
        return self._wobbler is not None

    @property
    def input_ready(self) -> bool:
        return self._input_source == "browser" or self._host_mic_ready

    @property
    def input_source(self) -> str:
        return self._input_source

    async def set_input_source(self, source: str) -> dict[str, Any]:
        source = (source or "reachy").strip().lower()
        if source not in {"browser", "reachy", "host_agent"}:
            source = "browser"
        if self._host_mic_task and not self._host_mic_task.done():
            self._host_mic_task.cancel()
            try:
                await self._host_mic_task
            except (asyncio.CancelledError, Exception):
                pass
        self._host_mic_task = None
        if self._host_mic_ws is not None:
            try:
                await self._host_mic_ws.close()
            except Exception:
                pass
            self._host_mic_ws = None
        self._input_source = source
        self._host_mic_ready = source == "browser"
        self._last_input_frame_at = None
        self._last_input_signal_at = None
        self._input_no_signal_since = None
        self._last_input_warning_at = 0.0
        self._input_health.update({
            "source": "browser_mic" if source == "browser" else "reachy_mic",
            "ready": self._host_mic_ready,
            "last_error": None,
            "confidence_state": "waiting_for_signal",
            "last_signal_at": None,
            "last_frame_at": None,
            "suggested_action": None,
        })
        if self._stalled_reason in {"reachy_mic_no_signal", "browser_mic_no_signal"}:
            await self._set_phase("listening")
        if source in {"reachy", "host_agent"} and self.handler is not None:
            input_rate = 16000 if self._current_backend in (BACKEND_LOCAL, BACKEND_GEMINI) else 24000
            self._host_mic_task = asyncio.create_task(
                self._run_host_mic_source(rate=input_rate),
                name="realtime-host-mic",
            )
        else:
            await self._safe_send({
                "type": "input.ready",
                "source": "browser_mic",
                "device_name": "Browser microphone",
                "rate": 16000 if self._current_backend in (BACKEND_LOCAL, BACKEND_GEMINI) else 24000,
            })
        await self._emit_health(force=True)
        payload = {"type": "input.source", "source": source, "ready": self._host_mic_ready}
        await self._safe_send(payload)
        return payload

    def health_snapshot(self) -> dict[str, Any]:
        phase = self._effective_phase()
        return {
            "session_phase": phase,
            "stalled_reason": self._stalled_reason,
            "last_user_audio_at": self._last_user_audio_at,
            "last_input_frame_at": self._last_input_frame_at,
            "last_input_signal_at": self._last_input_signal_at,
            "last_transcript_at": self._last_transcript_at,
            "last_assistant_audio_at": self._last_assistant_audio_at,
            "backend": self._current_backend,
            "profile": self._current_profile,
            "input_health": dict(self._input_health),
            "output_health": dict(self._output_health),
            "body_motion_enabled": self._body_motion_enabled,
            "motion_active": self.motion_active,
            "active_tools": self._tool_count,
        }

    def _effective_phase(self) -> str:
        if self._stalled_reason:
            return "stalled"
        if self._current_phase in {"thinking", "speaking", "moving", "transcribing"}:
            last = max(
                self._last_user_audio_at or 0.0,
                self._last_transcript_at or 0.0,
                self._last_assistant_audio_at or 0.0,
            )
            if last > 0.0 and (_now() - last) > _SESSION_STALL_S:
                self._stalled_reason = f"{self._current_phase} timed out"
                return "stalled"
        return self._current_phase

    async def _set_phase(self, phase: str, *, reason: str | None = None) -> None:
        if phase not in {"idle", "listening", "transcribing", "thinking", "speaking", "moving", "recovering", "stalled"}:
            return
        self._current_phase = phase
        if phase != "stalled":
            self._stalled_reason = None
        elif reason:
            self._stalled_reason = reason
        await self._emit_health(force=True)

    async def _emit_health(self, *, force: bool = False) -> None:
        now = _now()
        if not force and (now - self._last_health_emit_at) < _SESSION_HEALTH_EMIT_INTERVAL_S:
            return
        self._last_health_emit_at = now
        await self._safe_send({"type": "session.health", **self.health_snapshot()})

    def _record_event_health(self, event: dict[str, Any]) -> None:
        etype = str(event.get("type") or "")
        now = _now()
        if etype == "input.ready":
            self._input_health.update({
                "source": event.get("source") or self._input_source,
                "ready": True,
                "last_error": None,
                "suggested_action": None,
            })
        elif etype == "input.warning":
            self._input_health.update({
                "ready": True,
                "rms": float(event.get("rms") or event.get("rms_norm") or self._input_health.get("rms") or 0.0),
                "peak": float(event.get("peak") or event.get("peak_norm") or self._input_health.get("peak") or 0.0),
                "empty_stt_count": int(event.get("empty_stt_count") or self._input_health.get("empty_stt_count") or 0),
                "confidence_state": event.get("confidence_state") or "low_confidence",
                "suggested_action": event.get("suggested_action"),
                "last_error": event.get("message"),
            })
        elif etype == "output.ready":
            self._output_health.update({
                "sink": event.get("sink") or "reachy_speaker",
                "ready": True,
                "queued_ms": 0,
                "last_error": None,
            })
        elif etype == "output.unavailable":
            self._output_health.update({
                "sink": event.get("sink") or "reachy_speaker",
                "ready": False,
                "last_error": event.get("message") or "speaker unavailable",
            })
        elif etype == "user.speech_started":
            self._last_user_audio_at = now
        elif etype in ("transcript", "transcript.partial"):
            role = str(event.get("role") or "")
            if role == "user":
                self._last_transcript_at = now
            elif role == "assistant":
                self._last_assistant_audio_at = now
        elif etype == "audio.delta":
            self._last_assistant_audio_at = now
        elif etype == "tool.start":
            self._tool_count += 1
        elif etype == "tool.end":
            self._tool_count = max(0, self._tool_count - 1)
        elif etype == "error":
            code = str(event.get("code") or "")
            if code in {
                "stt_timeout",
                "llm_timeout",
                "tts_timeout",
                "speaker_backpressure",
                "tool_timeout",
                "websocket_closed",
            }:
                self._stalled_reason = code
            else:
                self._stalled_reason = str(event.get("message") or "realtime error")

    def _mark_assistant_audio_playing(self) -> None:
        """Briefly gate host-mic frames so Reachy does not hear its own reply."""
        self._suppress_host_mic_until = max(
            self._suppress_host_mic_until,
            time.monotonic() + _HOST_MIC_ECHO_SUPPRESS_TAIL_S,
        )

    def _host_mic_suppressed(self) -> bool:
        return time.monotonic() < self._suppress_host_mic_until

    def _observe_input_frame(
        self,
        *,
        source: str,
        rms: float,
        peak: float,
        overflowed: bool = False,
    ) -> dict[str, Any] | None:
        """Update mic health from a frame and return a warning event if needed."""
        now = _now()
        self._last_input_frame_at = now
        state = _classify_input_level(rms, peak)
        warning: dict[str, Any] | None = None
        last_error: str | None = "input overflow" if overflowed else None
        suggested_action: str | None = None

        if state == "ok":
            self._last_input_signal_at = now
            self._input_no_signal_since = None
            if self._stalled_reason in {"reachy_mic_no_signal", "browser_mic_no_signal"}:
                self._stalled_reason = None
                if self._current_phase == "stalled":
                    self._current_phase = "listening"
        elif state == "no_signal":
            if self._input_no_signal_since is None:
                self._input_no_signal_since = now
            silent_for = now - self._input_no_signal_since
            if silent_for < _INPUT_NO_SIGNAL_GRACE_S:
                state = "waiting_for_signal"
            else:
                if source == "reachy_mic":
                    self._stalled_reason = "reachy_mic_no_signal"
                    last_error = (
                        "Reachy microphone is open but streaming digital silence; "
                        "switching to the computer mic is recommended."
                    )
                    suggested_action = "switch_to_browser_mic"
                else:
                    self._stalled_reason = "browser_mic_no_signal"
                    last_error = "Computer microphone is open but no signal is reaching Zero."
                if (now - self._last_input_warning_at) >= _INPUT_WARNING_INTERVAL_S:
                    self._last_input_warning_at = now
                    warning = {
                        "type": "input.warning",
                        "source": source,
                        "message": last_error,
                        "rms": rms,
                        "peak": peak,
                        "empty_stt_count": int(self._input_health.get("empty_stt_count") or 0),
                        "confidence_state": state,
                        "suggested_action": suggested_action,
                    }
        else:
            self._input_no_signal_since = None

        self._input_health.update({
            "source": source,
            "ready": True,
            "rms": rms,
            "peak": peak,
            "confidence_state": state,
            "last_signal_at": self._last_input_signal_at,
            "last_frame_at": self._last_input_frame_at,
            "suggested_action": suggested_action,
            "last_error": last_error,
        })
        return warning

    async def set_body_motion_enabled(self, enabled: bool) -> dict[str, Any]:
        self._body_motion_enabled = enabled
        deps = getattr(self.handler, "deps", None)
        extra = getattr(deps, "extra", None)
        if isinstance(extra, dict):
            extra["body_motion_enabled"] = enabled
        if enabled:
            if self._wobbler is None:
                self._wobbler = AsyncHeadWobbler(apply_offsets=_build_wobbler_apply())
                await self._wobbler.start()
            payload = {"type": "body_motion", "enabled": True, "active": True}
            await self._safe_send(payload)
            return payload

        was_active = self._wobbler is not None
        if self._wobbler is not None:
            try:
                await self._wobbler.stop()
            except Exception:
                pass
            self._wobbler = None
        payload = {
            "type": "body_motion",
            "enabled": False,
            "active": False,
            "motion_was_active": was_active,
        }
        await self._safe_send(payload)
        return payload

    async def suspend_motion(self, *, reason: str = "settle") -> dict[str, Any]:
        result = await self.set_body_motion_enabled(False)
        stop_result = await self._stop_active_motion(reason=reason)
        return {
            "ok": True,
            "reason": reason,
            "motion_was_active": bool(result.get("motion_was_active")),
            "body_motion_enabled": self._body_motion_enabled,
            "stop_move": stop_result,
        }

    async def _stop_active_motion(self, *, reason: str = "interrupt") -> dict[str, Any]:
        deps = getattr(self.handler, "deps", None)
        motion = getattr(deps, "motion", None)
        stop_move = getattr(motion, "stop_move", None)
        if not callable(stop_move):
            return {"ok": False, "reason": reason, "detail": "no stop_move dispatcher"}
        try:
            result = await asyncio.wait_for(stop_move(), timeout=2.0)
            return {
                "ok": not (isinstance(result, dict) and result.get("error")),
                "reason": reason,
                "result": result,
            }
        except Exception as e:
            return {"ok": False, "reason": reason, "error": str(e)}

    async def _handle_start(self, msg: dict) -> None:
        if self.handler is not None:
            await self._safe_send({"type": "error", "message": "session already started"})
            return

        settings = get_settings()
        backend = normalize_backend(msg.get("backend") or settings.reachy_realtime_backend)
        self._input_source = str(msg.get("input_source") or "browser").strip().lower()
        if self._input_source not in ("browser", "reachy", "host_agent"):
            self._input_source = "browser"
        self._host_mic_ready = self._input_source == "browser"
        self._last_user_audio_at = None
        self._last_input_frame_at = None
        self._last_input_signal_at = None
        self._input_no_signal_since = None
        self._last_input_warning_at = 0.0
        self._input_health.update({
            "source": "browser_mic" if self._input_source == "browser" else "reachy_mic",
            "ready": self._host_mic_ready,
            "confidence_state": "waiting_for_signal",
            "last_signal_at": None,
            "last_frame_at": None,
            "suggested_action": None,
            "last_error": None,
        })
        self._output_health.update({
            "sink": "reachy_speaker",
            "ready": False,
            "queued_ms": 0,
            "last_error": None,
        })
        await self._set_phase("listening")
        explicit_model = (msg.get("model") or "").strip() or None
        explicit_voice = (msg.get("voice") or "").strip() or None
        profile = msg.get("profile") or settings.reachy_realtime_profile

        # Persona-bound model/voice (when no explicit override) — lets
        # personas like ``companion_girlfriend`` ship with their preferred
        # uncensored Qwen brain without the user having to pick it twice.
        persona_model: Optional[str] = None
        persona_voice: Optional[str] = None
        try:
            from app.services.reachy_realtime.profiles import get_profile
            prof = get_profile(profile)
            persona_model = prof.model
            persona_voice = prof.voice
        except Exception as e:
            logger.debug("realtime_profile_lookup_failed", error=str(e))

        if backend == BACKEND_LOCAL:
            model = resolve_model(
                backend,
                explicit_model or persona_model or settings.reachy_realtime_model,
            )
        else:
            model = resolve_model(backend, explicit_model or settings.reachy_realtime_model)
        voice = explicit_voice or persona_voice or settings.reachy_realtime_voice

        # Wire the assistant-audio fan-out: head wobbler (visual) + Reachy
        # USB speaker (audible). Both are best-effort; if either fails we
        # keep the session alive — the browser still has a copy of the
        # audio.delta stream as a fallback.
        requested_body_motion = bool(
            msg.get("enable_body_motion")
            or msg.get("body_motion")
            or self._enable_head_wobble
        )
        self._body_motion_enabled = False
        if requested_body_motion:
            await self.set_body_motion_enabled(True)

        raw_speaker_flag = os.getenv("ZERO_REACHY_SPEAKER_SINK")
        if raw_speaker_flag is None:
            speaker_sink_enabled = bool(settings.host_agent_url)
        else:
            speaker_sink_enabled = raw_speaker_flag.strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
        self._speaker_sink_enabled = speaker_sink_enabled
        self._speaker_sink_url = settings.host_agent_url or "http://host.docker.internal:18796"
        self._speaker_sink_rate = 24000
        self._speaker_sink_retry_after = 0.0
        self._speaker_sink = None

        async def _on_audio(pcm_bytes: bytes, rate: int) -> None:
            self._mark_assistant_audio_playing()
            if self._wobbler is not None:
                try:
                    await self._wobbler.feed_pcm16(pcm_bytes, sample_rate=rate)
                except Exception as e:
                    logger.debug("wobbler_feed_failed", error=str(e))
            self._ensure_speaker_sink_connecting(handler=handler)
            if self._speaker_sink is not None:
                try:
                    await asyncio.wait_for(
                        self._speaker_sink.write_pcm(pcm_bytes, rate),
                        timeout=_SPEAKER_WRITE_TIMEOUT_S,
                    )
                    self._output_health["queued_ms"] = 0
                except asyncio.TimeoutError:
                    message = "Reachy speaker write timed out; queued audio may be backing up."
                    self._output_health.update({
                        "ready": False,
                        "last_error": message,
                    })
                    await self._safe_send({
                        "type": "error",
                        "code": "speaker_backpressure",
                        "message": message,
                    })
                    await self._set_phase("stalled", reason="speaker_backpressure")
                except Exception as e:
                    self._output_health.update({
                        "ready": False,
                        "last_error": f"speaker write failed: {e}",
                    })
                    logger.debug("speaker_sink_write_failed", error=str(e))

        async def _on_turn_end() -> None:
            if self._wobbler is not None:
                self._wobbler.request_reset_after_current_audio()

        on_audio: Optional[Any] = _on_audio
        on_turn_end: Optional[Any] = _on_turn_end

        # Cache provider keys so swap_backend can re-use them without the
        # frontend resending them on every hop.
        if (msg.get("api_key") or "").strip() and backend == BACKEND_OPENAI:
            self._cached_openai_key = msg.get("api_key").strip()
        if (msg.get("api_key") or "").strip() and backend == BACKEND_GEMINI:
            self._cached_gemini_key = msg.get("api_key").strip()

        handler = await self._build_handler(
            backend=backend,
            model=model,
            voice=voice,
            profile=profile,
            api_key=(msg.get("api_key") or "").strip() or None,
            on_audio=on_audio,
            on_turn_end=on_turn_end,
        )
        if handler is None:
            return  # error already emitted
        self.handler = handler
        self._current_profile = profile
        self._current_backend = backend
        self._handler_task = asyncio.create_task(
            self._run_handler(handler), name=f"realtime-{backend}"
        )
        if self._input_source in ("reachy", "host_agent"):
            input_rate = 16000 if backend in (BACKEND_LOCAL, BACKEND_GEMINI) else 24000
            self._host_mic_task = asyncio.create_task(
                self._run_host_mic_source(rate=input_rate),
                name="realtime-host-mic",
            )
        self._ensure_speaker_sink_connecting(handler=handler, force=True)

    def _ensure_speaker_sink_connecting(self, *, handler: Handler, force: bool = False) -> None:
        if not self._speaker_sink_enabled or not self._speaker_sink_url:
            return
        if self.handler is not handler:
            return
        if self._speaker_sink is not None:
            return
        if self._speaker_sink_task is not None and not self._speaker_sink_task.done():
            return
        now = time.monotonic()
        if not force and now < self._speaker_sink_retry_after:
            return
        self._speaker_sink_retry_after = now + _SPEAKER_RETRY_COOLDOWN_S
        self._speaker_sink_task = asyncio.create_task(
            self._connect_speaker_sink_background(
                host_agent_url=self._speaker_sink_url,
                rate=self._speaker_sink_rate,
                handler=handler,
            ),
            name="realtime-reachy-speaker",
        )

    async def _connect_speaker_sink_background(
        self,
        *,
        host_agent_url: str,
        rate: int,
        handler: Handler,
    ) -> None:
        self._output_health.update({
            "sink": "reachy_speaker",
            "ready": False,
            "last_error": "connecting",
        })
        await self._safe_send({
            "type": "output.connecting",
            "sink": "reachy_speaker",
            "message": "Connecting Reachy speaker.",
        })
        await self._safe_send({"type": "session.health", **self.health_snapshot()})
        last_error = ""
        for attempt in range(1, 4):
            if self.handler is not handler:
                return
            try:
                sink = ReachySpeakerSink(host_agent_url)
                # OpenAI realtime emits 24 kHz mono; Gemini Live also emits 24 kHz
                # for output. The sink resamples on the host if the device prefers
                # a different rate.
                if await sink.connect(rate=rate):
                    if self.handler is not handler:
                        await sink.close()
                        return
                    old_sink = self._speaker_sink
                    self._speaker_sink = sink
                    self._speaker_sink_retry_after = 0.0
                    if old_sink is not None:
                        await old_sink.close()
                    sink_info = sink.info()
                    sink_info.pop("type", None)
                    self._output_health.update({
                        "sink": "reachy_speaker",
                        "ready": True,
                        "queued_ms": int(sink_info.get("queued_ms") or 0),
                        "last_error": None,
                    })
                    await self._safe_send({
                        **sink_info,
                        "type": "output.ready",
                        "sink": "reachy_speaker",
                    })
                    await self._safe_send({"type": "session.health", **self.health_snapshot()})
                    return
                last_error = getattr(sink, "last_error", None) or ""
                if not last_error:
                    last_error = "speaker stream did not start"
                    break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = str(e)
                logger.warning("reachy_speaker_sink_init_failed", error=str(e))
            if attempt < 3:
                await asyncio.sleep(float(attempt))
        if self.handler is handler:
            message = (
                "Reachy speaker stream did not start"
                + (f": {last_error}" if last_error else "")
                + "; browser speaker is available as a manual fallback."
            )
            self._output_health.update({
                "sink": "reachy_speaker",
                "ready": False,
                "last_error": message,
            })
            await self._safe_send({
                "type": "output.unavailable",
                "sink": "reachy_speaker",
                "message": message,
            })
            await self._safe_send({"type": "session.health", **self.health_snapshot()})

    def _make_client_writer(self):
        async def _client_writer(event: dict) -> None:
            etype = event.get("type")
            self._record_event_health(event)
            phase = _phase_from_event(event)
            if phase:
                self._current_phase = phase
                if phase != "stalled":
                    self._stalled_reason = None
                elif event.get("reason"):
                    self._stalled_reason = str(event.get("reason"))
            if (
                etype in ("user.speech_started", "audio.cancelled", "user.interrupt")
                and self._speaker_sink is not None
            ):
                try:
                    await self._speaker_sink.flush()
                except Exception:
                    pass
            if etype in ("user.speech_started", "audio.cancelled", "user.interrupt"):
                await self._stop_active_motion(reason=str(etype))
            await self._safe_send(event)
            await self._emit_health()
        return _client_writer

    async def _run_handler(self, handler: Handler) -> None:
        client_writer = self._make_client_writer()
        try:
            await handler.start(client_writer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("realtime_handler_crashed")
            await self._safe_send({"type": "error", "message": f"handler crashed: {e}"})
        finally:
            # Don't blanket-emit session.closed — a hot-swap stops the old
            # handler intentionally and the new one is still running. Only
            # emit when the swap-replacement field is False.
            if self.handler is handler:
                await self._safe_send({"type": "session.closed"})

    async def _build_handler(
        self,
        *,
        backend: str,
        model: str,
        voice: str,
        profile: Optional[str],
        api_key: Optional[str],
        on_audio,
        on_turn_end,
    ) -> Optional[Handler]:
        settings = get_settings()
        try:
            from app.services.reachy_realtime.config_store import load_config

            stored_config = load_config()
        except Exception as e:
            logger.debug("realtime_config_load_failed", error=str(e))
            stored_config = {}
        if backend == BACKEND_OPENAI:
            key = (
                api_key
                or self._cached_openai_key
                or stored_config.get("openai_api_key")
                or settings.openai_api_key
                or ""
            )
            key = key.strip()
            if not key:
                await self._safe_send({
                    "type": "error",
                    "message": "OPENAI_API_KEY missing — set ZERO_OPENAI_API_KEY or pass api_key in start",
                })
                return None
            self._cached_openai_key = key
            return OpenAIRealtimeHandler(
                api_key=key,
                model=model,
                voice=voice,
                profile_id=profile,
                deps=_build_tool_deps(body_motion_enabled=self._body_motion_enabled, profile_id=profile),
                on_assistant_audio=on_audio,
                on_turn_end=on_turn_end,
            )
        if backend == BACKEND_GEMINI:
            key = (
                api_key
                or self._cached_gemini_key
                or stored_config.get("gemini_api_key")
                or settings.gemini_api_key
                or ""
            )
            key = key.strip()
            if not key:
                await self._safe_send({
                    "type": "error",
                    "message": "GEMINI_API_KEY missing — set ZERO_GEMINI_API_KEY or pass api_key in start",
                })
                return None
            self._cached_gemini_key = key
            return GeminiLiveHandler(
                api_key=key,
                model=model,
                voice=voice,
                profile_id=profile,
                deps=_build_tool_deps(body_motion_enabled=self._body_motion_enabled, profile_id=profile),
                on_assistant_audio=on_audio,
                on_turn_end=on_turn_end,
            )
        if backend == BACKEND_LOCAL:
            return LocalRealtimeHandler(
                model=model,
                voice=voice,
                profile_id=profile,
                deps=_build_tool_deps(body_motion_enabled=self._body_motion_enabled, profile_id=profile),
                on_assistant_audio=on_audio,
                on_turn_end=on_turn_end,
            )
        await self._safe_send({"type": "error", "message": f"unknown backend: {backend}"})
        return None

    async def _handle_swap_backend(self, msg: dict) -> None:
        """Hot-swap to a different backend / voice / model / persona while
        keeping the WS, speaker sink, and head wobbler alive. The browser
        side keeps mic stream + transcript history. Tier-2 memory persists
        across the swap so the new handler inherits relationship context."""
        if self.handler is None:
            await self._safe_send({"type": "error", "message": "no active session to swap"})
            return

        settings = get_settings()
        backend = normalize_backend(msg.get("backend") or self._current_backend)
        explicit_model = (msg.get("model") or "").strip() or None
        explicit_voice = (msg.get("voice") or "").strip() or None
        profile = msg.get("profile") or self._current_profile or settings.reachy_realtime_profile

        persona_model: Optional[str] = None
        persona_voice: Optional[str] = None
        try:
            from app.services.reachy_realtime.profiles import get_profile
            prof = get_profile(profile)
            persona_model = prof.model
            persona_voice = prof.voice
        except Exception as e:
            logger.debug("realtime_profile_lookup_failed", error=str(e))

        if backend == BACKEND_LOCAL:
            model = resolve_model(
                backend,
                explicit_model or persona_model or settings.reachy_realtime_model,
            )
        else:
            model = resolve_model(backend, explicit_model or settings.reachy_realtime_model)
        voice = explicit_voice or persona_voice or settings.reachy_realtime_voice

        async def _on_audio(pcm_bytes: bytes, rate: int) -> None:
            self._mark_assistant_audio_playing()
            if self._wobbler is not None:
                try:
                    await self._wobbler.feed_pcm16(pcm_bytes, sample_rate=rate)
                except Exception:
                    pass
            if self._speaker_sink is not None:
                try:
                    await asyncio.wait_for(
                        self._speaker_sink.write_pcm(pcm_bytes, rate),
                        timeout=_SPEAKER_WRITE_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    message = "Reachy speaker write timed out; queued audio may be backing up."
                    self._output_health.update({
                        "ready": False,
                        "last_error": message,
                    })
                    await self._safe_send({
                        "type": "error",
                        "code": "speaker_backpressure",
                        "message": message,
                    })
                    await self._set_phase("stalled", reason="speaker_backpressure")
                except Exception as e:
                    self._output_health.update({
                        "ready": False,
                        "last_error": f"speaker write failed: {e}",
                    })

        async def _on_turn_end() -> None:
            if self._wobbler is not None:
                self._wobbler.request_reset_after_current_audio()

        new_handler = await self._build_handler(
            backend=backend,
            model=model,
            voice=voice,
            profile=profile,
            api_key=(msg.get("api_key") or "").strip() or None,
            on_audio=_on_audio,
            on_turn_end=_on_turn_end,
        )
        if new_handler is None:
            return  # error emitted

        # Tear down the current handler WITHOUT touching speaker sink /
        # wobbler / WS — that's the whole point of the hot-swap.
        old_handler = self.handler
        self.handler = new_handler  # do this first so _run_handler's finally block doesn't emit session.closed for the old one
        try:
            await old_handler.stop()
        except Exception:
            pass
        if self._handler_task and not self._handler_task.done():
            self._handler_task.cancel()
            try:
                await self._handler_task
            except (asyncio.CancelledError, Exception):
                pass

        # Flush the speaker so the tail of the old reply doesn't bleed.
        if self._speaker_sink is not None:
            try:
                await self._speaker_sink.flush()
            except Exception:
                pass

        self._current_profile = profile
        self._current_backend = backend
        self._handler_task = asyncio.create_task(
            self._run_handler(new_handler), name=f"realtime-{backend}"
        )
        if self._input_source in ("reachy", "host_agent"):
            if self._host_mic_task and not self._host_mic_task.done():
                self._host_mic_task.cancel()
                try:
                    await self._host_mic_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self._host_mic_ws is not None:
                try:
                    await self._host_mic_ws.close()
                except Exception:
                    pass
                self._host_mic_ws = None
            input_rate = 16000 if backend in (BACKEND_LOCAL, BACKEND_GEMINI) else 24000
            self._host_mic_task = asyncio.create_task(
                self._run_host_mic_source(rate=input_rate),
                name="realtime-host-mic",
            )
        await self._safe_send({
            "type": "backend_swapped",
            "backend": backend,
            "model": model,
            "voice": voice,
            "profile": profile,
        })

    async def _run_host_mic_source(self, *, rate: int) -> None:
        settings = get_settings()
        host_agent_url = settings.host_agent_url or "http://host.docker.internal:18796"
        url = host_agent_url.rstrip("/")
        if url.startswith("https://"):
            url = "wss://" + url[len("https://"):]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://"):]
        elif not url.startswith(("ws://", "wss://")):
            url = "ws://" + url
        url = f"{url}/mic/stream"
        capture_rate = 16000
        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, max_size=None, ping_interval=20),
                timeout=10.0,
            )
            self._host_mic_ws = ws
            await ws.send(_json_dumps({
                "type": "start",
                "rate": capture_rate,
                "frame_ms": 30,
                "pause_wake": True,
            }))
            async for raw in ws:
                try:
                    import json
                    evt = json.loads(raw)
                except Exception:
                    continue
                etype = evt.get("type")
                if etype == "ready":
                    self._host_mic_ready = True
                    await self._safe_send({
                        "type": "input.ready",
                        "source": "reachy_mic",
                        "device_name": evt.get("device_name"),
                        "rate": rate,
                        "capture_rate": evt.get("rate"),
                        "wake_paused": evt.get("wake_paused"),
                    })
                    logger.info(
                        "realtime_host_mic_connected",
                        device=evt.get("device_name"),
                        capture_rate=evt.get("rate"),
                        provider_rate=rate,
                    )
                    continue
                if etype == "error":
                    raw_message = str(evt.get("message") or "Reachy mic stream failed")
                    message = _user_facing_mic_error(raw_message, source="reachy_mic")
                    self._input_health.update({
                        "source": "reachy_mic",
                        "ready": False,
                        "confidence_state": "no_signal",
                        "suggested_action": "switch_to_browser_mic",
                        "last_error": message,
                    })
                    await self._safe_send({
                        "type": "error",
                        "code": "input_unavailable",
                        "message": message,
                    })
                    logger.warning("realtime_host_mic_error", error=raw_message)
                    continue
                if etype != "audio" or self._input_muted or self._host_mic_suppressed():
                    continue
                b64 = evt.get("audio_b64") or ""
                if not b64 or self.handler is None:
                    continue
                try:
                    pcm = base64.b64decode(b64)
                    source_rate = int(evt.get("rate") or capture_rate)
                    warning = self._observe_input_frame(
                        source="reachy_mic",
                        rms=float(evt.get("rms") or 0.0),
                        peak=float(evt.get("peak") or 0.0),
                        overflowed=bool(evt.get("overflowed")),
                    )
                    if warning:
                        await self._safe_send(warning)
                    await self._emit_health()
                    await self.handler.feed_pcm(
                        _resample_pcm16(pcm, from_rate=source_rate, to_rate=rate)
                    )
                except Exception as e:
                    logger.debug("realtime_host_mic_feed_failed", error=str(e))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            raw_message = str(e)
            message = _user_facing_mic_error(raw_message, source="reachy_mic")
            logger.warning("realtime_host_mic_failed", url=url, error=raw_message)
            self._input_health.update({
                "source": "reachy_mic",
                "ready": False,
                "confidence_state": "no_signal",
                "suggested_action": "switch_to_browser_mic",
                "last_error": message,
            })
            await self._safe_send({
                "type": "error",
                "code": "input_unavailable",
                "message": message,
            })
        finally:
            self._host_mic_ready = False
            ws = self._host_mic_ws
            self._host_mic_ws = None
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    async def _handle_audio(self, msg: dict) -> None:
        if not self.handler:
            return
        b64 = msg.get("audio_b64") or ""
        if not b64:
            return
        try:
            pcm = base64.b64decode(b64)
        except Exception:
            return
        stats = _pcm16_stats_norm(pcm)
        warning = self._observe_input_frame(
            source="browser_mic",
            rms=stats["rms"],
            peak=stats["peak"],
        )
        if warning:
            await self._safe_send(warning)
        await self._emit_health()
        await self.handler.feed_pcm(pcm)

    async def recover(self, *, reason: str = "manual") -> dict[str, Any]:
        """Recover a stuck voice turn without closing the browser WebSocket."""
        await self._set_phase("recovering", reason=reason)
        actions: list[dict[str, Any]] = []
        if self.handler is not None:
            try:
                await self.handler.cancel_response()
                actions.append({"id": "cancel_response", "ok": True})
            except Exception as e:
                actions.append({"id": "cancel_response", "ok": False, "error": str(e)})
            reset = getattr(self.handler, "recover", None)
            if callable(reset):
                try:
                    result = await reset(reason=reason)
                    actions.append({"id": "handler_recover", "ok": True, "result": result})
                except Exception as e:
                    actions.append({"id": "handler_recover", "ok": False, "error": str(e)})
        if self._speaker_sink is not None:
            try:
                await self._speaker_sink.flush()
                actions.append({"id": "speaker_flush", "ok": True})
            except Exception as e:
                actions.append({"id": "speaker_flush", "ok": False, "error": str(e)})
        try:
            motion = await self.suspend_motion(reason=f"recover:{reason}")
            actions.append({"id": "suspend_motion", "ok": True, "result": motion})
        except Exception as e:
            actions.append({"id": "suspend_motion", "ok": False, "error": str(e)})
        self._tool_count = 0
        self._stalled_reason = None
        self._input_health["last_error"] = None
        self._input_health["suggested_action"] = None
        self._input_no_signal_since = None
        self._last_input_warning_at = 0.0
        await self._safe_send({"type": "audio.cancelled"})
        await self._set_phase("listening")
        return {"ok": True, "reason": reason, "actions": actions, **self.health_snapshot()}

    async def _cleanup(self) -> None:
        if self.handler:
            try:
                await self.handler.stop()
            except Exception:
                pass
        if self._handler_task and not self._handler_task.done():
            self._handler_task.cancel()
            try:
                await self._handler_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._host_mic_task and not self._host_mic_task.done():
            self._host_mic_task.cancel()
            try:
                await self._host_mic_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._host_mic_ws is not None:
            try:
                await self._host_mic_ws.close()
            except Exception:
                pass
            self._host_mic_ws = None
        if self._speaker_sink_task and not self._speaker_sink_task.done():
            self._speaker_sink_task.cancel()
            try:
                await self._speaker_sink_task
            except (asyncio.CancelledError, Exception):
                pass
            self._speaker_sink_task = None
        if self._wobbler is not None:
            try:
                await self._wobbler.stop()
            except Exception:
                pass
            self._wobbler = None
        if self._speaker_sink is not None:
            try:
                await self._speaker_sink.close()
            except Exception:
                pass
            self._speaker_sink = None

    async def _safe_send(self, event: dict) -> None:
        try:
            await self.ws.send_json(event)
        except Exception as e:
            logger.debug("realtime_ws_send_failed", event_type=event.get("type"), error=str(e))
