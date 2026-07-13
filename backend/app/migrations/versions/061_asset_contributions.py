"""Add personal→business contribution fields to business_assets.

ADA AI LLC is a disregarded-entity SMLLC: equipment the owner already
possesses enters the business as a capital contribution (not a taxable sale).
The deduction basis for converted personal property is the LESSER of fair
market value at contribution or the owner's original cost (IRS Pub 551/946).
These columns let the asset register model that instead of overloading `cost`:

* acquisition_type        — purchased | contributed
* fmv_at_contribution     — FMV on the transfer date (contributed only)
* original_cost           — what the owner originally paid (basis ceiling)
* contribution_posted_at  — set once the Equity:Owner:Contributions journal
                            entry is written; makes the transfer idempotent.

Nothing here is tax advice; the CPA confirms basis and method at filing.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "business_assets",
        sa.Column("acquisition_type", sa.String(20), nullable=False, server_default="purchased"),
    )
    op.add_column("business_assets", sa.Column("fmv_at_contribution", sa.Float(), nullable=True))
    op.add_column("business_assets", sa.Column("original_cost", sa.Float(), nullable=True))
    op.add_column(
        "business_assets",
        sa.Column("contribution_posted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("business_assets", "contribution_posted_at")
    op.drop_column("business_assets", "original_cost")
    op.drop_column("business_assets", "fmv_at_contribution")
    op.drop_column("business_assets", "acquisition_type")
