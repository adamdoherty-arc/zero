"""Character reference videos: TikTok videos ingested from phone for character content.

Stores downloaded TikTok videos with transcripts and intent-dispatched LLM analysis
(inspiration / facts / discovery) to feed the character content system.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "022a"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "character_reference_videos",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tiktok_url", sa.Text, nullable=False),
        sa.Column("tiktok_video_id", sa.String(64), index=True),
        sa.Column(
            "character_id",
            sa.String(64),
            sa.ForeignKey("characters.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("intent", sa.String(20), nullable=False, server_default="inbox"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("error_message", sa.Text),
        sa.Column("retry_count", sa.Integer, server_default="0"),

        # TikTok metadata
        sa.Column("title", sa.Text),
        sa.Column("author_name", sa.String(200)),
        sa.Column("author_url", sa.Text),
        sa.Column("caption", sa.Text),
        sa.Column("hashtags", JSONB, server_default="[]"),
        sa.Column("duration_seconds", sa.Integer),
        sa.Column("thumbnail_url", sa.Text),
        sa.Column("views", sa.Integer),
        sa.Column("likes", sa.Integer),

        # Local storage (workspace-relative)
        sa.Column("video_path", sa.Text),
        sa.Column("thumbnail_path", sa.Text),
        sa.Column("audio_path", sa.Text),
        sa.Column("file_size_bytes", sa.BigInteger),

        # Transcription
        sa.Column("transcript", sa.Text),
        sa.Column("transcript_language", sa.String(10)),
        sa.Column("transcribed_at", sa.DateTime(timezone=True)),

        # Intent-specific LLM outputs
        sa.Column("style_analysis", JSONB),
        sa.Column("extracted_facts", JSONB),
        sa.Column("proposed_character", JSONB),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),

        # User notes and promotion tracking
        sa.Column("notes", sa.Text),
        sa.Column("promoted_character_id", sa.String(64)),
        sa.Column("applied_fact_count", sa.Integer, server_default="0"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index(
        "idx_cref_intent_status",
        "character_reference_videos",
        ["intent", "status"],
    )
    op.create_index(
        "idx_cref_character_created",
        "character_reference_videos",
        ["character_id", "created_at"],
    )
    op.create_unique_constraint(
        "uq_cref_video_character",
        "character_reference_videos",
        ["tiktok_video_id", "character_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_cref_video_character", "character_reference_videos", type_="unique")
    op.drop_index("idx_cref_character_created", "character_reference_videos")
    op.drop_index("idx_cref_intent_status", "character_reference_videos")
    op.drop_table("character_reference_videos")
