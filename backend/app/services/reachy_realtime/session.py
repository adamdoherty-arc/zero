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
import time
from typing import Any, Optional, Union

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
)
from app.services.reachy_realtime.gemini_handler import GeminiLiveHandler
from app.services.reachy_realtime.head_wobbler import AsyncHeadWobbler, Offsets
from app.services.reachy_realtime.local_handler import LocalRealtimeHandler
from app.services.reachy_realtime.openai_handler import OpenAIRealtimeHandler

logger = structlog.get_logger()


Handler = Union[OpenAIRealtimeHandler, GeminiLiveHandler, LocalRealtimeHandler]


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
        # Zero's daemon does not expose a head-tracking toggle endpoint today.
        # Record intent so the voice loop can mirror it elsewhere later.
        return {"ok": True, "enabled": enabled, "note": "head tracking handled client-side"}

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
        # host_agent_url is something like "http://host.docker.internal:18794".
        # Convert to ws:// for the streaming endpoint.
        url = host_agent_url.rstrip("/")
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

    async def connect(self, *, rate: int) -> bool:
        """Open the WS and send the start handshake. Returns True on success."""
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.url, max_size=None, ping_interval=20),
                timeout=3.0,
            )
            await self._ws.send(_json_dumps({"type": "start", "rate": rate}))
            self._connected_rate = rate
            logger.info("reachy_speaker_sink_connected", url=self.url, rate=rate)
            return True
        except Exception as e:
            logger.warning("reachy_speaker_sink_connect_failed", url=self.url, error=str(e))
            self._ws = None
            return False

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


class RealtimeSession:
    """Owns one active handler + WebSocket, dies when either side closes."""

    def __init__(self, ws: WebSocket, *, enable_head_wobble: bool = True) -> None:
        self.ws = ws
        self.handler: Optional[Handler] = None
        self._handler_task: Optional[asyncio.Task[None]] = None
        self._wobbler: Optional[AsyncHeadWobbler] = None
        self._enable_head_wobble = enable_head_wobble
        self._speaker_sink: Optional[ReachySpeakerSink] = None
        # Last-known session shape — preserved across hot-swaps so the
        # frontend can swap backends without re-sending profile / api_keys.
        self._current_profile: Optional[str] = None
        self._current_backend: Optional[str] = None
        self._cached_openai_key: Optional[str] = None
        self._cached_gemini_key: Optional[str] = None

    async def run(self) -> None:
        await self.ws.accept()
        try:
            await self._run_loop()
        except WebSocketDisconnect:
            pass
        finally:
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
            elif mtype == "stop":
                await self._safe_send({"type": "session.closed"})
                return

    async def _handle_start(self, msg: dict) -> None:
        if self.handler is not None:
            await self._safe_send({"type": "error", "message": "session already started"})
            return

        settings = get_settings()
        backend = normalize_backend(msg.get("backend") or settings.reachy_realtime_backend)
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
            model = explicit_model or persona_model or settings.reachy_realtime_model
        else:
            model = explicit_model or settings.reachy_realtime_model
        voice = explicit_voice or persona_voice or settings.reachy_realtime_voice

        # Wire the assistant-audio fan-out: head wobbler (visual) + Reachy
        # USB speaker (audible). Both are best-effort; if either fails we
        # keep the session alive — the browser still has a copy of the
        # audio.delta stream as a fallback.
        if self._enable_head_wobble:
            self._wobbler = AsyncHeadWobbler(apply_offsets=_build_wobbler_apply())
            await self._wobbler.start()

        # Open a streaming PCM sink to host_agent so the robot speaks out
        # loud. host_agent owns the Reachy USB output device.
        host_agent_url = settings.host_agent_url or "http://host.docker.internal:18794"
        try:
            sink = ReachySpeakerSink(host_agent_url)
            # OpenAI realtime emits 24 kHz mono; Gemini Live also emits 24 kHz
            # for output. The sink resamples on the host if the device
            # prefers a different rate.
            if await sink.connect(rate=24000):
                self._speaker_sink = sink
            else:
                self._speaker_sink = None
        except Exception as e:
            logger.warning("reachy_speaker_sink_init_failed", error=str(e))
            self._speaker_sink = None

        async def _on_audio(pcm_bytes: bytes, rate: int) -> None:
            if self._wobbler is not None:
                try:
                    await self._wobbler.feed_pcm16(pcm_bytes, sample_rate=rate)
                except Exception as e:
                    logger.debug("wobbler_feed_failed", error=str(e))
            if self._speaker_sink is not None:
                try:
                    await self._speaker_sink.write_pcm(pcm_bytes, rate)
                except Exception as e:
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

    def _make_client_writer(self):
        async def _client_writer(event: dict) -> None:
            etype = event.get("type")
            if (
                etype in ("user.speech_started", "audio.cancelled", "user.interrupt")
                and self._speaker_sink is not None
            ):
                try:
                    await self._speaker_sink.flush()
                except Exception:
                    pass
            await self._safe_send(event)
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
        if backend == BACKEND_OPENAI:
            key = api_key or self._cached_openai_key or settings.openai_api_key or ""
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
                deps=ToolDependencies(motion=build_motion_dispatcher()),
                on_assistant_audio=on_audio,
                on_turn_end=on_turn_end,
            )
        if backend == BACKEND_GEMINI:
            key = api_key or self._cached_gemini_key or settings.gemini_api_key or ""
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
                deps=ToolDependencies(motion=build_motion_dispatcher()),
                on_assistant_audio=on_audio,
                on_turn_end=on_turn_end,
            )
        if backend == BACKEND_LOCAL:
            return LocalRealtimeHandler(
                model=model,
                voice=voice,
                profile_id=profile,
                deps=ToolDependencies(motion=build_motion_dispatcher()),
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
            model = explicit_model or persona_model or settings.reachy_realtime_model
        else:
            model = explicit_model or settings.reachy_realtime_model
        voice = explicit_voice or persona_voice or settings.reachy_realtime_voice

        async def _on_audio(pcm_bytes: bytes, rate: int) -> None:
            if self._wobbler is not None:
                try:
                    await self._wobbler.feed_pcm16(pcm_bytes, sample_rate=rate)
                except Exception:
                    pass
            if self._speaker_sink is not None:
                try:
                    await self._speaker_sink.write_pcm(pcm_bytes, rate)
                except Exception:
                    pass

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
        await self._safe_send({
            "type": "backend_swapped",
            "backend": backend,
            "model": model,
            "voice": voice,
            "profile": profile,
        })

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
        await self.handler.feed_pcm(pcm)

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
