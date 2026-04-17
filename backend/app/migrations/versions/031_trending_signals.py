"""Trending signals: release calendar + viral trend ingestion for proactive content.

Adds trending_signals table keyed on source + release_date so Zero can prep
character and media carousels 7-14 days before a Marvel / Netflix / show drop
instead of reacting to its own backlog. Feeds character_discovery and the
media pipeline via linker jobs.

All changes are additive.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "trending_signals" not in existing_tables:
        op.create_table(
            "trending_signals",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("source", sa.String(30), nullable=False, index=True),
            sa.Column("signal_type", sa.String(20), nullable=False, server_default="trending"),
            sa.Column("title", sa.String(300), nullable=False, index=True),
            sa.Column("franchise", sa.String(200), nullable=True),
            sa.Column("universe", sa.String(50), nullable=True),
            sa.Column("media_type", sa.String(20), nullable=True),
            sa.Column("release_date", sa.Date, nullable=True, index=True),
            sa.Column("signal_strength", sa.Float, nullable=False, server_default="50.0"),
            sa.Column("score_reasoning", sa.Text, nullable=True),
            sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("external_id", sa.String(100), nullable=True),
            sa.Column("linked_character_ids", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("linked_media_title_ids", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("triggered_content_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
        )
        op.create_index(
            "idx_signals_source_discovered",
            "trending_signals",
            ["source", "discovered_at"],
        )
        op.create_index(
            "idx_signals_release_window",
            "trending_signals",
            ["release_date", "signal_strength"],
        )
        op.create_index(
            "idx_signals_external_id",
            "trending_signals",
            ["source", "external_id"],
        )


def downgrade() -> None:
    op.drop_index("idx_signals_external_id", table_name="trending_signals")
    op.drop_index("idx_signals_release_window", table_name="trending_signals")
    op.drop_index("idx_signals_source_discovered", table_name="trending_signals")
    op.drop_table("trending_signals")
