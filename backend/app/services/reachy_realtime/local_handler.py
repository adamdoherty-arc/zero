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
import os
import re
import time
from collections import Counter, deque
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
from app.services.reachy_emotion_parser import parse_and_strip

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
# Optional energy floor in addition to WebRTC VAD. Reachy Mini's speakerphone
# reports real speech quietly, but open-room USB/AEC noise tends to sit below
# ~90 raw RMS and otherwise becomes bogus "you"/"okay" turns.
VAD_MIN_RMS = int(os.getenv("REACHY_LOCAL_VAD_MIN_RMS", "90"))
HANGOVER_MS = int(os.getenv("REACHY_LOCAL_VAD_HANGOVER_MS", "700"))
MIN_SPEECH_MS = int(os.getenv("REACHY_LOCAL_VAD_MIN_SPEECH_MS", "450"))
# Do not let a noisy room keep the VAD open for minutes. Long speakerphone
# captures made the live assistant feel frozen because Whisper had to process
# the whole room before the LLM could answer.
MAX_SPEECH_MS = int(os.getenv("REACHY_LOCAL_VAD_MAX_SPEECH_MS", "6500"))
# Need a few consecutive speech frames to start, to ignore single-frame
# false positives like a click or door tap.
START_FRAMES = int(os.getenv("REACHY_LOCAL_VAD_START_FRAMES", "4"))
INPUT_WARMUP_S = float(os.getenv("REACHY_LOCAL_INPUT_WARMUP_S", "1.2"))
# Barge-in should be stricter than turn detection. On a degraded Reachy mic,
# low-level USB/AEC noise can trip WebRTC VAD continuously; that must not
# cancel a typed fallback turn or flush the robot speaker.
BARGE_IN_MIN_RMS = float(os.getenv("REACHY_LOCAL_BARGE_IN_MIN_RMS", "0.07"))
# Reachy Mini USB speakerphone input can arrive very quiet through WASAPI.
# Normalize captured utterances before Whisper so a real voice does not become
# an empty transcript just because Windows delivered it at -50 dBFS.
STT_TARGET_RMS = float(os.getenv("REACHY_LOCAL_STT_TARGET_RMS", "0.08"))
STT_MAX_GAIN = float(os.getenv("REACHY_LOCAL_STT_MAX_GAIN", "60"))
STT_MIN_PEAK_FOR_GAIN = float(os.getenv("REACHY_LOCAL_STT_MIN_PEAK_FOR_GAIN", "0.0005"))
# Defaults loosened 2026-05-08: base.en was hallucinating YouTube outro
# captions ("Thanks for watching.", "I'll see you next time.") on quiet
# Reachy speakerphone input and the old -1.0 / 0.85 thresholds rejected
# borderline real speech alongside the hallucinations. small.en handles
# noisy / quiet audio noticeably better, and a 0.92 no_speech cap keeps
# the caption_hallucination filter doing the heavy lifting against true
# hallucinations while letting real speech through more reliably.
STT_MIN_AVG_LOGPROB = float(os.getenv("REACHY_LOCAL_STT_MIN_AVG_LOGPROB", "-1.4"))
STT_ACTIVE_AUDIO_MIN_AVG_LOGPROB = float(
    os.getenv("REACHY_LOCAL_STT_ACTIVE_AUDIO_MIN_AVG_LOGPROB", "-1.4")
)
STT_MAX_NO_SPEECH_PROB = float(os.getenv("REACHY_LOCAL_STT_MAX_NO_SPEECH_PROB", "0.92"))
STT_MAX_COMPRESSION_RATIO = float(os.getenv("REACHY_LOCAL_STT_MAX_COMPRESSION_RATIO", "2.8"))
INPUT_WARNING_MIN_INTERVAL_S = float(os.getenv("REACHY_LOCAL_INPUT_WARNING_INTERVAL_S", "20"))
INPUT_WARNING_TRANSCRIPT_INTERVAL_S = float(
    os.getenv("REACHY_LOCAL_INPUT_WARNING_TRANSCRIPT_INTERVAL_S", "60")
)
# 2026-05-09: distil-large-v3 (~600MB faster-whisper) replaces small.en. It
# handles speakerphone audio noticeably better and runs at >RT on the 5090.
# Override with REACHY_LOCAL_WHISPER_MODEL if you need a smaller footprint.
STT_MODEL_NAME = (
    os.getenv("REACHY_LOCAL_WHISPER_MODEL", "distil-large-v3").strip()
    or "distil-large-v3"
)
STT_ACTIVE_AUDIO_RMS = float(os.getenv("REACHY_LOCAL_STT_ACTIVE_AUDIO_RMS", "0.012"))
STT_ACTIVE_AUDIO_PEAK = float(os.getenv("REACHY_LOCAL_STT_ACTIVE_AUDIO_PEAK", "0.08"))
STT_LONG_SHORT_AUDIO_S = float(os.getenv("REACHY_LOCAL_STT_LONG_SHORT_AUDIO_S", "5.0"))
STT_LONG_SHORT_MIN_WORDS = int(os.getenv("REACHY_LOCAL_STT_LONG_SHORT_MIN_WORDS", "6"))
OUTPUT_ECHO_GUARD_S = float(os.getenv("REACHY_LOCAL_OUTPUT_ECHO_GUARD_S", "0.35"))
SPEAKER_CALLBACK_TIMEOUT_S = float(
    os.getenv("REACHY_LOCAL_SPEAKER_CALLBACK_TIMEOUT_S", "0.25")
)
TTS_TIMEOUT_S = float(os.getenv("REACHY_LOCAL_TTS_TIMEOUT_S", "12"))
STT_TIMEOUT_S = float(os.getenv("REACHY_LOCAL_STT_TIMEOUT_S", "8"))
LLM_TURN_TIMEOUT_S = float(os.getenv("REACHY_LOCAL_LLM_TURN_TIMEOUT_S", "20"))
LLM_FIRST_TOKEN_TIMEOUT_S = float(
    os.getenv("REACHY_LOCAL_LLM_FIRST_TOKEN_TIMEOUT_S", str(LLM_TURN_TIMEOUT_S))
)
LLM_STREAM_IDLE_TIMEOUT_S = float(os.getenv("REACHY_LOCAL_LLM_STREAM_IDLE_TIMEOUT_S", "12"))
LLM_STREAM_HARD_TIMEOUT_S = float(os.getenv("REACHY_LOCAL_LLM_STREAM_HARD_TIMEOUT_S", "75"))
TOOL_TIMEOUT_S = float(os.getenv("REACHY_LOCAL_TOOL_TIMEOUT_S", "12"))
# Split assistant tokens into chunks at sentence-ish boundaries so TTS can
# start speaking before the model has finished generating.
SENTENCE_SPLIT = re.compile(r"(?<=[\.!\?])\s+|(?<=[,;:])\s+(?=\S{4,})")
EARLY_TTS_CHARS = int(os.getenv("REACHY_LOCAL_EARLY_TTS_CHARS", "36"))
LLM_MAX_TOKENS = int(os.getenv("REACHY_LOCAL_LLM_MAX_TOKENS", "100"))
LLM_TEMPERATURE = float(os.getenv("REACHY_LOCAL_LLM_TEMPERATURE", "0.25"))

