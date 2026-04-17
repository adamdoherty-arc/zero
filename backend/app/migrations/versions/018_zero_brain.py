"""Zero Brain: episodic memory, outcome learning, prompt evolution, benchmarks, experiments.

Creates tables for the autonomous learning employee system.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from pgvector.sqlalchemy import Vector


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Episodic Memories
    op.create_table(
        "episodic_memories",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("namespace", sa.String(50), nullable=False, server_default="general", index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False, index=True),
        sa.Column("source_id", sa.String(64)),
        sa.Column("importance", sa.Float, server_default="50.0"),
        sa.Column("tags", ARRAY(sa.Text), server_default="{}"),
        sa.Column("context", JSONB, server_default="{}"),
        sa.Column("embedding", Vector(768)),
        sa.Column("expires_at", sa.DateTime(timezone=True), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_episodic_importance", "episodic_memories", ["importance"])

    # 2. Brain Outcome Records
    op.create_table(
        "brain_outcome_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("domain", sa.String(30), nullable=False, index=True),
        sa.Column("action_type", sa.String(50), nullable=False, index=True),
        sa.Column("action_id", sa.String(64)),
        sa.Column("strategy_used", sa.String(100), index=True),
        sa.Column("predicted_score", sa.Float),
        sa.Column("actual_score", sa.Float),
        sa.Column("metrics", JSONB, server_default="{}"),
        sa.Column("learnings", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 3. Prompt Variants
    op.create_table(
        "prompt_variants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_type", sa.String(50), nullable=False, index=True),
        sa.Column("variant_name", sa.String(200), nullable=False),
        sa.Column("prompt_template", sa.Text, nullable=False),
        sa.Column("parameters", JSONB, server_default="{}"),
        sa.Column("success_count", sa.Integer, server_default="0"),
        sa.Column("failure_count", sa.Integer, server_default="0"),
        sa.Column("total_uses", sa.Integer, server_default="0"),
        sa.Column("avg_score", sa.Float, server_default="50.0"),
        sa.Column("is_active", sa.Boolean, server_default="true", index=True),
        sa.Column("is_baseline", sa.Boolean, server_default="false"),
        sa.Column("parent_id", sa.String(64)),
        sa.Column("generation", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_prompt_score", "prompt_variants", ["avg_score"])

    # 4. Benchmark Scores (current)
    op.create_table(
        "benchmark_scores",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("dimension", sa.String(50), nullable=False, index=True),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("details", JSONB, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 5. Benchmark History (snapshots)
    op.create_table(
        "benchmark_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("overall_score", sa.Float, nullable=False),
        sa.Column("dimension_scores", JSONB, nullable=False),
        sa.Column("weakest_dimension", sa.String(50)),
        sa.Column("improvement_action", sa.Text),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    # 6. Learning Cycles
    op.create_table(
        "learning_cycles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("cycle_type", sa.String(30), nullable=False, index=True),
        sa.Column("status", sa.String(20), server_default="running"),
        sa.Column("input_data", JSONB, server_default="{}"),
        sa.Column("results", JSONB, server_default="{}"),
        sa.Column("improvements", JSONB, server_default="[]"),
        sa.Column("cost_usd", sa.Float, server_default="0.0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
    )

    # 7. Content Experiments (A/B tests)
    op.create_table(
        "content_experiments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("hypothesis", sa.Text, nullable=False),
        sa.Column("experiment_type", sa.String(30), nullable=False, index=True),
        sa.Column("control_config", JSONB, nullable=False),
        sa.Column("variant_config", JSONB, nullable=False),
        sa.Column("status", sa.String(20), server_default="active", index=True),
        sa.Column("sample_size_target", sa.Integer, server_default="10"),
        sa.Column("control_results", JSONB, server_default="[]"),
        sa.Column("variant_results", JSONB, server_default="[]"),
        sa.Column("conclusion", sa.Text),
        sa.Column("winner", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("content_experiments")
    op.drop_table("learning_cycles")
    op.drop_table("benchmark_history")
    op.drop_table("benchmark_scores")
    op.drop_table("prompt_variants")
    op.drop_table("brain_outcome_records")
    op.drop_table("episodic_memories")
