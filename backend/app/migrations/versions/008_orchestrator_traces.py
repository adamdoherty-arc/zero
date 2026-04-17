"""Add orchestrator conversations and traces tables.

Revision ID: 008_orchestrator_traces
Revises: 007_image_validation
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "008_orchestrator_traces"
down_revision = "007_image_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Conversations table
    op.create_table(
        "orchestrator_conversations",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("channel", sa.String(30), server_default="api", nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("route", sa.String(30), nullable=True),
        sa.Column("route_method", sa.String(30), nullable=True),
        sa.Column("route_confidence", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orch_conv_thread_id", "orchestrator_conversations", ["thread_id"])
    op.create_index("ix_orch_conv_created_at", "orchestrator_conversations", ["created_at"])
    op.create_index("ix_orch_conv_route", "orchestrator_conversations", ["route"])
    op.create_index("idx_orch_conv_thread_created", "orchestrator_conversations", ["thread_id", "created_at"])
    op.create_index("idx_orch_conv_channel", "orchestrator_conversations", ["channel"])

    # Traces table
    op.create_table(
        "orchestrator_traces",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), sa.ForeignKey("orchestrator_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column("node_name", sa.String(50), nullable=False),
        sa.Column("node_order", sa.Integer(), nullable=False),
        sa.Column("input_data", JSONB(), nullable=True),
        sa.Column("output_data", JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_orch_trace_conv", "orchestrator_traces", ["conversation_id"])
    op.create_index("ix_orch_trace_thread_id", "orchestrator_traces", ["thread_id"])
    op.create_index("ix_orch_trace_node_name", "orchestrator_traces", ["node_name"])
    op.create_index("idx_orch_trace_node_time", "orchestrator_traces", ["node_name", "started_at"])


def downgrade() -> None:
    op.drop_index("idx_orch_trace_node_time", table_name="orchestrator_traces")
    op.drop_index("ix_orch_trace_node_name", table_name="orchestrator_traces")
    op.drop_index("ix_orch_trace_thread_id", table_name="orchestrator_traces")
    op.drop_index("idx_orch_trace_conv", table_name="orchestrator_traces")
    op.drop_table("orchestrator_traces")

    op.drop_index("idx_orch_conv_channel", table_name="orchestrator_conversations")
    op.drop_index("idx_orch_conv_thread_created", table_name="orchestrator_conversations")
    op.drop_index("ix_orch_conv_route", table_name="orchestrator_conversations")
    op.drop_index("ix_orch_conv_created_at", table_name="orchestrator_conversations")
    op.drop_index("ix_orch_conv_thread_id", table_name="orchestrator_conversations")
    op.drop_table("orchestrator_conversations")
