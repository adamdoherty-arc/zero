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
ENGINE_FISH = "fish-speech"
ENGINE_NONE = "none"

# Fish-Speech S2 Pro server (OpenAI-compatible /v1/audio/speech). Run on the
# Windows host via:
#     fish-speech serve --port 18802 --device cuda
# Voices that start with ``fish:`` route here; everything else falls through
# to Piper / Edge-TTS. Reference: https://github.com/fishaudio/fish-speech
_FISH_PREFIX = "fish:"
_FISH_DEFAULT_URL = os.getenv("FISH_SPEECH_URL", "http://host.docker.internal:18802/v1")
_FISH_TIMEOUT_S = float(os.getenv("FISH_SPEECH_TIMEOUT_S", "20"))
_VOICE_CLONE_DIR = Path(__file__).resolve().parents[1] / "data" / "voice_clones"


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

    async def synthesize(self, text: str, *, voice_override: Optional[str] = None) -> bytes:
        """
        Synthesize text to WAV audio bytes.

        Args:
            text: Text to speak
            voice_override: Optional edge-tts voice name (e.g. "en-GB-RyanNeural").
                When set, forces edge-tts with the given voice for this call only,
                regardless of the primary engine. Falls back to the default engine
                path if edge-tts is unavailable.
        """
        audio, _meta = await self.synthesize_with_meta(text, voice_override=voice_override)
        return audio

    async def synthesize_with_meta(
        self, text: str, *, voice_override: Optional[str] = None
    ) -> tuple[bytes, dict]:
        """
        Like :meth:`synthesize` but also returns ``{"engine", "voice"}`` so
        callers can surface which engine + voice actually produced the bytes.
        """
        await self.initialize()

        if voice_override:
            # Fish-Speech route — voice IDs prefixed with ``fish:`` resolve to
            # either a built-in preset (``fish:warm-female``) or a stored
            # reference clip (``fish:local-companion-warm`` → reads
            # ``data/voice_clones/local-companion-warm.wav``).
            if voice_override.startswith(_FISH_PREFIX):
                try:
                    audio = await self._synthesize_fish(text, voice_override)
                    return audio, {"engine": ENGINE_FISH, "voice": voice_override}
                except Exception as e:
                    logger.warning(
                        "fish_speech_failed_falling_back",
                        voice=voice_override,
                        error=str(e),
                    )
                    # Fall through to edge-tts so the voice loop never silently
                    # dies when the Fish-Speech server is offline.
            try:
                import edge_tts  # noqa: F401
                audio = await self._synthesize_edge(text, voice=voice_override)
                return audio, {"engine": ENGINE_EDGE, "voice": voice_override}
            except ImportError:
                logger.warning(
                    "voice_override_unavailable",
                    voice=voice_override,
                    reason="edge-tts not installed",
                )
                # fall through to default engine

        if self._engine == ENGINE_PIPER:
            try:
                audio = await self._synthesize_piper(text)
                return audio, {"engine": ENGINE_PIPER, "voice": self._model_name}
            except Exception as e:
                # Voice file missing or piper runtime error. Fall through to
                # edge-tts so the voice loop never goes silent. We pin the
                # engine to ENGINE_EDGE so subsequent calls don't pay the
                # piper-failure cost again this session.
                logger.warning("piper_synth_failed_falling_back_to_edge", error=str(e))
                try:
                    import edge_tts  # noqa: F401
                    self._engine = ENGINE_EDGE
                    audio = await self._synthesize_edge(text)
                    return audio, {"engine": ENGINE_EDGE, "voice": self._edge_voice}
                except ImportError:
                    raise
        elif self._engine == ENGINE_EDGE:
            audio = await self._synthesize_edge(text)
            return audio, {"engine": ENGINE_EDGE, "voice": self._edge_voice}
        else:
            raise RuntimeError(
                "No TTS engine available. Install edge-tts: pip install edge-tts"
            )

    async def set_piper_voice(self, voice: str) -> None:
        """Switch the Piper voice and drop the cached model so the next call reloads."""
        voice = (voice or "").strip()
        if not voice:
            raise ValueError("voice must be non-empty")
        if voice == self._model_name:
            return
        self._model_name = voice
        self._piper_model = None
        logger.info("tts_voice_changed", voice=voice)

    async def warmup(self) -> dict:
        """
        Load Piper (or edge-tts) and synthesize a one-word sample so the first
        real voice turn isn't paying cold-start cost. Returns status dict.
        """
        import time as _time
        t0 = _time.monotonic()
        try:
            await self.initialize()
            _ = await self.synthesize("ready")
            load_ms = int((_time.monotonic() - t0) * 1000)
            logger.info("tts_warmup", engine=self._engine, load_ms=load_ms)
            return {"engine": self._engine, "load_ms": load_ms, "ok": True}
        except Exception as e:
            logger.warning("tts_warmup_failed", error=str(e))
            return {"engine": self._engine, "ok": False, "error": str(e)}

    async def synthesize_to_file(self, text: str, path: str, *, voice_override: Optional[str] = None) -> str:
        """
        Synthesize text and save to a WAV file.

        Args:
            text: Text to speak
            path: Output file path
            voice_override: Optional edge-tts voice override (see synthesize()).
        """
        audio_bytes = await self.synthesize(text, voice_override=voice_override)
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        logger.info("tts_saved_to_file", path=str(output_path), size=len(audio_bytes))
        return str(output_path)

    def _resolve_piper_path(self) -> str:
        """Map a bare voice name (e.g. ``en_US-lessac-medium``) to the .onnx
        path on disk. The Dockerfile pre-downloads voices into /app/voices.
        Absolute paths are passed through unchanged so callers can override
        with ``TTS_MODEL=/some/other/voice.onnx``.
        """
        name = self._model_name
        if os.path.isabs(name) and os.path.exists(name):
            return name
        # Common search paths, in order of preference.
        for base in ("/app/voices", os.getenv("PIPER_VOICES_DIR", "")):
            if not base:
                continue
            cand = os.path.join(base, name)
            if cand.endswith(".onnx") and os.path.exists(cand):
                return cand
            cand_onnx = cand + ".onnx" if not cand.endswith(".onnx") else cand
            if os.path.exists(cand_onnx):
                return cand_onnx
        # Last resort — let piper try its own resolution. This is what the
        # legacy code did and produces the original FileNotFoundError if the
        # voice isn't installed anywhere.
        return name

    async def _synthesize_piper(self, text: str) -> bytes:
        """Synthesize using piper-tts (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._synthesize_piper_sync, text)

    def _synthesize_piper_sync(self, text: str) -> bytes:
        """Synchronous piper synthesis."""
        import piper
        import wave

        if self._piper_model is None:
            self._piper_model = piper.PiperVoice.load(self._resolve_piper_path())

        # piper-tts >=1.2 split the API: ``synthesize`` returns an iterable
        # of audio chunks (no WAV framing), and ``synthesize_wav`` writes a
        # complete WAV to a wave-file writer with ``set_wav_format=True``
        # handling the header. Use the WAV variant so we don't have to
        # reassemble PCM frames ourselves.
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            self._piper_model.synthesize_wav(text, wav_file, set_wav_format=True)

        return buffer.getvalue()

    async def _synthesize_edge(self, text: str, *, voice: Optional[str] = None) -> bytes:
        """Synthesize using edge-tts (async, returns MP3 converted to WAV-like bytes)."""
        import edge_tts

        communicate = edge_tts.Communicate(text, voice or self._edge_voice)

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

    async def _synthesize_fish(self, text: str, voice: str) -> bytes:
        """Call a local Fish-Speech S2 Pro server with OpenAI-compatible
        /v1/audio/speech. Returns WAV bytes. Raises on any failure so the
        caller can fall back to Edge-TTS.
        """
        try:
            import httpx  # type: ignore
        except ImportError as e:
            raise RuntimeError(f"httpx required for Fish-Speech: {e}")

        voice_id = voice[len(_FISH_PREFIX):] if voice.startswith(_FISH_PREFIX) else voice
        # Built-in preset → just pass the id through. Cloned voice → resolve
        # the path to the stored reference and pass it under ``reference_audio``
        # which Fish-Speech accepts in its OpenAI-compatible wrapper.
        clone_path = _VOICE_CLONE_DIR / f"{voice_id}.wav"
        payload: dict = {
            "model": "fish-speech",
            "input": text,
            "voice": voice_id,
            "response_format": "wav",
            "stream": False,
        }
        if clone_path.exists():
            payload["reference_audio"] = str(clone_path)

        async with httpx.AsyncClient(timeout=httpx.Timeout(_FISH_TIMEOUT_S, connect=3.0)) as c:
            r = await c.post(f"{_FISH_DEFAULT_URL}/audio/speech", json=payload)
            if r.status_code != 200:
                raise RuntimeError(f"fish-speech HTTP {r.status_code}: {r.text[:200]}")
            data = r.content
            if not data:
                raise RuntimeError("fish-speech returned empty audio")
            return data

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
