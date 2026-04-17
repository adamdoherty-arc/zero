"""Add blocked_image_urls to characters and unique constraint on character_images.

Enables per-character image blocklist so deleted images are not re-imported,
and prevents duplicate (character_id, url) rows in character_images.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add blocklist column to characters
    op.add_column(
        "characters",
        sa.Column("blocked_image_urls", JSONB, server_default="[]"),
    )

    # Remove duplicate (character_id, url) rows before adding unique constraint.
    # Keep the row with the earliest created_at for each pair.
    op.execute("""
        DELETE FROM character_images a
        USING character_images b
        WHERE a.character_id = b.character_id
          AND a.url = b.url
          AND a.created_at > b.created_at
    """)

    # Add unique constraint to prevent future duplicates
    op.create_unique_constraint(
        "uq_character_image_url",
        "character_images",
        ["character_id", "url"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_character_image_url", "character_images", type_="unique")
    op.drop_column("characters", "blocked_image_urls")
