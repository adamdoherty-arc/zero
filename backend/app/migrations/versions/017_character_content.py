"""Character content creation tables.

Characters, carousels, and sourced images for TikTok character development posts.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY


revision = "017"
down_revision = "016_tiktok_affiliate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "characters",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, index=True),
        sa.Column("universe", sa.String(50), server_default="other", index=True),
        sa.Column("franchise", sa.String(200)),
        sa.Column("real_name", sa.String(200)),
        sa.Column("description", sa.Text),
        sa.Column("image_url", sa.Text),
        sa.Column("image_urls", JSONB, server_default="[]"),
        sa.Column("research_data", JSONB, server_default="{}"),
        sa.Column("research_status", sa.String(20), server_default="pending", index=True),
        sa.Column("fact_bank", JSONB, server_default="[]"),
        sa.Column("tags", ARRAY(sa.Text), server_default="{}"),
        sa.Column("posts_created", sa.Integer, server_default="0"),
        sa.Column("total_views", sa.Integer, server_default="0"),
        sa.Column("total_likes", sa.Integer, server_default="0"),
        sa.Column("avg_engagement", sa.Float, server_default="0.0"),
        sa.Column("status", sa.String(20), server_default="active", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_researched", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_characters_universe_status", "characters", ["universe", "status"])

    op.create_table(
        "character_carousels",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("character_id", sa.String(64), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("angle", sa.String(100), nullable=False, index=True),
        sa.Column("title", sa.String(300)),
        sa.Column("hook_text", sa.Text),
        sa.Column("slides", JSONB, server_default="[]"),
        sa.Column("caption", sa.Text),
        sa.Column("hashtags", JSONB, server_default="[]"),
        sa.Column("music_mood", sa.String(50)),
        sa.Column("ai_review", JSONB),
        sa.Column("human_notes", sa.Text),
        sa.Column("status", sa.String(20), server_default="draft", index=True),
        sa.Column("content_queue_id", sa.String(64)),
        sa.Column("publish_url", sa.Text),
        sa.Column("views", sa.Integer),
        sa.Column("likes", sa.Integer),
        sa.Column("comments", sa.Integer),
        sa.Column("shares", sa.Integer),
        sa.Column("saves", sa.Integer),
        sa.Column("engagement_rate", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_carousel_character_status", "character_carousels", ["character_id", "status"])

    op.create_table(
        "character_images",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("character_id", sa.String(64), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("source", sa.String(50), server_default="manual"),
        sa.Column("query_used", sa.Text),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("is_valid", sa.Boolean, server_default="true"),
        sa.Column("is_primary", sa.Boolean, server_default="false"),
        sa.Column("usage_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("character_images")
    op.drop_table("character_carousels")
    op.drop_table("characters")
