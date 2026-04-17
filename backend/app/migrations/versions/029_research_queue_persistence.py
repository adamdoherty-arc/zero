"""Persist research queue state across container restarts.

Adds:
- research_queue_state: lightweight table tracking queue membership and order
  so the research queue auto-resumes on restart instead of starting from scratch.
- characters.research_completed_steps: JSONB array of step names that completed
  in the current research run, enabling per-step skip on resume.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_queue_state",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("character_id", sa.String(64), nullable=False, unique=True),
        sa.Column("queue_position", sa.Integer, nullable=False),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_research_queue_state_queue_position",
        "research_queue_state",
        ["queue_position"],
    )

    op.add_column(
        "characters",
        sa.Column("research_completed_steps", JSONB, server_default="[]", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characters", "research_completed_steps")
    op.drop_index("ix_research_queue_state_queue_position", table_name="research_queue_state")
    op.drop_table("research_queue_state")