# Qwen3 in thinking mode emits ``<think>...</think>`` blocks in front of the
# real reply. Without stripping, Reachy literally speaks the chain-of-thought
# out loud. We do two things: suffix ``/no_think`` to the system prompt to
# disable reasoning (Qwen3 honors this hint), AND defensively strip any
# remaining think blocks from the streamed text before it reaches TTS.
THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)
ASSISTANT_NAME_WORDS = {
    "reachy",
    "reachie",
    "reeche",
    "reechy",
    "richy",
    "richie",
    "richey",
    "rechie",
    "rechi",
    "zero",
}
EDGE_TTS_VOICE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural$")
PIPER_VOICE_RE = re.compile(r"^[a-z]{2}_[A-Z]{2}-.+")


def _is_edge_tts_voice(voice: str) -> bool:
    return bool(EDGE_TTS_VOICE_RE.match((voice or "").strip()))


def _is_piper_voice(voice: str) -> bool:
    voice = (voice or "").strip()
    return bool(PIPER_VOICE_RE.match(voice) or voice.endswith(".onnx") or voice.startswith("/"))


def _has_active_audio(stats: dict[str, float] | None) -> bool:
    stats = stats or {}
    return (
        stats.get("rms_norm", 0.0) >= STT_ACTIVE_AUDIO_RMS
        or stats.get("peak_norm", 0.0) >= STT_ACTIVE_AUDIO_PEAK
    )


def _stt_warning_message(stats: dict[str, float]) -> str:
    """Explain STT failures without pretending the robot replied.

    The Reachy mic can be electrically active while Whisper still rejects the
    segment for confidence. Calling every rejection "too quiet" misleads the
    user when the Windows meter is clearly moving.
    """
    if _has_active_audio(stats):
        return (
            "Reachy heard audio, but speech recognition was not confident "
            "enough to use it. Try speaking closer, a little slower, or use "
            "Computer mic if the room is noisy."
        )
    return (
        "Reachy mic is streaming, but the audio is too quiet for speech "
        "recognition. Check the Windows input level/unmute for Reachy Mini "
        "Audio, then try again."
    )


def _clean_assistant_text(text: str) -> str:
    """Remove reasoning and gesture markup before transcript/TTS output."""
    cleaned = THINK_BLOCK.sub("", text or "").strip()
    if not cleaned:
        return ""
    try:
        cleaned, _actions = parse_and_strip(cleaned)
    except Exception:
        pass
    return cleaned.strip()


class _ToneGuard:
    """Small session-local guard against repeated companion verbal tics."""

    _PET_NAME_RE = re.compile(
        r"(?i)(?:,\s*)?\b(darling|dear|honey|sweetheart|babe|baby|love)\b"
    )
    _BANNED_NICKNAME_RE = re.compile(
        r"(?i)(?:,\s*)?\b(cobalt|darlin')\b"
    )

    def __init__(self, profile_id: str) -> None:
        self.profile_id = (profile_id or "").lower()
        self._recent_sentences: deque[str] = deque(maxlen=10)
        self._pet_name_uses: Counter[str] = Counter()

    def clean(self, text: str) -> str:
        if self.profile_id not in {"companion", "sally", "companion_girlfriend"}:
            return text
        value = text.strip()
        if not value:
            return value
        value = self._BANNED_NICKNAME_RE.sub("", value)

        def _pet_repl(match: re.Match[str]) -> str:
            pet = match.group(1).lower()
            self._pet_name_uses[pet] += 1
            return "" if self._pet_name_uses[pet] > 1 else match.group(0)

        value = self._PET_NAME_RE.sub(_pet_repl, value)
        parts = re.split(r"(?<=[.!?])\s+", value)
        kept: list[str] = []
        for part in parts:
            normalized = re.sub(r"\s+", " ", part.lower()).strip(" .!?")
            if normalized and normalized in self._recent_sentences:
                continue
            kept.append(part.strip())
            if normalized:
                self._recent_sentences.append(normalized)
        value = " ".join(p for p in kept if p).strip()
        value = re.sub(r"\s{2,}", " ", value).strip(" ,")
        return value or "I'm here with you."


def _chat_completion_content(message: dict[str, Any]) -> str:
    """Return only the user-facing assistant text from an OpenAI-ish message."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _with_live_voice_rules(instructions: str) -> str:
    """Add voice-loop rules that keep local Qwen fast and contextful."""
    voice_rules = (
        "\n\nLive voice session rules:\n"
        "- Keep spoken replies short: usually one or two sentences.\n"
        "- Preserve immediate conversation context. If the user asks a "
        "follow-up like 'what is it?', 'which one?', 'tell me more', or "
        "'stop that', resolve it against your last answer and recent tool "
        "results instead of starting over.\n"
        "- If speech recognition looks imperfect but the intent is clear, "
        "answer the likely intent briefly and confirm only when needed."
    )
    if "Live voice session rules:" in instructions:
        return instructions
    return instructions.rstrip() + voice_rules


def _prepare_samples_for_stt(pcm: bytes) -> np.ndarray:
    """Convert PCM16 to float32 and auto-gain quiet Reachy mic captures."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    if not samples.size:
        return samples
    peak = float(np.max(np.abs(samples)))
    if peak < STT_MIN_PEAK_FOR_GAIN:
        return samples
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms <= 0.0 or rms >= STT_TARGET_RMS:
        return samples
    gain = min(STT_MAX_GAIN, STT_TARGET_RMS / rms)
    if gain <= 1.0:
        return samples
    boosted = np.clip(samples * gain, -1.0, 1.0).astype(np.float32)
    logger.debug(
        "local_stt_auto_gain",
        gain=round(gain, 2),
        rms=round(rms, 6),
        peak=round(peak, 6),
    )
    return boosted


