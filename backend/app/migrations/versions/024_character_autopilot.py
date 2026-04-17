"""Character Autopilot: autonomous discovery, gap filling, auto-approval, per-provider budget caps.

Adds:
- characters: autonomous_disabled, priority_tier, discovery_source, discovery_evidence, discovery_hits
- character_carousels: auto_approved, auto_approved_at, auto_approve_reason
- llm_daily_spend: per-provider daily spend table for MiniMax cap enforcement

Note: Base.metadata.create_all on startup also adds these. This migration exists so
alembic history stays correct.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # characters table
    op.add_column("characters", sa.Column("autonomous_disabled", sa.Boolean, server_default=sa.false(), nullable=False))
    op.add_column("characters", sa.Column("priority_tier", sa.String(20), server_default="standard", nullable=False))
    op.add_column("characters", sa.Column("discovery_source", sa.String(50), nullable=True))
    op.add_column("characters", sa.Column("discovery_evidence", JSONB, server_default="{}", nullable=True))
    op.add_column("characters", sa.Column("discovery_hits", sa.Integer, server_default="0", nullable=False))
    op.create_index("idx_characters_priority_tier", "characters", ["priority_tier"])
    op.create_index("idx_characters_discovery_source", "characters", ["discovery_source"])

    # character_carousels table
    op.add_column("character_carousels", sa.Column("auto_approved", sa.Boolean, nullable=True))
    op.add_column("character_carousels", sa.Column("auto_approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("character_carousels", sa.Column("auto_approve_reason", sa.Text, nullable=True))

    # llm_daily_spend table (per-provider budget tracking)
    op.create_table(
        "llm_daily_spend",
        sa.Column("provider", sa.String(50), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("spend_usd", sa.Float, server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("llm_daily_spend")

    op.drop_column("character_carousels", "auto_approve_reason")
    op.drop_column("character_carousels", "auto_approved_at")
    op.drop_column("character_carousels", "auto_approved")

    op.drop_index("idx_characters_discovery_source", table_name="characters")
    op.drop_index("idx_characters_priority_tier", table_name="characters")
    op.drop_column("characters", "discovery_hits")
    op.drop_column("characters", "discovery_evidence")
    op.drop_column("characters", "discovery_source")
    op.drop_column("characters", "priority_tier")
    op.drop_column("characters", "autonomous_disabled")
