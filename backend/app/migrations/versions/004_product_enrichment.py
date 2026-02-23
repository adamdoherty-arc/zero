"""Add image, success rating, and sourcing columns to tiktok_products.

Revision ID: 004_product_enrichment
Revises: 003_tiktok_extraction
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "004_product_enrichment"
down_revision = "003_tiktok_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Images
    op.add_column("tiktok_products", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("image_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("tiktok_products", sa.Column("image_search_done", sa.Boolean(), server_default=sa.text("false"), nullable=False))

    # Success rating
    op.add_column("tiktok_products", sa.Column("success_rating", sa.Float(), nullable=True))
    op.add_column("tiktok_products", sa.Column("success_factors", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))

    # Sourcing
    op.add_column("tiktok_products", sa.Column("supplier_url", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("supplier_name", sa.String(200), nullable=True))
    op.add_column("tiktok_products", sa.Column("sourcing_method", sa.String(50), nullable=True))
    op.add_column("tiktok_products", sa.Column("sourcing_notes", sa.Text(), nullable=True))
    op.add_column("tiktok_products", sa.Column("sourcing_links", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("tiktok_products", sa.Column("listing_steps", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    op.drop_column("tiktok_products", "listing_steps")
    op.drop_column("tiktok_products", "sourcing_links")
    op.drop_column("tiktok_products", "sourcing_notes")
    op.drop_column("tiktok_products", "sourcing_method")
    op.drop_column("tiktok_products", "supplier_name")
    op.drop_column("tiktok_products", "supplier_url")
    op.drop_column("tiktok_products", "success_factors")
    op.drop_column("tiktok_products", "success_rating")
    op.drop_column("tiktok_products", "image_search_done")
    op.drop_column("tiktok_products", "image_urls")
    op.drop_column("tiktok_products", "image_url")
