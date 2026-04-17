"""Speaker diarization using pyannote.audio with transcript alignment."""

import time
from pathlib import Path

import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger(__name__)


class MeetingDiarizationService:
    def __init__(self) -> None:
        self._pipeline = None

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def load_model(self) -> None:
        from pyannote.audio import Pipeline
        settings = get_settings()
        if not settings.hf_token:
            raise ValueError("HuggingFace token (ZERO_HF_TOKEN) required for pyannote diarization.")
        logger.info("loading_diarization_pipeline", model=settings.diarization_model)
        start = time.perf_counter()
        self._pipeline = Pipeline.from_pretrained(settings.diarization_model, use_auth_token=settings.hf_token)
        try:
            import torch
            if torch.cuda.is_available():
                self._pipeline.to(torch.device("cuda"))
                logger.info("diarization_pipeline_on_cuda")
        except ImportError:
            pass
        logger.info("diarization_pipeline_loaded", elapsed=f"{time.perf_counter() - start:.2f}s")

    def diarize(self, audio_path: Path) -> list[dict]:
        if not self.is_loaded:
            raise RuntimeError("Diarization pipeline not loaded.")
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        settings = get_settings()
        logger.info("diarizing", file=audio_path.name)
        start = time.perf_counter()
        diarization = self._pipeline(str(audio_path), max_speakers=settings.max_speakers)
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({"start": round(turn.start, 3), "end": round(turn.end, 3), "speaker": speaker})
        unique_speakers = {s["speaker"] for s in segments}
        logger.info("diarization_complete", segments=len(segments), speakers=len(unique_speakers),
                    elapsed=f"{time.perf_counter() - start:.2f}s")
        return segments

    def align_with_transcript(self, diarization_segments: list[dict], transcript_segments: list[dict]) -> list[dict]:
        aligned = []
        for tseg in transcript_segments:
            t_start, t_end = tseg["start"], tseg["end"]
            t_duration = t_end - t_start
            best_speaker, best_overlap = "UNKNOWN", 0.0
            for dseg in diarization_segments:
                overlap = max(0.0, min(t_end, dseg["end"]) - max(t_start, dseg["start"]))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = dseg["speaker"]
            if t_duration > 0 and (best_overlap / t_duration) <= 0.5:
                best_speaker = "UNKNOWN"
            aligned.append({
                "start": tseg["start"], "end": tseg["end"], "text": tseg["text"],
                "speaker": best_speaker, "confidence": tseg["confidence"],
            })
        assigned = sum(1 for s in aligned if s["speaker"] != "UNKNOWN")
        logger.info("alignment_complete", assigned=assigned, total=len(aligned))
        return aligned


_instance: MeetingDiarizationService | None = None

def get_meeting_diarization_service() -> MeetingDiarizationService:
    global _instance
    if _instance is None:
        _instance = MeetingDiarizationService()
    return _instance
