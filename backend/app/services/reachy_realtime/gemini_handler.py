"""
Gemini Live handler — port of
``reachy_mini_conversation_app.gemini_live.GeminiLiveHandler``.

Uses the ``google-genai`` SDK's Live API (``client.aio.live.connect``) that
Zero already ships (it's the same SDK powering the text Gemini provider in
``llm_providers/gemini_provider.py``). The upstream fastrtc stream handler is
replaced by a WebSocket-bridge shape identical to
``OpenAIRealtimeHandler`` — same ``feed_pcm``, same event protocol to the
browser.

Audio format (per Gemini Live spec):
  Input:  PCM16, 16 kHz, mono
  Output: PCM16, 24 kHz, mono

Upstream source:
https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/main/src/reachy_mini_conversation_app/gemini_live.py
Apache 2.0.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from app.services.reachy_realtime import tools as tool_registry
from app.services.reachy_realtime.bg_tool_manager import (
    BackgroundToolManager,
    ToolNotification,
)
from app.services.reachy_realtime.common import (
    BACKEND_GEMINI,
    DEFAULT_VOICE_BY_BACKEND,
    GEMINI_AVAILABLE_VOICES,
    ToolDependencies,
    resolve_model,
)
from app.services.reachy_realtime.profiles import (
    resolve_instructions,
    resolve_tools,
    resolve_voice as resolve_profile_voice,
)

logger = structlog.get_logger()

GEMINI_INPUT_SAMPLE_RATE = 16000
GEMINI_OUTPUT_SAMPLE_RATE = 24000

ClientWriter = Callable[[dict], Awaitable[None]]
AudioPCMCallback = Callable[[bytes, int], Awaitable[None]]


def _openai_specs_to_gemini(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI ``{type,name,description,parameters}`` → Gemini function_declarations.

    Gemini expects uppercase JSON Schema types and rejects ``additionalProperties``.
    Same transform the upstream applies.
    """
    declarations: List[Dict[str, Any]] = []
    for s in specs:
        decl: Dict[str, Any] = {"name": s["name"]}
        if "description" in s:
            decl["description"] = s["description"]
        if "parameters" in s and s["parameters"]:
            decl["parameters"] = _convert_schema(s["parameters"])
        declarations.append(decl)
    return declarations


