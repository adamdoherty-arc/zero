"""Add content_ideas JSONB column to characters table.

Stores per-character content idea pitches that organize existing
and planned content under thematic angles.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("content_ideas", JSONB, server_default="[]", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characters", "content_ideas")
