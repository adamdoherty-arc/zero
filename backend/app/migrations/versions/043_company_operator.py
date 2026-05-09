"""Company operator run log.

Persists each Zero Company Operator monitor, overnight work block, report, and
prompt-evaluation bridge run so the dashboard and Reachy can answer what Zero
did while Adam was away.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_operator_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_type", sa.String(40), nullable=False, index=True),
        sa.Column("requested_by", sa.String(100), nullable=False, server_default="scheduler", index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running", index=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("report", JSONB, server_default="{}"),
        sa.Column("actions", JSONB, server_default="[]"),
        sa.Column("errors", JSONB, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )
    op.create_index(
        "idx_company_operator_run_type_created",
        "company_operator_runs",
        ["run_type", "created_at"],
    )
    op.create_index(
        "idx_company_operator_status_created",
        "company_operator_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_company_operator_status_created", table_name="company_operator_runs")
    op.drop_index("idx_company_operator_run_type_created", table_name="company_operator_runs")
    op.drop_table("company_operator_runs")
