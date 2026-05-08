"""ImageCurator activity — fan-out fetch from 8 sources via aiometer.

Phase 2 implementation: calls ``ImageCuratorService.curate()`` which runs
TMDB + Fanart.tv + Comic Vine + Wikimedia + Reddit PRAW + IMDb GraphQL +
Pexels + Unsplash concurrently. Each source plugin is failure-soft (returns
``[]`` on error) so a dead source never blocks the workflow.
"""

from __future__ import annotations

from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def curate_images(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "curate_images", "generation_id": ctx["generation_id"]})

    from app.services.image_curator_service import get_image_curator
    from app.services.image_sources.types import ImageQuery

    query = ImageQuery(
        character=ctx["topic"],
        franchise=ctx.get("franchise"),
    )
    candidates = await get_image_curator().curate(query, per_source_limit=30)
    ctx["image_candidates"] = [c.model_dump() for c in candidates]
    logger.info(
        "carousel_curate_images_done",
        generation_id=ctx["generation_id"],
        count=len(candidates),
    )
    return ctx