def _pcm_stats(pcm: bytes) -> dict[str, float]:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if not samples.size:
        return {
            "duration_s": 0.0,
            "rms_raw": 0.0,
            "peak_raw": 0.0,
            "rms_norm": 0.0,
            "peak_norm": 0.0,
        }
    rms = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    return {
        "duration_s": float(samples.size) / float(INPUT_RATE),
        "rms_raw": rms,
        "peak_raw": peak,
        "rms_norm": rms / 32768.0,
        "peak_norm": peak / 32768.0,
    }


def _looks_like_repetitive_stt_hallucination(text: str) -> bool:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    if len(words) < 8:
        return False
    unique_ratio = len(set(words)) / max(1, len(words))
    if unique_ratio < 0.42:
        return True
    single_counts = Counter(words)
    if single_counts and single_counts.most_common(1)[0][1] >= 5:
        return True
    for n in (2, 3, 4):
        if len(words) < n * 3:
            continue
        grams = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
        if Counter(grams).most_common(1)[0][1] >= 3:
            return True
    return False


def _looks_like_caption_stt_hallucination(text: str) -> bool:
    """Catch common Whisper-on-noise captions from USB speakerphone input."""
    lower = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not lower:
        return False
    command_words = (
        *ASSISTANT_NAME_WORDS, "what", "why", "how", "when", "where", "who",
        "start", "stop", "set", "turn", "move", "look", "remember", "timer",
        "schedule", "calendar", "task", "jira", "email", "inbox", "meeting",
    )
    if any(word in lower for word in command_words):
        return False
    caption_phrases = (
        "awesome yeah",
        "awesome, yeah",
        "i'm going to go",
        "i am going to go",
        "thank you, i appreciate",
        "i appreciate it",
        "thanks for watching",
        "see you next time",
        "we also like",
        "we are on a stream",
        "we're on a stream",
        "in the speakerboard",
        "end of stream",
    )
    if any(phrase in lower for phrase in caption_phrases):
        return True
    if lower.startswith(("we also ", "we are ", "we're ")) and len(lower.split()) >= 7:
        return True
    if "are you going to" in lower and len(lower.split()) >= 7:
        return True
    if "more money this time" in lower:
        return True
    return False


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _has_assistant_intent(text: str) -> bool:
    """Best-effort gate for live open-mic input.

    The Reachy mic hears the room. We should keep direct commands, questions,
    and short follow-ups, but reject background work chatter that was not
    addressed to the assistant.
    """
    lower = re.sub(r"\s+", " ", (text or "").lower()).strip()
    words = _words(lower)
    if not words:
        return False
    if any(word in ASSISTANT_NAME_WORDS for word in words):
        return True
    first = words[0]
    question_starters = {"what", "what's", "why", "how", "when", "where", "who", "which"}
    if first in question_starters or first.rstrip("'s") in question_starters:
        if len(words) == 1:
            return True
        second = words[1].rstrip("'s")
        question_followers = {
            "am", "are", "can", "could", "did", "do", "does", "had", "has",
            "have", "is", "may", "might", "must", "should", "was", "were",
            "will", "would", "i", "you", "we", "they", "he", "she", "it",
            "my", "your", "our", "their", "the", "a", "an", "to",
        }
        if second in question_followers:
            return True
        if first.startswith("what") and second in {"day", "date", "time"}:
            return True
        return lower.endswith("?")
    if first in {"yes", "no"}:
        return lower.startswith(("yes please", "no thanks", "no thank you"))
    command_starters = {
        "start", "stop", "set", "turn", "move", "look", "remember", "schedule",
        "timer", "email", "inbox", "meeting", "help", "tell", "show",
        "summarize", "remind", "note", "focus", "wake", "sleep", "cancel",
        "continue", "repeat", "switch", "change", "open", "close", "say",
    }
    single_word_commands = {"start", "stop", "cancel", "continue", "repeat", "wake", "sleep"}
    if first in command_starters and (len(words) > 1 or first in single_word_commands):
        return True
    intent_phrases = (
        "can you", "could you", "would you", "please", "i need", "i want",
        "i'd like", "tell me", "show me", "remind me", "make a note",
        "take a note", "set a timer", "stop the timer", "start a timer",
        "my schedule", "my calendar", "my inbox", "my jira", "overdue task",
        "follow up", "follow-up", "say that again", "what was that",
        "look at me", "look ahead",
    )
    return any(phrase in lower for phrase in intent_phrases)


def _looks_like_low_content_stt_noise(text: str) -> bool:
    """Reject tiny filler transcripts that USB speakerphone noise produces."""
    words = _words(text)
    if not words:
        return False
    if _has_assistant_intent(text):
        return False
    filler_words = {
        "you", "okay", "ok", "alright", "right", "yeah", "yep", "uh", "um",
        "hmm", "hm", "oh", "ah", "so", "well", "thanks", "thank", "everybody",
    }
    if len(words) <= 2 and all(word in filler_words for word in words):
        return True
    if len(words) <= 8:
        filler_count = sum(1 for word in words if word in filler_words)
        if filler_count >= max(2, len(words) - 1):
            return True
        if Counter(words).most_common(1)[0][1] >= 3:
            return True
    return False


def _looks_like_unaddressed_background_speech(text: str) -> bool:
    words = _words(text)
    if not words:
        return False
    return not _has_assistant_intent(text)


