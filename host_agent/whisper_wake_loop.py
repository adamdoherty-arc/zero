"""
Whisper-based continuous wake-word listener.

Fallback / alternative to the Porcupine loop in wake_loop.py. Uses faster-whisper
"tiny" running on CPU to scan rolling 3-second audio windows for a wake phrase
(default "hey zero"). When it matches, the remaining text in the same window is
treated as the command; if nothing followed the wake, we capture additional
audio until silence and transcribe that as the command.

Trade-offs vs Porcupine:
  + Zero external-account dependency — nothing to approve, no access key.
  - Higher CPU (a few % of one core continuously; small because Whisper tiny is
    tiny and we only run it on VAD-speech chunks).
  - Slightly looser matching. "Hey Zero" variants, "zero", "zeroo" are all
    accepted; you get occasional false positives on similar words.

The public interface mirrors wake_loop.WakeLoop so host_agent/main.py can pick
one at runtime.
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf
import structlog

logger = structlog.get_logger()


SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000   # 480 samples per 30ms
SCAN_WINDOW_SECONDS = 3.0
SCAN_INTERVAL_SECONDS = 1.0                      # re-scan the buffer this often
# VAD threshold (float32). Raised from 0.008 → 0.015 so background TV/music
# doesn't continuously trigger whisper transcription attempts. The native
# Pollen app uses roughly -35 dBFS (≈ 0.018 RMS) for speech-on.
SILENCE_RMS = 0.015
COMMAND_SILENCE_MS = 800                         # stop capturing command after this quiet
COMMAND_MAX_SECONDS = 10.0
# Transcripts longer than this are almost always TV/video dialogue that happens
# to contain a wake-ish word. Reject them before fuzzy match.
MAX_WAKE_UTTERANCE_WORDS = 8
# Minimum fuzzy-match ratio (0-100) for a wake phrase. Raised from 82 → 85
# after empirical testing: all enumerated mishearings score 100 ("hey zero"
# is a substring of them), and the highest false positive was "is zero" at
# 83.3 against "hey zero". 85 cuts that cleanly.
WAKE_FUZZY_RATIO = 85
# rapidfuzz.partial_ratio matches any substring, so inputs shorter than a
# wake phrase score 100 trivially ("hey" vs "hey zero"). Require this many
# chars before fuzzy-matching so a wake utterance spans both words.
MIN_FUZZY_CHARS = 6
WAKE_PHRASES_DEFAULT = (
    "hey zero", "okay zero", "ok zero", "hello zero", "yo zero",
    # Common whisper mishearings — the model often substitutes the 'z' or
    # rephrases the salutation. These are drawn from real host_agent.log
    # transcripts of the user saying "hey zero" under ambient noise.
    # Exact-substring variants only in this list; fuzzy list below is
    # narrowed to "hey <variant>" to avoid "is zero" false positives.
    "hey sero", "hey cero", "hey xero", "hey arrow", "hey zara",
    "his zero", "hes zero", "he is zero", "heres zero",
    "hey zir", "hey ziro", "hey ziero",
)
# Only these are fuzzy-matched; others ("hi/yo/okay zero", "his zero") are
# too easy to collide with normal speech — "this IS ZERO point one five
# meters" trivially fuzzy-matches "his zero" because "is zero" is a
# substring. Fuzzy is restricted to "hey <variant>" only.
WAKE_PHRASES_FUZZY_DEFAULT = (
    "hey zero", "hey sero", "hey cero", "hey xero", "hey arrow", "hey zara",
    "hey ziro", "hey zir", "hey ziero",
)

# Characters to flatten before phrase matching. Whisper loves to add commas
# and periods between "okay" and "zero" so the raw transcript "Okay, zero."
# would never substring-match "okay zero" without this.
# Apostrophes/hyphens are DROPPED (not spaced) so "He's zero" → "hes zero".
_PUNCT_SPACE = str.maketrans({c: " " for c in ".,!?;:\"()[]"})
_PUNCT_DROP = str.maketrans({c: "" for c in "'`-"})

try:
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore

    def _fuzzy_score(text_low: str, phrase: str) -> int:
        return int(_rf_fuzz.partial_ratio(phrase, text_low))
except ImportError:  # pragma: no cover — graceful degrade when dep unavailable
    _rf_fuzz = None

    def _fuzzy_score(text_low: str, phrase: str) -> int:
        return 100 if phrase in text_low else 0


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Required because
    whisper output like "Okay, zero." won't substring-match "okay zero"
    without it."""
    return " ".join(
        text.lower().translate(_PUNCT_DROP).translate(_PUNCT_SPACE).split()
    )


