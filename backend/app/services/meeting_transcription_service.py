"""Meeting transcription using faster-whisper."""

import time
from functools import lru_cache
from pathlib import Path

import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


class MeetingTranscriptionService:
    def __init__(self) -> None:
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self) -> None:
        from faster_whisper import WhisperModel
        settings = get_settings()
        device = settings.whisper_device
        compute_type = settings.whisper_compute_type
        if device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    logger.warning("cuda_not_available_falling_back_to_cpu")
                    device = "cpu"
                    compute_type = "int8"
            except ImportError:
                device = "cpu"
                compute_type = "int8"
        logger.info("loading_whisper_model", model=settings.whisper_model_size, device=device, compute_type=compute_type)
        start = time.perf_counter()
        self._model = WhisperModel(settings.whisper_model_size, device=device, compute_type=compute_type)
        logger.info("whisper_model_loaded", elapsed=f"{time.perf_counter() - start:.2f}s")

    def transcribe(self, audio_path: Path) -> list[dict]:
        if not self.is_loaded:
            raise RuntimeError("Whisper model not loaded. Call load_model() first.")
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        settings = get_settings()
        logger.info("transcribing", file=audio_path.name)
        start = time.perf_counter()
        segments_iter, info = self._model.transcribe(
            str(audio_path), language=settings.whisper_language,
            beam_size=5, vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
        )
        segments = []
        for seg in segments_iter:
            # faster-whisper renamed avg_log_prob -> avg_logprob in 1.1+ and
            # some builds drop the attribute entirely; fall back gracefully.
            confidence = (
                getattr(seg, "avg_logprob", None)
                or getattr(seg, "avg_log_prob", None)
            )
            segments.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "confidence": round(confidence, 4) if confidence is not None else None,
            })
        elapsed = time.perf_counter() - start
        logger.info("transcription_complete", segments=len(segments), elapsed=f"{elapsed:.2f}s",
                    audio_duration=f"{info.duration:.1f}s", language=info.language)
        return segments


_instance: MeetingTranscriptionService | None = None

def get_meeting_transcription_service() -> MeetingTranscriptionService:
    global _instance
    if _instance is None:
        _instance = MeetingTranscriptionService()
    return _instance
