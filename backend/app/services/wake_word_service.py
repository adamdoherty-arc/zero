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

    # Note: bare "zero" was removed because it produced false matches on
    # unrelated phrases like "zero point one five meters".
    # Two tiers:
    #   - WAKE_PHRASES: accepted via exact/substring match only.
    #   - WAKE_PHRASES_FUZZY: additionally accepted via rapidfuzz when
    #     whisper mishears the user. Kept narrow ("hey <variant>") because
    #     broader fuzzy phrases like "hi zero" collide with common sentences
    #     ("this IS ZERO point one five meters").
    WAKE_PHRASES = [
        "hey zero", "hi zero", "okay zero", "ok zero", "yo zero",
        "hello zero", "hey z", "hey 0",
        # Whisper mishearings seen in the log — kept as exact substrings
        # (not fuzzy) because "his zero" alone would fuzzy-match "is zero"
        # in normal speech, but the exact substring "his zero" doesn't
        # appear in "this is zero point five meters" (different word break).
        "his zero", "hes zero", "he is zero", "heres zero",
    ]
    WAKE_PHRASES_FUZZY = [
        "hey zero",
        # Mishearings drawn from real host_agent log transcripts of the user
        # saying "hey zero": whisper swaps the z and sometimes the salutation.
        # Only keep variants that start with "hey" in the fuzzy list — shorter
        # forms like "his zero" trivially match "is zero" in normal speech.
        "hey sero", "hey cero", "hey xero", "hey arrow", "hey zara",
        "hey ziro", "hey zir", "hey ziero",
    ]
    # Characters to flatten before phrase matching. Without this,
    # "Okay, zero." (whisper's frequent rendering of a user "okay zero"
    # wake) never substring-matches because of the comma.
    # Apostrophes and hyphens are DROPPED (not replaced with space) so
    # "He's zero" normalizes to "hes zero", not "he s zero".
    _PUNCT_SPACE = str.maketrans({c: " " for c in ".,!?;:\"()[]"})
    _PUNCT_DROP = str.maketrans({c: "" for c in "'`-"})
    _PUNCT_TRANS = _PUNCT_SPACE  # back-compat alias

    # Transcripts longer than this are almost always TV/video dialogue — not
    # a deliberate wake. Reject before fuzzy-matching to avoid false positives.
    _MAX_WAKE_UTTERANCE_WORDS = 8
    # Minimum rapidfuzz partial_ratio for acceptance. Raised from 82 → 85
    # after testing: all enumerated mishearings score 100, so the margin is
    # generous; 83.3 was the highest false-positive ("is zero" vs "hey zero"),
    # so 85 cuts it cleanly.
    _FUZZY_RATIO = 85
    # partial_ratio matches any substring, so inputs shorter than a wake
    # phrase score 100 trivially ("hey" vs "hey zero"). Require the input to
    # be at least this long before fuzzy-matching, so wake utterances
    # actually span both words of the phrase.
    _MIN_FUZZY_CHARS = 6

    def __init__(self):
        self._active = False
        self._callback: Optional[Callable] = None
        self._continuous_task: Optional[asyncio.Task] = None

    def is_wake_phrase(self, text: str) -> bool:
        """Check if transcribed text contains a wake phrase.

        Substring match first (cheap), then rapidfuzz partial_ratio for whisper
        mishearings. Long transcripts are rejected before fuzzy to avoid
        matching ambient media.
        """
        # Flatten punctuation + collapse whitespace before matching —
        # whisper often renders a spoken "okay zero" as "Okay, zero." which
        # would never substring-match without normalization.
        text_lower = " ".join(
            text.lower().translate(self._PUNCT_DROP).translate(self._PUNCT_SPACE).split()
        )
        if not text_lower:
            return False
        if len(text_lower.split()) > self._MAX_WAKE_UTTERANCE_WORDS:
            return False
        # Stage 1: exact/starts-with/embedded substring match.
        for phrase in self.WAKE_PHRASES:
            if (
                text_lower == phrase
                or text_lower.startswith(phrase + " ")
                or text_lower.startswith(phrase + ",")
                or f" {phrase} " in f" {text_lower} "
            ):
                return True
            # Regex fallback kept for the z/s/x "zero" homophones.
            if re.search(rf"\bhey\s+[zsx]ero\b", text_lower):
                return True
        # Stage 2: fuzzy match (when rapidfuzz is installed). Skip for very
        # short inputs — partial_ratio matches any substring, so "hey" would
        # score 100 against "hey zero". Require enough chars for the input to
        # plausibly span a two-word wake phrase.
        if len(text_lower) < self._MIN_FUZZY_CHARS:
            return False
        try:
            from rapidfuzz import fuzz  # local import to avoid hard dep
        except ImportError:
            return False
        # Fuzzy-match only the narrow "hey <variant>" set so words like "is"
        # in normal speech don't line up with "hi zero" to fire a false wake.
        for phrase in self.WAKE_PHRASES_FUZZY:
            if fuzz.partial_ratio(phrase, text_lower) >= self._FUZZY_RATIO:
                return True
        return False

    def extract_command_after_wake(self, text: str) -> Optional[str]:
        """Extract the command part after the wake phrase."""
        # Normalize the same way is_wake_phrase does so boundary search agrees.
        text_lower = " ".join(
            text.lower().translate(self._PUNCT_DROP).translate(self._PUNCT_SPACE).split()
        )
        for phrase in sorted(self.WAKE_PHRASES, key=len, reverse=True):
            idx = text_lower.find(phrase)
            if idx >= 0:
                after = text_lower[idx + len(phrase):].strip()
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
