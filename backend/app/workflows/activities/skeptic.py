"""Skeptic activity — adversarial fact-checker over the atomic-claim list.

Phase 4 implementation: calls ``skeptic_service.review`` with Kimi K2.6
(different family from the Designer's Qwen3 to dodge shared blind spots).
KILLs drop the slide; REWRITEs replace the text.
"""

from __future__ import annotations

from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def skeptic_review(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "skeptic", "generation_id": ctx["generation_id"]})

    from app.services.carousel_v2 import skeptic_service
    from app.services.carousel_v2.atomic_facts_service import lookup_ids
    from app.services.carousel_v2.fact_verifier_service import decompose_to_claims

    slides = ctx.get("slides", []) or []
    if not slides:
        ctx["skeptic_verdicts"] = []
        ctx["skeptic_counts"] = {"keep": 0, "rewrite": 0, "kill": 0}
        return ctx

    # Collect claims (one per slide), evidence (cited facts).
    claims: list[str] = []
    cited_ids: set[str] = set()
    for slide in slides:
        text = slide.get("text") or ""
        decomposed = decompose_to_claims(text) or [text.strip()]
        # We pass one representative claim per slide to keep the JSON tight.
        claims.append(decomposed[0])
        for fid in slide.get("cited_fact_ids") or []:
            cited_ids.add(str(fid))

    evidence = await lookup_ids(cited_ids)
    reports = await skeptic_service.review(claims, evidence=evidence)
    updated_slides, counts = skeptic_service.apply_verdicts(slides, reports)

    ctx["slides"] = updated_slides
    ctx["skeptic_verdicts"] = [r.model_dump() for r in reports]
    ctx["skeptic_counts"] = counts
    logger.info(
        "carousel_skeptic_done",
        generation_id=ctx["generation_id"],
        keep=counts["keep"],
        rewrite=counts["rewrite"],
        kill=counts["kill"],
    )
    return ctx
