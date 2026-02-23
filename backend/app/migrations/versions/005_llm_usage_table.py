"""Add llm_usage tracking table.

Revision ID: 005_llm_usage
Revises: 004_product_enrichment
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa

revision = "005_llm_usage"
down_revision = "004_product_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("latency_ms", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("success", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_provider", "llm_usage", ["provider"])
    op.create_index("ix_llm_usage_task_type", "llm_usage", ["task_type"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])
    op.create_index("ix_llm_usage_provider_date", "llm_usage", ["provider", "created_at"])
    op.create_index("ix_llm_usage_task_provider", "llm_usage", ["task_type", "provider"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_task_provider", table_name="llm_usage")
    op.drop_index("ix_llm_usage_provider_date", table_name="llm_usage")
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_task_type", table_name="llm_usage")
    op.drop_index("ix_llm_usage_provider", table_name="llm_usage")
    op.drop_table("llm_usage")
