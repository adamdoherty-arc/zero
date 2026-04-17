"""Agent predictions: multi-agent swarm calibration tracking.

Every voting role in content_swarm_service records a prediction before the
carousel is produced + a post-hoc outcome is written back when performance
data arrives. Enables per-agent calibration (predicted vs actual engagement).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_predictions" in inspector.get_table_names():
        return
    op.create_table(
        "agent_predictions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("carousel_id", sa.String(64), nullable=False, index=True),
        sa.Column("content_type", sa.String(20), nullable=False, server_default="character"),
        sa.Column("role_name", sa.String(50), nullable=False, index=True),
        sa.Column("phase", sa.String(20), nullable=False),  # pre_gen | post_gen
        sa.Column("predicted_engagement", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("vote", sa.String(20), nullable=True),  # accept | hold | reject
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column("weight", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("outcome_engagement", sa.Float, nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calibration_error", sa.Float, nullable=True),
    )
    op.create_index("idx_agent_pred_role", "agent_predictions", ["role_name", "created_at"])
    op.create_index("idx_agent_pred_carousel", "agent_predictions", ["carousel_id"])


def downgrade() -> None:
    op.drop_index("idx_agent_pred_carousel", table_name="agent_predictions")
    op.drop_index("idx_agent_pred_role", table_name="agent_predictions")
    op.drop_table("agent_predictions")
