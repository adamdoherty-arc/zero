"""
Reachy Mini wake-word detector.

Thin wrapper around `openwakeword` (optional dep) so Zero can turn Reachy
into an always-listening assistant without shipping Porcupine's per-seat key.
If `openwakeword` is not installed, the service reports `available: false`
and every detection call returns `(False, 0.0)` — callers treat that as
"wake-word never fired" and fall back to push-to-talk.

Install:
    pip install openwakeword onnxruntime

Default model: `hey_jarvis` (ships with openwakeword) because there is no
pre-trained "hey reachy" model. Override with ``ZERO_REACHY_WAKE_MODEL``.

Detection API is deliberately dumb: feed 16 kHz mono int16 PCM chunks of
~80 ms each, get back (fired: bool, score: float). Matching the
`reachy_mini_conversation_app` integration point so we can swap this for
the upstream wake-word Space later.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import numpy as np
import structlog

logger = structlog.get_logger()


DEFAULT_MODEL = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5
DEFAULT_COOLDOWN_S = 2.0
SAMPLE_RATE = 16_000


class ReachyWakeWordService:
    _instance: Optional["ReachyWakeWordService"] = None

    def __init__(self) -> None:
        self._model = None
        self._model_name = os.environ.get("ZERO_REACHY_WAKE_MODEL", DEFAULT_MODEL)
        self._threshold = float(os.environ.get("ZERO_REACHY_WAKE_THRESHOLD", DEFAULT_THRESHOLD))
        self._cooldown_s = float(os.environ.get("ZERO_REACHY_WAKE_COOLDOWN", DEFAULT_COOLDOWN_S))
        self._last_fired_at = 0.0
        self._lock = threading.Lock()
        self._import_error: Optional[str] = None
        self._last_score = 0.0

    @classmethod
    def get_instance(cls) -> "ReachyWakeWordService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Availability / lazy init
    # ------------------------------------------------------------------

    def backend_status(self) -> dict:
        self._try_load()
        return {
            "available": self._model is not None,
            "model": self._model_name,
            "threshold": self._threshold,
            "cooldown_s": self._cooldown_s,
            "last_score": self._last_score,
            "import_error": self._import_error,
        }

    def _try_load(self) -> None:
        if self._model is not None or self._import_error:
            return
        try:
            # openwakeword is optional. First import is heavy (loads the ONNX
            # models), so we only do it when explicitly asked.
            from openwakeword.model import Model  # type: ignore[import-not-found]
            self._model = Model(
                wakeword_models=[self._model_name] if self._model_name else None,
                inference_framework="onnx",
            )
            logger.info("reachy_wakeword_loaded", model=self._model_name)
        except Exception as e:
            self._import_error = str(e)
            logger.info("reachy_wakeword_unavailable", error=str(e))

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def predict(self, pcm_int16: np.ndarray) -> tuple[bool, float]:
        """
        Feed one chunk of 16 kHz mono int16 PCM. Returns (fired, score).
        Empty / too-short chunks return (False, 0.0).
        """
        self._try_load()
        if self._model is None or pcm_int16.size == 0:
            return (False, 0.0)

        with self._lock:
            try:
                preds = self._model.predict(pcm_int16)
            except Exception as e:
                logger.debug("reachy_wakeword_predict_failed", error=str(e))
                return (False, 0.0)
            # openwakeword returns {model_name: score, ...}
            score = 0.0
            for key, val in preds.items():
                if isinstance(val, (int, float)) and val > score:
                    score = float(val)
            self._last_score = score

            now = time.monotonic()
            if score < self._threshold:
                return (False, score)
            if now - self._last_fired_at < self._cooldown_s:
                return (False, score)
            self._last_fired_at = now
            return (True, score)

    def predict_bytes(self, pcm_bytes: bytes) -> tuple[bool, float]:
        if not pcm_bytes:
            return (False, 0.0)
        arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        return self.predict(arr)


def get_reachy_wake_word_service() -> ReachyWakeWordService:
    return ReachyWakeWordService.get_instance()
