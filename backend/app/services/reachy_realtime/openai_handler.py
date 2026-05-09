"""
OpenAI Realtime handler — raw WebSocket port of
``reachy_mini_conversation_app.openai_realtime.OpenaiRealtimeHandler``.

The upstream handler subclasses fastrtc's ``AsyncStreamHandler`` and uses the
``openai`` SDK's ``realtime.connect()``. Zero's bridge is a plain FastAPI
WebSocket endpoint, so this class:

- Talks to OpenAI via the raw WebSocket at
  ``wss://api.openai.com/v1/realtime?model=...`` — no SDK version coupling.
- Exposes ``feed_pcm(int16_mono_pcm)`` for inbound audio (browser mic) and
  emits events through a ``ClientWriter`` callback (goes back to the browser).
- Keeps the upstream tool-call plumbing, partial-transcript debouncer, idle
  signal, response-in-progress guard, cost tracking, and API-key fallback.

Audio format (same as upstream):
  Input:  PCM16, 24 kHz, mono
  Output: PCM16, 24 kHz, mono

Upstream source:
https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/main/src/reachy_mini_conversation_app/openai_realtime.py
Apache 2.0.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

import structlog
import websockets

from app.services.reachy_realtime import tools as tool_registry
from app.services.reachy_realtime.bg_tool_manager import (
    BackgroundToolManager,
    ToolNotification,
)
from app.services.reachy_realtime.common import (
    BACKEND_OPENAI,
    ToolDependencies,
    resolve_model,
    resolve_voice,
)
from app.services.reachy_realtime.profiles import (
    get_profile,
    resolve_instructions,
    resolve_tools,
)
from app.services.reachy_realtime.profiles import resolve_voice as resolve_profile_voice

logger = structlog.get_logger()

OPENAI_SAMPLE_RATE = 24000  # in + out

# 2026-02 API pricing for gpt-realtime ($/1M tokens).
_AUDIO_IN_COST_PER_1M = 32.0
_AUDIO_OUT_COST_PER_1M = 64.0
_TEXT_IN_COST_PER_1M = 4.0
_TEXT_OUT_COST_PER_1M = 16.0
_IMG_IN_COST_PER_1M = 5.0

_RESPONSE_DONE_TIMEOUT = 30.0

ClientWriter = Callable[[dict], Awaitable[None]]
AudioPCMCallback = Callable[[bytes, int], Awaitable[None]]  # (pcm_bytes, sample_rate)


def _compute_cost(usage: dict) -> float:
    inp = usage.get("input_token_details") or {}
    out = usage.get("output_token_details") or {}
    cost = 0.0
    cost += (inp.get("audio_tokens") or 0) * _AUDIO_IN_COST_PER_1M / 1e6
    cost += (inp.get("text_tokens") or 0) * _TEXT_IN_COST_PER_1M / 1e6
    cost += (inp.get("image_tokens") or 0) * _IMG_IN_COST_PER_1M / 1e6
    cost += (out.get("audio_tokens") or 0) * _AUDIO_OUT_COST_PER_1M / 1e6
    cost += (out.get("text_tokens") or 0) * _TEXT_OUT_COST_PER_1M / 1e6
    return cost


class OpenAIRealtimeHandler:
    """One OpenAI Realtime session.

    The owning ``RealtimeSession`` creates the handler, calls
    ``start(client_writer)``, then pushes browser mic PCM via ``feed_pcm``.
    The handler pushes audio deltas and events back through ``client_writer``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: Optional[str],
        voice: Optional[str],
        profile_id: Optional[str],
        deps: ToolDependencies,
        on_assistant_audio: Optional[AudioPCMCallback] = None,
        on_turn_end: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        self.api_key = api_key
        self.model = resolve_model(BACKEND_OPENAI, model)
        self.voice_override = voice
        self.profile_id = profile_id or "default"
        self.deps = deps
        self._on_assistant_audio = on_assistant_audio
        self._on_turn_end = on_turn_end

        self.tool_manager = BackgroundToolManager()

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._client_writer: Optional[ClientWriter] = None
        self._response_done_event = asyncio.Event()
        self._response_done_event.set()
        self._last_response_rejected = False
        self._pending_responses: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._response_sender_task: Optional[asyncio.Task[None]] = None
        self._receiver_task: Optional[asyncio.Task[None]] = None
        self._partial_task: Optional[asyncio.Task[None]] = None
        # Lower debounce = user's live caption updates faster ≈ lower perceived
        # turn-start latency. 100ms coalesces the burst of 20-40ms deltas
        # without feeling laggy; the upstream app used 500ms for low-bandwidth
        # deployments which does not apply to our local/Docker topology.
        self._partial_debounce_s = 0.1
        self._partial_chunks: dict[str, list[str]] = {}
        self._partial_item_id: Optional[str] = None

        self.is_idle_tool_call = False
        self.last_activity = time.monotonic()
        self.start_time = time.monotonic()
        self.cumulative_cost = 0.0
        self._stop = asyncio.Event()

    # -------------------- lifecycle --------------------

    async def start(self, client_writer: ClientWriter) -> None:
        """Connect to OpenAI, send the session config, run the receive loop."""
        self._client_writer = client_writer

        url = f"wss://api.openai.com/v1/realtime?model={self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Belt-and-suspenders timeout for the upstream WebSocket handshake.
        # Without it a stalled TLS connect could park the session for tens of
        # seconds per attempt — the browser used to show "Connecting…" forever
        # because it had no way to abort. The frontend hook also has a 12 s
        # watchdog; this just makes sure the backend doesn't leak the wait.
        connect_timeout_s = 10.0

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                ws_cm = websockets.connect(
                    url,
                    additional_headers=headers,
                    max_size=None,
                    ping_interval=20,
                )
                try:
                    ws = await asyncio.wait_for(ws_cm.__aenter__(), timeout=connect_timeout_s)
                except asyncio.TimeoutError:
                    logger.warning(
                        "openai_realtime_connect_timeout",
                        attempt=attempt,
                        timeout_s=connect_timeout_s,
                    )
                    if attempt < max_attempts:
                        delay = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                        await asyncio.sleep(delay)
                        continue
                    await self._emit_client({
                        "type": "error",
                        "message": (
                            f"OpenAI realtime handshake timed out after "
                            f"{connect_timeout_s:.0f}s. Check your key, "
                            f"network, or try Gemini Live."
                        ),
                    })
                    return
                try:
                    self._ws = ws
                    await self._send_session_update()
                    if not await self._await_session_update_ack():
                        return
                    await self.tool_manager.start_up(callbacks=[self._on_tool_complete])
                    self._response_sender_task = asyncio.create_task(
                        self._response_sender_loop(),
                        name="openai-response-sender",
                    )
                    await self._emit_client({"type": "session.ready", "model": self.model, "voice": self._voice()})
                    await self._receive_loop()
                finally:
                    try:
                        await ws_cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                return
            except (websockets.ConnectionClosed, OSError) as e:
                logger.warning("openai_realtime_closed", attempt=attempt, error=str(e))
                if attempt < max_attempts:
                    delay = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                    continue
                await self._emit_client({"type": "error", "message": f"OpenAI websocket closed: {e}"})
                raise
            finally:
                if self._response_sender_task:
                    self._response_sender_task.cancel()
                    try:
                        await self._response_sender_task
                    except asyncio.CancelledError:
                        pass
                    self._response_sender_task = None
                await self.tool_manager.shutdown()
                self._ws = None

    async def stop(self) -> None:
        self._stop.set()
        self._response_done_event.set()
        if self._partial_task and not self._partial_task.done():
            self._partial_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    # -------------------- inbound audio / control --------------------

    async def feed_pcm(self, pcm_bytes: bytes) -> None:
        """Browser → OpenAI: append PCM16 24 kHz mono frame(s)."""
        if not self._ws or not pcm_bytes:
            return
        try:
            await self._ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm_bytes).decode("ascii"),
            }))
        except Exception as e:
            logger.debug("openai_feed_pcm_dropped", error=str(e))

    async def commit_audio(self) -> None:
        if not self._ws:
            return
        try:
            await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        except Exception as e:
            logger.debug("openai_commit_audio_dropped", error=str(e))

    async def cancel_response(self) -> None:
        if not self._ws:
            return
        if self._response_done_event.is_set():
            logger.debug("openai_cancel_response_no_active_response")
            return
        try:
            await self._ws.send(json.dumps({"type": "response.cancel"}))
            self._response_done_event.set()
        except Exception as e:
            logger.debug("openai_cancel_response_dropped", error=str(e))

    async def send_text(self, text: str) -> None:
        """Push a text message as the user turn (useful for tests + push-to-type)."""
        if not self._ws:
            return
        await self._ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        }))
        await self._safe_response_create({})

    # -------------------- private: session config --------------------

    def _voice(self) -> str:
        return resolve_voice(
            BACKEND_OPENAI,
            self.voice_override or resolve_profile_voice(self.profile_id, BACKEND_OPENAI),
        )

    async def _send_session_update(self) -> None:
        """Initial ``session.update`` with instructions, tools, audio format."""
        instructions = resolve_instructions(self.profile_id)
        enabled = list(resolve_tools(self.profile_id))
        tool_specs = tool_registry.get_tool_specs(enabled=enabled)
        session = {
            "type": "realtime",
            "instructions": instructions,
            # Cap the model's output so a chatty turn doesn't keep the TTS
            # playback running for 10 s. Our persona prompt already asks for
            # 1-2 sentences; this is the enforcement layer. ~80 tokens ≈ 60
            # words ≈ ~18 s of speech max (usually cuts well before).
            "max_output_tokens": 80,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": OPENAI_SAMPLE_RATE},
                    "noise_reduction": {"type": "far_field"},
                    "transcription": {"model": "gpt-4o-transcribe", "language": "en"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.35,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 450,
                        "create_response": True,
                        "interrupt_response": True,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": OPENAI_SAMPLE_RATE},
                    "voice": self._voice(),
                },
            },
            "tools": tool_specs,
            "tool_choice": "auto",
        }
        if self._ws:
            await self._ws.send(json.dumps({"type": "session.update", "session": session}))
        logger.info("openai_realtime_session_update", profile=self.profile_id, voice=self._voice(), tools=len(tool_specs))

    async def _await_session_update_ack(self) -> bool:
        """Wait for OpenAI to accept session.update before the UI shows ready."""
        if self._ws is None:
            return False
        deadline_s = 8.0
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=deadline_s)
            except asyncio.TimeoutError:
                await self._emit_client({
                    "type": "error",
                    "message": "OpenAI realtime session configuration timed out before it became ready.",
                })
                return False
            except websockets.ConnectionClosed as e:
                await self._emit_client({"type": "error", "message": f"OpenAI websocket closed during setup: {e}"})
                return False

            try:
                event = json.loads(raw)
            except Exception:
                continue

            etype = event.get("type", "")
            if etype == "session.updated":
                return True
            if etype == "error":
                await self._handle_event(event)
                return False
            if etype == "session.created":
                continue
            await self._handle_event(event)
        return False

    # -------------------- private: receive loop --------------------

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if self._stop.is_set():
                    break
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                await self._handle_event(event)
        except websockets.ConnectionClosed:
            return

    async def _handle_event(self, event: dict) -> None:
        etype = event.get("type", "")

        if etype == "input_audio_buffer.speech_started":
            await self._emit_client({"type": "user.speech_started"})
            return

        if etype == "input_audio_buffer.speech_stopped":
            await self._emit_client({"type": "user.speech_stopped"})
            return

        if etype == "response.created":
            self._response_done_event.clear()
            return

        if etype == "response.done":
            self._response_done_event.set()
            usage = (event.get("response") or {}).get("usage") or {}
            if usage:
                cost = _compute_cost(usage)
                self.cumulative_cost += cost
                await self._emit_client({"type": "usage", "cost_usd": cost, "cumulative_usd": self.cumulative_cost})
            return

        if etype in (
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.partial",
        ):
            item_id = event.get("item_id")
            delta = event.get("delta") or event.get("transcript") or ""
            if item_id is None:
                return
            if self._partial_item_id != item_id:
                self._partial_item_id = item_id
                self._partial_chunks[item_id] = [delta]
            else:
                self._partial_chunks.setdefault(item_id, []).append(delta)
            await self._schedule_partial(item_id)
            return

        if etype == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            self._partial_item_id = None
            await self._emit_client({"type": "transcript", "role": "user", "content": transcript})
            return

        if etype == "response.output_audio_transcript.done":
            transcript = event.get("transcript", "")
            await self._emit_client({"type": "transcript", "role": "assistant", "content": transcript})
            return

        if etype == "response.output_audio.delta":
            self.last_activity = time.monotonic()
            delta_b64 = event.get("delta", "")
            await self._emit_client({
                "type": "audio.delta",
                "format": "pcm16",
                "rate": OPENAI_SAMPLE_RATE,
                "audio_b64": delta_b64,
            })
            if self._on_assistant_audio and delta_b64:
                try:
                    pcm_bytes = base64.b64decode(delta_b64)
                    await self._on_assistant_audio(pcm_bytes, OPENAI_SAMPLE_RATE)
                except Exception as e:
                    logger.debug("openai_on_assistant_audio_failed", error=str(e))
            return

        if etype == "response.output_audio.done":
            await self._emit_client({"type": "audio.done"})
            if self._on_turn_end:
                try:
                    await self._on_turn_end()
                except Exception as e:
                    logger.debug("openai_on_turn_end_failed", error=str(e))
            return

        if etype == "response.function_call_arguments.done":
            tool_name = event.get("name")
            args_json = event.get("arguments") or "{}"
            call_id = str(event.get("call_id") or uuid.uuid4())
            if not isinstance(tool_name, str):
                return
            await self._dispatch_tool(tool_name, args_json, call_id)
            return

        if etype == "error":
            err = event.get("error") or {}
            code = err.get("code", "")
            msg = err.get("message", "unknown error")
            if code == "conversation_already_has_active_response":
                self._last_response_rejected = True
                return
            if code in ("input_audio_buffer_commit_empty", "response_cancel_not_active"):
                logger.debug("openai_realtime_benign_error", code=code, message=msg)
                return
            logger.error("openai_realtime_error", code=code, message=msg)
            if code not in ("input_audio_buffer_commit_empty",):
                await self._emit_client({"type": "error", "code": code, "message": msg})

    async def _schedule_partial(self, item_id: str) -> None:
        if self._partial_task and not self._partial_task.done():
            self._partial_task.cancel()
            try:
                await self._partial_task
            except asyncio.CancelledError:
                pass

        chunks_snapshot = list(self._partial_chunks.get(item_id, []))
        partial = "".join(chunks_snapshot)
        seq = len(chunks_snapshot) - 1

        async def _emit() -> None:
            try:
                await asyncio.sleep(self._partial_debounce_s)
                if self._partial_item_id == item_id and (
                    len(self._partial_chunks.get(item_id, [])) - 1 == seq
                ):
                    await self._emit_client(
                        {"type": "transcript.partial", "role": "user", "content": partial}
                    )
            except asyncio.CancelledError:
                pass

        self._partial_task = asyncio.create_task(_emit(), name="openai-partial-emit")

    # -------------------- private: response sender --------------------

    async def _safe_response_create(self, params: dict) -> None:
        await self._pending_responses.put(params)

    async def _response_sender_loop(self) -> None:
        while not self._stop.is_set():
            try:
                params = await self._pending_responses.get()
            except asyncio.CancelledError:
                return

            sent = False
            attempts = 0
            while not sent and self._ws is not None and attempts < 5:
                try:
                    await asyncio.wait_for(self._response_done_event.wait(), timeout=_RESPONSE_DONE_TIMEOUT)
                except asyncio.TimeoutError:
                    self._response_done_event.set()

                if self._ws is None:
                    break

                self._last_response_rejected = False
                try:
                    await self._ws.send(json.dumps({
                        "type": "response.create",
                        "response": params,
                    }))
                except Exception as e:
                    logger.debug("openai_response_create_failed", error=str(e))
                    self._response_done_event.set()
                    break

                try:
                    await asyncio.wait_for(self._response_done_event.wait(), timeout=_RESPONSE_DONE_TIMEOUT)
                except asyncio.TimeoutError:
                    self._response_done_event.set()
                    break

                if self._last_response_rejected:
                    attempts += 1
                    continue
                sent = True

    # -------------------- private: tool plumbing --------------------

    async def _dispatch_tool(self, tool_name: str, args_json: str, call_id: str) -> None:
        await self._emit_client({
            "type": "tool.start",
            "tool_name": tool_name,
            "call_id": call_id,
            "args": args_json,
        })
        deps = self.deps
        mgr = self.tool_manager

        async def _routine(_mgr: BackgroundToolManager) -> dict:
            return await tool_registry.dispatch(tool_name, args_json, deps, _mgr)

        await self.tool_manager.start_tool(
            call_id=call_id,
            tool_name=tool_name,
            routine=_routine,
            is_idle_tool_call=self.is_idle_tool_call,
        )
        if self.is_idle_tool_call:
            self.is_idle_tool_call = False

    async def _on_tool_complete(self, note: ToolNotification) -> None:
        tool_result: dict[str, Any]
        if note.error is not None:
            tool_result = {"error": note.error}
        elif note.result is not None:
            tool_result = note.result
        else:
            tool_result = {"error": "No result returned from tool execution"}

        status = "failed" if isinstance(tool_result, dict) and tool_result.get("error") else note.status.value
        await self._emit_client({
            "type": "tool.end",
            "tool_name": note.tool_name,
            "call_id": note.id,
            "result": tool_result,
            "status": status,
        })

        if self._ws is None:
            return

        try:
            await self._ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": note.id,
                    "output": json.dumps(tool_result),
                },
            }))
            # Camera tool returns a JPEG base64 — also push it as an input_image
            # so the model can reason about pixels, matching upstream behaviour.
            if note.tool_name == "camera" and isinstance(tool_result, dict) and "b64_im" in tool_result:
                b64 = tool_result["b64_im"]
                if isinstance(b64, str):
                    await self._ws.send(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{
                                "type": "input_image",
                                "image_url": f"data:image/jpeg;base64,{b64}",
                            }],
                        },
                    }))
            if not note.is_idle_tool_call:
                await self._safe_response_create({
                    "instructions": (
                        "Use the tool result just returned and answer concisely in spoken English. "
                        "Do not say or output bracketed emotion tags, dance tags, JSON, or markdown."
                    ),
                })
        except websockets.ConnectionClosed:
            return

    async def _emit_client(self, event: dict) -> None:
        if self._client_writer is None:
            return
        try:
            await self._client_writer(event)
        except Exception as e:
            logger.debug("client_writer_failed", event_type=event.get("type"), error=str(e))
