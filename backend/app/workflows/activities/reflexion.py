"""Judge + Reflexion activity — runs the 3-judge panel and decides whether
the carousel passes the auto-publish gate or needs another Designer pass.

Phase 4 implementation: calls ``judge_panel_service.score_carousel`` for
Bradley-Terry-weighted scoring, persists every judge × axis row to
``judge_scores``, and produces a coachable reflection from the lowest axes
when the composite is below 7.5.
"""

from __future__ import annotations

from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def judge_and_reflect(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "reflexion", "generation_id": ctx["generation_id"]})

    from app.models.carousel import (
        AUTO_PUBLISH_THRESHOLD,
        CarouselV2,
        Slide,
        SlideRole,
    )
    from app.services.carousel_v2 import judge_panel_service, reflexion_service

    slides_raw = ctx.get("slides", []) or []
    if not slides_raw:
        # Nothing to judge — composite 0, fail the gate.
        return {"passes": False, "context": {**ctx, "composite_score": 0.0, "auto_approved": False}}

    # Build a CarouselV2 stub for the panel.
    slides_typed = []
    for s in slides_raw:
        try:
            slides_typed.append(
                Slide(
                    slide_num=int(s.get("slide_num", len(slides_typed) + 1)),
                    role=SlideRole(s.get("role", "fact" if slides_typed else "hook")),
                    text=s.get("text", ""),
                    transition_to_next=s.get("transition_to_next"),
                    cited_fact_ids=s.get("cited_fact_ids", []) or [],
                    template=s.get("template", "fact"),
                )
            )
        except Exception:  # noqa: BLE001
            continue

    carousel = CarouselV2(
        id=ctx["generation_id"],
        topic=ctx["topic"],
        franchise=ctx.get("franchise"),
        slides=slides_typed,
        revision_count=int(ctx.get("revision_count", 0)),
    )

    rubric = await judge_panel_service.score_carousel(carousel)

    try:
        await judge_panel_service.persist_rubric(
            generation_id=ctx["generation_id"],
            carousel_id=ctx.get("carousel_id"),
            rubric=rubric,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rubric_persist_failed", error=str(exc))

    composite = rubric.composite
    passes = rubric.passes_auto_publish

    ctx["composite_score"] = composite
    ctx["rubric_axes"] = {axis.value: score for axis, score in rubric.aggregated.items()}
    ctx["auto_approved"] = ctx.get("auto_publish", False) and composite >= AUTO_PUBLISH_THRESHOLD

    if not passes:
        reflection = reflexion_service.make_reflection(rubric)
        history = ctx.get("reflections", []) or []
        ctx["reflections"] = reflexion_service.append_reflection(history, reflection)
        ctx["revision_count"] = int(ctx.get("revision_count", 0)) + 1

    # Persist composite + slides snapshot so post-hoc replay reproduces what
    # was judged. Failure-soft — no DB connection means a no-op.
    try:
        from app.services.carousel_v2.generation_state import upsert_state
        await upsert_state(
            ctx["generation_id"],
            slides_json=ctx.get("slides", []) or [],
            judge_scores_json=ctx["rubric_axes"],
            composite_score=composite,
            revision_count=ctx.get("revision_count"),
            status="awaiting_review" if passes else "reflexion",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("reflexion_state_persist_failed", error=str(exc))

    logger.info(
        "carousel_reflexion_done",
        generation_id=ctx["generation_id"],
        composite=composite,
        passes=passes,
        revision_count=ctx.get("revision_count"),
    )
    return {"passes": passes, "context": ctx}
