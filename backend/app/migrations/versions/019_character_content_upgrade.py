"""Character content upgrade: research fragments, relationships, inspirations, music, templates.

Adds deep research, cross-character relationships, content inspiration tracking,
music library, and story templates for enhanced character carousel generation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Add columns to existing tables ---

    # characters: research + relationship columns
    op.add_column("characters", sa.Column("research_sources", JSONB, server_default="[]"))
    op.add_column("characters", sa.Column("relationship_map", JSONB, server_default="{}"))
    op.add_column("characters", sa.Column("research_depth_score", sa.Float, server_default="0.0"))
    op.add_column("characters", sa.Column("content_themes", JSONB, server_default="[]"))

    # character_carousels: series, multi-character, music, templates, brain context
    op.add_column("character_carousels", sa.Column("story_template", sa.String(100)))
    op.add_column("character_carousels", sa.Column("series_id", sa.String(64)))
    op.add_column("character_carousels", sa.Column("series_part", sa.Integer))
    op.add_column("character_carousels", sa.Column("multi_character_ids", JSONB, server_default="[]"))
    op.add_column("character_carousels", sa.Column("music_track", JSONB))
    op.add_column("character_carousels", sa.Column("text_overlay_specs", JSONB, server_default="[]"))
    op.add_column("character_carousels", sa.Column("brain_context_used", JSONB))
    op.add_column("character_carousels", sa.Column("generation_metadata", JSONB, server_default="{}"))

    # --- Create new tables ---

    # 1. Character Research Fragments
    op.create_table(
        "character_research_fragments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("character_id", sa.String(64), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("source", sa.String(50), nullable=False, index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("relevance_score", sa.Float, server_default="0.5"),
        sa.Column("fragment_type", sa.String(50), index=True),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Character Relationships
    op.create_table(
        "character_relationships",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("character_a_id", sa.String(64), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("character_b_id", sa.String(64), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("strength", sa.Float, server_default="0.5"),
        sa.Column("source", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_char_rel_pair", "character_relationships", ["character_a_id", "character_b_id"])

    # 3. Content Inspirations
    op.create_table(
        "content_inspirations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("platform", sa.String(30), nullable=False, index=True),
        sa.Column("source_url", sa.Text),
        sa.Column("creator_handle", sa.String(200)),
        sa.Column("content_type", sa.String(50), index=True),
        sa.Column("hook_text", sa.Text),
        sa.Column("slide_count", sa.Integer),
        sa.Column("structure_analysis", JSONB),
        sa.Column("engagement_metrics", JSONB, server_default="{}"),
        sa.Column("tags", ARRAY(sa.Text), server_default="{}"),
        sa.Column("patterns_extracted", JSONB, server_default="[]"),
        sa.Column("status", sa.String(20), server_default="'pending'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
    )

    # 4. Music Tracks
    op.create_table(
        "music_tracks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("artist", sa.String(200)),
        sa.Column("mood", sa.String(50), index=True),
        sa.Column("energy_level", sa.String(20)),
        sa.Column("genre", sa.String(100)),
        sa.Column("tiktok_sound_id", sa.String(100)),
        sa.Column("tiktok_sound_url", sa.Text),
        sa.Column("is_trending", sa.Boolean, server_default="false"),
        sa.Column("trending_score", sa.Float, server_default="0.0"),
        sa.Column("use_count", sa.Integer, server_default="0"),
        sa.Column("avg_engagement", sa.Float, server_default="0.0"),
        sa.Column("tags", ARRAY(sa.Text), server_default="{}"),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_checked", sa.DateTime(timezone=True)),
    )

    # 5. Story Templates
    op.create_table(
        "story_templates",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("template_type", sa.String(100), nullable=False, index=True),
        sa.Column("description", sa.Text),
        sa.Column("slide_structure", JSONB, nullable=False),
        sa.Column("prompt_template", sa.Text, nullable=False),
        sa.Column("example_hook", sa.Text),
        sa.Column("suitable_angles", ARRAY(sa.Text), server_default="{}"),
        sa.Column("suitable_universes", ARRAY(sa.Text), server_default="{}"),
        sa.Column("times_used", sa.Integer, server_default="0"),
        sa.Column("avg_score", sa.Float, server_default="0.0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    # Drop new tables (reverse order of creation)
    op.drop_table("story_templates")
    op.drop_table("music_tracks")
    op.drop_table("content_inspirations")
    op.drop_index("idx_char_rel_pair", table_name="character_relationships")
    op.drop_table("character_relationships")
    op.drop_table("character_research_fragments")

    # Remove added columns from character_carousels
    op.drop_column("character_carousels", "generation_metadata")
    op.drop_column("character_carousels", "brain_context_used")
    op.drop_column("character_carousels", "text_overlay_specs")
    op.drop_column("character_carousels", "music_track")
    op.drop_column("character_carousels", "multi_character_ids")
    op.drop_column("character_carousels", "series_part")
    op.drop_column("character_carousels", "series_id")
    op.drop_column("character_carousels", "story_template")

    # Remove added columns from characters
    op.drop_column("characters", "content_themes")
    op.drop_column("characters", "research_depth_score")
    op.drop_column("characters", "relationship_map")
    op.drop_column("characters", "research_sources")
