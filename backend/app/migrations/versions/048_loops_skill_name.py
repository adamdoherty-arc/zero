"""Add skill_name column to loops for cross-link with Legion's skill registry.

Zero's loop registry remains the source of truth for execution (cron, runner,
runner_target). Legion's `skill_definitions` table holds the canonical skill
metadata. The loops.skill_name column is a soft FK by name — no Postgres-level
foreign key because the registries live in different databases.

Loops created by Legion's SkillSyncService set skill_name on creation; manual
loops created via /api/loops/upsert may leave it null.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("loops", sa.Column("skill_name", sa.String(150), nullable=True))
    op.create_index("idx_loops_skill_name", "loops", ["skill_name"])


def downgrade() -> None:
    op.drop_index("idx_loops_skill_name", table_name="loops")
    op.drop_column("loops", "skill_name")
