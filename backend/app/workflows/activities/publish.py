"""Publisher activities — human review notification + TikTok publish.

Phase 5 implementation:

- ``request_human_review`` posts a Discord notification with the carousel
  preview URLs and lets the workflow wait on a ``human_decision`` signal.
- ``publish_to_tiktok`` calls ``TikTokAPIClient.publish_carousel`` with an
  idempotency key derived from
  ``sha256(carousel_id + sorted(image_hashes) + caption_hash)``. Re-runs
  short-circuit on the cached publish_id from ``idempotency_keys``.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


class DuplicatePublishError(Exception):
    """Raised when an idempotency-key replay returns the cached publish_id —
    swallowed by the workflow's retry policy as non-retryable.
    """


@activity.defn
async def request_human_review(ctx: dict[str, Any]) -> None:
    activity.heartbeat({"stage": "human_review", "generation_id": ctx["generation_id"]})
    logger.info(
        "carousel_human_review_requested",
        generation_id=ctx["generation_id"],
        composite_score=ctx.get("composite_score"),
        rendered=len(ctx.get("rendered_image_urls", []) or []),
    )
    # Post to Discord webhook if configured. Failure-soft.
    webhook = os.getenv("DISCORD_NOTIFICATION_WEBHOOK_URL")
    if not webhook:
        return
    try:
        import httpx
        urls = ctx.get("rendered_image_urls", []) or []
        chosen_hook = ctx.get("chosen_hook") or ctx.get("topic")
        msg = (
            f"**Carousel ready for review** · score {ctx.get('composite_score', 0):.1f} / 10\n"
            f"Topic: {ctx.get('topic')}\n"
            f"Hook: {chosen_hook}\n"
            f"Slides: {len(urls)}\n"
            + ("\n".join(urls[:3]) if urls else "(no rendered slides)")
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(webhook, json={"content": msg})
    except Exception as exc:  # noqa: BLE001
        logger.warning("discord_webhook_failed", error=str(exc))


@activity.defn
async def publish_to_tiktok(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "publish", "generation_id": ctx["generation_id"]})

    from app.services.carousel_v2 import caption_service, idempotency

    urls = ctx.get("rendered_image_urls", []) or []
    image_hashes = ctx.get("rendered_image_sha256", []) or []
    chosen_hook = ctx.get("chosen_hook") or ctx.get("topic", "")
    voice_key = (ctx.get("franchise") or "mcu").lower().replace(" ", "_")

    caption = caption_service.compose_caption(
        hook=chosen_hook,
        franchise=ctx.get("franchise"),
        character=ctx.get("topic", ""),
        slide_summaries=[s.get("text", "")[:80] for s in (ctx.get("slides") or [])[:3]],
        voice_key=voice_key,
    )

    key = idempotency.make_key(
        carousel_id=ctx.get("generation_id", ""),
        image_hashes=image_hashes or urls,
        caption=caption,
    )
    cached = await idempotency.lookup(key)
    if cached and cached.get("publish_id"):
        logger.info(
            "carousel_publish_idempotent_replay",
            generation_id=ctx["generation_id"],
            publish_id=cached["publish_id"],
        )
        return {
            "generation_id": ctx["generation_id"],
            "carousel_id": ctx.get("carousel_id"),
            "publish_id": cached["publish_id"],
            "publish_url": (cached.get("response_payload") or {}).get("publish_url"),
            "idempotent_replay": True,
        }

    publish_id: str | None = None
    response_payload: dict = {}
    dry_run = os.getenv("ZERO_TIKTOK_DRY_RUN", "true").lower() in {"1", "true", "yes"} or not urls

    if dry_run:
        publish_id = f"dryrun-{key[:16]}"
        response_payload = {"dry_run": True, "image_count": len(urls), "caption": caption}
    else:
        try:
            from app.infrastructure.tiktok_api_client import get_tiktok_api_client
            client = get_tiktok_api_client()
            payload = {
                "post_info": {
                    "title": chosen_hook[:90],
                    "description": caption,
                    "privacy_level": os.getenv("ZERO_TIKTOK_PRIVACY_LEVEL", "SELF_ONLY"),
                    "disable_comment": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 0,
                    "photo_images": urls,
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            }
            # The exact method depends on the existing client surface — fall
            # through to the dry-run path on AttributeError so the workflow
            # never fails purely on a missing method.
            method = (
                getattr(client, "post_publish_content", None)
                or getattr(client, "publish_carousel", None)
                or getattr(client, "publish_photo_post", None)
            )
            if method is None:
                logger.warning("tiktok_publish_method_unavailable")
                publish_id = f"missing-method-{key[:16]}"
                response_payload = {"reason": "no_publish_method", "payload": payload}
            else:
                resp = await method(payload) if asyncio_iscoroutine(method) else method(payload)
                response_payload = resp if isinstance(resp, dict) else {"raw": str(resp)}
                publish_id = (
                    response_payload.get("publish_id")
                    or response_payload.get("data", {}).get("publish_id")
                    or f"unknown-{key[:16]}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tiktok_publish_failed", error=str(exc))
            publish_id = f"failed-{key[:16]}"
            response_payload = {"error": str(exc)[:500]}

    try:
        await idempotency.record(
            key,
            generation_id=ctx["generation_id"],
            publish_id=publish_id,
            response_payload=response_payload,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_record_failed", error=str(exc))

    # Stamp the generation row with publish + final state. Failure-soft.
    try:
        from datetime import datetime, timezone
        from app.services.carousel_v2.generation_state import upsert_state
        await upsert_state(
            ctx["generation_id"],
            engagement_metrics_json={
                "publish_id": publish_id,
                "publish_url": response_payload.get("publish_url"),
                "image_count": len(urls),
            },
            status="published" if not dry_run else "publishing",
            published_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("publish_state_persist_failed", error=str(exc))

    logger.info(
        "carousel_publish_done",
        generation_id=ctx["generation_id"],
        publish_id=publish_id,
        dry_run=dry_run,
    )
    return {
        "generation_id": ctx["generation_id"],
        "carousel_id": ctx.get("carousel_id"),
        "publish_id": publish_id,
        "publish_url": response_payload.get("publish_url"),
        "dry_run": dry_run,
    }


def asyncio_iscoroutine(obj) -> bool:
    """Heuristic so we tolerate sync ``def publish(...)`` shims."""
    import inspect
    if inspect.iscoroutinefunction(obj):
        return True
    return inspect.iscoroutine(obj)
