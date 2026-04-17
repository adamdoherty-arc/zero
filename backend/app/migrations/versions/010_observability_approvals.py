"""Add observability_spans and approval_requests tables.

Revision ID: 010_observability_approvals
Revises: 009_gateway_agents
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "010_observability_approvals"
down_revision = "009_gateway_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Observability spans
    op.create_table(
        "observability_spans",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("parent_span_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("span_type", sa.String(30), nullable=False),
        sa.Column("input_data", JSONB(), nullable=True),
        sa.Column("output_data", JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_obs_span_trace", "observability_spans", ["trace_id"])
    op.create_index("idx_obs_span_parent", "observability_spans", ["parent_span_id"])
    op.create_index("idx_obs_span_type_time", "observability_spans", ["span_type", "started_at"])

    # Approval requests
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("request_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("context_data", JSONB(), nullable=True),
        sa.Column("initiated_by", sa.String(50), server_default="system", nullable=False),
        sa.Column("route", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("decision_by", sa.String(50), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_action_on_expiry", sa.String(20), server_default="reject", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_approval_type", "approval_requests", ["request_type"])
    op.create_index("idx_approval_status", "approval_requests", ["status"])
    op.create_index("idx_approval_expires", "approval_requests", ["expires_at"])
    op.create_index("idx_approval_status_created", "approval_requests", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_approval_status_created", table_name="approval_requests")
    op.drop_index("idx_approval_expires", table_name="approval_requests")
    op.drop_index("idx_approval_status", table_name="approval_requests")
    op.drop_index("idx_approval_type", table_name="approval_requests")
    op.drop_table("approval_requests")

    op.drop_index("idx_obs_span_type_time", table_name="observability_spans")
    op.drop_index("idx_obs_span_parent", table_name="observability_spans")
    op.drop_index("idx_obs_span_trace", table_name="observability_spans")
    op.drop_table("observability_spans")
