"""Add meeting intelligence tables (DailyMemory migration).

Revision ID: 013_meeting_intelligence
Revises: 012_tiktok_enhancements
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

revision = "013_meeting_intelligence"
down_revision = "012_tiktok_enhancements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension exists (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- meetings ---
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("calendar_event_id", sa.String(255), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("participants", JSONB, server_default="[]"),
        sa.Column("status", sa.String(20), server_default="scheduled", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_meetings_status", "meetings", ["status"])
    op.create_index("idx_meetings_start_time", "meetings", ["start_time"])

    # --- meeting_recordings ---
    op.create_table(
        "meeting_recordings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("meeting_id", sa.String(64), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("format", sa.String(10), server_default="wav"),
        sa.Column("sample_rate", sa.Integer(), server_default="16000"),
        sa.Column("channels", sa.Integer(), server_default="1"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(10), server_default="mixed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_meeting_recordings_meeting", "meeting_recordings", ["meeting_id"])

    # --- meeting_transcript_segments ---
    op.create_table(
        "meeting_transcript_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meeting_id", sa.String(64), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("speaker", sa.String(100), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_meeting_transcript_meeting", "meeting_transcript_segments", ["meeting_id"])

    # --- meeting_summaries ---
    op.create_table(
        "meeting_summaries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("meeting_id", sa.String(64), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("key_topics", JSONB, server_default="[]"),
        sa.Column("action_items", JSONB, server_default="[]"),
        sa.Column("decisions", JSONB, server_default="[]"),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("generation_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_meeting_summaries_meeting", "meeting_summaries", ["meeting_id"])

    # --- meeting_speaker_mappings ---
    op.create_table(
        "meeting_speaker_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("meeting_id", sa.String(64), nullable=False),
        sa.Column("speaker_label", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
    )
    op.create_index("idx_meeting_speaker_mappings_meeting", "meeting_speaker_mappings", ["meeting_id"])


def downgrade() -> None:
    op.drop_table("meeting_speaker_mappings")
    op.drop_table("meeting_summaries")
    op.drop_table("meeting_transcript_segments")
    op.drop_table("meeting_recordings")
    op.drop_table("meetings")
