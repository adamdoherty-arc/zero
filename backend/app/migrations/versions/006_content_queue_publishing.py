"""Add publishing columns to content_queue table.

Revision ID: 006_content_queue_publishing
Revises: 005_llm_usage
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "006_content_queue_publishing"
down_revision = "005_llm_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_queue", sa.Column("publish_status", sa.String(20), nullable=True))
    op.add_column("content_queue", sa.Column("publish_platform", sa.String(30), nullable=True))
    op.add_column("content_queue", sa.Column("publish_url", sa.Text(), nullable=True))
    op.add_column("content_queue", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_queue", sa.Column("publish_error", sa.Text(), nullable=True))
    op.add_column("content_queue", sa.Column("caption", sa.Text(), nullable=True))
    op.add_column("content_queue", sa.Column("hashtags", JSONB(), nullable=True))

    op.create_index("ix_content_queue_publish_status", "content_queue", ["publish_status"])


def downgrade() -> None:
    op.drop_index("ix_content_queue_publish_status", table_name="content_queue")
    op.drop_column("content_queue", "hashtags")
    op.drop_column("content_queue", "caption")
    op.drop_column("content_queue", "publish_error")
    op.drop_column("content_queue", "published_at")
    op.drop_column("content_queue", "publish_url")
    op.drop_column("content_queue", "publish_platform")
    op.drop_column("content_queue", "publish_status")
