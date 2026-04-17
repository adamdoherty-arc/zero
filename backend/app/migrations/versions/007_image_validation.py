"""Add image_validated column to tiktok_products table.

Revision ID: 007_image_validation
Revises: 006_content_queue_publishing
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa

revision = "007_image_validation"
down_revision = "006_content_queue_publishing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tiktok_products",
        sa.Column("image_validated", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tiktok_products", "image_validated")
