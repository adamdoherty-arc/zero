"""
openWakeWord-based continuous wake-word listener for host_agent.

Why this exists: whisper-tiny on 3-second windows is unreliable for wake
detection (it hallucinates YouTube filler like "Thank you for watching"
and rarely transcribes the word "zero" cleanly from a Reachy speakerphone
mic). openWakeWord is a 1 MB ONNX model trained specifically per keyword,
runs at ~10 ms per 80 ms chunk, needs no external API key, and has a near-
zero false-positive rate.

Architecture mirrors whisper_wake_loop.WhisperWakeLoop and wake_loop.WakeLoop
so host_agent/main.py can pick one at runtime.

  wake_loop.WakeLoop              (Porcupine — needs Picovoice key)
  openwakeword_loop.OpenWakeWordLoop   (this file — 100% local, no key)
  whisper_wake_loop.WhisperWakeLoop    (fallback — works but flaky)

Flow:
  1. Open the configured mic at 16 kHz mono int16 PCM.
  2. Feed 80 ms (1280-sample) chunks into openWakeWord.Model.predict().
  3. When the target keyword's score crosses a threshold, trigger the wake.
  4. Capture audio from the mic until `COMMAND_SILENCE_MS` of quiet (or
     `COMMAND_MAX_SECONDS`), then transcribe with faster-whisper and hand
     the command text off to ``on_command``.

Default keyword is ``hey_jarvis`` because openWakeWord ships a well-trained
model for it out of the box. If you want "hey reachy" or "hey zero", you
need to train a custom model via openWakeWord's pipeline and point
``ZERO_OWW_MODEL_PATH`` at the resulting .onnx/.tflite file.
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
FRAME_MS = 80  # openWakeWord expects 80 ms (1280 samples) chunks
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

COMMAND_SILENCE_MS = 800
COMMAND_MAX_SECONDS = 10.0
COMMAND_VAD_RMS = 0.015  # float32 RMS threshold for end-of-command silence


def _clean_command(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" .,!?\n")


class OpenWakeWordLoop:
    """Continuous wake detector using openWakeWord pre-trained models.

    After the keyword fires, records the user's follow-up utterance and
    transcribes it with faster-whisper before handing off to ``on_command``.
    Interface mirrors ``WakeLoop`` / ``WhisperWakeLoop`` so host_agent
    can select any of the three at boot.
    """

    def __init__(
        self,
        *,
        keyword: str = "hey_jarvis",
        model_path: Optional[str] = None,
        threshold: float = 0.5,
        cooldown_s: float = 2.0,
        device_index: Optional[int] = None,
        on_command: Optional[Callable[[str], None]] = None,
        whisper_model: str = "base",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
    ) -> None:
        # ``keyword`` is the "spoken name" we advertise (e.g. "hey jarvis").
        # ``model_path`` is an optional override — when set, we load that .onnx
        # instead of the openWakeWord-shipped one. Lets the user drop a custom
        # "hey reachy" model in without touching code.
        self._keyword = keyword.lower().strip()
        self._model_path = model_path
        self._threshold = float(threshold)
        self._cooldown_s = float(cooldown_s)

        self._device_index = device_index
        self._on_command = on_command
        self._whisper_model_name = whisper_model
        self._whisper_device = whisper_device
        self._whisper_compute_type = whisper_compute_type

        self._model = None  # openwakeword.Model (lazy-loaded)
        self._model_key: Optional[str] = None  # the key inside Model.prediction_buffer
        self._whisper = None
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._last_wake_at: Optional[float] = None
        self._frame_q: queue.Queue = queue.Queue(maxsize=200)

    # ------------------------------------------------------------------
    # Public surface (mirrors wake_loop.WakeLoop / WhisperWakeLoop)
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
            "mode": "openwakeword",
            "keyword": self._keyword,
            "model_path": self._model_path,
            "threshold": self._threshold,
            "cooldown_s": self._cooldown_s,
            "device_index": self._device_index,
            "last_wake_at": self._last_wake_at,
            "model_key": self._model_key,
        }

    def start(self) -> None:
        if self._running:
            logger.info("oww_wake_loop_already_running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="reachy-oww-wake",
        )
        self._thread.start()
        logger.info(
            "oww_wake_loop_started",
            keyword=self._keyword,
            model_path=self._model_path,
            threshold=self._threshold,
            device_index=self._device_index,
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
        logger.info("oww_wake_loop_stopped")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_model(self):
        if self._model is not None:
            return self._model
        from openwakeword.model import Model

        if self._model_path:
            # Custom model file (user trained a "hey reachy" etc.).
            self._model = Model(
                wakeword_models=[self._model_path],
                inference_framework="onnx",
            )
            # Resolve the key the Model used to index predictions for this file.
            key_stem = Path(self._model_path).stem
            self._model_key = key_stem
        else:
            # Built-in keyword. openWakeWord maps keyword names → bundled models
            # in its resources dir.
            keyword_key = self._keyword.replace(" ", "_")
            self._model = Model(
                wakeword_models=[keyword_key],
                inference_framework="onnx",
            )
            self._model_key = keyword_key
        logger.info(
            "oww_model_loaded",
            keyword=self._keyword,
            model_key=self._model_key,
            available_keys=list(self._model.prediction_buffer.keys()),
        )
        return self._model

    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel(
                self._whisper_model_name,
                device=self._whisper_device,
                compute_type=self._whisper_compute_type,
            )
            logger.info(
                "oww_whisper_loaded",
                model=self._whisper_model_name,
            )
        return self._whisper

    def _candidate_devices(self) -> list[Optional[int]]:
        """Reachy-mic-preferring device order; fall back through host APIs.

        Same logic as WhisperWakeLoop so both detectors end up on the same
        physical mic when auto-selecting.
        """
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
                api_name = (
                    host_apis[host_idx].get("name", "?").lower()
                    if host_idx < len(host_apis)
                    else "?"
                )
                candidates.append((priority.get(api_name, 99), idx))
            for _, idx in sorted(candidates):
                if idx not in seen:
                    result.append(idx)
                    seen.add(idx)
        except Exception as e:
            logger.debug("oww_candidates_enum_failed", error=str(e))
        return result

    def _run(self) -> None:
        """Main thread loop. Blocking reads on the mic, predict() per chunk."""
        import sounddevice as sd

        try:
            self._load_model()
        except Exception as e:
            logger.error("oww_model_load_failed", error=str(e))
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
                dtype="int16",  # openWakeWord wants int16
                blocksize=FRAME_SAMPLES,
            )
            if device is not None:
                kwargs["device"] = device
            try:
                stream = sd.InputStream(**kwargs)
                stream.start()
                self._device_index = device
                logger.info("oww_stream_open", device=device)
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "oww_stream_open_failed", device=device, error=str(e)[:160],
                )
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
                stream = None

        if stream is None:
            logger.error(
                "oww_no_usable_device",
                tried=candidates,
                last_error=str(last_error)[:160] if last_error else None,
            )
            self._running = False
            return

        try:
            self._stream = stream
            model = self._model
            last_heartbeat = time.time()
            frames_seen = 0
            while self._running:
                try:
                    chunk, _overflowed = stream.read(FRAME_SAMPLES)
                except Exception as e:
                    logger.error("oww_read_failed", error=str(e)[:160])
                    break
                if self._paused:
                    continue
                if chunk.ndim > 1:
                    chunk = chunk[:, 0]
                frames_seen += 1

                # predict() expects int16 numpy array. Feed it, then check
                # the prediction buffer for our model key.
                try:
                    model.predict(chunk)
                except Exception as e:
                    logger.error("oww_predict_failed", error=str(e)[:160])
                    continue

                now = time.time()
                if now - last_heartbeat > 15.0:
                    # Emit a heartbeat with the max recent score so we can
                    # tell at a glance whether the mic is even delivering
                    # audio the model recognizes.
                    last_scores = {
                        k: float(v[-1]) if len(v) else 0.0
                        for k, v in model.prediction_buffer.items()
                    }
                    logger.info(
                        "oww_heartbeat",
                        frames_seen=frames_seen,
                        last_scores=last_scores,
                    )
                    last_heartbeat = now

                score = float(model.prediction_buffer[self._model_key][-1])
                if score < self._threshold:
                    continue

                # Cooldown — don't re-fire inside the same utterance.
                if self._last_wake_at and (now - self._last_wake_at) < self._cooldown_s:
                    continue
                self._last_wake_at = now

                logger.info(
                    "oww_wake_detected",
                    keyword=self._keyword,
                    score=round(score, 3),
                )

                # Drain the model's prediction buffer so the next scan starts
                # fresh (prevents the same activation re-firing).
                try:
                    model.reset()
                except Exception:
                    pass

                try:
                    command = self._capture_command(stream)
                except Exception as e:
                    logger.error("oww_capture_command_failed", error=str(e))
                    continue

                command = _clean_command(command)
                if not command:
                    logger.info("oww_command_empty")
                    continue

                if self._on_command is not None:
                    try:
                        self._on_command(command)
                    except Exception as e:
                        logger.error("oww_on_command_failed", error=str(e))
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
            self._running = False

    def _capture_command(self, stream) -> str:
        """Grab audio after the wake until COMMAND_SILENCE_MS of quiet,
        transcribe with faster-whisper."""
        from_here: list[np.ndarray] = []
        silent_ms = 0
        total_ms = 0
        max_ms = int(COMMAND_MAX_SECONDS * 1000)
        while total_ms < max_ms and self._running:
            try:
                chunk, _ = stream.read(FRAME_SAMPLES)
            except Exception:
                break
            if chunk.ndim > 1:
                chunk = chunk[:, 0]
            # Convert int16 → float32 for RMS calc + whisper feed.
            frame_f = chunk.astype(np.float32) / 32768.0
            from_here.append(frame_f)
            total_ms += FRAME_MS
            rms = float(np.sqrt(np.mean(frame_f ** 2)))
            if rms < COMMAND_VAD_RMS:
                silent_ms += FRAME_MS
                if silent_ms >= COMMAND_SILENCE_MS and total_ms > 600:
                    break
            else:
                silent_ms = 0
        if not from_here:
            return ""
        audio = np.concatenate(from_here)
        return self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray) -> str:
        # Persist to wav for faster-whisper file-path API (same pattern as
        # WhisperWakeLoop).
        out_dir = Path(os.getenv("ZERO_RECORDINGS_DIR", "."))
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / f"oww_cmd_{int(time.time() * 1000)}.wav"
        try:
            sf.write(str(tmp), audio, SAMPLE_RATE, subtype="PCM_16")
            whisper = self._load_whisper()
            segments_iter, _info = whisper.transcribe(
                str(tmp),
                language="en",
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=250),
            )
            text = " ".join(s.text.strip() for s in segments_iter).strip()
            logger.info("oww_command_transcribed", text=text[:200])
            return text
        except Exception as e:
            logger.debug("oww_transcribe_failed", error=str(e))
            return ""
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
