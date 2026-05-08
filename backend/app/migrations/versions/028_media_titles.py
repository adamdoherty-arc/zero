"""TV & Movie content: media_titles, character_media_titles, media_images,
media_research_fragments tables. Adds content_type + media_title_id to
character_carousels and makes character_id nullable.

All changes are additive. Existing character carousel data is unaffected
(content_type defaults to 'character', character_id keeps its existing value).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # --- media_titles ---
    if "media_titles" not in existing_tables:
        op.create_table(
            "media_titles",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("media_type", sa.String(20), nullable=False, index=True),
            sa.Column("title", sa.String(300), nullable=False, index=True),
            sa.Column("year", sa.Integer, nullable=True),
            sa.Column("end_year", sa.Integer, nullable=True),
            sa.Column("genre", postgresql.ARRAY(sa.Text), nullable=True, server_default="{}"),
            sa.Column("franchise", sa.String(200), nullable=True),
            sa.Column("universe", sa.String(50), nullable=False, server_default="other"),
            sa.Column("poster_url", sa.Text, nullable=True),
            sa.Column("backdrop_url", sa.Text, nullable=True),
            sa.Column("synopsis", sa.Text, nullable=True),
            sa.Column("tagline", sa.Text, nullable=True),
            # TV-specific
            sa.Column("season_count", sa.Integer, nullable=True),
            sa.Column("episode_count", sa.Integer, nullable=True),
            sa.Column("network", sa.String(100), nullable=True),
            sa.Column("show_status", sa.String(30), nullable=True),
            # Movie-specific
            sa.Column("runtime_minutes", sa.Integer, nullable=True),
            sa.Column("budget_usd", sa.BigInteger, nullable=True),
            sa.Column("box_office_usd", sa.BigInteger, nullable=True),
            sa.Column("mpaa_rating", sa.String(10), nullable=True),
            # Research
            sa.Column("research_data", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("research_status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("fact_bank", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("research_sources", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("research_depth_score", sa.Float, nullable=False, server_default="0.0"),
            sa.Column("content_themes", postgresql.JSONB, nullable=False, server_default="[]"),
            # External IDs
            sa.Column("tmdb_id", sa.Integer, nullable=True, unique=True),
            sa.Column("imdb_id", sa.String(20), nullable=True, unique=True),
            # Stats
            sa.Column("carousels_created", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_views", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_likes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("avg_engagement", sa.Float, nullable=False, server_default="0.0"),
            # Meta
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_researched", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_media_type_status", "media_titles", ["media_type", "status"])
        op.create_index("idx_media_universe", "media_titles", ["universe"])

    # --- character_media_titles ---
    if "character_media_titles" not in existing_tables:
        op.create_table(
            "character_media_titles",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("character_id", sa.String(64), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
            sa.Column("media_title_id", sa.String(64), sa.ForeignKey("media_titles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role_name", sa.String(200), nullable=True),
            sa.Column("role_type", sa.String(30), nullable=False, server_default="supporting"),
            sa.Column("actor_name", sa.String(200), nullable=True),
            sa.Column("seasons_appeared", postgresql.JSONB, nullable=False, server_default="[]"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("character_id", "media_title_id", name="uq_character_media_title"),
        )
        op.create_index("idx_cmt_character", "character_media_titles", ["character_id"])
        op.create_index("idx_cmt_media", "character_media_titles", ["media_title_id"])

    # --- media_images ---
    if "media_images" not in existing_tables:
        op.create_table(
            "media_images",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("media_title_id", sa.String(64), sa.ForeignKey("media_titles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("url", sa.Text, nullable=False),
            sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
            sa.Column("query_used", sa.Text, nullable=True),
            sa.Column("width", sa.Integer, nullable=True),
            sa.Column("height", sa.Integer, nullable=True),
            sa.Column("is_valid", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("quality_score", sa.Float, nullable=False, server_default="0.0"),
            sa.Column("content_type", sa.String(50), nullable=True),
            sa.Column("file_size", sa.Integer, nullable=True),
            sa.Column("is_approved", sa.Boolean, nullable=True),
            sa.Column("feedback_reason", sa.Text, nullable=True),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("media_title_id", "url", name="uq_media_image_url"),
        )
        op.create_index("idx_media_images_title", "media_images", ["media_title_id"])

    # --- media_research_fragments ---
    if "media_research_fragments" not in existing_tables:
        op.create_table(
            "media_research_fragments",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("media_title_id", sa.String(64), sa.ForeignKey("media_titles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("content", sa.Text, nullable=False),
            sa.Column("url", sa.Text, nullable=True),
            sa.Column("relevance_score", sa.Float, nullable=False, server_default="0.5"),
            sa.Column("fragment_type", sa.String(50), nullable=False),
            sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_mrf_media", "media_research_fragments", ["media_title_id"])
        op.create_index("idx_mrf_source", "media_research_fragments", ["source"])

    # --- Modify character_carousels: add content_type + media_title_id ---
    carousel_cols = {c["name"] for c in inspector.get_columns("character_carousels")}

    if "content_type" not in carousel_cols:
        op.add_column(
            "character_carousels",
            sa.Column("content_type", sa.String(20), nullable=False, server_default="character"),
        )
        op.create_index("idx_carousel_content_type", "character_carousels", ["content_type"])

    if "media_title_id" not in carousel_cols:
        op.add_column(
            "character_carousels",
            sa.Column("media_title_id", sa.String(64), nullable=True),
        )
        # Add FK only if media_titles table exists (it was just created above)
        op.create_foreign_key(
            "fk_carousel_media_title",
            "character_carousels",
            "media_titles",
            ["media_title_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Make character_id nullable (it was NOT NULL before).
    # This is safe because all existing rows have character_id populated.
    op.alter_column(
        "character_carousels",
        "character_id",
        nullable=True,
    )


def downgrade() -> None:
    # Restore character_id to NOT NULL (only if no NULLs exist)
    op.alter_column("character_carousels", "character_id", nullable=False)

    op.drop_constraint("fk_carousel_media_title", "character_carousels", type_="foreignkey")
    op.drop_index("idx_carousel_content_type", table_name="character_carousels")
    op.drop_column("character_carousels", "media_title_id")
    op.drop_column("character_carousels", "content_type")

    op.drop_table("media_research_fragments")
    op.drop_table("media_images")
    op.drop_table("character_media_titles")
    op.drop_table("media_titles")
