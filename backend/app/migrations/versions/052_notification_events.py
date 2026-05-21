"""Add notification_events table for Enhancement-11 persistence.

The in-memory notification_bus has a 50-entry ring buffer that evaporates
every zero-api restart. The Meeting Steward status card and the live
notification feed both look stale because of it. This migration adds a
durable backing table so recent events survive restarts and the steward
can still answer "what alarms fired in the last hour" after a deploy.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(120), nullable=False),
        sa.Column("source", sa.String(120), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notification_events_created_at", "notification_events", ["created_at"])
    op.create_index("ix_notification_events_type", "notification_events", ["type"])


def downgrade() -> None:
    op.drop_index("ix_notification_events_type", table_name="notification_events")
    op.drop_index("ix_notification_events_created_at", table_name="notification_events")
    op.drop_table("notification_events")
