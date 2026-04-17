"""Character carousel versions: snapshots + revert for carousel edits.

Adds:
- character_carousel_versions: stores full snapshots of mutable carousel fields
  every time they change (manual_edit, enhance, council_vote, restore, backfill).
  Enables undo/redo and history UI.
- character_carousels.current_version_id: pointer to the latest version row
  for fast head lookups.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: tables/columns may have been pre-created by
    # Base.metadata.create_all on startup. Only apply what's missing.
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "character_carousel_versions" not in inspector.get_table_names():
        op.create_table(
            "character_carousel_versions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("carousel_id", sa.String(64), sa.ForeignKey("character_carousels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_number", sa.Integer, nullable=False),
            sa.Column("parent_version_id", sa.String(64), nullable=True),
            # Snapshot fields
            sa.Column("title", sa.String(300), nullable=True),
            sa.Column("hook_text", sa.Text, nullable=True),
            sa.Column("slides", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("caption", sa.Text, nullable=True),
            sa.Column("hashtags", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("human_notes", sa.Text, nullable=True),
            sa.Column("music_track", postgresql.JSONB, nullable=True),
            sa.Column("text_overlay_specs", postgresql.JSONB, nullable=False, server_default="[]"),
            # Provenance
            sa.Column("source", sa.String(30), nullable=False),
            sa.Column("source_metadata", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    existing_indexes = {
        ix["name"]
        for ix in inspector.get_indexes("character_carousel_versions")
    } if "character_carousel_versions" in inspector.get_table_names() else set()

    if "ix_carousel_versions_carousel_version" not in existing_indexes:
        op.create_index(
            "ix_carousel_versions_carousel_version",
            "character_carousel_versions",
            ["carousel_id", "version_number"],
            unique=True,
        )
    if "ix_carousel_versions_created_at" not in existing_indexes:
        op.create_index(
            "ix_carousel_versions_created_at",
            "character_carousel_versions",
            ["created_at"],
        )

    carousel_cols = {c["name"] for c in inspector.get_columns("character_carousels")}
    if "current_version_id" not in carousel_cols:
        op.add_column(
            "character_carousels",
            sa.Column("current_version_id", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("character_carousels", "current_version_id")
    op.drop_index("ix_carousel_versions_created_at", table_name="character_carousel_versions")
    op.drop_index("ix_carousel_versions_carousel_version", table_name="character_carousel_versions")
    op.drop_table("character_carousel_versions")
