"""
Pydantic schemas for Meeting Intelligence (DailyMemory).
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- Meeting ---

class MeetingCreate(BaseModel):
    title: str
    start_time: datetime
    end_time: Optional[datetime] = None
    participants: Optional[list[str]] = None
    calendar_event_id: Optional[str] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    end_time: Optional[datetime] = None
    participants: Optional[list[str]] = None
    status: Optional[Literal["scheduled", "recording", "processing", "completed", "failed"]] = None


class MeetingResponse(BaseModel):
    id: str
    title: str
    calendar_event_id: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[int]
    participants: Optional[list[str]]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingListResponse(BaseModel):
    meetings: list[MeetingResponse]
    total: int


# --- Recording ---

class RecordingStartRequest(BaseModel):
    meeting_id: Optional[str] = None
    title: Optional[str] = None
    source: Literal["system", "mic", "mixed"] = "mixed"


class RecordingStatusResponse(BaseModel):
    is_recording: bool
    meeting_id: Optional[str] = None
    duration_seconds: float = 0
    audio_levels: Optional[dict] = None


class RecordingMetadataResponse(BaseModel):
    meeting_id: str
    duration_seconds: Optional[float]
    file_size_bytes: Optional[int]
    format: str
    sample_rate: int
    channels: int

    model_config = {"from_attributes": True}


# --- Transcript ---

class TranscriptSegmentResponse(BaseModel):
    id: int
    speaker: Optional[str]
    start_time: float
    end_time: float
    text: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    meeting_id: str
    segments: list[TranscriptSegmentResponse]
    total_segments: int


# --- Summary ---

class SummaryResponse(BaseModel):
    id: str
    meeting_id: str
    summary_text: str
    key_topics: Optional[list[str]]
    action_items: Optional[list[dict]]
    decisions: Optional[list[str]]
    model_used: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Chat ---

class MeetingChatRequest(BaseModel):
    message: str = Field(..., max_length=5000)
    meeting_id: Optional[str] = None


class MeetingChatSource(BaseModel):
    meeting_id: str
    meeting_title: str
    text: str
    speaker: Optional[str]
    timestamp: Optional[float]


class MeetingChatResponse(BaseModel):
    answer: str
    sources: list[MeetingChatSource]


# --- Search ---

class MeetingSearchResult(BaseModel):
    meeting_id: str
    meeting_title: str
    snippet: str
    score: float
    timestamp: Optional[float]
    speaker: Optional[str]


class MeetingSearchResponse(BaseModel):
    results: list[MeetingSearchResult]
    total: int
    query: str


# --- Speaker Mapping ---

class SpeakerMappingResponse(BaseModel):
    id: int
    meeting_id: str
    speaker_label: str
    display_name: str

    model_config = {"from_attributes": True}


class SpeakerMappingUpdate(BaseModel):
    speaker_label: str
    display_name: str
