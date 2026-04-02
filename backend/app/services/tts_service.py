"""
Text-to-Speech service with piper-tts (primary) and edge-tts (fallback).

Provides local TTS synthesis returning WAV audio bytes.
"""

import asyncio
import io
import os
import tempfile
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger()

# TTS engine constants
ENGINE_PIPER = "piper"
ENGINE_EDGE = "edge-tts"
ENGINE_NONE = "none"


class TTSService:
    """Text-to-Speech service with lazy initialization and fallback engines."""

    _instance: Optional["TTSService"] = None

    def __init__(self):
        self._engine: str = ENGINE_NONE
        self._piper_model = None
        self._initialized = False
        self._model_name = os.getenv("TTS_MODEL", "en_US-lessac-medium")
        self._edge_voice = os.getenv("TTS_EDGE_VOICE", "en-US-AriaNeural")

    @classmethod
    def get_instance(cls) -> "TTSService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(self) -> str:
        """
        Lazy-initialize TTS engine. Tries piper first, falls back to edge-tts.
        Returns the engine name that was initialized.
        """
        if self._initialized:
            return self._engine

        # Try piper-tts first
        try:
            import piper  # noqa: F401
            self._engine = ENGINE_PIPER
            self._initialized = True
            logger.info("tts_initialized", engine=ENGINE_PIPER, model=self._model_name)
            return self._engine
        except ImportError:
            logger.info("piper_not_available", fallback="edge-tts")

        # Try edge-tts fallback
        try:
            import edge_tts  # noqa: F401
            self._engine = ENGINE_EDGE
            self._initialized = True
            logger.info("tts_initialized", engine=ENGINE_EDGE, voice=self._edge_voice)
            return self._engine
        except ImportError:
            logger.warning("no_tts_engine_available",
                           hint="Install edge-tts: pip install edge-tts")
            self._engine = ENGINE_NONE
            self._initialized = True
            return self._engine

    async def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to WAV audio bytes.

        Args:
            text: Text to speak

        Returns:
            WAV audio bytes
        """
        await self.initialize()

        if self._engine == ENGINE_PIPER:
            return await self._synthesize_piper(text)
        elif self._engine == ENGINE_EDGE:
            return await self._synthesize_edge(text)
        else:
            raise RuntimeError(
                "No TTS engine available. Install edge-tts: pip install edge-tts"
            )

    async def synthesize_to_file(self, text: str, path: str) -> str:
        """
        Synthesize text and save to a WAV file.

        Args:
            text: Text to speak
            path: Output file path

        Returns:
            Path to the saved file
        """
        audio_bytes = await self.synthesize(text)
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        logger.info("tts_saved_to_file", path=str(output_path), size=len(audio_bytes))
        return str(output_path)

    async def _synthesize_piper(self, text: str) -> bytes:
        """Synthesize using piper-tts (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._synthesize_piper_sync, text)

    def _synthesize_piper_sync(self, text: str) -> bytes:
        """Synchronous piper synthesis."""
        import piper
        import wave

        if self._piper_model is None:
            self._piper_model = piper.PiperVoice.load(self._model_name)

        # Synthesize to in-memory buffer
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self._piper_model.synthesize(text, wav_file)

        return buffer.getvalue()

    async def _synthesize_edge(self, text: str) -> bytes:
        """Synthesize using edge-tts (async, returns MP3 converted to WAV-like bytes)."""
        import edge_tts

        communicate = edge_tts.Communicate(text, self._edge_voice)

        # edge-tts produces MP3 chunks; collect them
        mp3_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buffer.write(chunk["data"])

        mp3_bytes = mp3_buffer.getvalue()

        if not mp3_bytes:
            raise RuntimeError("edge-tts returned empty audio")

        # Try to convert MP3 to WAV using soundfile/numpy if available
        try:
            import soundfile as sf
            import numpy as np

            # Write MP3 to temp file for soundfile to read
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(mp3_bytes)
                tmp_path = tmp.name

            try:
                data, samplerate = sf.read(tmp_path)
                wav_buffer = io.BytesIO()
                sf.write(wav_buffer, data, samplerate, format="WAV")
                return wav_buffer.getvalue()
            finally:
                os.unlink(tmp_path)
        except Exception:
            # If conversion fails, return raw MP3 bytes
            # (most audio players handle both)
            logger.debug("mp3_to_wav_conversion_skipped", reason="soundfile unavailable")
            return mp3_bytes

    def get_status(self) -> dict:
        """Get TTS engine status."""
        return {
            "initialized": self._initialized,
            "engine": self._engine,
            "model": self._model_name if self._engine == ENGINE_PIPER else self._edge_voice,
            "available": self._engine != ENGINE_NONE,
        }


def get_tts_service() -> TTSService:
    """Get singleton TTSService instance."""
    return TTSService.get_instance()
