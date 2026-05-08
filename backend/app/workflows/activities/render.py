"""Render activity — Pillow + numpy LUT/grain/vignette pre-stage → Jinja2 +
Tailwind + Playwright per-slide render → 1080×1920 JPEG outputs uploaded to
MinIO/R2 ready for TikTok ``PULL_FROM_URL``.

Phase 5 implementation: picks the kept image per slide from the funnel,
renders through ``playwright_renderer.render_slide``, applies the cinematic
post-pass, uploads to R2 (or MinIO fallback), and writes the public URLs
back onto the workflow context.
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


def _pick_image_for_slide(scored: list[dict], slide_num: int) -> str | None:
    """Round-robin from the kept-and-ranked images. Slide 1 takes the top
    image, the rest cycle through the remainder so we don't repeat the same
    photo.
    """
    kept = [s for s in scored if s.get("kept")]
    kept.sort(key=lambda s: (s.get("rank") if s.get("rank") is not None else 99))
    if not kept:
        return None
    idx = (slide_num - 1) % len(kept)
    return kept[idx].get("upscaled_url") or kept[idx].get("source_url")


@activity.defn
async def render_slides(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "render", "generation_id": ctx["generation_id"]})

    from app.services.carousel_v2 import playwright_renderer, r2_uploader

    slides = ctx.get("slides", []) or []
    scored_images = ctx.get("scored_images", []) or []
    if not slides:
        ctx["rendered_image_urls"] = []
        return ctx

    # Decorate slides with chosen images.
    enriched = []
    for slide in slides:
        s = dict(slide)
        s["image_url"] = _pick_image_for_slide(scored_images, s.get("slide_num", 1)) or ""
        enriched.append(s)

    brand_kit_key = (ctx.get("franchise") or "mcu").lower().replace(" ", "_")
    rendered = await playwright_renderer.render_slides_concurrent(
        enriched, brand_kit_key=brand_kit_key, max_concurrent=4
    )

    public_urls: list[str] = []
    image_hashes: list[str] = []
    for slide_num, body in enumerate(rendered, start=1):
        if not body:
            continue
        sha = hashlib.sha256(body).hexdigest()
        image_hashes.append(sha)
        key = r2_uploader.make_key(generation_id=ctx["generation_id"], slide_num=slide_num)
        try:
            url = await r2_uploader.upload_image(body=body, key=key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("render_upload_failed", slide=slide_num, error=str(exc))
            continue
        public_urls.append(url)

    ctx["rendered_image_urls"] = public_urls
    ctx["rendered_image_sha256"] = image_hashes
    logger.info(
        "carousel_render_done",
        generation_id=ctx["generation_id"],
        rendered=len(public_urls),
    )
    return ctx
