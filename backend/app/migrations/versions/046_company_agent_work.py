"""Company agent work loop, leases, and questions.

Adds the durable queue state needed for the 24/7 ADA AI LLC company
agents: lightweight task leases to prevent duplicate execution and a
first-class question queue for Adam.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("lease_id", sa.String(64), nullable=True))
    op.add_column("agent_tasks", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_tasks", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_tasks", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_agent_tasks_lease_id", "agent_tasks", ["lease_id"])
    op.create_index("ix_agent_tasks_lease_expires_at", "agent_tasks", ["lease_expires_at"])
    op.create_index("idx_agent_tasks_lease_status", "agent_tasks", ["lease_expires_at", "status"])

    op.create_table(
        "company_agent_questions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", JSONB, nullable=True, server_default="{}"),
        sa.Column("answer_type", sa.String(30), nullable=False, server_default="text"),
        sa.Column("options", JSONB, nullable=True, server_default="[]"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("asked_by_agent", sa.String(64), nullable=False, server_default="ceo"),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("agent_task_id", sa.String(64), nullable=True),
        sa.Column("operator_run_id", sa.String(64), nullable=True),
        sa.Column("source", sa.String(80), nullable=False, server_default="company_agent"),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_company_agent_questions_answer_type", "company_agent_questions", ["answer_type"])
    op.create_index("ix_company_agent_questions_priority", "company_agent_questions", ["priority"])
    op.create_index("ix_company_agent_questions_status", "company_agent_questions", ["status"])
    op.create_index("ix_company_agent_questions_asked_by_agent", "company_agent_questions", ["asked_by_agent"])
    op.create_index("ix_company_agent_questions_task_id", "company_agent_questions", ["task_id"])
    op.create_index("ix_company_agent_questions_agent_task_id", "company_agent_questions", ["agent_task_id"])
    op.create_index("ix_company_agent_questions_operator_run_id", "company_agent_questions", ["operator_run_id"])
    op.create_index("ix_company_agent_questions_source", "company_agent_questions", ["source"])
    op.create_index("ix_company_agent_questions_created_at", "company_agent_questions", ["created_at"])
    op.create_index(
        "idx_company_agent_questions_status_created",
        "company_agent_questions",
        ["status", "created_at"],
    )
    op.create_index(
        "idx_company_agent_questions_task_status",
        "company_agent_questions",
        ["task_id", "status"],
    )
    op.create_index(
        "idx_company_agent_questions_agent_status",
        "company_agent_questions",
        ["asked_by_agent", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_company_agent_questions_agent_status", table_name="company_agent_questions")
    op.drop_index("idx_company_agent_questions_task_status", table_name="company_agent_questions")
    op.drop_index("idx_company_agent_questions_status_created", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_created_at", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_source", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_operator_run_id", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_agent_task_id", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_task_id", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_asked_by_agent", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_status", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_priority", table_name="company_agent_questions")
    op.drop_index("ix_company_agent_questions_answer_type", table_name="company_agent_questions")
    op.drop_table("company_agent_questions")

    op.drop_index("idx_agent_tasks_lease_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_lease_expires_at", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_lease_id", table_name="agent_tasks")
    op.drop_column("agent_tasks", "last_heartbeat_at")
    op.drop_column("agent_tasks", "attempt_count")
    op.drop_column("agent_tasks", "lease_expires_at")
    op.drop_column("agent_tasks", "lease_id")
