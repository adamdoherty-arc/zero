"""
Voice loop service — orchestrates the full voice pipeline.

Pipeline: listen → transcribe (STT) → think (LLM) → speak (TTS)
Optionally drives Reachy Mini robot actions when connected.
"""

import asyncio
from typing import Optional, Dict, Any
import structlog

from app.services.audio_service import get_audio_service
from app.services.tts_service import get_tts_service
from app.services.reachy_service import get_reachy_service

logger = structlog.get_logger()


class VoiceLoopService:
    """Orchestrates listen → transcribe → think → speak pipeline."""

    _instance: Optional["VoiceLoopService"] = None

    def __init__(self):
        self._listening = False
        self._listen_task: Optional[asyncio.Task] = None
        self._audio_service = get_audio_service()
        self._tts_service = get_tts_service()
        self._reachy_service = get_reachy_service()

    @classmethod
    def get_instance(cls) -> "VoiceLoopService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def process_voice_input(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Full voice pipeline: transcribe → think → speak.

        Args:
            audio_bytes: Raw audio bytes (WAV/MP3/etc.)

        Returns:
            Dict with transcription, llm_response, and audio_response
        """
        result: Dict[str, Any] = {
            "transcription": None,
            "llm_response": None,
            "audio_response": None,
            "robot_connected": False,
        }

        # Step 1: Transcribe audio (STT)
        try:
            transcription = await self._audio_service.transcribe_upload(
                audio_bytes, "voice_input.wav"
            )
            result["transcription"] = {
                "text": transcription.text,
                "language": transcription.language,
                "duration": transcription.duration_seconds,
            }
            user_text = transcription.text
        except Exception as e:
            logger.error("voice_stt_failed", error=str(e))
            result["error"] = f"Transcription failed: {e}"
            return result

        if not user_text or not user_text.strip():
            result["error"] = "No speech detected"
            return result

        logger.info("voice_transcribed", text=user_text[:100])

        # Step 2: Get LLM response via orchestration graph
        try:
            response_text = await self._get_llm_response(user_text)
            result["llm_response"] = response_text
        except Exception as e:
            logger.error("voice_llm_failed", error=str(e))
            response_text = "I'm sorry, I had trouble processing that."
            result["llm_response"] = response_text
            result["llm_error"] = str(e)

        # Step 3: Synthesize response (TTS)
        try:
            audio_response = await self._tts_service.synthesize(response_text)
            result["audio_response_size"] = len(audio_response)
            result["audio_response"] = audio_response
        except Exception as e:
            logger.error("voice_tts_failed", error=str(e))
            result["tts_error"] = str(e)

        # Step 4: Robot actions (if connected)
        try:
            robot_connected = await self._reachy_service.is_connected()
            result["robot_connected"] = robot_connected

            if robot_connected:
                # Play emotion based on response, then speak
                await self._reachy_service.say(response_text)
        except Exception as e:
            logger.debug("voice_robot_skipped", error=str(e))

        return result

    async def _get_llm_response(self, text: str) -> str:
        """Route text through LLM orchestration and get response."""
        try:
            from app.services.chat_service import get_chat_service
            chat_service = get_chat_service()
            response = await chat_service.chat(text)
            # chat_service returns various formats; extract text
            if isinstance(response, dict):
                return response.get("response", response.get("text", str(response)))
            return str(response)
        except ImportError:
            logger.warning("chat_service_unavailable", fallback="direct_llm")
            # Fallback: use LLM router directly
            try:
                from app.infrastructure.llm_router import get_llm_router
                router = get_llm_router()
                response = await router.chat(
                    messages=[{"role": "user", "content": text}],
                    model_preference="fast",
                )
                return response.get("content", str(response))
            except Exception as e:
                raise RuntimeError(f"No LLM backend available: {e}")

    async def start_listening(self):
        """Start continuous voice loop (listens for audio input)."""
        if self._listening:
            logger.info("voice_loop_already_running")
            return

        self._listening = True
        logger.info("voice_loop_started")

        # Note: Actual microphone capture requires platform-specific audio input
        # (e.g., sounddevice, PyAudio). This is a framework that processes
        # audio chunks as they arrive via the API.
        # For continuous listening, the frontend/client sends audio chunks
        # to POST /api/reachy/say or a WebSocket endpoint.

    async def stop_listening(self):
        """Stop continuous voice loop."""
        if not self._listening:
            return

        self._listening = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        self._listen_task = None
        logger.info("voice_loop_stopped")

    def get_status(self) -> dict:
        """Get voice loop status."""
        return {
            "listening": self._listening,
            "tts": self._tts_service.get_status(),
        }


def get_voice_loop_service() -> VoiceLoopService:
    """Get singleton VoiceLoopService instance."""
    return VoiceLoopService.get_instance()
