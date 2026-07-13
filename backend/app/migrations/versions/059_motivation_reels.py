"""Motivation Reels — quote-driven video pipeline tables.

A parallel plane to the carousel_v2 tables (migration 039). Reuses the
content-agnostic learning tables (engagement_signals, bandit_logs,
judge_scores, idempotency_keys) by string key — reel rows there carry
``carousel_id=reel_id``, ``decision_point="reel_*"``, ``scope="reel_publish_*"``
— so only the reel-specific rows need new tables here.

Tables:

- ``reel_generations`` — one row per reel generation attempt (mirrors
  carousel_generations). Full ``MotivationReel`` denormalised across JSONB.
- ``reel_music_tracks`` — royalty-free / generated audio library. Real audio in
  ``storage_url`` + ``beat_grid`` for caption sync. Only ``is_bakeable`` rows may
  be muxed into a monetized MP4. Seeded by the ingest job, not this migration.
- ``reel_platform_publishes`` — one row per (reel × platform) publish attempt.
- ``reel_links`` / ``reel_link_clicks`` — tracked CTA redirect + CTR/conversion.
- ``reel_revenue`` — creator-fund / ad-rev / affiliate (read-only imports).

Safe to re-run — every create is guarded by ``if not exists``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)

    # ------------------------------------------------------------------
    # reel_generations — one row per reel generation attempt.
    # ------------------------------------------------------------------
    if "reel_generations" not in existing:
        op.create_table(
            "reel_generations",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("reel_id", sa.String(64), nullable=True, index=True),
            sa.Column("workflow_id", sa.String(120), nullable=True, index=True),
            sa.Column("workflow_run_id", sa.String(120), nullable=True, index=True),
            sa.Column("sub_niche", sa.String(60), nullable=True, index=True),
            sa.Column("theme", sa.String(120), nullable=True),
            sa.Column("mood", sa.String(40), nullable=True),
            sa.Column("quote_text", sa.Text(), nullable=True),
            sa.Column("quote_author", sa.String(160), nullable=True),
            sa.Column("quote_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("scenes_json", pg.JSONB(), nullable=False, server_default="[]"),
            sa.Column("music_track_id", sa.String(64), nullable=True, index=True),
            sa.Column("music_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("voiceover", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("voiceover_url", sa.Text(), nullable=True),
            sa.Column("video_url", sa.Text(), nullable=True),
            sa.Column("video_sha256", sa.String(64), nullable=True),
            sa.Column("duration_s", sa.Float(), nullable=True),
            sa.Column("visual_style", sa.String(40), nullable=True),
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("hashtags_json", pg.JSONB(), nullable=False, server_default="[]"),
            sa.Column("cta_text", sa.Text(), nullable=True),
            sa.Column("cta_link", sa.Text(), nullable=True),
            sa.Column("judge_scores_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("composite_score", sa.Float(), nullable=True, index=True),
            sa.Column("rubric_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("arms_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("bandit_log_ids_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("engagement_metrics_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("initiated_by", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_reel_generations_niche_status",
            "reel_generations",
            ["sub_niche", "status", "published_at"],
        )

    # ------------------------------------------------------------------
    # reel_music_tracks — RF / generated audio library.
    # ------------------------------------------------------------------
    if "reel_music_tracks" not in existing:
        op.create_table(
            "reel_music_tracks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("source", sa.String(24), nullable=False, server_default="rf_library", index=True),
            sa.Column("provider", sa.String(40), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("artist", sa.String(160), nullable=True),
            sa.Column("mood", sa.String(40), nullable=True, index=True),
            sa.Column("energy", sa.String(16), nullable=True),
            sa.Column("bpm", sa.Float(), nullable=True),
            sa.Column("beat_grid_json", pg.JSONB(), nullable=False, server_default="[]"),
            sa.Column("duration_s", sa.Float(), nullable=True),
            sa.Column("license", sa.String(24), nullable=False, server_default="cc0", index=True),
            sa.Column("attribution", sa.Text(), nullable=True),
            sa.Column("storage_url", sa.Text(), nullable=True),
            sa.Column("local_path", sa.Text(), nullable=True),
            sa.Column("loop_safe", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("is_bakeable", sa.Boolean(), nullable=False, server_default=sa.text("true"), index=True),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_reward", sa.Float(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # ------------------------------------------------------------------
    # reel_platform_publishes — one row per (reel × platform).
    # ------------------------------------------------------------------
    if "reel_platform_publishes" not in existing:
        op.create_table(
            "reel_platform_publishes",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("reel_id", sa.String(64), nullable=False, index=True),
            sa.Column("generation_id", sa.String(64), nullable=True, index=True),
            sa.Column("platform", sa.String(20), nullable=False, index=True),
            sa.Column("platform_post_id", sa.String(160), nullable=True, index=True),
            sa.Column("publish_url", sa.Text(), nullable=True),
            sa.Column("publish_status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("publish_error", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(64), nullable=True, index=True),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("reel_id", "platform", name="uq_reel_platform"),
        )

    # ------------------------------------------------------------------
    # reel_links / reel_link_clicks — tracked CTA redirect + CTR.
    # ------------------------------------------------------------------
    if "reel_links" not in existing:
        op.create_table(
            "reel_links",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("reel_id", sa.String(64), nullable=False, index=True),
            sa.Column("token", sa.String(32), nullable=False, unique=True, index=True),
            sa.Column("link_type", sa.String(24), nullable=False, server_default="bio_funnel"),
            sa.Column("destination_url", sa.Text(), nullable=False),
            sa.Column("product_id", sa.String(64), nullable=True, index=True),
            sa.Column("utm_template_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "reel_link_clicks" not in existing:
        op.create_table(
            "reel_link_clicks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("link_id", sa.String(64), nullable=False, index=True),
            sa.Column("reel_id", sa.String(64), nullable=True, index=True),
            sa.Column("platform", sa.String(20), nullable=True),
            sa.Column("ip_hash", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("clicked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("conversion_value_usd", sa.Float(), nullable=True),
        )

    # ------------------------------------------------------------------
    # reel_revenue — creator-fund / ad-rev / affiliate (read-only imports).
    # ------------------------------------------------------------------
    if "reel_revenue" not in existing:
        op.create_table(
            "reel_revenue",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("platform", sa.String(20), nullable=False, index=True),
            sa.Column("reel_id", sa.String(64), nullable=True, index=True),
            sa.Column("revenue_source", sa.String(24), nullable=False),
            sa.Column("amount_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("views_in_period", sa.BigInteger(), nullable=True),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    for table in (
        "reel_revenue",
        "reel_link_clicks",
        "reel_links",
        "reel_platform_publishes",
        "reel_music_tracks",
        "reel_generations",
    ):
        try:
            op.drop_table(table)
        except Exception:  # noqa: BLE001
            pass
