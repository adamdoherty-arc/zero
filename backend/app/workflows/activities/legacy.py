"""Legacy bridge activity — wraps ``CharacterContentService.generate_carousel``
so existing carousel traffic can flip through Temporal via
``ZERO_USE_TEMPORAL=true`` without touching the legacy pipeline.

This activity exists for the duration of the Phase 1-5 migration window.
Phase 6 retires it once every per-stage activity is real and the
APScheduler-driven jobs route through ``GenerateCarouselWorkflow`` directly.
"""

from __future__ import annotations

import structlog
from temporalio import activity

from app.models.carousel import CarouselGenerationStatus, CarouselWorkflowInput, CarouselWorkflowResult

logger = structlog.get_logger(__name__)


@activity.defn
async def legacy_generate(payload: CarouselWorkflowInput) -> CarouselWorkflowResult:
    """Run the legacy monolith inside a Temporal activity.

    Activities tolerate full async + I/O — this is where Temporal's
    determinism constraint stops applying. The activity itself is replayed
    deterministically from history, but the side effects (LLM calls, DB
    writes, image fetches) happen here, idempotency-keyed where it matters.
    """
    activity.heartbeat({"stage": "legacy_generate"})

    if not payload.character_id:
        logger.warning(
            "legacy_generate_missing_character_id",
            topic=payload.topic,
            franchise=payload.franchise,
        )
        return CarouselWorkflowResult(
            generation_id="legacy",
            status=CarouselGenerationStatus.FAILED,
            error="character_id required for legacy path; topic-only generation is Phase 3+",
        )

    # Deferred imports — pulling these at module level breaks Temporal's
    # determinism check on the workflow side and is also expensive to load.
    from app.models.character_content import CarouselCreate
    from app.services.character_content_service import CharacterContentService

    create_args: dict = {
        "character_id": payload.character_id,
        "slide_count": payload.slide_count,
    }
    if payload.angle:
        create_args["angle"] = payload.angle

    service = CharacterContentService()
    carousel = await service.generate_carousel(CarouselCreate(**create_args))

    return CarouselWorkflowResult(
        generation_id=str(getattr(carousel, "id", "legacy")),
        carousel_id=str(getattr(carousel, "id", None)) if getattr(carousel, "id", None) else None,
        status=CarouselGenerationStatus.AWAITING_REVIEW,
        composite_score=getattr(carousel, "ai_review_score", None),
    )
