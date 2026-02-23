"""Add approval tracking columns to tiktok_products.

Revision ID: 001_tiktok_approval
Revises:
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa

revision = "001_tiktok_approval"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tiktok_products", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tiktok_products", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tiktok_products", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tiktok_products", "rejection_reason")
    op.drop_column("tiktok_products", "rejected_at")
    op.drop_column("tiktok_products", "approved_at")
