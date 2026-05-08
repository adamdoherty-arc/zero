"""
Reachy voice stack configuration — which STT / LLM / TTS the voice loop uses.

Persists to ``workspace/reachy/voice_config.json`` via JsonStorage. The LLM
choice proxies through the shared LlmRouter (task_type ``voice_reply``) so
there is one source of truth for model assignments; this service only owns
the STT model and TTS voice.

Defaults:
    stt_model  = "tiny"     (Whisper size; fastest cold-start; drop-in later)
    tts_voice  = env TTS_MODEL or "en_US-lessac-medium"
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import structlog

from app.infrastructure.config import get_workspace_path
from app.infrastructure.storage import JsonStorage

logger = structlog.get_logger(__name__)

_CONFIG_FILE = "voice_config.json"
_DEFAULT_STT_MODEL = "tiny"


def _default_tts_voice() -> str:
    return os.getenv("TTS_MODEL", "en_US-lessac-medium")


class ReachyVoiceConfigService:
    """Singleton holding the current voice-stack selections."""

    _instance: Optional["ReachyVoiceConfigService"] = None

    def __init__(self) -> None:
        self._storage = JsonStorage(get_workspace_path("reachy"))
        self._stt_model: str = _DEFAULT_STT_MODEL
        self._tts_voice: str = _default_tts_voice()
        self._loaded: bool = False

    @classmethod
    def get_instance(cls) -> "ReachyVoiceConfigService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def load(self) -> None:
        """Read persisted config. Called once at startup; safe to re-call."""
        data = await self._storage.read(_CONFIG_FILE)
        if isinstance(data, dict):
            stt = data.get("stt_model")
            if isinstance(stt, str) and stt.strip():
                self._stt_model = stt.strip()
            tts = data.get("tts_voice")
            if isinstance(tts, str) and tts.strip():
                self._tts_voice = tts.strip()
        self._loaded = True
        logger.info(
            "reachy_voice_config_loaded",
            stt_model=self._stt_model,
            tts_voice=self._tts_voice,
        )

    async def _save(self) -> None:
        await self._storage.write(
            _CONFIG_FILE,
            {"stt_model": self._stt_model, "tts_voice": self._tts_voice},
        )

    def get_stt_model(self) -> str:
        return self._stt_model

    def get_tts_voice(self) -> str:
        return self._tts_voice

    async def set_stt_model(self, model: str) -> None:
        model = (model or "").strip()
        if not model:
            raise ValueError("stt_model must be a non-empty string")
        self._stt_model = model
        await self._save()
        logger.info("reachy_voice_stt_changed", model=model)

    async def set_tts_voice(self, voice: str) -> None:
        voice = (voice or "").strip()
        if not voice:
            raise ValueError("tts_voice must be a non-empty string")
        self._tts_voice = voice
        await self._save()
        logger.info("reachy_voice_tts_changed", voice=voice)


@lru_cache()
def get_reachy_voice_config() -> ReachyVoiceConfigService:
    return ReachyVoiceConfigService.get_instance()