def _has_wake(text: str, phrases: tuple[str, ...]) -> Optional[int]:
    """Return the index just after the wake phrase, or None if not found.

    Two-stage: cheap substring match first, then rapidfuzz partial_ratio for
    whisper's typical mishearings. Long transcripts (> MAX_WAKE_UTTERANCE_WORDS)
    are rejected regardless — they're almost always ambient media.
    """
    low = _normalize(text)
    if not low:
        return None
    # Short-circuit on absurdly long transcripts — those are TV/video, not wakes.
    if len(low.split()) > MAX_WAKE_UTTERANCE_WORDS:
        return None
    # Stage 1: exact substring (fast path).
    for p in phrases:
        idx = low.find(p)
        if idx >= 0:
            return idx + len(p)
    # Stage 2: fuzzy — only if the input is long enough that partial_ratio
    # isn't trivially 100 from a short substring match. Restrict to the
    # narrow "hey <variant>" set so mishearing tolerance doesn't open the
    # door to false wakes from normal speech.
    if len(low) < MIN_FUZZY_CHARS:
        return None
    for p in WAKE_PHRASES_FUZZY_DEFAULT:
        if _fuzzy_score(low, p) >= WAKE_FUZZY_RATIO:
            # Approximate end-index by length of matched phrase; exact position
            # is unrecoverable from partial_ratio, but tail-extraction below
            # handles both "[wake][tail]" and "[wake]" cleanly.
            return len(low)
    return None


def _clean_command(text: str) -> str:
    # Whisper sometimes keeps trailing punctuation / newlines
    return re.sub(r"\s+", " ", text).strip(" .,!?\n")


