"""Reel publish activity — idempotent multi-platform publish after approval."""

from __future__ import annotations

from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def publish_reel_activity(args: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "reel_publish"})
    from app.services.reels import reel_publish_service

    generation_id = args["generation_id"]
    platforms = args.get("platforms") or ["tiktok"]
    pubs = await reel_publish_service.publish_reel_by_id(
        generation_id, platforms=platforms, dry_run=args.get("dry_run"),
    )
    logger.info("reel_publish_activity_done", generation_id=generation_id,
                platforms=[p.platform for p in pubs])
    return {
        "generation_id": generation_id,
        "platform_publishes": [p.model_dump(mode="json") for p in pubs],
    }
