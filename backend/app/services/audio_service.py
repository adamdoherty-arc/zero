"""
Audio transcription service using faster-whisper for local processing.
"""

import os
import time
import uuid
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache
from datetime import datetime
import structlog

# Lazy import for faster-whisper (may not be installed)
WhisperModel = None

from app.models.audio import (
    TranscriptionStatus,
    WhisperModel as WhisperModelEnum,
    TranscriptionSegment,
    TranscriptionResult,
    TranscriptionJob,
    TranscribeRequest,
    TranscribeToNoteRequest,
)
from app.models.knowledge import NoteCreate, NoteSource, NoteType


logger = structlog.get_logger()

# Supported audio formats
SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac", ".mp4", ".mpeg", ".mpga"}


class AudioService:
    """Service for audio transcription using local Whisper models."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.audio_path = self.workspace_path / "audio"
        self.audio_path.mkdir(parents=True, exist_ok=True)
        self.jobs_file = self.audio_path / "jobs.json"
        self._model_cache: Dict[str, Any] = {}
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure jobs storage file exists."""
        if not self.jobs_file.exists():
            import json
            self.jobs_file.write_text(json.dumps({"jobs": []}))

    def _load_jobs(self) -> List[Dict[str, Any]]:
        """Load jobs from storage."""
        import json
        try:
            data = json.loads(self.jobs_file.read_text())
            return data.get("jobs", [])
        except Exception:
            return []

    def _save_jobs(self, jobs: List[Dict[str, Any]]):
        """Save jobs to storage."""
        import json
        self.jobs_file.write_text(json.dumps({"jobs": jobs}, indent=2, default=str))

    def _get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        jobs = self._load_jobs()
        for job in jobs:
            if job.get("id") == job_id:
                return job
        return None

    def _update_job(self, job_id: str, updates: Dict[str, Any]):
        """Update a job."""
        jobs = self._load_jobs()
        for i, job in enumerate(jobs):
            if job.get("id") == job_id:
                jobs[i].update(updates)
                break
        self._save_jobs(jobs)

    def _add_job(self, job: Dict[str, Any]):
        """Add a new job."""
        jobs = self._load_jobs()
        jobs.append(job)
        self._save_jobs(jobs)

    def _get_model(self, model_size: str) -> Any:
        """Get or load a Whisper model."""
        global WhisperModel

        if model_size in self._model_cache:
            return self._model_cache[model_size]

        # Lazy import
        if WhisperModel is None:
            try:
                from faster_whisper import WhisperModel as FasterWhisperModel
                WhisperModel = FasterWhisperModel
            except ImportError:
                raise RuntimeError(
                    "faster-whisper is not installed. "
                    "Install it with: pip install faster-whisper"
                )

        logger.info("loading_whisper_model", model=model_size)

        # Use CPU by default, can be configured for CUDA
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        device = os.getenv("WHISPER_DEVICE", "cpu")

        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._model_cache[model_size] = model

        logger.info("whisper_model_loaded", model=model_size, device=device)
        return model

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available Whisper models."""
        return [
            {
                "id": "tiny",
                "name": "Tiny",
                "description": "Fastest, lowest accuracy (~1GB VRAM)",
                "size_mb": 75,
            },
            {
                "id": "base",
                "name": "Base",
                "description": "Fast with decent accuracy (~1GB VRAM)",
                "size_mb": 145,
            },
            {
                "id": "small",
                "name": "Small",
                "description": "Balanced speed and accuracy (~2GB VRAM)",
                "size_mb": 488,
            },
            {
                "id": "medium",
                "name": "Medium",
                "description": "Good accuracy, slower (~5GB VRAM)",
                "size_mb": 1500,
            },
            {
                "id": "large",
                "name": "Large (large-v3)",
                "description": "Best accuracy, slowest (~10GB VRAM)",
                "size_mb": 3100,
            },
        ]

    def is_supported_format(self, filename: str) -> bool:
        """Check if file format is supported."""
        ext = Path(filename).suffix.lower()
        return ext in SUPPORTED_FORMATS

    async def transcribe(
        self,
        audio_file_path: str,
        model: WhisperModelEnum = WhisperModelEnum.BASE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file to text.

        Args:
            audio_file_path: Path to the audio file
            model: Whisper model size to use
            language: Language code (auto-detect if None)

        Returns:
            TranscriptionResult with text and segments
        """
        path = Path(audio_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        if not self.is_supported_format(path.name):
            raise ValueError(f"Unsupported audio format: {path.suffix}")

        start_time = time.time()

        # Run transcription in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._transcribe_sync,
            str(path),
            model.value,
            language,
        )

        processing_time = time.time() - start_time
        result.processing_time_seconds = round(processing_time, 2)

        logger.info(
            "transcription_complete",
            file=path.name,
            model=model.value,
            duration_seconds=result.duration_seconds,
            processing_time_seconds=result.processing_time_seconds,
        )

        return result

    def _transcribe_sync(
        self,
        audio_file_path: str,
        model_size: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Synchronous transcription (runs in thread pool)."""
        whisper_model = self._get_model(model_size)

        # Transcribe
        segments_gen, info = whisper_model.transcribe(
            audio_file_path,
            language=language,
            beam_size=5,
            vad_filter=True,  # Filter out silence
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        # Collect segments
        segments = []
        full_text_parts = []

        for segment in segments_gen:
            segments.append(
                TranscriptionSegment(
                    start=round(segment.start, 2),
                    end=round(segment.end, 2),
                    text=segment.text.strip(),
                    confidence=round(segment.avg_logprob, 3) if hasattr(segment, 'avg_logprob') else None,
                )
            )
            full_text_parts.append(segment.text.strip())

        full_text = " ".join(full_text_parts)

        return TranscriptionResult(
            text=full_text,
            language=info.language,
            duration_seconds=round(info.duration, 2),
            segments=segments,
            model_used=model_size,
        )

    async def transcribe_upload(
        self,
        file_content: bytes,
        filename: str,
        model: WhisperModelEnum = WhisperModelEnum.BASE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an uploaded audio file.

        Args:
            file_content: Raw file bytes
            filename: Original filename
            model: Whisper model size
            language: Language code (auto-detect if None)

        Returns:
            TranscriptionResult
        """
        if not self.is_supported_format(filename):
            raise ValueError(f"Unsupported audio format: {Path(filename).suffix}")

        # Save to temp file
        file_id = str(uuid.uuid4())[:8]
        ext = Path(filename).suffix
        temp_path = self.audio_path / f"temp_{file_id}{ext}"

        try:
            temp_path.write_bytes(file_content)
            result = await self.transcribe(str(temp_path), model, language)
            return result
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()

    async def create_job(
        self,
        audio_file_path: str,
        request: TranscribeRequest,
    ) -> TranscriptionJob:
        """
        Create a transcription job for async processing.

        Args:
            audio_file_path: Path to audio file
            request: Transcription request parameters

        Returns:
            TranscriptionJob with pending status
        """
        path = Path(audio_file_path)

        job = TranscriptionJob(
            id=str(uuid.uuid4()),
            status=TranscriptionStatus.PENDING,
            audio_file=str(path),
            audio_format=path.suffix.lower().lstrip("."),
            file_size_bytes=path.stat().st_size if path.exists() else None,
            created_at=datetime.utcnow(),
        )

        self._add_job(job.model_dump())
        return job

    async def process_job(self, job_id: str, request: TranscribeRequest) -> TranscriptionJob:
        """
        Process a transcription job.

        Args:
            job_id: Job ID to process
            request: Transcription parameters

        Returns:
            Updated TranscriptionJob
        """
        job_data = self._get_job(job_id)
        if not job_data:
            raise ValueError(f"Job not found: {job_id}")

        # Update status to processing
        self._update_job(job_id, {"status": TranscriptionStatus.PROCESSING.value})

        try:
            result = await self.transcribe(
                job_data["audio_file"],
                request.model,
                request.language,
            )

            self._update_job(job_id, {
                "status": TranscriptionStatus.COMPLETED.value,
                "result": result.model_dump(),
                "completed_at": datetime.utcnow().isoformat(),
            })

        except Exception as e:
            logger.error("transcription_job_failed", job_id=job_id, error=str(e))
            self._update_job(job_id, {
                "status": TranscriptionStatus.FAILED.value,
                "error": str(e),
                "completed_at": datetime.utcnow().isoformat(),
            })

        job_data = self._get_job(job_id)
        return TranscriptionJob(**job_data)

    async def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        """Get a transcription job by ID."""
        job_data = self._get_job(job_id)
        if job_data:
            return TranscriptionJob(**job_data)
        return None

    async def list_jobs(
        self,
        status: Optional[TranscriptionStatus] = None,
        limit: int = 50,
    ) -> List[TranscriptionJob]:
        """List transcription jobs."""
        jobs = self._load_jobs()

        if status:
            jobs = [j for j in jobs if j.get("status") == status.value]

        # Sort by created_at descending
        jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return [TranscriptionJob(**j) for j in jobs[:limit]]

    async def transcribe_to_note(
        self,
        file_content: bytes,
        filename: str,
        request: TranscribeToNoteRequest,
    ) -> Dict[str, Any]:
        """
        Transcribe audio and create a note from the transcription.

        Args:
            file_content: Raw audio file bytes
            filename: Original filename
            request: Note creation parameters

        Returns:
            Dict with transcription result and created note
        """
        # Import knowledge service here to avoid circular imports
        from app.services.knowledge_service import get_knowledge_service

        # Transcribe
        result = await self.transcribe_upload(
            file_content,
            filename,
            request.model,
            request.language,
        )

        # Create note
        knowledge_service = get_knowledge_service()

        note_title = request.title or f"Audio Note - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

        note_create = NoteCreate(
            type=NoteType.NOTE,
            title=note_title,
            content=result.text,
            source=NoteSource.AUDIO,
            source_reference=filename,
            tags=request.tags,
            project_id=request.project_id,
            task_id=request.task_id,
        )

        note = await knowledge_service.create_note(note_create)

        logger.info(
            "audio_note_created",
            note_id=note.id,
            duration_seconds=result.duration_seconds,
            text_length=len(result.text),
        )

        return {
            "transcription": result,
            "note": note,
        }


@lru_cache()
def get_audio_service() -> AudioService:
    """Get singleton AudioService instance."""
    return AudioService()
