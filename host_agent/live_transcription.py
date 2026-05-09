"""
Live transcription for the host agent.

Runs faster-whisper on a rolling window of the audio ring buffer while a
recording is active and pushes new text segments to WebSocket subscribers.
Post-recording Whisper (higher-quality pass) still happens in zero-api's
meeting_processing_pipeline after the file is written.

Design choices:
- Model: faster-whisper `base` on CPU with int8 — real-time-ish latency
  without hogging the GPU that the post-recording `small`+diarization
  pipeline needs.
- Window: 8-second slice read every 2s from AudioCapture.ring_buffer.
  Slight overlap lets Whisper anchor word boundaries across chunks.
- Dedup: we keep a running transcript string and only emit text that
  extends past what we've already shown. Whisper re-reads its own past
  text on each window, so naive emit-everything would produce duplicates.
- Broadcast: subscribers register an asyncio.Queue; the worker thread
  schedules `queue.put_nowait` via run_coroutine_threadsafe so the loop
  stays responsive.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


_DEFAULT_MODEL_SIZE = "base"
_DEFAULT_WINDOW_S = 4.0
_DEFAULT_POLL_INTERVAL_S = 1.2
_DEFAULT_LANGUAGE = "en"
_DEFAULT_SAMPLE_RATE = 16000


class LiveTranscriptionService:
    """Background live-whisper loop tied to a running AudioCapture.

    Lifecycle: load_model() (lazy) → start(capture) → stop().
    Subscribers receive dicts shaped like the frontend expects:
      {type: "segment", id: str, start: float, end: float, text: str}
    """

    def __init__(
        self,
        model_size: str = _DEFAULT_MODEL_SIZE,
        window_s: float = _DEFAULT_WINDOW_S,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        language: str = _DEFAULT_LANGUAGE,
    ) -> None:
        self.model_size = model_size
        self.window_s = window_s
        self.poll_interval_s = poll_interval_s
        self.language = language

        self._model = None
        self._model_lock = threading.Lock()

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._capture = None  # AudioCapture reference while active

        self._subscribers: list[Callable[[dict], None]] = []
        self._subscribers_lock = threading.Lock()

        self._last_text: str = ""
        self._segment_counter: int = 0

    # --- Model -------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self) -> None:
        """Lazy-load faster-whisper. Cheap after first call."""
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel  # type: ignore

            logger.info("live_transcription_model_loading", size=self.model_size)
            t0 = time.time()
            self._model = WhisperModel(
                self.model_size,
                device="auto",
                compute_type="int8",
            )
            logger.info(
                "live_transcription_model_loaded",
                size=self.model_size,
                elapsed_s=round(time.time() - t0, 2),
            )

    def set_model(self, model_size: str) -> dict:
        """Swap the live-transcript Whisper model. Safe to call between recordings.

        Returns a small dict suitable for a router response.
        """
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Cannot swap model while live transcription is running")
        valid = {"tiny", "base", "small", "medium", "large-v3"}
        if model_size not in valid:
            raise ValueError(f"Unknown Whisper size '{model_size}'. Valid: {sorted(valid)}")
        with self._model_lock:
            self._model = None
            self.model_size = model_size
        # Eagerly warm so the next recording starts hot.
        self.load_model()
        return {"model": self.model_size, "loaded": self.is_loaded}

    # --- Subscribers -------------------------------------------------------

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """Register a synchronous callback that receives segment dicts."""
        with self._subscribers_lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        with self._subscribers_lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    def _broadcast(self, message: dict) -> None:
        with self._subscribers_lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(message)
            except Exception as e:
                logger.debug("live_transcription_subscriber_error", error=str(e))

    # --- Lifecycle ---------------------------------------------------------

    def start(self, capture: Any) -> None:
        """Begin polling `capture.ring_buffer` in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("live_transcription_already_running")
            return
        self._capture = capture
        self._stop.clear()
        self._last_text = ""
        self._segment_counter = 0
        self._thread = threading.Thread(
            target=self._run, name="LiveTranscription", daemon=True,
        )
        self._thread.start()
        logger.info("live_transcription_started", model=self.model_size)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._thread = None
        self._capture = None
        logger.info("live_transcription_stopped")

    # --- Worker ------------------------------------------------------------

    def _run(self) -> None:
        try:
            self.load_model()
        except Exception as e:
            logger.warning("live_transcription_model_load_failed", error=str(e))
            return

        sample_rate = _DEFAULT_SAMPLE_RATE
        window_samples = int(self.window_s * sample_rate)

        while not self._stop.is_set():
            # Wait up to poll_interval_s, but bail early if stop is signalled.
            if self._stop.wait(self.poll_interval_s):
                break

            capture = self._capture
            if capture is None or not capture.is_recording:
                continue

            try:
                audio = capture.ring_buffer.read_latest(window_samples)
            except Exception as e:
                logger.debug("live_transcription_read_failed", error=str(e))
                continue

            if audio is None or len(audio) < sample_rate:  # need at least 1s
                continue

            # faster-whisper wants float32 in [-1, 1]. Our ring buffer already
            # stores float32, but be defensive about shape.
            audio_np = np.asarray(audio, dtype=np.float32).reshape(-1)

            try:
                segments, _info = self._model.transcribe(
                    audio_np,
                    language=self.language,
                    beam_size=1,
                    vad_filter=False,
                    without_timestamps=False,
                    condition_on_previous_text=False,
                )
                text_parts: list[str] = []
                spans: list[tuple[float, float, str]] = []
                for seg in segments:
                    seg_text = (seg.text or "").strip()
                    if not seg_text:
                        continue
                    text_parts.append(seg_text)
                    spans.append((seg.start, seg.end, seg_text))
                full_text = " ".join(text_parts).strip()
            except Exception as e:
                logger.debug("live_transcription_transcribe_failed", error=str(e))
                continue

            # Diff against last window. Whisper re-hears the overlap, so emit
            # only what extends beyond the prior output.
            new_suffix = self._diff_suffix(self._last_text, full_text)
            if new_suffix:
                self._segment_counter += 1
                duration = capture.duration_seconds
                # We don't have an absolute start offset (the window is
                # rolling), so we pin start to "now minus window" and end to
                # "now", giving the UI a monotonically-advancing cursor.
                start_t = max(0.0, duration - self.window_s)
                end_t = duration
                self._broadcast({
                    "type": "segment",
                    "id": f"live-{self._segment_counter}",
                    "start": round(start_t, 2),
                    "end": round(end_t, 2),
                    "text": new_suffix,
                })
                self._last_text = full_text

    @staticmethod
    def _diff_suffix(previous: str, current: str) -> str:
        """Return the fragment of `current` that wasn't present in `previous`.

        Handles the common case where Whisper's new window repeats the tail
        of the previous window plus new words. We find the largest suffix of
        `previous` that is also a prefix of `current` and return the rest.
        If there's no overlap (e.g. speaker paused and silence reset the
        context), return the whole current text — better to show a duplicate
        than to swallow new speech.
        """
        if not current:
            return ""
        if not previous:
            return current.strip()
        # Quick win: exact prefix match.
        if current.startswith(previous):
            return current[len(previous):].strip()
        # Find longest suffix of `previous` that's a prefix of `current`.
        max_overlap = min(len(previous), len(current))
        overlap = 0
        for n in range(max_overlap, 0, -1):
            if previous.endswith(current[:n]):
                overlap = n
                break
        tail = current[overlap:].strip()
        return tail


_singleton: Optional[LiveTranscriptionService] = None


def get_live_transcription() -> LiveTranscriptionService:
    global _singleton
    if _singleton is None:
        _singleton = LiveTranscriptionService()
    return _singleton
