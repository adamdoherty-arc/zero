"""
Wake-word loop: always-on Reachy microphone listener.

Architecture:
  * Porcupine (pvporcupine) scans 512-sample 16kHz frames for the wake word
    ("jarvis" by default). Frame processing runs on a background thread.
  * On wake detection, we switch to "command capture" mode: record audio until
    a silence threshold is met or max_command_seconds elapses, then transcribe
    with faster-whisper ("base" size, CPU, int8).
  * The transcribed command is POSTed to zero-api's reachy-intent router,
    which returns response text + optional actions. The host agent speaks the
    response through the Reachy speaker via the existing TTS path.

Privacy:
  * Audio before wake never leaves the host — it's only fed to the Porcupine
    frame processor, which operates on raw PCM locally.
  * Audio after wake is transcribed locally (Whisper); only the final text
    reaches zero-api.

Device conflict notes:
  * Windows USB Audio Class devices are claimed in shared mode by default, so
    the wake stream and an active meeting-recording stream can coexist on the
    same Reachy USB mic (tested: both see audio).
  * If meeting recording starts after the wake loop is already open, the
    AudioCapture callback still receives its independent stream.
"""

from __future__ import annotations

import asyncio
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


WAKE_SAMPLE_RATE = 16000
WAKE_FRAME_LENGTH = 512            # Porcupine requirement at 16 kHz
COMMAND_SILENCE_RMS = 0.008        # stop recording the command after ~this level
COMMAND_SILENCE_FRAMES = 24        # ~750ms of silence at 32ms/frame
COMMAND_MAX_SECONDS = 10.0
POST_WAKE_PAD_FRAMES = 4           # grab 4 frames before stopping to avoid cutting words


class WakeLoop:
    """
    Background wake-word listener. Construct, call `start()`, and `stop()`
    cleanly. Uses callables for the high-latency transcription + TTS so this
    module stays testable without the rest of the host_agent.
    """

    def __init__(
        self,
        *,
        access_key: str,
        keyword: str = "jarvis",
        device_index: Optional[int] = None,
        on_command: Optional[Callable[[str], None]] = None,
        whisper_model: str = "base",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
    ) -> None:
        self._access_key = access_key
        self._keyword = keyword
        self._device_index = device_index
        self._on_command = on_command
        self._whisper_model_name = whisper_model
        self._whisper_device = whisper_device
        self._whisper_compute_type = whisper_compute_type

        self._porcupine = None
        self._whisper = None
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._last_wake_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
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
            "keyword": self._keyword,
            "device_index": self._device_index,
            "last_wake_at": self._last_wake_at,
        }

    def start(self) -> None:
        if self._running:
            logger.info("wake_loop_already_running")
            return
        import pvporcupine
        self._porcupine = pvporcupine.create(
            access_key=self._access_key,
            keywords=[self._keyword],
        )
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="reachy-wake-loop",
        )
        self._thread.start()
        logger.info(
            "wake_loop_started",
            keyword=self._keyword,
            device_index=self._device_index,
            sample_rate=WAKE_SAMPLE_RATE,
            frame_length=WAKE_FRAME_LENGTH,
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
        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None
        logger.info("wake_loop_stopped")

    def pause(self) -> None:
        """Temporarily stop processing frames; stream stays open."""
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
            logger.info("wake_whisper_loaded", model=self._whisper_model_name)
        return self._whisper

    def _run(self) -> None:
        import sounddevice as sd

        kwargs = dict(
            samplerate=WAKE_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=WAKE_FRAME_LENGTH,
        )
        if self._device_index is not None:
            kwargs["device"] = self._device_index

        try:
            with sd.InputStream(**kwargs) as stream:
                self._stream = stream
                while self._running:
                    if self._paused:
                        time.sleep(0.1)
                        continue
                    frame, overflowed = stream.read(WAKE_FRAME_LENGTH)
                    if overflowed:
                        logger.debug("wake_loop_overflow")
                    pcm = frame[:, 0].astype(np.int16).tolist()
                    if len(pcm) != WAKE_FRAME_LENGTH:
                        continue
                    result = self._porcupine.process(pcm)
                    if result >= 0:
                        self._last_wake_at = time.time()
                        logger.info("wake_detected", keyword=self._keyword)
                        try:
                            self._handle_wake(stream)
                        except Exception as e:
                            logger.error("wake_handle_failed", error=str(e))
        except Exception as e:
            logger.error("wake_loop_crashed", error=str(e))
        finally:
            self._running = False

    def _handle_wake(self, stream) -> None:
        """Capture the command phrase, transcribe it, fire the callback."""
        audio_chunks: list[np.ndarray] = []
        silent_run = 0
        total_frames = 0
        max_frames = int(COMMAND_MAX_SECONDS * WAKE_SAMPLE_RATE / WAKE_FRAME_LENGTH)

        while total_frames < max_frames:
            frame, _ = stream.read(WAKE_FRAME_LENGTH)
            total_frames += 1
            audio_chunks.append(frame[:, 0].astype(np.float32) / 32768.0)
            rms = float(np.sqrt(np.mean(audio_chunks[-1] ** 2)))
            if rms < COMMAND_SILENCE_RMS:
                silent_run += 1
                if silent_run >= COMMAND_SILENCE_FRAMES and total_frames > POST_WAKE_PAD_FRAMES + COMMAND_SILENCE_FRAMES:
                    break
            else:
                silent_run = 0

        audio = np.concatenate(audio_chunks) if audio_chunks else np.zeros(0, dtype=np.float32)
        duration = len(audio) / WAKE_SAMPLE_RATE
        logger.info("wake_command_captured", duration=f"{duration:.2f}s", frames=total_frames)

        if duration < 0.3:
            logger.info("wake_command_too_short_ignoring")
            return

        # Write a tmp wav + transcribe
        tmp = Path(os.getenv("ZERO_RECORDINGS_DIR", "."))
        tmp.mkdir(parents=True, exist_ok=True)
        tmp_file = tmp / f"wake_cmd_{int(time.time() * 1000)}.wav"
        sf.write(str(tmp_file), audio, WAKE_SAMPLE_RATE, subtype="PCM_16")

        try:
            whisper = self._load_whisper()
            segments_iter, info = whisper.transcribe(
                str(tmp_file), language="en", beam_size=1,
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300),
            )
            text = " ".join(seg.text.strip() for seg in segments_iter).strip()
            logger.info("wake_command_transcribed", text=text, lang=info.language)
        except Exception as e:
            logger.error("wake_transcribe_failed", error=str(e))
            text = ""
        finally:
            try:
                tmp_file.unlink()
            except Exception:
                pass

        if not text:
            return

        if self._on_command is not None:
            try:
                self._on_command(text)
            except Exception as e:
                logger.error("wake_on_command_failed", error=str(e), text=text)
