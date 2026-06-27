"""Add business_assets register (hardware / equipment / Section 179).

ADA AI LLC capital-asset register. Each row is a piece of equipment bought or
transferred into the business: cost, business-use %, placed-in-service date, and
the depreciation/expensing method. The asset service derives a current-year
deduction estimate from these for the consolidated tax-savings summary.

This replaces the previously-static `assets` array the Finance tab rendered.
Nothing here is tax advice; the CPA elects §179 vs MACRS at filing.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_assets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("asset_type", sa.String(80), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("business_use_pct", sa.Float(), nullable=False, server_default=sa.text("100")),
        sa.Column("placed_in_service", sa.Date(), nullable=True),
        # section_179 | de_minimis | macrs_5yr | none
        sa.Column("method", sa.String(40), nullable=False, server_default="section_179"),
        sa.Column("disposed_at", sa.Date(), nullable=True),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("business_assets_placed_idx", "business_assets", ["placed_in_service"])


def downgrade() -> None:
    op.drop_index("business_assets_placed_idx", table_name="business_assets")
    op.drop_table("business_assets")
