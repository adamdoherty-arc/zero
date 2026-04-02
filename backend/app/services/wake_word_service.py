"""
Wake Word Detection Service

Listens for "Hey Zero" trigger phrase using keyword spotting.
Uses simple energy + keyword detection without heavy ML dependencies.
"""

import asyncio
import re
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class WakeWordService:
    """Detects wake word "Hey Zero" in transcribed audio."""

    WAKE_PHRASES = [
        "hey zero", "hi zero", "okay zero", "yo zero",
        "zero", "hey z", "hey 0",
    ]

    def __init__(self):
        self._active = False
        self._callback: Optional[Callable] = None
        self._continuous_task: Optional[asyncio.Task] = None

    def is_wake_phrase(self, text: str) -> bool:
        """Check if transcribed text contains a wake phrase."""
        text_lower = text.lower().strip()
        # Check exact match or starts with wake phrase
        for phrase in self.WAKE_PHRASES:
            if text_lower == phrase or text_lower.startswith(phrase + " ") or text_lower.startswith(phrase + ","):
                return True
            # Fuzzy: "hey zero" might transcribe as "hey xero", "hey sero"
            if re.search(rf"\bhey\s+[zsx]ero\b", text_lower):
                return True
        return False

    def extract_command_after_wake(self, text: str) -> Optional[str]:
        """Extract the command part after the wake phrase."""
        text_lower = text.lower().strip()
        for phrase in sorted(self.WAKE_PHRASES, key=len, reverse=True):
            idx = text_lower.find(phrase)
            if idx >= 0:
                after = text[idx + len(phrase):].strip().lstrip(",").strip()
                return after if after else None
        return None

    async def start_listening(self, callback: Callable):
        """Start continuous wake word detection loop.

        Uses faster-whisper for continuous transcription, then checks for wake phrase.
        When detected, calls callback with the command text.
        """
        self._active = True
        self._callback = callback
        logger.info("[WakeWord] Listening for wake phrase...")

        while self._active:
            try:
                # Use audio service for short recording + transcription
                from app.services.audio_service import get_audio_service
                audio_svc = get_audio_service()

                # Record a short clip (3 seconds)
                audio_bytes = await audio_svc.record_clip(duration_seconds=3)
                if not audio_bytes:
                    await asyncio.sleep(0.5)
                    continue

                # Transcribe
                text = await audio_svc.transcribe(audio_bytes)
                if not text or len(text.strip()) < 2:
                    continue

                # Check for wake phrase
                if self.is_wake_phrase(text):
                    command = self.extract_command_after_wake(text)
                    logger.info(f"[WakeWord] Detected! Command: {command or '(listening...)'}")

                    if command:
                        # Wake phrase + command in same utterance
                        await self._callback(command)
                    else:
                        # Just wake phrase — record the actual command
                        logger.info("[WakeWord] Listening for command...")
                        cmd_audio = await audio_svc.record_clip(duration_seconds=10)
                        if cmd_audio:
                            cmd_text = await audio_svc.transcribe(cmd_audio)
                            if cmd_text:
                                await self._callback(cmd_text)

            except Exception as e:
                logger.debug(f"[WakeWord] Error in listening loop: {e}")
                await asyncio.sleep(1)

            await asyncio.sleep(0.1)

    def stop_listening(self):
        """Stop wake word detection."""
        self._active = False
        logger.info("[WakeWord] Stopped listening")

    @property
    def is_active(self) -> bool:
        return self._active


_wake_word_service: Optional[WakeWordService] = None

def get_wake_word_service() -> WakeWordService:
    global _wake_word_service
    if _wake_word_service is None:
        _wake_word_service = WakeWordService()
    return _wake_word_service
