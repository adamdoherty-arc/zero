"""Live transcription service — streams partial transcripts during recording."""

import asyncio
import json
import threading
import time

import numpy as np
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

# WebSocket clients for live transcript broadcast
_live_ws_clients: list = []


def register_live_ws(ws):
    _live_ws_clients.append(ws)


def unregister_live_ws(ws):
    if ws in _live_ws_clients:
        _live_ws_clients.remove(ws)


async def _broadcast_live(data: dict) -> None:
    msg = json.dumps(data)
    for ws in _live_ws_clients[:]:
        try:
            await ws.send_text(msg)
        except Exception:
            _live_ws_clients.remove(ws)


class LiveTranscriptionService:
    """Transcribes audio from the ring buffer in near-real-time during recording."""

    def __init__(self):
        self._model = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._segment_counter = 0
        self._transcribed_samples = 0

    @property
    def is_running(self) -> bool:
        return self._running

    def _ensure_model(self) -> bool:
        """Lazy-load the fast whisper model for live use."""
        if self._model is not None:
            return True
        try:
            from app.services.whisper_compat import WhisperModel
            settings = get_settings()
            model_size = settings.live_whisper_model_size
            device = "cpu"
            compute_type = "int8"
            # Try CUDA
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
            except ImportError:
                pass
            logger.info("loading_live_whisper_model", model=model_size, device=device)
            self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info("live_whisper_model_loaded")
            return True
        except ImportError:
            logger.warning("faster_whisper_not_installed_live_transcription_disabled")
            return False
        except Exception as e:
            logger.error("live_whisper_model_load_failed", error=str(e))
            return False

    def start(self, audio_capture) -> None:
        """Start live transcription. Call after audio capture has started."""
        if self._running:
            return
        if not self._ensure_model():
            return

        self._running = True
        self._segment_counter = 0
        self._transcribed_samples = 0
        self._loop = asyncio.get_event_loop()

        self._thread = threading.Thread(
            target=self._transcription_loop,
            args=(audio_capture,),
            daemon=True,
            name="live-transcription",
        )
        self._thread.start()
        logger.info("live_transcription_started")

        # Notify clients
        asyncio.ensure_future(_broadcast_live({
            "type": "status", "message": "Live transcription started",
        }))

    def stop(self) -> None:
        """Stop live transcription."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("live_transcription_stopped")

    def _transcription_loop(self, audio_capture) -> None:
        """Background thread: periodically transcribe from ring buffer."""
        settings = get_settings()
        sample_rate = settings.sample_rate
        # Wait for some audio to accumulate
        time.sleep(3)

        while self._running and audio_capture.is_recording:
            try:
                # Read available audio from ring buffer
                ring = audio_capture.ring_buffer
                available = ring.available
                if available < sample_rate * 2:  # Need at least 2 seconds
                    time.sleep(1)
                    continue

                # Read up to 10 seconds from the buffer
                read_samples = min(available, sample_rate * 10)
                audio_data = ring.read(read_samples)
                if audio_data is None or len(audio_data) == 0:
                    time.sleep(1)
                    continue

                # Transcribe the audio chunk
                # vad_filter disabled: requires torch+silero which is not installed
                segments_iter, info = self._model.transcribe(
                    audio_data, language=settings.whisper_language,
                    beam_size=1, vad_filter=False,
                )

                # Calculate time offset based on total recorded duration
                total_duration = audio_capture.duration_seconds
                chunk_duration = len(audio_data) / sample_rate
                time_offset = max(0, total_duration - chunk_duration)

                new_segments = []
                for seg in segments_iter:
                    text = seg.text.strip()
                    if not text:
                        continue
                    self._segment_counter += 1
                    segment_data = {
                        "type": "segment",
                        "id": self._segment_counter,
                        "start": round(time_offset + seg.start, 2),
                        "end": round(time_offset + seg.end, 2),
                        "text": text,
                    }
                    new_segments.append(segment_data)

                # Broadcast new segments
                if new_segments and self._loop is not None:
                    for seg_data in new_segments:
                        asyncio.run_coroutine_threadsafe(
                            _broadcast_live(seg_data), self._loop,
                        )

                # Wait before next transcription cycle
                time.sleep(3)

            except Exception as e:
                logger.error("live_transcription_error", error=str(e))
                time.sleep(2)


_instance: LiveTranscriptionService | None = None


def get_live_transcription_service() -> LiveTranscriptionService:
    global _instance
    if _instance is None:
        _instance = LiveTranscriptionService()
    return _instance
