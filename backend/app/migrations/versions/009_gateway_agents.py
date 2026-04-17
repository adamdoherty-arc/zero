"""Add gateway_agent_configs table.

Revision ID: 009_gateway_agents
Revises: 008_orchestrator_traces
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

revision = "009_gateway_agents"
down_revision = "008_orchestrator_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_agent_configs",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("role", sa.String(30), server_default="general", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("routes", ARRAY(sa.Text()), nullable=True),
        sa.Column("channels", ARRAY(sa.Text()), nullable=True),
        sa.Column("model_override", sa.String(100), nullable=True),
        sa.Column("system_prompt_override", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), server_default="0.7", nullable=False),
        sa.Column("proactive_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("proactive_triggers", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gw_agent_role", "gateway_agent_configs", ["role"])
    op.create_index("ix_gw_agent_enabled", "gateway_agent_configs", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_gw_agent_enabled", table_name="gateway_agent_configs")
    op.drop_index("ix_gw_agent_role", table_name="gateway_agent_configs")
    op.drop_table("gateway_agent_configs")
