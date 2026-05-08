"""Perceptual hash column on character_images for near-duplicate image dedup.

See /zero-character-content plan (Phase 2.1). pHash is stored as a 64-bit
hex string; comparisons use Hamming distance on the binary form. Nullable so
existing rows keep working until backfilled.
"""

from alembic import op
import sqlalchemy as sa


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "character_images" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("character_images")}
        if "phash" not in cols:
            op.add_column(
                "character_images",
                sa.Column("phash", sa.String(32), nullable=True, index=True),
            )

    if "media_images" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("media_images")}
        if "phash" not in cols:
            op.add_column(
                "media_images",
                sa.Column("phash", sa.String(32), nullable=True, index=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "character_images" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("character_images")}
        if "phash" in cols:
            op.drop_column("character_images", "phash")
    if "media_images" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("media_images")}
        if "phash" in cols:
            op.drop_column("media_images", "phash")
