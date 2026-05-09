"""Company work item review packets.

Stores the latest 0-100 dashboard review and enrichment packet for each
Company OS work item.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_work_item_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False, unique=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recommendation", sa.String(40), nullable=False, server_default="keep"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("missing_info", JSONB, nullable=True, server_default="[]"),
        sa.Column("action_steps", JSONB, nullable=True, server_default="[]"),
        sa.Column("acceptance_criteria", JSONB, nullable=True, server_default="[]"),
        sa.Column("automation_plan", JSONB, nullable=True, server_default="{}"),
        sa.Column("source_links", JSONB, nullable=True, server_default="[]"),
        sa.Column("reviewed_by", sa.String(100), nullable=False, server_default="zero-company-operator"),
        sa.Column("operator_run_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_company_work_item_reviews_task_id", "company_work_item_reviews", ["task_id"])
    op.create_index("ix_company_work_item_reviews_score", "company_work_item_reviews", ["score"])
    op.create_index("ix_company_work_item_reviews_recommendation", "company_work_item_reviews", ["recommendation"])
    op.create_index("ix_company_work_item_reviews_reviewed_by", "company_work_item_reviews", ["reviewed_by"])
    op.create_index("ix_company_work_item_reviews_operator_run_id", "company_work_item_reviews", ["operator_run_id"])
    op.create_index("ix_company_work_item_reviews_created_at", "company_work_item_reviews", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_company_work_item_reviews_created_at", table_name="company_work_item_reviews")
    op.drop_index("ix_company_work_item_reviews_operator_run_id", table_name="company_work_item_reviews")
    op.drop_index("ix_company_work_item_reviews_reviewed_by", table_name="company_work_item_reviews")
    op.drop_index("ix_company_work_item_reviews_recommendation", table_name="company_work_item_reviews")
    op.drop_index("ix_company_work_item_reviews_score", table_name="company_work_item_reviews")
    op.drop_index("ix_company_work_item_reviews_task_id", table_name="company_work_item_reviews")
    op.drop_table("company_work_item_reviews")