_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _convert_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    t = out.get("type")
    if isinstance(t, str):
        out["type"] = _TYPE_MAP.get(t.lower(), t.upper())
    if isinstance(out.get("properties"), dict):
        out["properties"] = {k: _convert_schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = _convert_schema(out["items"])
    out.pop("additionalProperties", None)
    return out


def _resolve_gemini_voice(profile_voice: str) -> str:
    pool = {v.lower(): v for v in GEMINI_AVAILABLE_VOICES}
    return pool.get(profile_voice.lower(), DEFAULT_VOICE_BY_BACKEND[BACKEND_GEMINI])


class GeminiLiveHandler:
    """One Gemini Live session, wired through the browser WebSocket bridge."""

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
        self.model = resolve_model(BACKEND_GEMINI, model)
        self.voice_override = voice
        self.profile_id = profile_id or "default"
        self.deps = deps
        self._on_assistant_audio = on_assistant_audio
        self._on_turn_end = on_turn_end
        self.tool_manager = BackgroundToolManager()

        self._client: Any = None
        self._session: Any = None
        self._client_writer: Optional[ClientWriter] = None
        self._stop = asyncio.Event()
        self._pending_user_chunks: list[str] = []
        self._pending_assistant_chunks: list[str] = []
        self._listening = False
        self.is_idle_tool_call = False
        self.last_activity = time.monotonic()
        self.start_time = time.monotonic()

    async def start(self, client_writer: ClientWriter) -> None:
        try:
            from google import genai  # lazy import
        except ImportError as e:
            raise RuntimeError(f"google-genai not installed: {e}") from e

        self._client_writer = client_writer
        self._client = genai.Client(api_key=self.api_key)

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                await self._run_session()
                return
            except Exception as e:
                logger.warning("gemini_live_closed", attempt=attempt, error=str(e))
                if attempt < max_attempts:
                    delay = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                    continue
                await self._emit_client({"type": "error", "message": f"Gemini Live failed: {e}"})
                raise

    async def stop(self) -> None:
        self._stop.set()
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass

    async def feed_pcm(self, pcm_bytes: bytes) -> None:
        """Browser → Gemini: raw PCM16 16kHz frames wrapped as Blob."""
        from google.genai import types as gtypes  # lazy
        if not self._session or not pcm_bytes:
            return
        try:
            await self._session.send_realtime_input(
                audio=gtypes.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000"),
            )
        except Exception as e:
            logger.debug("gemini_feed_pcm_dropped", error=str(e))

    async def commit_audio(self) -> None:
        # Gemini handles VAD server-side; explicit commit is a no-op.
        return

    async def cancel_response(self) -> None:
        # Handled by Gemini's interrupt detection when new user audio arrives.
        return

    async def send_text(self, text: str) -> None:
        if not self._session:
            return
        try:
            await self._session.send_realtime_input(text=text)
        except Exception as e:
            logger.debug("gemini_send_text_failed", error=str(e))

    # -------------------- session --------------------

    def _voice(self) -> str:
        v = self.voice_override or resolve_profile_voice(self.profile_id, BACKEND_GEMINI)
        return _resolve_gemini_voice(v)

    def _build_config(self):
        from google.genai import types as gtypes

        instructions = resolve_instructions(self.profile_id)
        enabled = list(resolve_tools(self.profile_id))
        tool_specs = tool_registry.get_tool_specs(enabled=enabled)
        function_declarations = _openai_specs_to_gemini(tool_specs)
        tools_config: List[Dict[str, Any]] = []
        if function_declarations:
            tools_config.append({"function_declarations": function_declarations})

        return gtypes.LiveConnectConfig(
            response_modalities=[gtypes.Modality.AUDIO],
            system_instruction=gtypes.Content(parts=[gtypes.Part(text=instructions)]),
            speech_config=gtypes.SpeechConfig(
                voice_config=gtypes.VoiceConfig(
                    prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(voice_name=self._voice()),
                ),
            ),
            tools=tools_config,
            input_audio_transcription=gtypes.AudioTranscriptionConfig(),
            output_audio_transcription=gtypes.AudioTranscriptionConfig(),
        )

    async def _run_session(self) -> None:
        config = self._build_config()
        # Same belt-and-suspenders timeout as the OpenAI handler: don't park
        # the upstream WebSocket handshake. The frontend hook also has a
        # 12 s watchdog; this prevents a stalled connect from leaking on the
        # backend side.
        connect_timeout_s = 10.0
        cm = self._client.aio.live.connect(model=self.model, config=config)
        try:
            session = await asyncio.wait_for(cm.__aenter__(), timeout=connect_timeout_s)
        except asyncio.TimeoutError:
            logger.warning("gemini_live_connect_timeout", timeout_s=connect_timeout_s)
            await self._emit_client({
                "type": "error",
                "message": (
                    f"Gemini Live handshake timed out after "
                    f"{connect_timeout_s:.0f}s. Check your key, network, "
                    f"or try OpenAI Realtime."
                ),
            })
            raise
        try:
            self._session = session
            await self.tool_manager.start_up(callbacks=[self._on_tool_complete])
            await self._emit_client({
                "type": "session.ready",
                "model": self.model,
                "voice": self._voice(),
            })
            try:
                while not self._stop.is_set():
                    async for response in session.receive():
                        if self._stop.is_set():
                            break
                        await self._on_response(response)
            finally:
                await self.tool_manager.shutdown()
                self._session = None
        finally:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass

    async def _on_response(self, response: Any) -> None:
        sc = getattr(response, "server_content", None)
        if sc is not None:
            if getattr(sc, "interrupted", False):
                await self._flush("assistant", self._pending_assistant_chunks)
                self._listening = True
                await self._emit_client({"type": "user.interrupt"})

            mt = getattr(sc, "model_turn", None)
            if mt is not None and getattr(mt, "parts", None):
                for part in mt.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        data = inline.data
                        if isinstance(data, str):
                            audio_bytes = base64.b64decode(data)
                        else:
                            audio_bytes = bytes(data)
                        if audio_bytes:
                            self.last_activity = time.monotonic()
                            await self._emit_client({
                                "type": "audio.delta",
                                "format": "pcm16",
                                "rate": GEMINI_OUTPUT_SAMPLE_RATE,
                                "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
                            })
                            if self._on_assistant_audio:
                                try:
                                    await self._on_assistant_audio(audio_bytes, GEMINI_OUTPUT_SAMPLE_RATE)
                                except Exception as e:
                                    logger.debug("gemini_on_assistant_audio_failed", error=str(e))

            it = getattr(sc, "input_transcription", None)
            if it is not None and getattr(it, "text", None):
                self._pending_user_chunks.append(it.text)
                if not self._listening:
                    self._listening = True
                    await self._emit_client({"type": "user.speech_started"})

            ot = getattr(sc, "output_transcription", None)
            if ot is not None and getattr(ot, "text", None):
                self._pending_assistant_chunks.append(ot.text)

            if getattr(sc, "turn_complete", False):
                await self._flush("user", self._pending_user_chunks)
                await self._flush("assistant", self._pending_assistant_chunks)
                self._listening = False
                await self._emit_client({"type": "audio.done"})
                if self._on_turn_end:
                    try:
                        await self._on_turn_end()
                    except Exception as e:
                        logger.debug("gemini_on_turn_end_failed", error=str(e))

        tc = getattr(response, "tool_call", None)
        if tc is not None and getattr(tc, "function_calls", None):
            for fc in tc.function_calls:
                tool_name = getattr(fc, "name", "")
                call_id = getattr(fc, "id", None) or str(uuid.uuid4())
                args = dict(getattr(fc, "args", {}) or {})
                args_json = json.dumps(args)
                await self._dispatch_tool(tool_name, args_json, call_id)

    async def _flush(self, role: str, chunks: list[str]) -> None:
        if not chunks:
            return
        text = "".join(chunks).strip()
        chunks.clear()
        if not text:
            return
        await self._emit_client({"type": "transcript", "role": role, "content": text})

    async def _dispatch_tool(self, tool_name: str, args_json: str, call_id: str) -> None:
        await self._emit_client({
            "type": "tool.start",
            "tool_name": tool_name,
            "call_id": call_id,
            "args": args_json,
        })
        deps = self.deps

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
        from google.genai import types as gtypes

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

        if self._session is None:
            return

        try:
            if note.tool_name == "camera" and isinstance(tool_result, dict) and "b64_im" in tool_result:
                b64 = tool_result.pop("b64_im")
                if not tool_result:
                    tool_result = {"status": "image_captured"}
                try:
                    image_bytes = base64.b64decode(b64) if isinstance(b64, str) else bytes(b64)
                    await self._session.send_realtime_input(
                        video=gtypes.Blob(data=image_bytes, mime_type="image/jpeg"),
                    )
                except Exception as e:
                    logger.warning("gemini_push_image_failed", error=str(e))

            function_response = gtypes.FunctionResponse(
                id=note.id if isinstance(note.id, str) else str(note.id),
                name=note.tool_name,
                response=tool_result,
            )
            await self._session.send_tool_response(function_responses=[function_response])
        except Exception as e:
            logger.warning("gemini_tool_result_send_failed", error=str(e))

    async def _emit_client(self, event: dict) -> None:
        if self._client_writer is None:
            return
        try:
            await self._client_writer(event)
        except Exception as e:
            logger.debug("client_writer_failed", event_type=event.get("type"), error=str(e))
