"""
Audio transcription API endpoints.
Provides local Whisper-based transcription for audio files.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from typing import List, Optional
import structlog

from app.models.audio import (
    TranscriptionStatus,
    WhisperModel,
    TranscriptionResult,
    TranscriptionJob,
    TranscribeToNoteRequest,
)
from app.services.audio_service import get_audio_service, SUPPORTED_FORMATS

router = APIRouter()
logger = structlog.get_logger()


@router.get("/models")
async def list_models():
    """Get available Whisper models with their specifications."""
    service = get_audio_service()
    return {
        "models": service.get_available_models(),
        "default": "base",
    }


@router.get("/formats")
async def list_formats():
    """Get supported audio formats."""
    return {
        "formats": sorted(list(SUPPORTED_FORMATS)),
        "description": "Supported audio file extensions",
    }


@router.post("/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(
    file: UploadFile = File(..., description="Audio file to transcribe"),
    model: WhisperModel = Form(default=WhisperModel.BASE, description="Whisper model size"),
    language: Optional[str] = Form(default=None, description="Language code (e.g., 'en', 'es'). Auto-detect if not specified."),
):
    """
    Transcribe an uploaded audio file to text.

    Supports: mp3, wav, m4a, ogg, webm, flac, mp4, mpeg, mpga

    Models (ordered by speed/accuracy tradeoff):
    - tiny: Fastest, lowest accuracy
    - base: Fast with decent accuracy (recommended)
    - small: Balanced speed and accuracy
    - medium: Good accuracy, slower
    - large: Best accuracy, slowest
    """
    service = get_audio_service()

    # Validate format
    if not file.filename or not service.is_supported_format(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    # Read file content
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Check file size (max 100MB)
    max_size = 100 * 1024 * 1024  # 100MB
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is 100MB."
        )

    try:
        result = await service.transcribe_upload(
            content,
            file.filename,
            model,
            language,
        )
        return result
    except RuntimeError as e:
        # faster-whisper not installed
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("transcription_failed", error=str(e), filename=file.filename)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.post("/transcribe-to-note")
async def transcribe_to_note(
    file: UploadFile = File(..., description="Audio file to transcribe"),
    model: WhisperModel = Form(default=WhisperModel.BASE),
    language: Optional[str] = Form(default=None),
    title: Optional[str] = Form(default=None, description="Note title (auto-generated if not provided)"),
    tags: str = Form(default="", description="Comma-separated tags"),
    project_id: Optional[str] = Form(default=None),
    task_id: Optional[str] = Form(default=None),
):
    """
    Transcribe audio and automatically create a note from the transcription.

    This combines transcription with note creation in the Second Brain system.
    Perfect for voice memos and audio notes.
    """
    service = get_audio_service()

    # Validate format
    if not file.filename or not service.is_supported_format(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    # Read file content
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

    # Parse tags
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    request = TranscribeToNoteRequest(
        model=model,
        language=language,
        title=title,
        tags=tag_list,
        project_id=project_id,
        task_id=task_id,
    )

    try:
        result = await service.transcribe_to_note(content, file.filename, request)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("transcribe_to_note_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed: {str(e)}")


@router.get("/jobs", response_model=List[TranscriptionJob])
async def list_jobs(
    status: Optional[TranscriptionStatus] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List transcription jobs."""
    service = get_audio_service()
    return await service.list_jobs(status, limit)


@router.get("/jobs/{job_id}", response_model=TranscriptionJob)
async def get_job(job_id: str):
    """Get a transcription job by ID."""
    service = get_audio_service()
    job = await service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/transcribe-file")
async def transcribe_file_path(
    file_path: str = Form(..., description="Path to audio file on server"),
    model: WhisperModel = Form(default=WhisperModel.BASE),
    language: Optional[str] = Form(default=None),
):
    """
    Transcribe an audio file from a server path.

    Useful for processing files already on the server (e.g., from voice messages).
    """
    service = get_audio_service()

    try:
        result = await service.transcribe(file_path, model, language)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Audio file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("transcription_failed", error=str(e), file_path=file_path)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
