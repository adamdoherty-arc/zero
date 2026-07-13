"""Drop reachy_sequences table.

Robot/Reachy hardware control moved to a separate app (Zero Studio).
The reachy_sequences table backed the Cockpit's custom motion-sequence
builder, which no longer exists in Zero. Migration 038 is left in place
as history; this migration reverses it.

Note: in practice this table was created by SQLAlchemy's create_all()
(the ORM model, since create_all runs before alembic on Zero's startup)
rather than by migration 038's raw DDL, so its unique index carries
SQLAlchemy's default name (``ix_reachy_sequences_name``) rather than
038's explicit ``uq_reachy_sequences_name``. DROP TABLE cascades to
whichever index actually exists, so we don't need to guess the name.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if "reachy_sequences" in _tables(bind):
        op.drop_table("reachy_sequences")


def downgrade() -> None:
    bind = op.get_bind()
    if "reachy_sequences" not in _tables(bind):
        import sqlalchemy as sa_
        from sqlalchemy.dialects import postgresql as pg

        op.create_table(
            "reachy_sequences",
            sa_.Column("id", sa_.BigInteger, primary_key=True, autoincrement=True),
            sa_.Column("name", sa_.String(128), nullable=False),
            sa_.Column("description", sa_.Text, nullable=True),
            sa_.Column("steps", pg.JSONB, nullable=False, server_default="[]"),
            sa_.Column("aliases", pg.JSONB, nullable=False, server_default="[]"),
            sa_.Column(
                "created_at",
                sa_.DateTime(timezone=True),
                server_default=sa_.func.now(),
                nullable=False,
            ),
            sa_.Column(
                "updated_at",
                sa_.DateTime(timezone=True),
                server_default=sa_.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "uq_reachy_sequences_name",
            "reachy_sequences",
            ["name"],
            unique=True,
        )
