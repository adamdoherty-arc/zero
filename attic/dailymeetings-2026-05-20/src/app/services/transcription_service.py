"""Meeting transcription using faster-whisper."""

import time
from pathlib import Path

import structlog

from app.config import get_settings
from app.services.whisper_compat import WhisperModel, load_audio

logger = structlog.get_logger(__name__)


class MeetingTranscriptionService:
    def __init__(self) -> None:
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self, model_size: str | None = None) -> None:
        settings = get_settings()
        model = model_size or settings.whisper_model_size
        device = settings.whisper_device
        compute_type = settings.whisper_compute_type
        # Resolve device: auto/cuda → check torch availability
        if device in ("cuda", "auto"):
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    if compute_type == "int8":
                        compute_type = "float16"
                else:
                    device = "cpu"
                    compute_type = "int8"
            except ImportError:
                device = "cpu"
                compute_type = "int8"
        logger.info("loading_whisper_model", model=model, device=device, compute_type=compute_type)
        start = time.perf_counter()
        self._model = WhisperModel(model, device=device, compute_type=compute_type)
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
        # Load audio via soundfile (av/PyAV DLLs blocked by Windows App Control)
        audio_array = load_audio(audio_path, target_sr=settings.sample_rate)
        # vad_filter disabled: requires torch+silero which is not installed
        segments_iter, info = self._model.transcribe(
            audio_array, language=settings.whisper_language,
            beam_size=5, vad_filter=False,
        )
        segments = []
        for seg in segments_iter:
            segments.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "confidence": round(seg.avg_logprob, 4),
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
