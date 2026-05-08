"""Reachy custom motion sequences.

Adds ``reachy_sequences`` table: user-defined chains of emotion/dance clips
with optional inter-step gaps and aliases. Sequences become first-class
motion library entries — resolvable by ``reachy_motion_library.resolve_motion``
so the LLM can invoke them via ``[emotion:my_sequence]`` just like any
hardcoded clip.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if "reachy_sequences" in _tables(bind):
        return

    op.create_table(
        "reachy_sequences",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("steps", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("aliases", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_reachy_sequences_name",
        "reachy_sequences",
        ["name"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "reachy_sequences" in _tables(bind):
        op.drop_index("uq_reachy_sequences_name", table_name="reachy_sequences")
        op.drop_table("reachy_sequences")
