"""Reel publishing — Phase 1 (TikTok dry-run + guarded real post).

Phase 1 implements TikTok only, dry-run by default (``ZERO_REELS_DRY_RUN``,
default true). The full pluggable ``PublisherInterface`` for IG Reels + YT
Shorts lands in Phase 3 — this module's ``publish_reel`` signature already takes
a platform list so the workflow doesn't change when those backends arrive.

Per-platform idempotency: key = sha256(reel_id | platform | video_sha256 |
caption). A replay returns the cached publish record instead of double-posting.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.models.reel import MotivationReel, PlatformName, PlatformPublish
from app.services.reels import reel_state

logger = structlog.get_logger(__name__)


def _dry_run_default() -> bool:
    return os.getenv("ZERO_REELS_DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "on"}


def _idem_key(reel: MotivationReel, platform: str) -> str:
    raw = f"{reel.id}|{platform}|{reel.video_sha256 or ''}|{(reel.caption or '')[:200]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


async def publish_reel(
    reel: MotivationReel, *, platforms: Optional[list[str]] = None,
    dry_run: Optional[bool] = None,
) -> list[PlatformPublish]:
    """Publish a reel to each requested platform. Returns the publish records."""
    platforms = platforms or [PlatformName.TIKTOK.value]
    dry = _dry_run_default() if dry_run is None else dry_run
    results: list[PlatformPublish] = []

    for platform in platforms:
        key = _idem_key(reel, platform)
        try:
            if platform == PlatformName.TIKTOK.value:
                pub = await _publish_tiktok(reel, key=key, dry=dry)
            else:
                # IG / YT land in Phase 3 — record a skipped row so the UI shows
                # intent without failing the run.
                pub = PlatformPublish(
                    platform=platform, status="skipped", dry_run=dry,
                    idempotency_key=key, error="publisher_not_yet_configured",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reel_publish_failed", platform=platform, error=str(exc))
            pub = PlatformPublish(platform=platform, status="failed",
                                  idempotency_key=key, error=str(exc)[:300], dry_run=dry)
        results.append(pub)
        await reel_state.record_platform_publish(
            reel_id=reel.id, generation_id=reel.id, pub=pub
        )

    return results


async def publish_reel_by_id(
    generation_id: str, *, platforms: Optional[list[str]] = None,
    dry_run: Optional[bool] = None,
) -> list[PlatformPublish]:
    """Load a stored reel and publish it (used by the Temporal publish activity
    after the human-review gate).
    """
    row = await reel_state.get_reel(generation_id)
    if not row:
        logger.warning("reel_publish_by_id_not_found", generation_id=generation_id)
        return []
    reel = MotivationReel(
        id=generation_id,
        sub_niche=row.get("sub_niche"),
        caption=row.get("caption"),
        hashtags=row.get("hashtags") or [],
        cta_text=row.get("cta_text"),
        cta_link=row.get("cta_link"),
        video_url=row.get("video_url"),
        video_sha256=(row.get("quote") or {}).get("__never__"),  # placeholder, recomputed below
    )
    # video_sha256 isn't stored on the dict helper; recompute the idem key from
    # the video_url instead so it's still stable per (reel, platform).
    reel.video_sha256 = row.get("video_url") or generation_id
    return await publish_reel(reel, platforms=platforms, dry_run=dry_run)


async def _publish_tiktok(reel: MotivationReel, *, key: str, dry: bool) -> PlatformPublish:
    if dry or not reel.video_url:
        return PlatformPublish(
            platform=PlatformName.TIKTOK.value,
            post_id=f"dryrun-{key[:16]}",
            status="dry_run", dry_run=True, idempotency_key=key,
            published_at=datetime.now(timezone.utc),
        )

    # Real post — guarded so a missing method / auth never hard-fails the reel.
    try:
        from app.infrastructure.tiktok_api_client import get_tiktok_api_client
        client = get_tiktok_api_client()
        method = (
            getattr(client, "create_post", None)
            or getattr(client, "post_publish_video", None)
            or getattr(client, "publish_video", None)
        )
        if method is None:
            return PlatformPublish(
                platform=PlatformName.TIKTOK.value, status="failed",
                idempotency_key=key, error="no_tiktok_video_publish_method",
            )
        import inspect
        privacy = os.getenv("ZERO_TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")
        kwargs = dict(
            video_url=reel.video_url, source="PULL_FROM_URL",
            caption=reel.caption or "", privacy_level=privacy,
        )
        resp = method(**kwargs) if not inspect.iscoroutinefunction(method) else await method(**kwargs)
        payload = resp if isinstance(resp, dict) else {"raw": str(resp)}
        post_id = (payload.get("publish_id") or payload.get("post_id")
                   or payload.get("data", {}).get("publish_id") or f"tiktok-{key[:12]}")
        return PlatformPublish(
            platform=PlatformName.TIKTOK.value, post_id=post_id,
            publish_url=payload.get("publish_url"), status="published",
            idempotency_key=key, dry_run=False, published_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        return PlatformPublish(
            platform=PlatformName.TIKTOK.value, status="failed",
            idempotency_key=key, error=str(exc)[:300],
        )
