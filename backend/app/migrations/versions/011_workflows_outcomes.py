"""Add visual_workflow_definitions, visual_workflow_executions, and outcome_tracking tables.

Revision ID: 011_workflows_outcomes
Revises: 010_observability_approvals
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "011_workflows_outcomes"
down_revision = "010_observability_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Visual workflow definitions
    op.create_table(
        "visual_workflow_definitions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("nodes", JSONB(), nullable=False),
        sa.Column("edges", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("trigger_type", sa.String(30), nullable=True),
        sa.Column("trigger_config", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_vw_def_status", "visual_workflow_definitions", ["status"])

    # Visual workflow executions
    op.create_table(
        "visual_workflow_executions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(64), sa.ForeignKey("visual_workflow_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("current_node_id", sa.String(64), nullable=True),
        sa.Column("execution_log", JSONB(), nullable=True),
        sa.Column("output", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_vw_exec_workflow", "visual_workflow_executions", ["workflow_id"])
    op.create_index("idx_vw_exec_status", "visual_workflow_executions", ["status"])

    # Outcome tracking
    op.create_table(
        "outcome_tracking",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("action_source", sa.String(50), nullable=False),
        sa.Column("action_id", sa.String(64), nullable=True),
        sa.Column("kpi_type", sa.String(50), nullable=False),
        sa.Column("kpi_value", sa.Float(), nullable=False),
        sa.Column("kpi_unit", sa.String(30), server_default="count", nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_outcome_source", "outcome_tracking", ["action_source"])
    op.create_index("idx_outcome_kpi_type", "outcome_tracking", ["kpi_type"])
    op.create_index("idx_outcome_recorded", "outcome_tracking", ["recorded_at"])
    op.create_index("idx_outcome_source_type", "outcome_tracking", ["action_source", "kpi_type"])


def downgrade() -> None:
    op.drop_index("idx_outcome_source_type", table_name="outcome_tracking")
    op.drop_index("idx_outcome_recorded", table_name="outcome_tracking")
    op.drop_index("idx_outcome_kpi_type", table_name="outcome_tracking")
    op.drop_index("idx_outcome_source", table_name="outcome_tracking")
    op.drop_table("outcome_tracking")

    op.drop_index("idx_vw_exec_status", table_name="visual_workflow_executions")
    op.drop_index("idx_vw_exec_workflow", table_name="visual_workflow_executions")
    op.drop_table("visual_workflow_executions")

    op.drop_index("idx_vw_def_status", table_name="visual_workflow_definitions")
    op.drop_table("visual_workflow_definitions")
