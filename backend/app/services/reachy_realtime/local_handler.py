"""
Local realtime handler — STT (faster-whisper) + LLM (vLLM) + TTS
(piper-tts / edge-tts) glued together to satisfy the same Handler protocol
as ``OpenAIRealtimeHandler`` and ``GeminiLiveHandler``. No cloud calls.

Why composed in-house instead of a framework:
- The OpenAI/Gemini handlers stream bidi-audio over a single provider WS;
  there is no analogous local API. The closest thing is pipecat's pipeline,
  but plugging it under the existing Handler shape requires a custom
  InputTransport + OutputTransport bridge that is bigger than this glue.
- All three components already exist as Zero services:
    * ``faster_whisper`` lives in audio_service.py
    * vLLM is the project's local provider, served at ``host.docker.internal:18800``
      with ``qwen3-chat`` warm on the 5090
    * ``TTSService`` (piper primary, edge-tts fallback) handles synthesis
- webrtcvad adds proper barge-in detection so the experience matches the
  cloud realtime feel — short interrupt gap, no speak-over-each-other.
  Picked over silero-vad to keep the backend image lean (silero pulls
  torch ~500 MB; webrtcvad is a 50 KB C extension and is plenty for
  clear speech close to the mic).

Pipeline:

    browser mic 16 kHz PCM16
        → SileroVAD (chunked, prob > 0.5 = speech, < 0.35 + hangover = end)
        → faster-whisper STT on the captured segment (text)
        → emit transcript.partial / transcript to client
        → vLLM /v1/chat/completions (stream=true)
              with system=profile instructions, tools=registry specs
        → tool calls dispatched via tools.dispatch (Reachy motion)
        → token stream split on sentence boundaries
        → TTSService.synthesize per sentence
        → decoded to PCM16 24 kHz mono → emitted as audio.delta to client
        → on_assistant_audio callback also fires (head wobbler + Reachy speaker)

Barge-in:
    When VAD detects new user speech while the assistant is still speaking,
    we set a cancel flag, drain the speaker pipe, and emit user.speech_started.
    The session orchestrator's ``_client_writer`` catches user.speech_started
    and flushes the host_agent speaker queue too.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import time
from typing import Any, Awaitable, Callable, List, Optional

import httpx
import numpy as np
import structlog

from app.infrastructure.config import get_settings
from app.services.reachy_realtime import tools as tool_registry
from app.services.reachy_realtime.bg_tool_manager import (
    BackgroundToolManager,
    ToolNotification,
)
from app.services.reachy_realtime.common import (
    BACKEND_LOCAL,
    ToolDependencies,
    resolve_model,
    resolve_voice,
)
from app.services.reachy_realtime.profiles import (
    resolve_instructions,
    resolve_tools,
)

logger = structlog.get_logger()

ClientWriter = Callable[[dict], Awaitable[None]]
AudioPCMCallback = Callable[[bytes, int], Awaitable[None]]

INPUT_RATE = 16000
OUTPUT_RATE = 24000
# webrtcvad accepts only 10/20/30 ms frames at 8k/16k/32k/48k. We use
# 30 ms @ 16k = 480 samples = 960 bytes. Speech/silence are decided per
# frame; the state machine smooths over noisy individual decisions.
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = INPUT_RATE * VAD_FRAME_MS // 1000  # 480
VAD_FRAME_BYTES = VAD_FRAME_SAMPLES * 2
VAD_AGGRESSIVENESS = 2  # 0..3, higher = more aggressive at filtering non-speech
HANGOVER_MS = 350
MIN_SPEECH_MS = 250
# Need a few consecutive speech frames to start, to ignore single-frame
# false positives like a click or door tap.
START_FRAMES = 3
# Split assistant tokens into chunks at sentence-ish boundaries so TTS can
# start speaking before the model has finished generating.
SENTENCE_SPLIT = re.compile(r"(?<=[\.!\?])\s+|(?<=[,;:])\s+(?=\S{4,})")

# Qwen3 in thinking mode emits ``<think>...</think>`` blocks in front of the
# real reply. Without stripping, Reachy literally speaks the chain-of-thought
# out loud. We do two things: suffix ``/no_think`` to the system prompt to
# disable reasoning (Qwen3 honors this hint), AND defensively strip any
# remaining think blocks from the streamed text before it reaches TTS.
THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)


def _convert_tools_for_chat_completions(specs: list[dict]) -> list[dict]:
    """Realtime tool spec → chat completions tool spec.

    Realtime expects ``{type: function, name, description, parameters}``;
    chat completions expects the function bits nested under ``function``.
    """
    out = []
    for s in specs:
        out.append({
            "type": "function",
            "function": {
                "name": s.get("name"),
                "description": s.get("description", ""),
                "parameters": s.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return out


class _WebRTCVAD:
    """Streaming voice activity detector backed by webrtcvad. Lazy-loaded.

    webrtcvad is a binary classifier per 10/20/30 ms frame, not a
    probability — so the public API returns booleans instead of floats.
    Callers should still smooth via START_FRAMES / HANGOVER_MS to ignore
    single-frame false positives.
    """

    def __init__(self) -> None:
        self._vad = None
        self._buf = bytearray()

    def _ensure(self) -> None:
        if self._vad is not None:
            return
        import webrtcvad  # type: ignore
        self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    def feed_pcm(self, pcm_bytes: bytes) -> List[bool]:
        """Push raw int16 mono 16 kHz PCM in; return one is-speech bool per
        VAD_FRAME_BYTES (~30 ms) chunk consumed."""
        if not pcm_bytes:
            return []
        self._ensure()
        self._buf.extend(pcm_bytes)
        out: list[bool] = []
        while len(self._buf) >= VAD_FRAME_BYTES:
            frame = bytes(self._buf[:VAD_FRAME_BYTES])
            del self._buf[:VAD_FRAME_BYTES]
            try:
                out.append(bool(self._vad.is_speech(frame, INPUT_RATE)))
            except Exception:
                out.append(False)
        return out

    def reset(self) -> None:
        self._buf = bytearray()


class LocalRealtimeHandler:
    """Local STT + LLM + TTS realtime session, same protocol as the cloud
    handlers."""

    def __init__(
        self,
        *,
        model: Optional[str],
        voice: Optional[str],
        profile_id: Optional[str],
        deps: ToolDependencies,
        on_assistant_audio: Optional[AudioPCMCallback] = None,
        on_turn_end: Optional[Callable[[], Awaitable[None]]] = None,
        vllm_url: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.model = resolve_model(BACKEND_LOCAL, model)
        self.voice = resolve_voice(BACKEND_LOCAL, voice)
        self.profile_id = profile_id or "default"
        self.deps = deps
        self._on_assistant_audio = on_assistant_audio
        self._on_turn_end = on_turn_end
        # The project routes all LLM traffic through the shared LiteLLM
        # router at host.docker.internal:4444 (see CLAUDE.md / memory
        # "Shared LiteLLM Router"). ``vllm_chat_url`` resolves to that
        # router; ``vllm_api_key`` is the master key it expects as Bearer
        # auth. Falling back to the direct vLLM port keeps the handler
        # working when LiteLLM is down for maintenance.
        raw_url = (
            vllm_url
            or getattr(settings, "vllm_chat_url", None)
            or "http://host.docker.internal:18800/v1"
        )
        if "localhost" in raw_url or "127.0.0.1" in raw_url:
            try:
                import os
                if os.path.exists("/.dockerenv"):
                    raw_url = raw_url.replace("localhost", "host.docker.internal")
                    raw_url = raw_url.replace("127.0.0.1", "host.docker.internal")
            except Exception:
                pass
        self._vllm_url = raw_url.rstrip("/")
        api_key = getattr(settings, "vllm_api_key", None) or "EMPTY"
        # vLLM accepts "EMPTY" as a no-auth sentinel; LiteLLM expects the
        # real master key. Either way we always send a Bearer header so
        # the same handler talks to both transparently.
        self._auth_header = {"Authorization": f"Bearer {api_key}"}

        self.tool_manager = BackgroundToolManager()
        self._client_writer: Optional[ClientWriter] = None
        self._stop = asyncio.Event()
        self._cancel_response = asyncio.Event()
        self._turn_lock = asyncio.Lock()

        # Audio + VAD state
        self._vad = _WebRTCVAD()
        self._speech_buf = bytearray()  # current user utterance, raw PCM16 16k
        self._silence_ms = 0.0
        self._in_speech = False
        self._consecutive_speech_frames = 0
        self._pre_buffer = bytearray()  # rolling pre-roll so we don't lose the
        # first ~90 ms of the user's speech before VAD latches on.
        self._speech_start_ts: Optional[float] = None
        self._speech_started_emitted = False
        self._pending_segment: Optional[bytes] = None

        # Conversation memory — keep it small; this is a voice loop, not a
        # research chat.
        self._messages: list[dict] = []
        self._conversation_started = False

        self._http: Optional[httpx.AsyncClient] = None
        self._tts_service = None  # lazy
        self._whisper_model = None  # lazy, cached for the session lifetime

    # -------------------- lifecycle --------------------

    async def start(self, client_writer: ClientWriter) -> None:
        self._client_writer = client_writer
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        try:
            instructions = resolve_instructions(self.profile_id)
        except Exception:
            instructions = "You are Reachy, a small expressive robot. Reply briefly."

        # Tier-3 relationship summary — fixed for the session. Cheap disk
        # read; no LLM call. Lets the companion remember "we talked about
        # hiking last week" without needing per-turn RAG. Best-effort: if
        # the memory subsystem isn't reachable we just skip the block.
        try:
            from app.services.reachy_memory import get_reachy_memory_service
            mem = get_reachy_memory_service()
            summary = mem.load_summary("default", self.profile_id)
            block = summary.render_block()
            if block:
                instructions = instructions.rstrip() + "\n\n" + block
        except Exception as e:
            logger.debug("reachy_memory_block_skipped", error=str(e))

        # Disable Qwen3's reasoning-block emission for the voice loop. We
        # want short conversational replies, not chain-of-thought spoken
        # out loud. Harmless for non-Qwen models.
        if "/no_think" not in instructions:
            instructions = instructions.rstrip() + "\n\n/no_think"
        self._messages = [{"role": "system", "content": instructions}]

        # Probe vLLM so we fail fast (and tell the client) if the GPU
        # backend isn't actually running. ALSO validate the chosen model is
        # in the router's catalog — silent "Invalid model name" rejections
        # made the cockpit look live but produce no replies for users with
        # stale model strings in their saved config.
        available_models: list[str] = []
        try:
            r = await self._http.get(
                f"{self._vllm_url}/models",
                headers=self._auth_header,
                timeout=4.0,
            )
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
            available_models = [m.get("id", "") for m in data if m.get("id")]
        except Exception as e:
            await self._emit({
                "type": "error",
                "message": (
                    f"vLLM unreachable at {self._vllm_url}: {e}. "
                    "Start it on the host (docker compose -f docker-compose.vllm.yml up -d)."
                ),
            })
            return

        if available_models and self.model not in available_models:
            # User has a stale or hand-typed model name (e.g. "qwen3-heretic-9b")
            # that the router doesn't know. Fall back to the default and
            # surface the swap as a transcript so the user actually sees it
            # in the cockpit — emit-as-error gets quietly hidden during a
            # "live" session.
            fallback = "qwen3-chat" if "qwen3-chat" in available_models else available_models[0]
            logger.warning(
                "local_model_unavailable_falling_back",
                requested=self.model,
                fallback=fallback,
                available=available_models[:8],
            )
            await self._emit({
                "type": "transcript",
                "role": "assistant",
                "content": (
                    f"Heads up: the model '{self.model}' isn't loaded on the "
                    f"router. Switching to '{fallback}' for this session. "
                    f"Pick a different one in Settings if you'd like."
                ),
            })
            self.model = fallback

        await self.tool_manager.start_up(callbacks=[self._on_tool_complete])
        await self._emit({
            "type": "session.ready",
            "model": self.model,
            "voice": self.voice,
            "backend": BACKEND_LOCAL,
        })

        try:
            # Run until stop. We don't have a long-poll loop here — frames
            # arrive via feed_pcm() and we drive turns inline.
            await self._stop.wait()
        finally:
            await self.tool_manager.shutdown()
            if self._http is not None:
                await self._http.aclose()
                self._http = None

    async def stop(self) -> None:
        self._stop.set()
        self._cancel_response.set()

    # -------------------- inbound audio + VAD --------------------

    async def feed_pcm(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        # Maintain a small pre-roll buffer (~3 frames = 90 ms) so when VAD
        # latches we don't lose the leading consonants of the utterance.
        max_preroll = VAD_FRAME_BYTES * 3
        if not self._in_speech:
            self._pre_buffer.extend(pcm_bytes)
            if len(self._pre_buffer) > max_preroll:
                del self._pre_buffer[: len(self._pre_buffer) - max_preroll]

        try:
            decisions = self._vad.feed_pcm(pcm_bytes)
        except Exception as e:
            logger.warning("local_vad_failed", error=str(e))
            decisions = []

        if self._in_speech:
            self._speech_buf.extend(pcm_bytes)

        for is_speech in decisions:
            frame_ms = float(VAD_FRAME_MS)
            if not self._in_speech:
                if is_speech:
                    self._consecutive_speech_frames += 1
                else:
                    self._consecutive_speech_frames = 0
                if self._consecutive_speech_frames >= START_FRAMES:
                    self._in_speech = True
                    self._speech_start_ts = time.monotonic()
                    self._silence_ms = 0.0
                    # Seed with pre-roll so the leading audio is preserved.
                    self._speech_buf = bytearray(self._pre_buffer)
                    self._pre_buffer = bytearray()
                    self._speech_started_emitted = False
                    self._consecutive_speech_frames = 0
                    # Barge-in: tell the orchestrator to flush the speaker
                    # queue + cancel any in-flight assistant response.
                    self._cancel_response.set()
                    asyncio.create_task(
                        self._emit({"type": "user.speech_started"})
                    )
                continue
            # in_speech == True
            if not is_speech:
                self._silence_ms += frame_ms
            else:
                self._silence_ms = 0.0
            if self._silence_ms >= HANGOVER_MS:
                # End of utterance.
                segment = bytes(self._speech_buf)
                self._speech_buf = bytearray()
                self._in_speech = False
                self._silence_ms = 0.0
                duration_ms = (
                    (time.monotonic() - (self._speech_start_ts or time.monotonic())) * 1000
                )
                if duration_ms < MIN_SPEECH_MS:
                    # Too short — likely a click or a cough. Drop it.
                    continue
                # Kick the turn handler. Use a task so we don't block
                # the audio ingest path.
                asyncio.create_task(self._handle_turn(segment))

    async def commit_audio(self) -> None:
        # Force end-of-turn even if VAD hasn't fired (used by the frontend
        # send-text + push-to-talk paths).
        if self._in_speech and self._speech_buf:
            segment = bytes(self._speech_buf)
            self._speech_buf = bytearray()
            self._in_speech = False
            self._silence_ms = 0.0
            asyncio.create_task(self._handle_turn(segment))

    async def cancel_response(self) -> None:
        self._cancel_response.set()

    async def send_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        await self._emit({"type": "transcript", "role": "user", "content": text})
        self._messages.append({"role": "user", "content": text})
        self._record_user_memory(text)
        asyncio.create_task(self._run_llm_turn())

    # -------------------- turn pipeline --------------------

    async def _handle_turn(self, pcm_segment: bytes) -> None:
        async with self._turn_lock:
            self._cancel_response.clear()
            transcript = await self._transcribe(pcm_segment)
            if not transcript:
                return
            await self._emit({"type": "transcript", "role": "user", "content": transcript})
            self._messages.append({"role": "user", "content": transcript})
            self._record_user_memory(transcript)
            await self._run_llm_turn()
            await self._maybe_summarize()

    def _record_user_memory(self, text: str) -> None:
        """Fire-and-forget tier-2 memory write. Best-effort; never blocks."""
        try:
            from app.services.reachy_memory import get_reachy_memory_service
            mem = get_reachy_memory_service()
            asyncio.create_task(mem.add_memory("default", self.profile_id, text))
        except Exception as e:
            logger.debug("reachy_memory_record_skipped", error=str(e))

    async def _maybe_summarize(self) -> None:
        """Trigger tier-3 summary every SUMMARY_TURN_INTERVAL turns. Cheap
        no-op until the threshold is crossed."""
        try:
            from app.services.reachy_memory import (
                SUMMARY_TURN_INTERVAL,
                get_reachy_memory_service,
            )
            # Count user/assistant pairs we've seen this session. The system
            # message at index 0 doesn't count.
            convo_turns = sum(
                1 for m in self._messages if m.get("role") in ("user", "assistant")
            )
            if convo_turns < SUMMARY_TURN_INTERVAL:
                return
            if convo_turns % SUMMARY_TURN_INTERVAL != 0:
                return
            mem = get_reachy_memory_service()
            await mem.maybe_summarize(
                "default",
                self.profile_id,
                [m for m in self._messages if m.get("role") in ("user", "assistant")],
            )
        except Exception as e:
            logger.debug("reachy_summarize_skipped", error=str(e))

    async def _transcribe(self, pcm: bytes) -> str:
        loop = asyncio.get_event_loop()

        def _run() -> str:
            try:
                if self._whisper_model is None:
                    from faster_whisper import WhisperModel  # type: ignore
                    # ``base`` balances quality vs. latency for short voice
                    # turns. Larger models are noticeably slower on CPU and
                    # the user typically speaks short sentences here.
                    self._whisper_model = WhisperModel(
                        "base", device="auto", compute_type="int8"
                    )
                samples = (
                    np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                )
                segments, _info = self._whisper_model.transcribe(
                    samples,
                    language="en",
                    beam_size=1,
                    vad_filter=False,  # we already VAD'd
                )
                text = "".join(seg.text for seg in segments).strip()
                return text
            except Exception as e:
                logger.warning("local_stt_failed", error=str(e))
                return ""

        return await loop.run_in_executor(None, _run)

    async def _run_llm_turn(self) -> None:
        """Stream tokens from vLLM, dispatch tool calls, speak as we go."""
        if self._http is None:
            return
        enabled = list(resolve_tools(self.profile_id))
        tool_specs = tool_registry.get_tool_specs(enabled=enabled)
        chat_tools = _convert_tools_for_chat_completions(tool_specs)

        # Up to 3 tool-calling rounds — generous enough for "look at me then
        # play happy", tight enough that a runaway loop self-bounds.
        for _round in range(3):
            if self._cancel_response.is_set():
                return
            assistant_text, tool_calls = await self._stream_completion(chat_tools)
            # Persist the cleaned (think-block-stripped) reply in conversation
            # history; otherwise the model's own prior chain-of-thought would
            # bias the next turn.
            cleaned_text = THINK_BLOCK.sub("", assistant_text).strip()
            if cleaned_text:
                self._messages.append({"role": "assistant", "content": cleaned_text})
            if not tool_calls:
                break
            # Dispatch each tool, append results, loop for the model's next
            # response.
            self._messages.append({
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                await self._emit({
                    "type": "tool.start",
                    "call_id": tc["id"],
                    "tool_name": tc["name"],
                    "args": tc["arguments"],
                })
                result = await tool_registry.dispatch(
                    tc["name"], tc["arguments"], self.deps, self.tool_manager
                )
                await self._emit({
                    "type": "tool.end",
                    "call_id": tc["id"],
                    "tool_name": tc["name"],
                    "status": "completed",
                    "result": result,
                })
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": json.dumps(result, default=str),
                })

        if self._on_turn_end is not None:
            try:
                await self._on_turn_end()
            except Exception as e:
                logger.debug("on_turn_end_failed", error=str(e))

    async def _stream_completion(
        self, chat_tools: list[dict]
    ) -> tuple[str, list[dict]]:
        """Stream a chat completion. Returns (assistant_text, tool_calls).

        While text streams in we accumulate sentence-sized chunks and pass
        them to TTS so the assistant starts speaking before the LLM finishes.
        """
        assert self._http is not None
        url = f"{self._vllm_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": self._messages,
            "tools": chat_tools or None,
            "tool_choice": "auto" if chat_tools else None,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 512,
        }
        # Drop None values (vLLM's OpenAI surface is strict about extras).
        body = {k: v for k, v in body.items() if v is not None}

        text_acc = ""
        spoken_to_idx = 0  # how much of text_acc we've already spoken
        tool_call_acc: dict[int, dict] = {}

        try:
            async with self._http.stream(
                "POST", url, json=body, headers=self._auth_header
            ) as resp:
                if resp.status_code != 200:
                    err = await resp.aread()
                    await self._emit({
                        "type": "error",
                        "message": f"vLLM {resp.status_code}: {err.decode('utf-8', 'replace')[:200]}",
                    })
                    return "", []
                async for line in resp.aiter_lines():
                    if self._cancel_response.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line.strip() == "[DONE]":
                        break
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    choices = evt.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        text_acc += content
                        cleaned = THINK_BLOCK.sub("", text_acc).lstrip()
                        # If we're still inside an unclosed <think> block,
                        # don't surface or speak anything yet — wait for
                        # </think> to land.
                        if "<think>" in text_acc and "</think>" not in text_acc:
                            continue
                        await self._emit({
                            "type": "transcript.partial",
                            "role": "assistant",
                            "content": cleaned,
                        })
                        # Speak any complete sentences we have so far.
                        # Note: spoken_to_idx tracks position in the
                        # CLEANED text, not the raw stream.
                        spoken_to_idx = await self._speak_through(
                            cleaned, spoken_to_idx
                        )
                    tcs = delta.get("tool_calls") or []
                    for tc in tcs:
                        idx = tc.get("index", 0)
                        slot = tool_call_acc.setdefault(idx, {
                            "id": tc.get("id") or f"call_{idx}",
                            "name": "",
                            "arguments": "",
                        })
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        except httpx.HTTPError as e:
            await self._emit({"type": "error", "message": f"vLLM stream failed: {e}"})
            return text_acc, []

        # Strip any final think-block before the tail-flush + transcript.
        cleaned_full = THINK_BLOCK.sub("", text_acc).strip()
        if not self._cancel_response.is_set() and cleaned_full[spoken_to_idx:].strip():
            await self._speak_chunk(cleaned_full[spoken_to_idx:])

        if cleaned_full:
            await self._emit({
                "type": "transcript", "role": "assistant", "content": cleaned_full,
            })

        tool_calls = [tool_call_acc[k] for k in sorted(tool_call_acc.keys())]
        # Drop empty tool calls (some streams emit a placeholder before
        # filling).
        tool_calls = [tc for tc in tool_calls if tc.get("name")]
        return text_acc, tool_calls

    async def _speak_through(self, text_acc: str, spoken_to_idx: int) -> int:
        """If new full sentences have arrived since spoken_to_idx, synth
        them and return the new index."""
        # Find sentence-ish breakpoints after spoken_to_idx.
        tail = text_acc[spoken_to_idx:]
        if not tail:
            return spoken_to_idx
        last_break = -1
        for m in SENTENCE_SPLIT.finditer(tail):
            last_break = m.end()
        if last_break <= 0:
            return spoken_to_idx
        chunk = tail[:last_break]
        await self._speak_chunk(chunk)
        return spoken_to_idx + last_break

    async def _speak_chunk(self, text: str) -> None:
        text = text.strip()
        if not text or self._cancel_response.is_set():
            return
        wav_bytes: bytes = b""
        try:
            from app.services.tts_service import get_tts_service
            self._tts_service = self._tts_service or get_tts_service()
            wav_bytes, _meta = await self._tts_service.synthesize_with_meta(
                text, voice_override=self.voice if "-" in self.voice else None
            )
        except Exception as e:
            logger.warning("local_tts_failed", voice=self.voice, error=str(e))
            await self._emit({
                "type": "error",
                "code": "tts_failed",
                "message": f"TTS synthesis failed for voice '{self.voice}': {e}",
            })
            return
        if not wav_bytes:
            logger.warning("local_tts_empty", voice=self.voice)
            await self._emit({
                "type": "error",
                "code": "tts_empty",
                "message": f"TTS returned no audio for voice '{self.voice}'. Try a different voice in settings.",
            })
            return
        # Decode WAV → PCM16 mono OUTPUT_RATE.
        pcm = await asyncio.get_event_loop().run_in_executor(
            None, _wav_bytes_to_pcm16, wav_bytes, OUTPUT_RATE
        )
        if not pcm or self._cancel_response.is_set():
            return
        # Emit in 50 ms chunks so the head wobbler animates smoothly and the
        # speaker pipe doesn't get flooded.
        chunk_samples = OUTPUT_RATE // 20  # 50 ms
        chunk_bytes = chunk_samples * 2
        for i in range(0, len(pcm), chunk_bytes):
            if self._cancel_response.is_set():
                break
            piece = pcm[i:i + chunk_bytes]
            await self._emit({
                "type": "audio.delta",
                "format": "pcm16",
                "rate": OUTPUT_RATE,
                "audio_b64": base64.b64encode(piece).decode("ascii"),
            })
            if self._on_assistant_audio is not None:
                try:
                    await self._on_assistant_audio(piece, OUTPUT_RATE)
                except Exception as e:
                    logger.debug("on_assistant_audio_failed", error=str(e))
            # Yield so cancellation can land between frames.
            await asyncio.sleep(0)

    # -------------------- helpers --------------------

    async def _emit(self, event: dict) -> None:
        cw = self._client_writer
        if cw is None:
            return
        try:
            await cw(event)
        except Exception as e:
            logger.debug("local_emit_failed", error=str(e))

    async def _on_tool_complete(self, notif: ToolNotification) -> None:
        # Background tool finished — surface the result so the LLM can
        # narrate it on the next turn. We don't currently re-prompt the
        # model automatically (cheaper, simpler); the user can ask "what
        # happened" and the tool result is already in conversation history.
        await self._emit({
            "type": "tool.end",
            "call_id": notif.call_id,
            "tool_name": notif.tool_name,
            "status": notif.status,
            "result": notif.result,
        })


def _wav_bytes_to_pcm16(wav_bytes: bytes, target_rate: int) -> bytes:
    """Best-effort WAV/MP3 → PCM16 mono @ target_rate. Returns b'' on failure."""
    try:
        import soundfile as sf
        with io.BytesIO(wav_bytes) as buf:
            data, samplerate = sf.read(buf, dtype="float32", always_2d=False)
    except Exception as e:
        logger.warning("local_tts_decode_failed", error=str(e))
        return b""
    if data.ndim > 1:
        data = data.mean(axis=1)
    if samplerate != target_rate:
        ratio = target_rate / float(samplerate)
        new_len = max(1, int(round(data.size * ratio)))
        xs = np.linspace(0, data.size - 1, num=new_len, dtype=np.float32)
        data = np.interp(xs, np.arange(data.size, dtype=np.float32), data).astype(np.float32)
    clipped = np.clip(data, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    return pcm
