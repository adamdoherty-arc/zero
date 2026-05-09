"""
Voice capture for push-to-talk / hotkey / wake-word triggered intents.

Captures from the Reachy USB mic (or whichever device is the default mic),
transcribes with faster-whisper, then hands the text to a caller-supplied
callback. Single-recording-at-a-time: calling `start()` while already active
raises. Designed to be driven by three different entry points that all end
up in the same intent pipeline:

  1. UI floating button (click-start / click-stop)
  2. Windows global keyboard shortcut
  3. Whisper-based wake-word loop

Separate from the meeting-recording AudioCapture because meetings are
long-form WAV-to-disk; this is short-form in-memory audio that gets fed
straight to Whisper and discarded.
"""

from __future__ import annotations

import io
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf
import structlog

logger = structlog.get_logger()


VOICE_SAMPLE_RATE = 16000
VOICE_BLOCKSIZE = 1024
VOICE_MAX_SECONDS = 15.0  # hard cap to avoid accidentally recording forever


class VoiceCapture:
    """Single-slot voice recorder. Thread-safe start/stop."""

    def __init__(
        self,
        *,
        mic_device_index: Optional[int] = None,
        whisper_model: str = "base",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
    ) -> None:
        self._mic_device_index = mic_device_index
        self._whisper_model_name = whisper_model
        self._whisper_device = whisper_device
        self._whisper_compute_type = whisper_compute_type

        self._whisper = None
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._is_capturing = False
        self._started_at: Optional[float] = None
        self._guard_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    def status(self) -> dict:
        if not self._is_capturing:
            return {"capturing": False}
        return {
            "capturing": True,
            "started_at": self._started_at,
            "elapsed_seconds": (time.time() - self._started_at) if self._started_at else 0.0,
        }

    def start(self) -> None:
        """Open the mic stream and begin buffering audio chunks."""
        with self._lock:
            if self._is_capturing:
                raise RuntimeError("Already capturing")
            import sounddevice as sd
            self._chunks = []
            kwargs = dict(
                samplerate=VOICE_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=VOICE_BLOCKSIZE,
                callback=self._callback,
            )
            if self._mic_device_index is not None:
                kwargs["device"] = self._mic_device_index
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
            self._is_capturing = True
            self._started_at = time.time()
            # Safety cap: auto-stop after VOICE_MAX_SECONDS regardless of caller
            self._guard_timer = threading.Timer(VOICE_MAX_SECONDS, self._guard_stop)
            self._guard_timer.daemon = True
            self._guard_timer.start()
            logger.info(
                "voice_capture_started",
                device_index=self._mic_device_index,
                rate=VOICE_SAMPLE_RATE,
            )

    def _callback(self, indata, frames, time_info, status):
        if not self._is_capturing:
            return
        try:
            self._chunks.append(indata[:, 0].copy())
        except Exception:
            pass

    def _guard_stop(self) -> None:
        if self._is_capturing:
            logger.info("voice_capture_guard_stop", max_seconds=VOICE_MAX_SECONDS)
            try:
                self.stop_and_transcribe()
            except Exception as e:
                logger.warning("voice_capture_guard_stop_failed", error=str(e))

    def stop_and_transcribe(self) -> dict:
        """
        Stop the mic stream, assemble the buffered audio, and transcribe it.
        Returns {"text": str, "duration_seconds": float, "captured": bool}.
        """
        with self._lock:
            if not self._is_capturing:
                return {"text": "", "duration_seconds": 0.0, "captured": False}
            self._is_capturing = False
            if self._guard_timer is not None:
                try:
                    self._guard_timer.cancel()
                except Exception:
                    pass
                self._guard_timer = None
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

        if not self._chunks:
            return {"text": "", "duration_seconds": 0.0, "captured": False}

        audio = np.concatenate(self._chunks)
        duration = float(len(audio)) / VOICE_SAMPLE_RATE
        self._chunks = []
        elapsed = time.time() - (self._started_at or time.time())
        self._started_at = None

        if duration < 0.4:
            logger.info("voice_capture_too_short", duration=duration)
            return {"text": "", "duration_seconds": duration, "captured": True}

        text = self._transcribe(audio)
        logger.info(
            "voice_capture_stopped",
            duration=f"{duration:.2f}s",
            stream_elapsed=f"{elapsed:.2f}s",
            text=text,
        )
        return {"text": text, "duration_seconds": duration, "captured": True}

    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(
                self._whisper_model_name,
                device=self._whisper_device,
                compute_type=self._whisper_compute_type,
            )
            logger.info("voice_whisper_loaded", model=self._whisper_model_name)
        return self._whisper

    def warmup(self) -> dict:
        """Load the Whisper model now so the first voice turn doesn't cold-start."""
        t0 = time.time()
        self._load_whisper()
        return {
            "model": self._whisper_model_name,
            "load_ms": int((time.time() - t0) * 1000),
        }

    def set_whisper_model(self, model: str) -> dict:
        """Swap to a new Whisper model and pre-warm it. Returns warmup result."""
        model = (model or "").strip()
        if not model:
            raise ValueError("model must be a non-empty string")
        if model != self._whisper_model_name:
            self._whisper = None
            self._whisper_model_name = model
        return self.warmup()

    @property
    def whisper_model_name(self) -> str:
        return self._whisper_model_name

    def _transcribe(self, audio: np.ndarray) -> str:
        tmp_path = Path(os.getenv("ZERO_RECORDINGS_DIR", ".")) / f"voice_{int(time.time() * 1000)}.wav"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            sf.write(str(tmp_path), audio, VOICE_SAMPLE_RATE, subtype="PCM_16")
            whisper = self._load_whisper()
            segments_iter, info = whisper.transcribe(
                str(tmp_path),
                language="en",
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
            )
            return " ".join(s.text.strip() for s in segments_iter).strip()
        except Exception as e:
            logger.error("voice_transcribe_failed", error=str(e))
            return ""
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
