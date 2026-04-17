"""Prompt runs: full prompt + response capture with LLM-as-judge grading.

Stores every LLM call made through the instrumented entry points, along with
the variant used, the full system/user prompt, the full response, latency,
tokens, cost, and a Kimi-K2.5-judged quality score. Feeds Thompson Sampling
selection in prompt_evolution_service and the brain's research_depth signal.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "023"
# Linear chain: 021 -> 022 (character_final_review) -> 022a (character_reference_videos) -> 023.
down_revision = "022a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("variant_id", sa.String(64), nullable=True, index=True),
        sa.Column("task_type", sa.String(80), nullable=False, index=True),
        sa.Column("source", sa.String(120), nullable=False, index=True),
        sa.Column("source_id", sa.String(120), nullable=True, index=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("user_prompt", sa.Text, nullable=False),
        sa.Column("rendered_variables", JSONB, server_default="{}"),
        sa.Column("response_text", sa.Text, nullable=True),
        sa.Column("prompt_tokens", sa.Integer, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, server_default="0"),
        sa.Column("latency_ms", sa.Float, server_default="0"),
        sa.Column("cost_usd", sa.Float, server_default="0"),
        sa.Column("success", sa.Boolean, server_default="true", index=True),
        sa.Column("error_type", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("quality_flags", JSONB, server_default="[]"),
        sa.Column("quality_summary", sa.Text, nullable=True),
        sa.Column("grader_model", sa.String(120), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_score", sa.Float, nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    op.create_index("idx_prompt_runs_ungraded", "prompt_runs", ["graded_at", "success"])
    op.create_index("idx_prompt_runs_source_created", "prompt_runs", ["source", "created_at"])
    op.create_index("idx_prompt_runs_task_created", "prompt_runs", ["task_type", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_prompt_runs_task_created", table_name="prompt_runs")
    op.drop_index("idx_prompt_runs_source_created", table_name="prompt_runs")
    op.drop_index("idx_prompt_runs_ungraded", table_name="prompt_runs")
    op.drop_table("prompt_runs")