# Standard Whisper hallucination phrases that show up as "transcripts" of
# silence / room tone, especially with the small.en model. These get a hard
# drop when paired with low avg_logprob (no active_audio escape hatch).
_STT_LOW_LOGPROB_JUNK_PHRASES = frozenset({
    "okay",
    "uh-huh",
    "uh huh",
    "you",
    "thank you",
    "thanks",
    "bye",
    "goodbye",
    "yeah",
    "yes",
    "no",
    "hmm",
    "hm",
    "oh",
    "ah",
})


def _looks_like_low_logprob_junk(text: str) -> bool:
    """Match the canonical Whisper hallucination set on near-silence."""
    if not text:
        return False
    normalized = re.sub(r"[^a-z\- ]+", "", text.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in _STT_LOW_LOGPROB_JUNK_PHRASES


def _looks_like_live_short_utterance(text: str) -> bool:
    """Keep short, clear live-session utterances that are not wake-worded."""
    lower = re.sub(r"\s+", " ", (text or "").lower()).strip()
    words = _words(lower)
    if not (3 <= len(words) <= 8):
        return False
    if _looks_like_low_content_stt_noise(text):
        return False
    if words[0] in {"all", "and", "but", "he", "i'm", "it", "she", "so", "the", "they", "we"}:
        return False
    live_check_phrases = (
        "can you hear me",
        "hello",
        "hey there",
        "mic check",
        "microphone check",
        "test one two",
        "testing one two",
        "voice check",
        "voice test",
    )
    if any(phrase in lower for phrase in live_check_phrases):
        return True
    return words[0] in {
        "can",
        "could",
        "hello",
        "hey",
        "hi",
        "microphone",
        "mic",
        "test",
        "testing",
        "voice",
    }


def _looks_like_long_short_noise_transcript(
    text: str,
    stats: dict[str, float] | None,
) -> bool:
    """Reject long VAD-open noise chunks that Whisper captions as a tiny phrase.

    A Reachy speakerphone can hold VAD open on fan/room/echo noise for many
    seconds, then Whisper occasionally returns a short generic phrase. Those
    bogus turns pollute conversational context and make follow-ups feel broken.
    Keep short command/follow-up utterances such as "what is it" or "stop the
    timer"; only reject when the captured audio was much longer than the text.
    """
    stats = stats or {}
    duration_s = float(stats.get("duration_s") or 0.0)
    if duration_s < STT_LONG_SHORT_AUDIO_S:
        return False
    words = _words(text)
    if len(words) >= STT_LONG_SHORT_MIN_WORDS:
        return False
    keep_words = {
        *ASSISTANT_NAME_WORDS, "what", "why", "how", "when", "where", "who",
        "start", "stop", "set", "turn", "move", "look", "remember", "timer",
        "schedule", "calendar", "task", "jira", "email", "inbox", "meeting",
        "yes", "no", "cancel", "continue", "repeat", "again", "more", "tell", "say",
    }
    return not any(word in keep_words for word in words)


def _segment_float(segment: Any, *names: str) -> float | None:
    for name in names:
        value = getattr(segment, name, None)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            return None
    return None


def _stt_segment_debug(segment: Any, text: str, reason: str) -> dict[str, Any]:
    debug: dict[str, Any] = {
        "reason": reason,
        "preview": text[:80],
    }
    for key, names in {
        "avg_logprob": ("avg_logprob", "avg_log_prob"),
        "no_speech_prob": ("no_speech_prob",),
        "compression_ratio": ("compression_ratio",),
    }.items():
        value = _segment_float(segment, *names)
        if value is not None:
            debug[key] = round(value, 4)
    return debug


def _stt_segment_quality_reason(
    segment: Any,
    text: str,
    *,
    active_audio: bool = False,
) -> str | None:
    if not text.strip():
        return "empty"
    if not _words(text):
        return "low_content"
    avg_logprob = _segment_float(segment, "avg_logprob", "avg_log_prob")
    no_speech_prob = _segment_float(segment, "no_speech_prob")
    compression_ratio = _segment_float(segment, "compression_ratio")
    if no_speech_prob is not None and no_speech_prob > STT_MAX_NO_SPEECH_PROB:
        return "no_speech"
    if compression_ratio is not None and compression_ratio > STT_MAX_COMPRESSION_RATIO:
        return "compression"
    if _looks_like_repetitive_stt_hallucination(text):
        return "repetitive"
    if _looks_like_caption_stt_hallucination(text):
        return "caption_hallucination"
    if _looks_like_low_content_stt_noise(text):
        return "low_content"
    if _looks_like_unaddressed_background_speech(text):
        if active_audio and _looks_like_live_short_utterance(text):
            return None
        return "background"
    if avg_logprob is not None and avg_logprob < STT_MIN_AVG_LOGPROB:
        # Hard drop for the classic Whisper hallucination set ("you", "thank
        # you", "bye", etc.) when the model itself is unsure: these are
        # always silence misreads, never real user intent.
        if _looks_like_low_logprob_junk(text):
            return "low_logprob_junk"
        if active_audio and avg_logprob >= STT_ACTIVE_AUDIO_MIN_AVG_LOGPROB:
            return None
        return "low_logprob"
    return None


def _segments_to_transcript(
    segments: Any,
    *,
    pcm_stats: dict[str, float] | None = None,
) -> str:
    pieces: list[str] = []
    rejected: Counter[str] = Counter()
    rejected_debug: list[dict[str, Any]] = []
    active_audio = _has_active_audio(pcm_stats)
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        reason = _stt_segment_quality_reason(
            segment,
            text,
            active_audio=active_audio,
        )
        if reason:
            rejected[reason] += 1
            if len(rejected_debug) < 4:
                rejected_debug.append(_stt_segment_debug(segment, text, reason))
            continue
        pieces.append(text)
    if rejected:
        logger.info(
            "local_stt_segments_rejected",
            rejected=dict(rejected),
            active_audio=active_audio,
            details=rejected_debug,
        )
    transcript = " ".join(pieces).strip()
    if transcript and _looks_like_long_short_noise_transcript(transcript, pcm_stats):
        logger.info(
            "local_stt_long_short_rejected",
            duration_s=round(float((pcm_stats or {}).get("duration_s") or 0.0), 3),
            preview=transcript[:120],
        )
        return ""
    return transcript


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
                is_speech = bool(self._vad.is_speech(frame, INPUT_RATE))
                if is_speech and VAD_MIN_RMS > 0:
                    samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
                    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
                    is_speech = rms >= VAD_MIN_RMS
                out.append(is_speech)
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
        self._listening_nod_at = 0.0
        self._pending_segment: Optional[bytes] = None
        self._ignore_input_until = time.monotonic() + INPUT_WARMUP_S
        self._drop_audio_turns_until = 0.0
        self._empty_transcript_count = 0
        self._last_input_warning_ts = 0.0
        self._last_input_warning_transcript_ts = 0.0
        self._assistant_audio_active_until = 0.0
        self._phase = "idle"
        self._last_input_stats: dict[str, float] = {}
        self._last_error: Optional[str] = None
        self._tone_guard = _ToneGuard(self.profile_id)

        # Conversation memory — keep it small; this is a voice loop, not a
        # research chat.
        self._messages: list[dict] = []
        self._conversation_started = False

        self._http: Optional[httpx.AsyncClient] = None
        self._tts_service = None  # lazy
        self._whisper_model = None  # lazy, cached for the session lifetime

    def health_snapshot(self) -> dict[str, Any]:
        stats = self._last_input_stats or {}
        confidence = "low_confidence" if self._empty_transcript_count else "unknown"
        if stats and self._empty_transcript_count == 0:
            confidence = "ok"
        return {
            "phase": self._phase,
            "input_health": {
                "source": "reachy_mic",
                "ready": True,
                "rms": float(stats.get("rms_norm") or 0.0),
                "peak": float(stats.get("peak_norm") or 0.0),
                "empty_stt_count": self._empty_transcript_count,
                "confidence_state": confidence,
                "last_error": self._last_error,
            },
        }

    async def recover(self, *, reason: str = "manual") -> dict[str, Any]:
        self._cancel_response.set()
        self._reset_audio_turn_state()
        self._drop_audio_turns_until = time.monotonic() + 0.8
        self._ignore_input_until = time.monotonic() + 0.8
        self._assistant_audio_active_until = 0.0
        self._last_error = None
        try:
            for task in self.tool_manager.get_running_tools():
                await self.tool_manager.cancel_tool(task.tool_id)
        except Exception:
            pass
        await self._emit_phase("recovering", reason=reason)
        await self._emit({"type": "audio.cancelled"})
        await self._emit_phase("listening")
        return self.health_snapshot()

    async def _emit_phase(self, phase: str, **extra: Any) -> None:
        self._phase = phase
        await self._emit({"type": "session.phase", "phase": phase, **extra})

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

        # Memory facade — fan-in across all stores (mem0/episodic/user/blocks).
        # Surface the persistent "always-on" context block here at session
        # start so it doesn't have to be re-fetched on every turn. Per-turn
        # recall happens just-in-time inside the LLM call.
        try:
            from app.services.memory_facade import get_memory_facade
            facade = get_memory_facade()
            seed_notes = await facade.recall(
                f"profile:{self.profile_id} session start",
                k=3,
            )
            if seed_notes:
                seed_block = facade.format_for_system_prompt(
                    seed_notes, max_chars=600
                )
                if seed_block:
                    instructions = instructions.rstrip() + "\n\n" + seed_block
        except Exception as e:
            logger.debug("memory_facade_seed_skipped", error=str(e))

        # Disable Qwen3's reasoning-block emission for the voice loop. We
        # want short conversational replies, not chain-of-thought spoken
        # out loud. Harmless for non-Qwen models.
        instructions = _with_live_voice_rules(instructions)
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
        await self._emit_phase("listening")

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
        await self._emit_phase("idle")

    # -------------------- inbound audio + VAD --------------------

    async def feed_pcm(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        if time.monotonic() < self._ignore_input_until:
            self._reset_audio_turn_state()
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
                    asyncio.create_task(self._maybe_listening_nod())
                continue
            # in_speech == True
            if not is_speech:
                self._silence_ms += frame_ms
            else:
                self._silence_ms = 0.0
            speech_ms = (len(self._speech_buf) / 2) / float(INPUT_RATE) * 1000.0
            if MAX_SPEECH_MS > 0 and speech_ms >= MAX_SPEECH_MS:
                segment = bytes(self._speech_buf)
                self._speech_buf = bytearray()
                self._in_speech = False
                self._silence_ms = 0.0
                self._speech_started_emitted = False
                logger.info(
                    "local_vad_forced_turn",
                    duration_s=round(speech_ms / 1000.0, 3),
                )
                asyncio.create_task(self._handle_turn(segment))
                continue
            if not self._speech_started_emitted and speech_ms >= MIN_SPEECH_MS:
                # Barge-in only after sustained speech. Short USB speakerphone
                # noise bursts should not cancel replies or flash the UI. Keep
                # the utterance for STT either way; this only gates interruption.
                if (
                    self._assistant_audio_is_active()
                    and self._speech_buf_loud_enough_for_barge_in()
                ):
                    self._speech_started_emitted = True
                    self._cancel_response.set()
                    asyncio.create_task(self._emit({"type": "user.speech_started"}))
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
                if not self._speech_started_emitted:
                    if (
                        self._assistant_audio_is_active()
                        and self._speech_buf_loud_enough_for_barge_in()
                    ):
                        self._speech_started_emitted = True
                        self._cancel_response.set()
                        asyncio.create_task(self._emit({"type": "user.speech_started"}))
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
        self._ignore_input_until = time.monotonic() + 2.0
        self._drop_audio_turns_until = max(
            self._drop_audio_turns_until,
            time.monotonic() + 1.5,
        )
        self._reset_audio_turn_state()
        self._cancel_response.clear()

        async def _text_turn() -> None:
            async with self._turn_lock:
                await self._emit({"type": "transcript", "role": "user", "content": text})
                await self._emit_phase("thinking")
                self._messages.append({"role": "user", "content": text})
                if isinstance(self.deps.extra, dict):
                    self.deps.extra["latest_user_text"] = text
                self._record_user_memory(text)
                await self._inject_scene_context(text)
                try:
                    await self._run_llm_turn()
                    await self._maybe_summarize()
                finally:
                    self._ignore_input_until = time.monotonic() + 0.5
                    if self._phase != "stalled":
                        await self._emit_phase("listening")

        asyncio.create_task(_text_turn())

    def _reset_audio_turn_state(self) -> None:
        """Drop a half-open VAD segment before a typed/direct command turn."""
        self._vad.reset()
        self._speech_buf = bytearray()
        self._silence_ms = 0.0
        self._in_speech = False
        self._consecutive_speech_frames = 0
        self._pre_buffer = bytearray()
        self._speech_start_ts = None
        self._speech_started_emitted = False

    def _speech_buf_loud_enough_for_barge_in(self) -> bool:
        if BARGE_IN_MIN_RMS <= 0:
            return True
        if not self._speech_buf:
            return False
        return _pcm_stats(bytes(self._speech_buf))["rms_norm"] >= BARGE_IN_MIN_RMS

    def _assistant_audio_is_active(self) -> bool:
        return time.monotonic() < self._assistant_audio_active_until

    async def _maybe_listening_nod(self) -> None:
        """Tiny head nod the moment VAD latches onto user speech, so the user
        sees instant feedback that Reachy heard them. Throttled to once per
        ~3 s and skipped while assistant audio is active (barge-in path
        already animates the head)."""
        now = time.monotonic()
        if now - self._listening_nod_at < 3.0:
            return
        if self._assistant_audio_is_active():
            return
        if not bool((self.deps.extra or {}).get("body_motion_enabled")):
            return
        if self.deps.motion.move_head is None:
            return
        self._listening_nod_at = now
        try:
            await asyncio.wait_for(
                self.deps.motion.move_head(roll=0, pitch=8, yaw=0, duration=0.15),
                timeout=0.5,
            )
            await asyncio.sleep(0.12)
            await asyncio.wait_for(
                self.deps.motion.move_head(roll=0, pitch=0, yaw=0, duration=0.15),
                timeout=0.5,
            )
        except Exception as e:
            logger.debug("listening_nod_failed", error=str(e))

    # -------------------- turn pipeline --------------------

    async def _handle_turn(self, pcm_segment: bytes) -> None:
        if time.monotonic() < self._drop_audio_turns_until:
            return
        async with self._turn_lock:
            if time.monotonic() < self._drop_audio_turns_until:
                return
            self._cancel_response.clear()
            stats = _pcm_stats(pcm_segment)
            self._last_input_stats = stats
            await self._emit_phase("transcribing")
            try:
                transcript = await asyncio.wait_for(
                    self._transcribe(pcm_segment),
                    timeout=STT_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                self._last_error = "speech recognition timed out"
                await self._emit({
                    "type": "error",
                    "code": "stt_timeout",
                    "message": "Speech recognition timed out. Try again or switch to Computer mic.",
                })
                await self._emit_phase("stalled", reason="stt_timeout")
                return
            if not transcript:
                self._empty_transcript_count += 1
                logger.info(
                    "local_stt_empty",
                    empty_count=self._empty_transcript_count,
                    duration_s=round(stats["duration_s"], 3),
                    rms_norm=round(stats["rms_norm"], 6),
                    peak_norm=round(stats["peak_norm"], 6),
                )
                if self._empty_transcript_count >= 2:
                    message = _stt_warning_message(stats)
                    now = time.monotonic()
                    first_warning = self._last_input_warning_ts <= 0.0
                    if (
                        first_warning
                        or now - self._last_input_warning_ts >= INPUT_WARNING_MIN_INTERVAL_S
                    ):
                        self._last_input_warning_ts = now
                        await self._emit({
                            "type": "input.warning",
                            "message": message,
                            "rms": stats["rms_norm"],
                            "peak": stats["peak_norm"],
                            "empty_stt_count": self._empty_transcript_count,
                            "confidence_state": "audio_not_speech" if _has_active_audio(stats) else "too_quiet",
                        })
                await self._emit_phase("listening")
                return
            self._empty_transcript_count = 0
            self._last_input_warning_ts = 0.0
            self._last_input_warning_transcript_ts = 0.0
            logger.info(
                "local_stt_accepted",
                duration_s=round(stats["duration_s"], 3),
                rms_norm=round(stats["rms_norm"], 6),
                peak_norm=round(stats["peak_norm"], 6),
                preview=transcript[:120],
            )
            await self._emit({"type": "transcript", "role": "user", "content": transcript})
            self._messages.append({"role": "user", "content": transcript})
            if isinstance(self.deps.extra, dict):
                self.deps.extra["latest_user_text"] = transcript
            self._record_user_memory(transcript)
            await self._emit_phase("thinking")
            await self._inject_scene_context(transcript)
            await self._run_llm_turn()
            await self._maybe_summarize()
            if self._phase != "stalled":
                await self._emit_phase("listening")

    def _record_user_memory(self, text: str) -> None:
        """Fire-and-forget tier-2 memory write. Best-effort; never blocks."""
        try:
            from app.services.reachy_memory import get_reachy_memory_service
            mem = get_reachy_memory_service()
            asyncio.create_task(mem.add_memory("default", self.profile_id, text))
        except Exception as e:
            logger.debug("reachy_memory_record_skipped", error=str(e))

    @staticmethod
    def _is_vision_relevant(text: str) -> bool:
        """Cheap regex gate so we only call the VLM on turns where the user
        actually asks about what Reachy is seeing. Keeps the token cost of
        the camera frame off the 80%+ of turns that are pure conversation."""
        if not text:
            return False
        lower = text.lower()
        triggers = (
            "what do you see",
            "what are you looking at",
            "what's in front",
            "what is in front",
            "look at",
            "describe what",
            "describe the scene",
            "describe the room",
            "describe me",
            "tell me what you see",
            "can you see",
            "do you see",
            "who's in",
            "who is in",
            "what color",
            "is anyone",
            "am i",
            "how do i look",
            "read this",
            "read that",
            "read the",
        )
        return any(phrase in lower for phrase in triggers)

    async def _inject_scene_context(self, transcript: str) -> None:
        """When the user asks a vision question, prepend a brief scene caption
        as a system note so even a text-only Qwen can answer about what
        Reachy is currently looking at. Best-effort; never blocks the turn."""
        if not self._is_vision_relevant(transcript):
            return
        try:
            from app.services.reachy_vision_service import get_reachy_vision_service
            vision = get_reachy_vision_service()
            analysis = await asyncio.wait_for(
                vision.analyze_latest(kind="face", provider_id="reachy", question=transcript),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            logger.debug("scene_context_vlm_timeout")
            return
        except Exception as e:
            logger.debug("scene_context_vlm_failed", error=str(e))
            return
        if not isinstance(analysis, dict) or not analysis.get("available"):
            return
        caption = (analysis.get("caption") or "").strip()
        answer = (analysis.get("answer") or "").strip()
        detections = analysis.get("detections") or []
        face_count = sum(1 for d in detections if isinstance(d, dict) and d.get("kind") == "face")
        parts = []
        if caption:
            parts.append(f"Scene: {caption}")
        if face_count:
            parts.append(f"Faces visible: {face_count}")
        if answer:
            parts.append(f"VLM answer: {answer}")
        if not parts:
            return
        note = (
            "[Reachy camera context — use only if the user's question is about "
            "what Reachy can see right now]\n" + "\n".join(parts)
        )
        self._messages.append({"role": "system", "content": note})
        logger.info(
            "scene_context_injected",
            caption_len=len(caption),
            face_count=face_count,
            had_answer=bool(answer),
        )

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
                    # English-only models avoid the multilingual language
                    # detector and shave time off short local voice turns.
                    self._whisper_model = WhisperModel(
                        STT_MODEL_NAME, device="auto", compute_type="int8"
                    )
                stats = _pcm_stats(pcm)
                samples = _prepare_samples_for_stt(pcm)
                segments, _info = self._whisper_model.transcribe(
                    samples,
                    language="en",
                    beam_size=1,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.95,
                    # LocalRealtimeHandler already owns VAD turn detection.
                    # Running faster-whisper's second VAD here discards quiet
                    # but real Reachy Mini speakerphone turns before our
                    # confidence filters can inspect them.
                    vad_filter=False,
                )
                return _segments_to_transcript(segments, pcm_stats=stats)
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
        logger.info(
            "local_llm_turn_start",
            model=self.model,
            profile=self.profile_id,
            messages=len(self._messages),
            tools=len(chat_tools),
        )
        started = time.perf_counter()
        assistant_replied = False
        self._last_error = None
        for _round in range(3):
            if self._cancel_response.is_set():
                logger.info("local_llm_turn_cancelled", round=_round)
                return
            assistant_text, tool_calls, eager_tasks = await self._stream_completion(chat_tools)
            if self._last_error == "local LLM timed out":
                await self._emit({
                    "type": "error",
                    "code": "llm_timeout",
                    "message": "Local Qwen timed out while thinking. Use Recover Voice and try a shorter prompt.",
                })
                await self._emit_phase("stalled", reason="llm_timeout")
                return
            # Persist the cleaned (think-block-stripped) reply in conversation
            # history; otherwise the model's own prior chain-of-thought would
            # bias the next turn.
            cleaned_text = _clean_assistant_text(assistant_text)
            if cleaned_text:
                assistant_replied = True
                self._messages.append({"role": "assistant", "content": cleaned_text})
            if cleaned_text and tool_calls and all(
                tc.get("name") == "do_nothing" for tc in tool_calls
            ):
                # Qwen often emits a natural spoken answer followed by a
                # do_nothing tool call to say no body motion is required.
                # Treat that no-op as internal; a second tool-result round can
                # otherwise leak do_nothing(...) into the visible transcript.
                break
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
                tool_timed_out = False
                eager_task = eager_tasks.pop(tc["id"], None)
                try:
                    if eager_task is not None:
                        # Already fired mid-stream so motion + audio land
                        # together. Just await the result.
                        result = await asyncio.wait_for(
                            eager_task, timeout=TOOL_TIMEOUT_S
                        )
                    else:
                        result = await asyncio.wait_for(
                            tool_registry.dispatch(
                                tc["name"], tc["arguments"], self.deps, self.tool_manager
                            ),
                            timeout=TOOL_TIMEOUT_S,
                        )
                except asyncio.TimeoutError:
                    tool_timed_out = True
                    result = {"error": f"tool timed out after {TOOL_TIMEOUT_S:.0f}s"}
                    await self._emit({
                        "type": "error",
                        "code": "tool_timeout",
                        "message": f"{tc['name']} timed out after {TOOL_TIMEOUT_S:.0f}s.",
                    })
                    await self._emit_phase("stalled", reason="tool_timeout")
                status = "failed" if isinstance(result, dict) and result.get("error") else "completed"
                await self._emit({
                    "type": "tool.end",
                    "call_id": tc["id"],
                    "tool_name": tc["name"],
                    "status": status,
                    "result": result,
                })
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": json.dumps(result, default=str),
                })
                if tool_timed_out:
                    return

        if not assistant_replied and not self._cancel_response.is_set():
            fallback = "I heard you, but I couldn't complete that action."
            logger.info("local_llm_empty_fallback", messages=len(self._messages))
            self._messages.append({"role": "assistant", "content": fallback})
            await self._emit({
                "type": "transcript",
                "role": "assistant",
                "content": fallback,
            })
            await self._speak_chunk(fallback)

        if self._on_turn_end is not None:
            try:
                await self._on_turn_end()
            except Exception as e:
                logger.debug("on_turn_end_failed", error=str(e))
        logger.info(
            "local_llm_turn_done",
            elapsed_s=round(time.perf_counter() - started, 3),
            messages=len(self._messages),
        )

    async def _stream_completion(
        self, chat_tools: list[dict]
    ) -> tuple[str, list[dict], dict[str, asyncio.Task]]:
        """Stream a chat completion. Returns (assistant_text, tool_calls, eager_tasks).

        While text streams in we accumulate sentence-sized chunks and pass
        them to TTS so the assistant starts speaking before the LLM finishes.
        Motion tool calls (play_emotion / dance / play_motion / look_at) are
        fired eagerly in parallel as soon as their JSON args become parseable,
        so the body moves *with* the audio rather than 0.5-2 s after TTS ends.
        eager_tasks maps tool_call_id -> the in-flight dispatch Task.
        """
        assert self._http is not None
        url = f"{self._vllm_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": self._messages,
            "tools": chat_tools or None,
            "tool_choice": "auto" if chat_tools else None,
            "stream": True,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            # llama.cpp/Qwen3 otherwise may spend the whole voice-turn budget
            # in ``reasoning_content`` and return no spoken answer.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        # Drop None values (vLLM's OpenAI surface is strict about extras).
        body = {k: v for k, v in body.items() if v is not None}

        text_acc = ""
        spoken_to_idx = 0  # how much of text_acc we've already spoken
        tool_call_acc: dict[int, dict] = {}
        started_at = time.monotonic()
        saw_stream_progress = False
        eager_motion_tools = {"play_emotion", "dance", "play_motion", "look_at"}
        eager_tasks: dict[str, asyncio.Task] = {}

        async def _next_line(line_iter: Any) -> str | None:
            nonlocal saw_stream_progress
            elapsed = time.monotonic() - started_at
            if elapsed >= LLM_STREAM_HARD_TIMEOUT_S:
                self._last_error = "local LLM timed out"
                return None
            timeout_s = (
                LLM_STREAM_IDLE_TIMEOUT_S
                if saw_stream_progress
                else LLM_FIRST_TOKEN_TIMEOUT_S
            )
            timeout_s = max(0.1, min(timeout_s, LLM_STREAM_HARD_TIMEOUT_S - elapsed))
            try:
                return await asyncio.wait_for(line_iter.__anext__(), timeout=timeout_s)
            except StopAsyncIteration:
                return None
            except asyncio.TimeoutError:
                self._last_error = "local LLM timed out"
                return None

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
                line_iter = resp.aiter_lines().__aiter__()
                while True:
                    if self._cancel_response.is_set():
                        break
                    line = await _next_line(line_iter)
                    if line is None:
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
                    content = _chat_completion_content(delta)
                    if content:
                        saw_stream_progress = True
                        text_acc += content
                        cleaned = _clean_assistant_text(text_acc).lstrip()
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
                        saw_stream_progress = True
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
                        if (
                            slot["name"] in eager_motion_tools
                            and slot["id"] not in eager_tasks
                            and slot["arguments"]
                        ):
                            try:
                                parsed_args = json.loads(slot["arguments"])
                            except (json.JSONDecodeError, ValueError):
                                parsed_args = None
                            if isinstance(parsed_args, dict):
                                eager_tasks[slot["id"]] = asyncio.create_task(
                                    tool_registry.dispatch(
                                        slot["name"],
                                        slot["arguments"],
                                        self.deps,
                                        self.tool_manager,
                                    )
                                )
                                logger.debug(
                                    "local_motion_eager_fire",
                                    tool=slot["name"],
                                    call_id=slot["id"],
                                )
        except httpx.HTTPError as e:
            await self._emit({"type": "error", "message": f"vLLM stream failed: {e}"})
            return text_acc, []

        # Strip any final think-block before the tail-flush + transcript.
        cleaned_full = self._tone_guard.clean(_clean_assistant_text(text_acc))
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
        return text_acc, tool_calls, eager_tasks

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
            if len(tail) < EARLY_TTS_CHARS:
                return spoken_to_idx
            # Qwen sometimes streams a long clause before punctuation. Speak
            # a stable word boundary so the robot does not sit silent until
            # the whole answer has finished generating.
            soft_break = tail.rfind(" ", 0, EARLY_TTS_CHARS)
            if soft_break < 50:
                return spoken_to_idx
            last_break = soft_break + 1
        chunk = tail[:last_break]
        await self._speak_chunk(chunk)
        return spoken_to_idx + last_break

    async def _speak_chunk(self, text: str) -> None:
        text = self._tone_guard.clean(text.strip())
        if not text or self._cancel_response.is_set():
            return
        await self._emit_phase("speaking")
        wav_bytes: bytes = b""
        try:
            from app.services.tts_service import get_tts_service
            self._tts_service = self._tts_service or get_tts_service()
            voice_override = self.voice if (
                self.voice.startswith("fish:") or _is_edge_tts_voice(self.voice)
            ) else None
            if _is_piper_voice(self.voice):
                await self._tts_service.set_piper_voice(self.voice)
            wav_bytes, _meta = await asyncio.wait_for(
                self._tts_service.synthesize_with_meta(
                    text,
                    voice_override=voice_override,
                ),
                timeout=TTS_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            self._last_error = "tts synthesis timed out"
            logger.warning("local_tts_timeout", voice=self.voice, timeout_s=TTS_TIMEOUT_S)
            await self._emit({
                "type": "error",
                "code": "tts_timeout",
                "message": "TTS synthesis timed out. Use Recover Voice or pick a faster voice.",
            })
            await self._emit_phase("stalled", reason="tts_timeout")
            return
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
        speech_seconds = (len(pcm) / 2) / float(OUTPUT_RATE)
        self._ignore_input_until = max(
            self._ignore_input_until,
            time.monotonic() + speech_seconds + OUTPUT_ECHO_GUARD_S,
        )
        self._assistant_audio_active_until = max(
            self._assistant_audio_active_until,
            time.monotonic() + speech_seconds + OUTPUT_ECHO_GUARD_S,
        )
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
                    self._assistant_audio_active_until = max(
                        self._assistant_audio_active_until,
                        time.monotonic() + 0.6,
                    )
                    await asyncio.wait_for(
                        self._on_assistant_audio(piece, OUTPUT_RATE),
                        timeout=SPEAKER_CALLBACK_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    logger.debug("on_assistant_audio_timeout")
                    await self._emit({
                        "type": "error",
                        "code": "speaker_backpressure",
                        "message": "Reachy speaker is not accepting audio fast enough.",
                    })
                    await self._emit_phase("stalled", reason="speaker_backpressure")
                    break
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
