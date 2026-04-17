"""Music preview URL: add preview_url column to music_tracks for in-app audio preview.

Adds:
- music_tracks: preview_url (Text, nullable)

Note: Base.metadata.create_all on startup also adds this column. This migration
exists so alembic history stays correct for fresh environments.
"""

from alembic import op
import sqlalchemy as sa


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "music_tracks",
        sa.Column("preview_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("music_tracks", "preview_url")
