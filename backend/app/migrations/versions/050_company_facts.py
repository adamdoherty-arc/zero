"""Add company_facts KV registry + tasks.completion_outputs JSONB.

company_facts persists structured outputs captured at task completion time
(e.g. the actual EIN number, Florida document number, bank account last four).
The registry is the canonical "company definition" surface: a queryable
key/value store keyed back to the source task that produced each fact.

tasks.completion_outputs is the per-task JSONB blob preserving the full set of
outputs + free-text note recorded at completion, even if individual facts get
later edited, redacted, or deleted from the registry.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_facts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(80), nullable=True),
        sa.Column("source_task_id", sa.String(64), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="task_completion"),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("company_facts_key_unique", "company_facts", ["key"], unique=True)
    op.create_index("company_facts_domain_idx", "company_facts", ["domain"])
    op.create_index("company_facts_source_task_idx", "company_facts", ["source_task_id"])

    op.add_column(
        "tasks",
        sa.Column("completion_outputs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("tasks", "completion_outputs")
    op.drop_index("company_facts_source_task_idx", table_name="company_facts")
    op.drop_index("company_facts_domain_idx", table_name="company_facts")
    op.drop_index("company_facts_key_unique", table_name="company_facts")
    op.drop_table("company_facts")