class WhisperWakeLoop:
    def __init__(
        self,
        *,
        keyword: str = "hey zero",
        device_index: Optional[int] = None,
        on_command: Optional[Callable[[str], None]] = None,
        whisper_model: str = "tiny",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
        extra_phrases: Optional[tuple[str, ...]] = None,
    ) -> None:
        self._primary = keyword.lower().strip()
        # Always include the primary + a few common variants so Whisper's
        # occasional drop of articles doesn't miss a wake.
        phrases = [self._primary] + list(extra_phrases or ())
        for w in WAKE_PHRASES_DEFAULT:
            if w not in phrases:
                phrases.append(w)
        self._phrases: tuple[str, ...] = tuple(phrases)

        self._device_index = device_index
        self._on_command = on_command
        self._whisper_model_name = whisper_model
        self._whisper_device = whisper_device
        self._whisper_compute_type = whisper_compute_type

        self._whisper = None
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._last_wake_at: Optional[float] = None
        self._frame_q: queue.Queue = queue.Queue(maxsize=200)
        # Rolling buffer of recent audio (float32 mono)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._buffer_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public surface (mirrors wake_loop.WakeLoop)
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def status(self) -> dict:
        return {
            "running": self._running,
            "paused": self._paused,
            "mode": "whisper",
            "keyword": self._primary,
            "phrases": list(self._phrases),
            "device_index": self._device_index,
            "whisper_model": self._whisper_model_name,
            "last_wake_at": self._last_wake_at,
        }

    def start(self) -> None:
        if self._running:
            logger.info("whisper_wake_loop_already_running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="reachy-whisper-wake",
        )
        self._thread.start()
        logger.info(
            "whisper_wake_loop_started",
            keyword=self._primary,
            phrases=list(self._phrases),
            device_index=self._device_index,
            whisper_model=self._whisper_model_name,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        logger.info("whisper_wake_loop_stopped")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(
                self._whisper_model_name,
                device=self._whisper_device,
                compute_type=self._whisper_compute_type,
            )
            logger.info("whisper_wake_model_loaded", model=self._whisper_model_name)
        return self._whisper

    def _candidate_devices(self) -> list[Optional[int]]:
        """Return device indices to try in order. First is the configured one,
        then Reachy mics on other host APIs as a fallback (callback-mode
        InputStream on Windows can fail on certain APIs even when blocking
        reads work)."""
        seen: set[Optional[int]] = {self._device_index}
        result: list[Optional[int]] = [self._device_index]
        try:
            import sounddevice as sd

            host_apis = sd.query_hostapis()
            reachy_hints = ("reachy mini", "reachy_mini", "xmos", "xvf", "pollen")
            priority = {
                "mme": 0,
                "windows wasapi": 1,
                "windows directsound": 2,
                "windows wdm-ks": 3,
            }
            candidates: list[tuple[int, int]] = []
            for idx, dev in enumerate(sd.query_devices()):
                if int(dev.get("max_input_channels", 0)) < 1:
                    continue
                name = dev.get("name", "").lower()
                if not any(h in name for h in reachy_hints):
                    continue
                host_idx = int(dev.get("hostapi", 0))
                api_name = host_apis[host_idx].get("name", "?").lower() if host_idx < len(host_apis) else "?"
                candidates.append((priority.get(api_name, 99), idx))
            for _, idx in sorted(candidates):
                if idx not in seen:
                    result.append(idx)
                    seen.add(idx)
        except Exception as e:
            logger.debug("whisper_wake_candidates_enum_failed", error=str(e))
        return result

    def _run(self) -> None:
        """
        Main loop. Uses blocking reads (`stream.read()`) instead of the
        callback API — PortAudio's callback mode deadlocks against the
        Python GIL on Windows + Python 3.13 + MME / DirectSound, where the
        callback thread blocks inside the C runtime and the Python loop's
        `queue.get(timeout=...)` never returns.
        """
        import sounddevice as sd

        try:
            self._load_whisper()
        except Exception as e:
            logger.error("whisper_wake_model_load_failed", error=str(e))
            self._running = False
            return

        candidates = self._candidate_devices()
        last_error: Optional[Exception] = None
        stream = None
        for device in candidates:
            if not self._running:
                break
            kwargs = dict(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME_SAMPLES,
            )
            if device is not None:
                kwargs["device"] = device
            try:
                stream = sd.InputStream(**kwargs)  # no callback — blocking read()
                stream.start()
                self._device_index = device
                logger.info("whisper_wake_stream_open", device=device, mode="blocking")
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "whisper_wake_stream_open_failed", device=device, error=str(e)[:160],
                )
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
                stream = None

        if stream is None:
            logger.error(
                "whisper_wake_no_usable_device",
                tried=candidates,
                last_error=str(last_error)[:160] if last_error else None,
            )
            self._running = False
            return

        try:
            self._stream = stream
            try:
                last_scan = 0.0
                frames_seen = 0
                last_heartbeat = time.time()
                max_buffer_samples = int(SCAN_WINDOW_SECONDS * SAMPLE_RATE)
                while self._running:
                    # Blocking read — returns after `blocksize` samples are
                    # available or instantly if they already are. No callbacks,
                    # no cross-thread queues, no GIL deadlock.
                    try:
                        chunk, overflowed = stream.read(FRAME_SAMPLES)
                    except Exception as e:
                        logger.error("whisper_wake_read_failed", error=str(e)[:160])
                        break
                    if self._paused:
                        continue
                    frame = chunk[:, 0] if chunk.ndim > 1 else chunk
                    frames_seen += 1
                    with self._buffer_lock:
                        self._buffer = np.concatenate([self._buffer, frame])
                        if len(self._buffer) > max_buffer_samples:
                            self._buffer = self._buffer[-max_buffer_samples:]

                    now = time.time()
                    if now - last_heartbeat > 10.0:
                        with self._buffer_lock:
                            buf_len = len(self._buffer)
                        logger.info(
                            "whisper_wake_heartbeat",
                            frames_seen=frames_seen,
                            buffer_samples=buf_len,
                        )
                        last_heartbeat = now
                    if now - last_scan < SCAN_INTERVAL_SECONDS:
                        continue
                    last_scan = now
                    try:
                        self._scan_for_wake(stream)
                    except Exception as e:
                        logger.error("whisper_wake_scan_error", error=str(e))
            finally:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
                self._stream = None
        except Exception as e:
            logger.error("whisper_wake_stream_crashed", error=str(e))
        finally:
            self._running = False

    def _scan_for_wake(self, stream) -> None:
        with self._buffer_lock:
            buf = self._buffer.copy()
        if len(buf) < SAMPLE_RATE * 0.5:
            return  # not enough audio yet
        rms = float(np.sqrt(np.mean(buf ** 2)))
        # Skip if the window is essentially silent
        if rms < SILENCE_RMS:
            logger.debug("whisper_wake_scan_silent", rms=f"{rms:.4f}", samples=len(buf))
            return

        text = self._transcribe(buf)
        # Always log the transcribed text so we can see what Whisper is hearing
        # and diagnose missed wakes. Empty transcripts are normal during music /
        # ambient noise — log those only at debug.
        if text:
            logger.info(
                "whisper_wake_scan_heard",
                text=text,
                rms=f"{rms:.4f}",
                matched=_has_wake(text, self._phrases) is not None,
            )
        else:
            logger.debug("whisper_wake_scan_empty_transcript", rms=f"{rms:.4f}")
        if not text:
            return
        end_idx = _has_wake(text, self._phrases)
        if end_idx is None:
            return

        # Debounce: ignore wakes less than 2s after the previous one.
        now = time.time()
        if self._last_wake_at and (now - self._last_wake_at) < 2.0:
            return
        self._last_wake_at = now

        # Clear the buffer so the wake phrase isn't re-detected next scan.
        with self._buffer_lock:
            self._buffer = np.zeros(0, dtype=np.float32)

        tail = _clean_command(text[end_idx:])
        logger.info(
            "whisper_wake_detected",
            heard=text,
            tail_preview=tail[:80],
        )

        # If the wake phrase was followed by substantive content, use that as
        # the command straight away (short commands like "hey zero what's up").
        if len(tail) >= 4:
            command = tail
        else:
            command = self._capture_command(stream)

        command = _clean_command(command)
        if not command:
            logger.info("whisper_wake_command_empty")
            return
        if self._on_command is not None:
            try:
                self._on_command(command)
            except Exception as e:
                logger.error("whisper_wake_on_command_failed", error=str(e))

    def _capture_command(self, stream) -> str:
        """Grab audio after the wake phrase until `COMMAND_SILENCE_MS` of quiet."""
        from_here: list[np.ndarray] = []
        silent_ms = 0
        total_ms = 0
        max_ms = int(COMMAND_MAX_SECONDS * 1000)
        while total_ms < max_ms and self._running:
            try:
                chunk, _ = stream.read(FRAME_SAMPLES)
            except Exception:
                break
            frame = chunk[:, 0] if chunk.ndim > 1 else chunk
            from_here.append(frame)
            total_ms += FRAME_MS
            rms = float(np.sqrt(np.mean(frame ** 2)))
            if rms < SILENCE_RMS:
                silent_ms += FRAME_MS
                if silent_ms >= COMMAND_SILENCE_MS and from_here and total_ms > 600:
                    break
            else:
                silent_ms = 0
        if not from_here:
            return ""
        audio = np.concatenate(from_here)
        return self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> str:
        # Persist to a short-lived wav for faster-whisper's file-path API.
        out_dir = Path(os.getenv("ZERO_RECORDINGS_DIR", "."))
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / f"wake_{int(time.time() * 1000)}.wav"
        try:
            sf.write(str(tmp), audio, SAMPLE_RATE, subtype="PCM_16")
            whisper = self._load_whisper()
            segments_iter, info = whisper.transcribe(
                str(tmp),
                language="en",
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=250),
            )
            return " ".join(s.text.strip() for s in segments_iter).strip()
        except Exception as e:
            logger.debug("whisper_wake_transcribe_failed", error=str(e))
            return ""
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
