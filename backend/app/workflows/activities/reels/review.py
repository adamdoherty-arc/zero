"""Human-review notification for a generated reel (Discord webhook, failure-soft)."""

from __future__ import annotations

import os
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


@activity.defn
async def request_reel_review(result: dict[str, Any]) -> None:
    activity.heartbeat({"stage": "reel_review"})
    logger.info("reel_human_review_requested", generation_id=result.get("generation_id"),
                video_url=result.get("video_url"))
    webhook = os.getenv("DISCORD_NOTIFICATION_WEBHOOK_URL")
    if not webhook:
        return
    try:
        import httpx
        msg = (
            "**Motivation reel ready for review**\n"
            f"Status: {result.get('status')} · Duration: {result.get('duration_s')}s\n"
            f"Video: {result.get('video_url') or '(no url)'}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(webhook, json={"content": msg})
    except Exception as exc:  # noqa: BLE001
        logger.warning("reel_review_webhook_failed", error=str(exc))
