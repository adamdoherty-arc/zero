"""Add walkthrough + completion_review JSONB to company_work_item_reviews.

walkthrough holds the structured "how to actually do this task" guide
(prerequisites, steps with URLs and field-by-field instructions, evidence to
archive, what this unlocks). It is attached during dashboard review so the
task detail drawer can render the walkthrough inline.

completion_review holds the post-completion LLM verdict: follow-up tasks Zero
recommends, infrastructure suggestions for the command center, and a confidence
score that the task was actually completed correctly.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_work_item_reviews",
        sa.Column("walkthrough", JSONB, nullable=True),
    )
    op.add_column(
        "company_work_item_reviews",
        sa.Column("completion_review", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company_work_item_reviews", "completion_review")
    op.drop_column("company_work_item_reviews", "walkthrough")
