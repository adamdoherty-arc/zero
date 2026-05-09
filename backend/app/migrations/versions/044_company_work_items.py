"""Company work item fields and audit events.

Adds the richer task-management properties used by Zero Company OS while
keeping the existing generic tasks table as the canonical work-item store.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("domain", sa.String(80), nullable=True))
    op.add_column("tasks", sa.Column("owner_agent", sa.String(100), nullable=True))
    op.add_column("tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("risk_level", sa.String(20), nullable=False, server_default="medium"))
    op.add_column("tasks", sa.Column("approval_state", sa.String(20), nullable=False, server_default="none"))
    op.add_column("tasks", sa.Column("approval_id", sa.String(64), nullable=True))
    op.add_column("tasks", sa.Column("tags", ARRAY(sa.Text()), nullable=True, server_default="{}"))
    op.add_column("tasks", sa.Column("links", JSONB, nullable=True, server_default="[]"))
    op.add_column("tasks", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("estimate_points", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("parent_task_id", sa.String(64), nullable=True))

    op.create_index("ix_tasks_domain", "tasks", ["domain"])
    op.create_index("ix_tasks_owner_agent", "tasks", ["owner_agent"])
    op.create_index("ix_tasks_due_at", "tasks", ["due_at"])
    op.create_index("ix_tasks_scheduled_for", "tasks", ["scheduled_for"])
    op.create_index("ix_tasks_risk_level", "tasks", ["risk_level"])
    op.create_index("ix_tasks_approval_state", "tasks", ["approval_state"])
    op.create_index("ix_tasks_approval_id", "tasks", ["approval_id"])
    op.create_index("ix_tasks_sort_order", "tasks", ["sort_order"])
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    op.create_index("idx_tasks_project_status_sort", "tasks", ["project_id", "status", "sort_order"])
    op.create_index("idx_tasks_project_domain_status", "tasks", ["project_id", "domain", "status"])
    op.create_index("idx_tasks_project_due", "tasks", ["project_id", "due_at"])

    op.create_table(
        "company_task_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False, server_default="system"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("before", JSONB, nullable=True, server_default="{}"),
        sa.Column("after", JSONB, nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_company_task_events_task_id", "company_task_events", ["task_id"])
    op.create_index("ix_company_task_events_event_type", "company_task_events", ["event_type"])
    op.create_index("ix_company_task_events_actor", "company_task_events", ["actor"])
    op.create_index("ix_company_task_events_created_at", "company_task_events", ["created_at"])
    op.create_index("idx_company_task_events_task_created", "company_task_events", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_company_task_events_task_created", table_name="company_task_events")
    op.drop_index("ix_company_task_events_created_at", table_name="company_task_events")
    op.drop_index("ix_company_task_events_actor", table_name="company_task_events")
    op.drop_index("ix_company_task_events_event_type", table_name="company_task_events")
    op.drop_index("ix_company_task_events_task_id", table_name="company_task_events")
    op.drop_table("company_task_events")

    op.drop_index("idx_tasks_project_due", table_name="tasks")
    op.drop_index("idx_tasks_project_domain_status", table_name="tasks")
    op.drop_index("idx_tasks_project_status_sort", table_name="tasks")
    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    op.drop_index("ix_tasks_sort_order", table_name="tasks")
    op.drop_index("ix_tasks_approval_id", table_name="tasks")
    op.drop_index("ix_tasks_approval_state", table_name="tasks")
    op.drop_index("ix_tasks_risk_level", table_name="tasks")
    op.drop_index("ix_tasks_scheduled_for", table_name="tasks")
    op.drop_index("ix_tasks_due_at", table_name="tasks")
    op.drop_index("ix_tasks_owner_agent", table_name="tasks")
    op.drop_index("ix_tasks_domain", table_name="tasks")

    for column in (
        "parent_task_id",
        "estimate_points",
        "sort_order",
        "links",
        "tags",
        "approval_id",
        "approval_state",
        "risk_level",
        "scheduled_for",
        "due_at",
        "owner_agent",
        "domain",
    ):
        op.drop_column("tasks", column)
