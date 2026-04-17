"""Competitor content samples: winning external hooks/captions for prompt breeding.

Stores hook/caption + engagement from public TikTok/IG/YouTube pages so the
Strategist role in the swarm + the prompt breeder can learn from what's winning
off-platform. 30-day decay keeps the store fresh.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "competitor_content_samples" in inspector.get_table_names():
        return
    op.create_table(
        "competitor_content_samples",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("niche", sa.String(80), nullable=False, index=True),
        sa.Column("platform", sa.String(30), nullable=False, index=True),
        sa.Column("hook_text", sa.Text, nullable=True),
        sa.Column("caption", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("creator_handle", sa.String(100), nullable=True),
        sa.Column("view_count", sa.BigInteger, nullable=True),
        sa.Column("like_count", sa.BigInteger, nullable=True),
        sa.Column("comment_count", sa.BigInteger, nullable=True),
        sa.Column("engagement_rate", sa.Float, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index(
        "idx_competitor_niche_engagement",
        "competitor_content_samples",
        ["niche", "engagement_rate"],
    )
    op.create_index(
        "idx_competitor_platform_retrieved",
        "competitor_content_samples",
        ["platform", "retrieved_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_competitor_platform_retrieved", table_name="competitor_content_samples")
    op.drop_index("idx_competitor_niche_engagement", table_name="competitor_content_samples")
    op.drop_table("competitor_content_samples")
