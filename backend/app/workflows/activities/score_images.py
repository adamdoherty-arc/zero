"""ImageScorer activity — 11-stage cascading filter funnel.

Phase 2 implementation: calls ``ImageScorerService.score()`` which runs:
cheap CV → pHash dedup → CLIP / aesthetic / face / watermark (GPU stub) →
semantic dedup → Gemini Flash VLM verifier → composite z-score → upscale →
smart crop. GPU stages are no-ops until ``ZERO_USE_LOCAL_VISION_FUNNEL=true``
flips the switch.

Persistence: every scored candidate (kept and dropped) writes one row to
``image_scores`` so post-hoc weight calibration in Phase 6 can replay every
funnel decision and recompute the composite z formula against engagement.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def score_images(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "score_images", "generation_id": ctx["generation_id"]})

    from app.services.image_scorer_service import get_image_scorer
    from app.services.image_sources.types import CandidateImage

    candidates = [CandidateImage.model_validate(c) for c in ctx.get("image_candidates", [])]
    if not candidates:
        ctx["scored_images"] = []
        return ctx

    scored = await get_image_scorer().score(
        candidates,
        character=ctx["topic"],
        franchise=ctx.get("franchise"),
        top_k=30,
        vlm_top_k=15,  # cap cloud VLM cost per generation
        generation_id=ctx.get("generation_id"),
    )
    ctx["scored_images"] = [s.model_dump() for s in scored]
    kept_count = sum(1 for s in scored if s.kept)

    # Persist each candidate's funnel signals to ``image_scores`` so Phase 6
    # weight recalibration can replay decisions. Failure-soft.
    try:
        from app.db.models import ImageScoreModel
        from app.infrastructure.database import get_session
        async with get_session() as session:
            for s in scored:
                row = ImageScoreModel(
                    id=uuid.uuid4().hex,
                    generation_id=ctx["generation_id"],
                    carousel_id=ctx.get("carousel_id"),
                    source=s.source.value if hasattr(s.source, "value") else str(s.source),
                    source_url=s.source_url,
                    phash=s.phash,
                    dhash=s.dhash,
                    width=s.width,
                    height=s.height,
                    blur_variance=s.blur_variance,
                    nsfw_score=None,
                    aspect_match=s.aspect_match,
                    clip_relevance=s.clip_relevance,
                    clip_alt_softmax=s.clip_alt_softmax or None,
                    aesthetic_v2=s.aesthetic_v2,
                    maniqa=s.maniqa,
                    clip_iqa=None,
                    face_cosine=s.face_cosine,
                    face_actor=s.face_actor,
                    watermark_flag=bool(s.watermark_flag),
                    text_overlay_flag=bool(s.text_overlay_flag),
                    vlm_likeness=s.vlm_likeness,
                    vlm_is_promotional_still=s.vlm_is_promotional_still,
                    vlm_response_json=s.vlm_response or None,
                    vlm_model=s.vlm_model,
                    vlm_tier=getattr(s, "vlm_tier", None),
                    vlm_cost_usd=getattr(s, "vlm_cost_usd", None),
                    composite_z=s.composite_z,
                    rank=s.rank,
                    kept=bool(s.kept),
                    drop_reason=s.drop_reason,
                    upscaled_url=s.upscaled_url,
                    crop_box=s.crop_box,
                )
                session.add(row)
            await session.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_scores_persist_failed", generation_id=ctx["generation_id"], error=str(exc))

    logger.info(
        "carousel_score_images_done",
        generation_id=ctx["generation_id"],
        kept=kept_count,
        total=len(scored),
    )
    return ctx
