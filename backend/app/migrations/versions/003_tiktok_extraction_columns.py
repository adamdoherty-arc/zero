"""Add LLM extraction metadata columns to tiktok_products.

Revision ID: 003_tiktok_extraction
Revises: 002_video_content
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa

revision = "003_tiktok_extraction"
down_revision = "002_video_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tiktok_products", sa.Column("source_article_title", sa.String(500), nullable=True))
    op.add_column("tiktok_products", sa.Column("source_article_url", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("is_extracted", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("tiktok_products", sa.Column("why_trending", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("estimated_price_range", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("tiktok_products", "estimated_price_range")
    op.drop_column("tiktok_products", "why_trending")
    op.drop_column("tiktok_products", "is_extracted")
    op.drop_column("tiktok_products", "source_article_url")
    op.drop_column("tiktok_products", "source_article_title")
