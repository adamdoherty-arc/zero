"""Loops framework: registry + variants + runs + learnings + promotions.

Implements the cross-project self-improvement loop substrate. Zero is the
orchestrator and source of truth; Legion holds an immutable mirror (added in
its own revision under C:\\code\\Legion later).

Tables created:
- loops              registry of which skills/prompts run on cadence
- loop_variants      A/B variant pool per loop (canary + active)
- loop_runs          immutable run history with judge scores
- loop_learnings     cross-project learnings emitted by skills
- loop_promotions    audit trail for canary->active flips and rollbacks
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "loops",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("owner_project", sa.String(20), nullable=False),
        sa.Column("runner_kind", sa.String(30), nullable=False),
        sa.Column("runner_target", sa.Text(), nullable=False),
        sa.Column("cron", sa.String(80), nullable=False, server_default="manual"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sandbox_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("judge_tier", sa.String(20), nullable=False, server_default="local"),
        sa.Column("auto_promote_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("current_variant_id", sa.Integer(), nullable=True),
        sa.Column("baseline_score", sa.Float(), nullable=True),
        sa.Column("consecutive_regressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_token_budget", sa.Integer(), nullable=False, server_default="200000"),
        sa.Column("daily_run_cap", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("wall_clock_budget_s", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("last_run_id", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_loops_due",
        "loops",
        ["enabled", "next_due_at"],
        postgresql_where=sa.text("enabled = true"),
    )
    op.create_index("idx_loops_owner", "loops", ["owner_project"])

    op.create_table(
        "loop_variants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("loop_id", sa.Integer(), sa.ForeignKey("loops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("loop_variants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("variant_label", sa.String(120), nullable=False),
        sa.Column("payload_kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_canary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("canary_traffic_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_variants_loop_active", "loop_variants", ["loop_id", "is_active"])

    op.create_foreign_key(
        "fk_loops_current_variant",
        "loops",
        "loop_variants",
        ["current_variant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "loop_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("loop_id", sa.Integer(), sa.ForeignKey("loops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.Integer(), sa.ForeignKey("loop_variants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("runner_kind", sa.String(30), nullable=False),
        sa.Column("runner_id", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("judge_score", sa.Float(), nullable=True),
        sa.Column("judge_notes", sa.Text(), nullable=True),
        sa.Column("vault_path", sa.Text(), nullable=True),
        sa.Column("legion_run_id", sa.Integer(), nullable=True),
        sa.Column("cost_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_loop_runs_loop_started", "loop_runs", ["loop_id", sa.text("started_at DESC")])
    op.create_index("idx_loop_runs_variant", "loop_runs", ["variant_id"])
    op.create_index("idx_loop_runs_status", "loop_runs", ["status"])

    op.create_table(
        "loop_learnings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("loop_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_project", sa.String(20), nullable=False),
        sa.Column("pattern_kind", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("applied_to", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_learnings_kind", "loop_learnings", ["pattern_kind"])
    op.create_index("idx_learnings_source", "loop_learnings", ["source_project"])

    op.create_table(
        "loop_promotions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("loop_id", sa.Integer(), sa.ForeignKey("loops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_variant_id", sa.Integer(), sa.ForeignKey("loop_variants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_variant_id", sa.Integer(), sa.ForeignKey("loop_variants.id", ondelete="SET NULL"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_by", sa.String(80), nullable=False, server_default="auto"),
    )
    op.create_index("idx_promotions_loop", "loop_promotions", ["loop_id", sa.text("decided_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_promotions_loop", table_name="loop_promotions")
    op.drop_table("loop_promotions")

    op.drop_index("idx_learnings_source", table_name="loop_learnings")
    op.drop_index("idx_learnings_kind", table_name="loop_learnings")
    op.drop_table("loop_learnings")

    op.drop_index("idx_loop_runs_status", table_name="loop_runs")
    op.drop_index("idx_loop_runs_variant", table_name="loop_runs")
    op.drop_index("idx_loop_runs_loop_started", table_name="loop_runs")
    op.drop_table("loop_runs")

    op.drop_constraint("fk_loops_current_variant", "loops", type_="foreignkey")
    op.drop_index("idx_variants_loop_active", table_name="loop_variants")
    op.drop_table("loop_variants")

    op.drop_index("idx_loops_owner", table_name="loops")
    op.drop_index("idx_loops_due", table_name="loops")
    op.drop_table("loops")
