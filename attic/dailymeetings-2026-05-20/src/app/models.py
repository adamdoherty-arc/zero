"""SQLAlchemy ORM models for meeting tables."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.database import Base


class MeetingModel(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    participants: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("idx_meetings_start_time", "start_time"),
    )


class MeetingRecordingModel(Base):
    __tablename__ = "meeting_recordings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(10), default="wav")
    sample_rate: Mapped[int] = mapped_column(Integer, default=16000)
    channels: Mapped[int] = mapped_column(Integer, default=1)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(10), default="mixed")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingTranscriptSegmentModel(Base):
    __tablename__ = "meeting_transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    speaker: Mapped[Optional[str]] = mapped_column(String(100))
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    embedding = mapped_column(Vector(768), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingSummaryModel(Base):
    __tablename__ = "meeting_summaries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    key_topics: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    action_items: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    decisions: Mapped[Optional[list]] = mapped_column(JSONB, default=[])
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    generation_time_ms: Mapped[Optional[int]] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingSpeakerMappingModel(Base):
    __tablename__ = "meeting_speaker_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    speaker_label: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
