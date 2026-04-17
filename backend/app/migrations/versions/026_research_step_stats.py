"""Character research step stats: persist per-step durations for ETA computation.

Adds:
- character_research_step_stats: tracks every completed/failed step across jobs
  so we can compute running averages (avg, p50, p95) per step_name and surface
  accurate ETAs on the research queue UI.
"""

from alembic import op
import sqlalchemy as sa


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "character_research_step_stats",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("character_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("step_name", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_research_step_stats_step_name",
        "character_research_step_stats",
        ["step_name"],
    )
    op.create_index(
        "ix_research_step_stats_character_id",
        "character_research_step_stats",
        ["character_id"],
    )
    op.create_index(
        "ix_research_step_stats_created_at",
        "character_research_step_stats",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_step_stats_created_at", table_name="character_research_step_stats")
    op.drop_index("ix_research_step_stats_character_id", table_name="character_research_step_stats")
    op.drop_index("ix_research_step_stats_step_name", table_name="character_research_step_stats")
    op.drop_table("character_research_step_stats")
