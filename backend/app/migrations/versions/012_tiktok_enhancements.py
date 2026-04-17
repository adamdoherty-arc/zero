"""Add affiliate links, import tracking to tiktok_products; reference_videos table; reference_video_id to video_scripts.

Revision ID: 012_tiktok_enhancements
Revises: 011_workflows_outcomes
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "012_tiktok_enhancements"
down_revision = "011_workflows_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tiktok_products: affiliate/import columns ---
    op.add_column("tiktok_products", sa.Column("affiliate_link", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("tiktok_shop_url", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("import_url", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("import_source", sa.String(30), nullable=True))

    # --- video_scripts: link back to reference video ---
    op.add_column("video_scripts", sa.Column("reference_video_id", sa.String(64), nullable=True))

    # --- reference_videos table ---
    op.create_table(
        "reference_videos",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tiktok_url", sa.Text(), nullable=False),
        sa.Column("product_id", sa.String(64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("author_name", sa.String(200), nullable=True),
        sa.Column("author_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("hashtags", JSONB, server_default="[]"),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("hook_analysis", sa.Text(), nullable=True),
        sa.Column("structure_analysis", sa.Text(), nullable=True),
        sa.Column("style_notes", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(30), nullable=True),
        sa.Column("estimated_duration", sa.Integer(), nullable=True),
        sa.Column("generated_script_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_reference_videos_status", "reference_videos", ["status"])
    op.create_index("idx_reference_videos_product", "reference_videos", ["product_id"])


def downgrade() -> None:
    op.drop_index("idx_reference_videos_product")
    op.drop_index("idx_reference_videos_status")
    op.drop_table("reference_videos")
    op.drop_column("video_scripts", "reference_video_id")
    op.drop_column("tiktok_products", "import_source")
    op.drop_column("tiktok_products", "import_url")
    op.drop_column("tiktok_products", "tiktok_shop_url")
    op.drop_column("tiktok_products", "affiliate_link")
