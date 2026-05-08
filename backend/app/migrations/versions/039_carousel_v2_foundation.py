"""Carousel V2 foundation tables — schema + storage layer for the carosel.txt blueprint.

Creates the per-row state every later phase writes to. Without this migration, no
learning loop is possible: judges have nowhere to store axis scores, prompt-version
A/B tests have no registry, the image-curation funnel has no per-image audit trail,
and Temporal workflows have no idempotency table.

Tables in dependency order:

- ``prompt_versions`` — Designer/Hook/Skeptic/Judge prompt registry. Every active
  prompt has a row; DSPy GEPA mutations register children via ``parent_id``. The
  ``status`` column drives auto-rollback (``last_known_good`` flips on drift alert).

- ``carousel_generations`` — one row per generation attempt. References
  ``character_carousels.id`` so the existing pipeline keeps working alongside the
  new Temporal workflow. ``slides_json`` / ``judge_scores_json`` /
  ``source_citations_json`` / ``engagement_metrics_json`` are denormalised
  snapshots so a single row reproduces what shipped.

- ``judge_scores`` — per-axis × per-judge × per-carousel rubric scores. Drives
  Bradley-Terry aggregation and EWMA/CUSUM drift detection in Phase 6.

- ``golden_set`` — frozen hand-rated carousels. The CI gate replays every prompt
  change against this set before merge.

- ``atomic_facts`` — citation-grounded fact ledger. Every published claim's
  ``[fact_id:N]`` resolves here. ``trust_tier`` 1-4 + ``source_url`` + quote span
  are required; the Skeptic and FactVerifier read these directly.

- ``image_scores`` — 11-stage funnel audit trail per candidate image. Stores
  CLIP/aesthetic/face/watermark/VLM signals plus the composite z-score so
  Phase 6 can recalibrate weights against engagement.

- ``engagement_signals`` — TikTok analytics rolling window (every 6h × 48h,
  daily × 14d, weekly × 60d). ``residual`` is the confounder-controlled reward
  the bandit + DSPy trainset consume.

- ``bandit_logs`` — Vowpal Wabbit-style decision log: ``(decision_point,
  context_features, arm_chosen, propensity, reward)``. Doubly robust counterfactual
  evaluation reads from here.

- ``idempotency_keys`` — TikTok publish dedup. Temporal at-least-once semantics
  means the publish activity may fire twice; the key
  ``sha256(carousel_id || sorted(image_hashes) || caption_hash)`` prevents double
  posts.

Safe to re-run — every create is guarded by ``if not exists``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)

    # ------------------------------------------------------------------
    # prompt_versions — registry consumed by Designer / Hook / Skeptic /
    # Judges. DSPy GEPA writes new children with optimizer="gepa" and the
    # promotion flow flips status from "shadow" → "active" → "last_known_good".
    # ------------------------------------------------------------------
    if "prompt_versions" not in existing:
        op.create_table(
            "prompt_versions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("name", sa.String(120), nullable=False, index=True),  # e.g. "designer.fact_slide"
            sa.Column("parent_id", sa.String(64), nullable=True, index=True),
            sa.Column("prompt_text", sa.Text(), nullable=False),
            sa.Column("system_text", sa.Text(), nullable=True),
            sa.Column("optimizer", sa.String(40), nullable=False, server_default="manual"),
            # one of: manual | bootstrap_few_shot | miprov2 | gepa | dpo | simpo | human
            sa.Column("model_hint", sa.String(120), nullable=True),
            sa.Column("voice_file", sa.String(120), nullable=True),  # voices/{property}.yml
            sa.Column("metadata", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("golden_set_score", sa.Float(), nullable=True),
            sa.Column("live_win_rate", sa.Float(), nullable=True),
            sa.Column("engagement_lift", sa.Float(), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="shadow", index=True),
            # one of: shadow | active | last_known_good | archived | rolled_back
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index("ix_prompt_versions_name_status", "prompt_versions", ["name", "status"])

    # ------------------------------------------------------------------
    # carousel_generations — one row per Temporal workflow attempt. Lives
    # alongside CharacterCarouselModel until Phase 6 cutover.
    # ------------------------------------------------------------------
    if "carousel_generations" not in existing:
        op.create_table(
            "carousel_generations",
            sa.Column("id", sa.String(64), primary_key=True),
            # Soft FK to character_carousels.id — kept loose so the legacy
            # pipeline can operate without a Temporal record.
            sa.Column("carousel_id", sa.String(64), nullable=True, index=True),
            sa.Column("workflow_id", sa.String(120), nullable=True, index=True),
            sa.Column("workflow_run_id", sa.String(120), nullable=True, index=True),
            sa.Column("topic", sa.Text(), nullable=False),
            sa.Column("franchise", sa.String(80), nullable=True, index=True),
            sa.Column("character_id", sa.String(64), nullable=True, index=True),
            sa.Column("prompt_version_id", sa.String(64), nullable=True, index=True),
            sa.Column("designer_prompt_id", sa.String(64), nullable=True),
            sa.Column("skeptic_prompt_id", sa.String(64), nullable=True),
            # Denormalised snapshots — a single row reproduces what shipped.
            sa.Column("slides_json", pg.JSONB(), nullable=False, server_default="[]"),
            sa.Column("judge_scores_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("source_citations_json", pg.JSONB(), nullable=False, server_default="[]"),
            sa.Column("engagement_metrics_json", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("composite_score", sa.Float(), nullable=True),
            sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
            # one of: pending | researching | designing | skeptic | reflexion |
            #         rendering | awaiting_review | publishing | published |
            #         abandoned | failed
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_carousel_generations_published",
            "carousel_generations",
            ["franchise", "status", "published_at"],
        )

    # ------------------------------------------------------------------
    # judge_scores — per-axis × per-judge × per-carousel. 7 axes × 3 judges
    # ≈ 21 rows per carousel.
    # ------------------------------------------------------------------
    if "judge_scores" not in existing:
        op.create_table(
            "judge_scores",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("generation_id", sa.String(64), nullable=False, index=True),
            sa.Column("carousel_id", sa.String(64), nullable=True, index=True),
            sa.Column("judge_name", sa.String(80), nullable=False),  # kimi_k2_6 | minimax_m2_7 | qwen3_32b_local
            sa.Column("axis", sa.String(40), nullable=False),
            # one of: hook_strength | fact_accuracy | image_relevance |
            #         narrative_arc | design_polish | voice_consistency | novelty
            sa.Column("score", sa.Float(), nullable=False),  # 0-10 normalised
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("model_id", sa.String(120), nullable=True),
            sa.Column("temperature", sa.Float(), nullable=True),
            sa.Column("samples_n", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("trust_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column(
                "sampled_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_judge_scores_lookup",
            "judge_scores",
            ["generation_id", "judge_name", "axis"],
        )

    # ------------------------------------------------------------------
    # golden_set — frozen hand-rated carousels. CI gate replays prompt
    # changes against this set; κ vs human consensus tracked per judge.
    # ------------------------------------------------------------------
    if "golden_set" not in existing:
        op.create_table(
            "golden_set",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("carousel_id", sa.String(64), nullable=False, index=True),
            sa.Column("generation_id", sa.String(64), nullable=True),
            sa.Column("franchise", sa.String(80), nullable=True, index=True),
            sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            # human_score_per_axis: {hook_strength: 8, fact_accuracy: 9, ...}
            sa.Column("human_score_per_axis", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("human_composite", sa.Float(), nullable=True),
            sa.Column("human_rater", sa.String(80), nullable=True),
            # kappa_vs_judges: {kimi_k2_6: 0.78, minimax_m2_7: 0.71, qwen3_32b_local: 0.69}
            sa.Column("kappa_vs_judges", pg.JSONB(), nullable=False, server_default="{}"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("adversarial_category", sa.String(80), nullable=True),
            # one of: actor_swap | comic_vs_screen | retcon | made_up_easter_egg | null
            sa.Column(
                "added_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ------------------------------------------------------------------
    # atomic_facts — fact ledger. Every "[fact_id:N]" citation resolves here.
    # ------------------------------------------------------------------
    if "atomic_facts" not in existing:
        op.create_table(
            "atomic_facts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("subject", sa.Text(), nullable=False, index=True),
            sa.Column("predicate", sa.String(80), nullable=False),
            sa.Column("object", sa.Text(), nullable=False),
            sa.Column("source", sa.String(40), nullable=False, index=True),
            # one of: fandom | tmdb | tvdb | wikipedia | wikidata |
            #         comic_vine | imdb_graphql | reddit | youtube | news | other
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_quote", sa.Text(), nullable=True),
            sa.Column("trust_tier", sa.SmallInteger(), nullable=False, index=True),
            # 1 = canon structured, 2 = semi-structured, 3 = community signal,
            # 4 = news (cross-confirm required)
            sa.Column("entity_type", sa.String(40), nullable=True),
            sa.Column("entity_id", sa.String(64), nullable=True, index=True),
            sa.Column("franchise", sa.String(80), nullable=True, index=True),
            sa.Column("sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("supersedes_id", sa.String(64), nullable=True),
            sa.Column(
                "fetched_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_atomic_facts_subject_pred", "atomic_facts", ["subject", "predicate"])
        # Hybrid search: tsvector on subject + object for BM25 side of RRF fusion.
        op.execute(
            "ALTER TABLE atomic_facts ADD COLUMN content_tsv tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english', "
            "coalesce(subject,'') || ' ' || coalesce(object,'') || ' ' || coalesce(source_quote,''))) STORED"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_atomic_facts_content_tsv ON atomic_facts USING gin (content_tsv)"
        )

    # ------------------------------------------------------------------
    # image_scores — 11-stage funnel audit trail per candidate image.
    # ------------------------------------------------------------------
    if "image_scores" not in existing:
        op.create_table(
            "image_scores",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("generation_id", sa.String(64), nullable=False, index=True),
            sa.Column("carousel_id", sa.String(64), nullable=True, index=True),
            sa.Column("slide_num", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(40), nullable=False),
            # tmdb | fanart | comic_vine | wikimedia | reddit_praw | imdb |
            # pexels | unsplash | bing_cse | google_cse
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("phash", sa.String(20), nullable=True, index=True),
            sa.Column("dhash", sa.String(20), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            # Stage 1 cheap CV
            sa.Column("blur_variance", sa.Float(), nullable=True),
            sa.Column("nsfw_score", sa.Float(), nullable=True),
            sa.Column("aspect_match", sa.Boolean(), nullable=True),
            # Stage 3 CLIP
            sa.Column("clip_relevance", sa.Float(), nullable=True),
            sa.Column("clip_alt_softmax", pg.JSONB(), nullable=True),
            # Stage 4 aesthetic + IQA
            sa.Column("aesthetic_v2", sa.Float(), nullable=True),
            sa.Column("maniqa", sa.Float(), nullable=True),
            sa.Column("clip_iqa", sa.Float(), nullable=True),
            # Stage 5 face verify
            sa.Column("face_cosine", sa.Float(), nullable=True),
            sa.Column("face_actor", sa.String(120), nullable=True),
            # Stage 6 watermark / overlay
            sa.Column("watermark_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("text_overlay_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            # Stage 8 VLM final
            sa.Column("vlm_likeness", sa.Float(), nullable=True),
            sa.Column("vlm_is_promotional_still", sa.Boolean(), nullable=True),
            sa.Column("vlm_response_json", pg.JSONB(), nullable=True),
            sa.Column("vlm_model", sa.String(120), nullable=True),
            # Stage 9 composite
            sa.Column("composite_z", sa.Float(), nullable=True, index=True),
            sa.Column("rank", sa.Integer(), nullable=True),
            sa.Column("kept", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),
            sa.Column("drop_reason", sa.String(80), nullable=True),
            # Stage 10/11 outputs
            sa.Column("upscaled_url", sa.Text(), nullable=True),
            sa.Column("crop_box", pg.JSONB(), nullable=True),
            sa.Column(
                "scored_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_image_scores_generation_kept",
            "image_scores",
            ["generation_id", "kept", "composite_z"],
        )

    # ------------------------------------------------------------------
    # engagement_signals — rolling TikTok analytics window.
    # ------------------------------------------------------------------
    if "engagement_signals" not in existing:
        op.create_table(
            "engagement_signals",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("generation_id", sa.String(64), nullable=True, index=True),
            sa.Column("carousel_id", sa.String(64), nullable=False, index=True),
            sa.Column("publish_id", sa.String(120), nullable=True, index=True),
            # Hours since publish — discrete sample points: 1, 6, 24, 48, 168, 720, 1440
            sa.Column("t_offset_h", sa.Integer(), nullable=False),
            sa.Column("views", sa.BigInteger(), nullable=True),
            sa.Column("likes", sa.BigInteger(), nullable=True),
            sa.Column("comments", sa.BigInteger(), nullable=True),
            sa.Column("shares", sa.BigInteger(), nullable=True),
            sa.Column("saves", sa.BigInteger(), nullable=True),
            sa.Column("follows_from_video", sa.BigInteger(), nullable=True),
            sa.Column("completion_rate", sa.Float(), nullable=True),
            sa.Column("avg_swipe_depth", sa.Float(), nullable=True),
            sa.Column("for_you_pct", sa.Float(), nullable=True),
            # Niche-cohort z-scored composite reward.
            sa.Column("niche_z_score", sa.Float(), nullable=True),
            sa.Column("residual", sa.Float(), nullable=True),  # confounder-controlled
            sa.Column("cohort_key", sa.String(80), nullable=True, index=True),
            sa.Column("source", sa.String(24), nullable=False, server_default="display_api"),
            # display_api | studio_scrape | metricool | manual
            sa.Column(
                "sampled_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_engagement_signals_carousel_offset",
            "engagement_signals",
            ["carousel_id", "t_offset_h"],
        )

    # ------------------------------------------------------------------
    # bandit_logs — Vowpal Wabbit decision log.
    # ------------------------------------------------------------------
    if "bandit_logs" not in existing:
        op.create_table(
            "bandit_logs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("generation_id", sa.String(64), nullable=True, index=True),
            sa.Column("carousel_id", sa.String(64), nullable=True, index=True),
            sa.Column("decision_point", sa.String(40), nullable=False, index=True),
            # one of: topic_angle | hook_style | slide_count | design_template |
            #         image_source_mix | posting_slot
            sa.Column("context_features", pg.JSONB(), nullable=False),
            sa.Column("arm_chosen", sa.String(120), nullable=False),
            sa.Column("arms_offered", pg.JSONB(), nullable=True),
            sa.Column("propensity", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("policy_id", sa.String(80), nullable=True),
            sa.Column("reward", sa.Float(), nullable=True),  # null until engagement settles
            sa.Column("reward_t_offset_h", sa.Integer(), nullable=True),
            sa.Column(
                "decided_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ------------------------------------------------------------------
    # idempotency_keys — TikTok publish dedup. Temporal at-least-once
    # semantics means activities can fire twice on retry.
    # ------------------------------------------------------------------
    if "idempotency_keys" not in existing:
        op.create_table(
            "idempotency_keys",
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("scope", sa.String(40), nullable=False, server_default="tiktok_publish", index=True),
            sa.Column("generation_id", sa.String(64), nullable=True, index=True),
            sa.Column("publish_id", sa.String(120), nullable=True),
            sa.Column("response_payload", pg.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    # Drop in reverse dependency order. carousel_generations references
    # prompt_versions softly so it must go first.
    for table in (
        "idempotency_keys",
        "bandit_logs",
        "engagement_signals",
        "image_scores",
        "atomic_facts",
        "golden_set",
        "judge_scores",
        "carousel_generations",
        "prompt_versions",
    ):
        try:
            op.drop_table(table)
        except Exception:  # noqa: BLE001
            pass
