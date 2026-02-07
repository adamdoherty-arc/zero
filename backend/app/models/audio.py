"""
Audio transcription data models for ZERO.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class TranscriptionStatus(str, Enum):
    """Status of a transcription job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WhisperModel(str, Enum):
    """Available Whisper model sizes."""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class TranscriptionSegment(BaseModel):
    """A segment of transcribed audio."""
    start: float
    end: float
    text: str
    confidence: Optional[float] = None


class TranscriptionResult(BaseModel):
    """Result of audio transcription."""
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    segments: List[TranscriptionSegment] = Field(default_factory=list)
    model_used: str = "base"
    processing_time_seconds: Optional[float] = None


class TranscriptionJob(BaseModel):
    """A transcription job record."""
    id: str
    status: TranscriptionStatus = TranscriptionStatus.PENDING
    audio_file: str
    audio_format: Optional[str] = None
    file_size_bytes: Optional[int] = None
    result: Optional[TranscriptionResult] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class TranscribeRequest(BaseModel):
    """Request to transcribe audio."""
    model: WhisperModel = WhisperModel.BASE
    language: Optional[str] = None  # Auto-detect if not specified
    create_note: bool = False
    note_title: Optional[str] = None
    note_tags: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None


class TranscribeToNoteRequest(BaseModel):
    """Request to transcribe audio and create a note."""
    model: WhisperModel = WhisperModel.BASE
    language: Optional[str] = None
    title: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    task_id: Optional[str] = None
