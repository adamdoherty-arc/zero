"""Add video_scripts and content_queue tables.

Revision ID: 002_video_content
Revises: 001_tiktok_approval
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "002_video_content"
down_revision = "001_tiktok_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_scripts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("product_id", sa.String(64), nullable=False, index=True),
        sa.Column("topic_id", sa.String(64), nullable=True, index=True),
        sa.Column("template_type", sa.String(30), nullable=False, server_default="voiceover_broll", index=True),
        sa.Column("hook_text", sa.Text(), nullable=True),
        sa.Column("body_json", JSONB, nullable=True, server_default="[]"),
        sa.Column("cta_text", sa.Text(), nullable=True),
        sa.Column("text_overlays", JSONB, nullable=True, server_default="[]"),
        sa.Column("voiceover_script", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "content_queue",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("script_id", sa.String(64), nullable=False, index=True),
        sa.Column("product_id", sa.String(64), nullable=False, index=True),
        sa.Column("generation_type", sa.String(30), nullable=False, server_default="text_to_video"),
        sa.Column("act_job_id", sa.String(128), nullable=True),
        sa.Column("act_generation_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued", index=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("content_queue")
    op.drop_table("video_scripts")
