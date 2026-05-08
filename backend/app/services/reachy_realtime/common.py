"""
Shared types for the Reachy realtime bridge.

Zero runs the motion subsystem behind ``reachy_service``, which speaks REST to
the Pollen Reachy Mini daemon (``/api/move/*``, ``/api/media/*``, …). That is
different from the upstream conversation app, which drives a 60 Hz in-process
MovementManager thread and a local CameraWorker. The ``MotionDispatcher`` in
this module adapts the tool surface to call ``reachy_service`` instead, so the
ported OpenAI/Gemini handlers work without the upstream runtime.

Upstream reference:
https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/main/src/reachy_mini_conversation_app/tools/core_tools.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import structlog

BACKEND_OPENAI = "openai"
BACKEND_GEMINI = "gemini"
# "local" = faster-whisper (STT) + vLLM (LLM, default qwen3-chat on the
# 5090) + piper-tts/edge-tts (TTS) + Silero VAD for barge-in. No cloud calls.
BACKEND_LOCAL = "local"

DEFAULT_MODEL_BY_BACKEND: dict[str, str] = {
    BACKEND_OPENAI: "gpt-realtime",
    BACKEND_GEMINI: "gemini-3.1-flash-live-preview",
    BACKEND_LOCAL: "qwen3-chat",
}

OPENAI_AVAILABLE_VOICES: tuple[str, ...] = (
    "alloy", "ash", "ballad", "cedar", "coral",
    "echo", "marin", "sage", "shimmer", "verse",
)

GEMINI_AVAILABLE_VOICES: tuple[str, ...] = (
    "Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck", "Zephyr",
)

# Edge-tts voices; piper voices (en_US-lessac-medium etc.) are accepted too
# — the local handler hands the string straight to TTSService, which knows
# both naming schemes and falls back gracefully.
LOCAL_AVAILABLE_VOICES: tuple[str, ...] = (
    "en-US-AriaNeural", "en-US-JennyNeural", "en-US-GuyNeural",
    "en-GB-RyanNeural", "en-GB-SoniaNeural",
    "en_US-lessac-medium", "en_US-amy-medium",
)

DEFAULT_VOICE_BY_BACKEND: dict[str, str] = {
    BACKEND_OPENAI: "cedar",
    BACKEND_GEMINI: "Kore",
    BACKEND_LOCAL: "en-US-AriaNeural",
}


def normalize_backend(candidate: Optional[str]) -> str:
    """Return the canonical backend string, defaulting to OpenAI."""
    if not candidate:
        return BACKEND_OPENAI
    c = candidate.strip().lower()
    return c if c in DEFAULT_MODEL_BY_BACKEND else BACKEND_OPENAI


def resolve_model(backend: str, override: Optional[str]) -> str:
    """Pick a model for the backend, preferring a non-empty override."""
    backend = normalize_backend(backend)
    if override and override.strip():
        return override.strip()
    return DEFAULT_MODEL_BY_BACKEND[backend]


def resolve_voice(backend: str, override: Optional[str]) -> str:
    """Pick a voice for the backend, preferring a non-empty override.

    For the local backend we accept any string the TTSService knows (Piper /
    Edge-TTS / cloned voices), but we explicitly reject voices that belong to
    another backend's pool. Otherwise an OpenAI voice id like ``cedar`` leaks
    into a local session, the local TTS engine returns empty PCM, and the
    speaker sink stays silent — which is exactly the "robot doesn't speak in
    Local mode" bug.
    """
    backend = normalize_backend(backend)
    if override and override.strip():
        candidate = override.strip()
        if backend == BACKEND_OPENAI:
            pool: tuple[str, ...] = OPENAI_AVAILABLE_VOICES
        elif backend == BACKEND_GEMINI:
            pool = GEMINI_AVAILABLE_VOICES
        else:
            cand_lower = candidate.lower()
            cross_pool: set[str] = {v.lower() for v in OPENAI_AVAILABLE_VOICES}
            cross_pool |= {v.lower() for v in GEMINI_AVAILABLE_VOICES}
            if cand_lower in cross_pool:
                logger.warning(
                    "local_voice_rejected_cross_pool",
                    candidate=candidate,
                    fallback=DEFAULT_VOICE_BY_BACKEND[BACKEND_LOCAL],
                )
                return DEFAULT_VOICE_BY_BACKEND[BACKEND_LOCAL]
            return candidate
        lower = {v.lower(): v for v in pool}
        return lower.get(candidate.lower(), DEFAULT_VOICE_BY_BACKEND[backend])
    return DEFAULT_VOICE_BY_BACKEND[backend]


@dataclass
class MotionDispatcher:
    """Zero-side motion surface consumed by the realtime tools.

    Each callable returns a dict (mirrors ``reachy_service`` shapes) so tool
    results the LLM sees look like the upstream app's. ``None`` callables
    yield ``{"available": False}`` — safer than crashing when the daemon is
    offline.
    """

    move_head: Callable[..., Awaitable[dict]] | None = None
    play_emotion: Callable[[str], Awaitable[dict]] | None = None
    play_dance: Callable[[str], Awaitable[dict]] | None = None
    stop_move: Callable[..., Awaitable[dict]] | None = None
    list_emotions: Callable[[], list[str]] | None = None
    list_dances: Callable[[], list[str]] | None = None
    capture_image: Callable[[], Awaitable[bytes]] | None = None
    set_head_tracking: Callable[[bool], Awaitable[dict]] | None = None


@dataclass
class ToolDependencies:
    """Dependencies injected into realtime tools.

    The upstream ``ToolDependencies`` carries a ``reachy_mini`` SDK handle, a
    ``movement_manager`` thread, a ``camera_worker`` thread, and optional
    ``vision_processor`` / ``head_wobbler`` hooks. In Zero all of those are
    replaced by a single ``MotionDispatcher`` that fans out to
    ``reachy_service``.
    """

    motion: MotionDispatcher
    motion_duration_s: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)


logger = structlog.get_logger()
