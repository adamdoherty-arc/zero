"""Audit-87: codegraph enrichment observability columns on llm_usage.

Mirrors Legion's Alembic 118. Adds 5 columns so every LLM call records
whether codegraph context was injected, how many tokens it added, cache
hit/miss, the enrichment status, and which hints were used. Backs the
LLM Console "enriched vs raw" filter + coverage ratio per source.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column("codegraph_used", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "llm_usage",
        sa.Column("codegraph_tokens_added", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_usage",
        sa.Column("codegraph_cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "llm_usage",
        sa.Column("codegraph_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "llm_usage",
        sa.Column("codegraph_hints_used", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_llm_usage_codegraph", "llm_usage", ["codegraph_used", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_codegraph", table_name="llm_usage")
    op.drop_column("llm_usage", "codegraph_hints_used")
    op.drop_column("llm_usage", "codegraph_status")
    op.drop_column("llm_usage", "codegraph_cache_hit")
    op.drop_column("llm_usage", "codegraph_tokens_added")
    op.drop_column("llm_usage", "codegraph_used")
