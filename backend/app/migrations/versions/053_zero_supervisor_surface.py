"""Zero Supervisor Surface — zero_runs + zero_run_events + zero_critic_reviews.

Backs /api/zero/run/* + /api/zero/critic/* + /api/zero/stack-facts. Mirrors
Legion's Migration 103 and ADA's 20260612_ada_supervisor_surface so the three
supervisors share an event vocabulary. Sprint state still lives in Legion at
:8005 project_id=7 — these tables capture the supervisor's per-run gate
events + clean-context critic reviews ONLY.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zero_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=False), nullable=False, unique=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("robot_state", sa.String(20), nullable=True),
        sa.Column("dnd", sa.Boolean(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("metrics", JSONB(), nullable=True),
        sa.Column("supervisor_version", sa.String(40), nullable=True),
    )
    op.create_index("ix_zero_runs_run_id", "zero_runs", ["run_id"])
    op.create_index("ix_zero_runs_status_started", "zero_runs", ["status", "started_at"])

    op.create_table(
        "zero_run_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=False), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("phase", sa.String(40), nullable=True),
        sa.Column("event", sa.String(80), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("metrics", JSONB(), nullable=True),
        sa.Column("links", JSONB(), nullable=True),
        sa.Column("robot_state", sa.String(20), nullable=True),
        sa.Column("dnd", sa.Boolean(), nullable=True),
        sa.Column("partition", sa.String(20), nullable=True),
        sa.Column("approval_record_id", sa.String(120), nullable=True),
        sa.Column("vault_audit_id", sa.String(120), nullable=True),
        sa.Column("salience", sa.Float(), nullable=True),
        sa.Column("delegation_target", sa.String(20), nullable=True),
        sa.Column("legion_sprint_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_zero_run_events_run_id_ts", "zero_run_events", ["run_id", "ts"])
    op.create_index("ix_zero_run_events_event_ts", "zero_run_events", ["event", "ts"])
    op.create_index("ix_zero_run_events_phase", "zero_run_events", ["phase"])

    op.create_table(
        "zero_critic_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=False), nullable=True),
        sa.Column("legion_sprint_id", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("files_reviewed", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ac_extracted", sa.Text(), nullable=True),
        sa.Column("critic_prompt", sa.Text(), nullable=False),
        sa.Column("critique_text", sa.Text(), nullable=True),
        sa.Column("scores", JSONB(), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("reject_reasons", JSONB(), nullable=True),
        sa.Column("model_used", sa.String(80), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_zero_critic_reviews_sprint_round", "zero_critic_reviews", ["legion_sprint_id", "round"])
    op.create_index("ix_zero_critic_reviews_run_verdict", "zero_critic_reviews", ["run_id", "verdict"])
    op.create_index("ix_zero_critic_reviews_verdict", "zero_critic_reviews", ["verdict"])


def downgrade() -> None:
    op.drop_index("ix_zero_critic_reviews_verdict", table_name="zero_critic_reviews")
    op.drop_index("ix_zero_critic_reviews_run_verdict", table_name="zero_critic_reviews")
    op.drop_index("ix_zero_critic_reviews_sprint_round", table_name="zero_critic_reviews")
    op.drop_table("zero_critic_reviews")

    op.drop_index("ix_zero_run_events_phase", table_name="zero_run_events")
    op.drop_index("ix_zero_run_events_event_ts", table_name="zero_run_events")
    op.drop_index("ix_zero_run_events_run_id_ts", table_name="zero_run_events")
    op.drop_table("zero_run_events")

    op.drop_index("ix_zero_runs_status_started", table_name="zero_runs")
    op.drop_index("ix_zero_runs_run_id", table_name="zero_runs")
    op.drop_table("zero_runs")
