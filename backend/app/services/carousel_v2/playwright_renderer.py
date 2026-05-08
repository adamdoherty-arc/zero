"""Playwright + Jinja2 + Tailwind slide renderer (carosel.txt §2).

Renders one slide HTML through a single shared Chromium browser per
``render_slides_concurrent`` call, screenshots it at 1080×1920, and pipes
through the cinematic post-pass for grain / vignette / chromatic aberration.

Phase 5 ships the three load-bearing templates: hook, fact, cta. The other
six (fact_overlay, comparison, quote, reveal_blur, easter_egg, tier) follow
the same shape and slot in without code changes — drop a new file under
``templates/`` and pass its name as ``Slide.template``.

When Playwright isn't available (no Chromium download yet) the renderer
falls back to a minimal Pillow path that still produces a 1080×1920 JPEG so
the workflow never blocks.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
from pathlib import Path

import structlog

from app.services.carousel_v2.brand_kit_service import BrandKit, get_brand_kit
from app.services.carousel_v2.cinematic_pass import apply_cinematic_pass

logger = structlog.get_logger(__name__)


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _jinja_env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _render_html(*, template: str, kit: BrandKit, slide_num: int, text: str,
                 image_url: str, transition: str | None, sub: str | None) -> str:
    """Pure Jinja render — no I/O, kept separate so it's easily unit-testable."""
    template_name = f"{template}.html"
    if not (TEMPLATES_DIR / template_name).is_file():
        template_name = "fact.html"
    # Conditionals below must check the *resolved* template (which may differ
    # from the requested one after fallback), not the original parameter.
    resolved = template_name[:-5]  # strip ".html"
    env = _jinja_env()
    return env.get_template(template_name).render(
        kit=kit,
        text=text,
        image_url=image_url,
        transition=transition,
        sub=sub,
        number=str(slide_num).zfill(2) if resolved == "fact" else None,
        badge=str(slide_num).zfill(2) if resolved == "hook" else None,
    )


async def render_slide(
    *,
    template: str,
    slide_num: int,
    text: str,
    image_url: str,
    transition: str | None = None,
    sub: str | None = None,
    brand_kit_key: str | None = None,
) -> bytes:
    """Render a single slide → 1080×1920 JPEG bytes (post-cinematic-pass).

    Spins up a one-shot browser. For multi-slide carousels prefer
    ``render_slides_concurrent`` which shares one browser across all slides.
    """
    kit = get_brand_kit(brand_kit_key)
    html = _render_html(
        template=template, kit=kit, slide_num=slide_num, text=text,
        image_url=image_url, transition=transition, sub=sub,
    )
    raw = await _render_via_browser_oneshot(html, text_fallback=text, kit=kit)
    return apply_cinematic_pass(raw, brand_kit=kit)


async def render_slides_concurrent(
    slides: list[dict],
    *,
    brand_kit_key: str | None,
    max_concurrent: int = 4,
) -> list[bytes]:
    """Render N slides through ONE shared Chromium browser, max_concurrent
    pages in flight. Saves ~500 ms × N on cold-start.
    """
    if not slides:
        return []

    kit = get_brand_kit(brand_kit_key)

    if os.getenv("ZERO_DISABLE_PLAYWRIGHT", "false").lower() in {"1", "true", "yes"}:
        return [
            apply_cinematic_pass(
                _pillow_fallback(s.get("text", ""), kit=kit),
                brand_kit=kit,
            )
            for s in slides
        ]

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [
            apply_cinematic_pass(
                _pillow_fallback(s.get("text", ""), kit=kit),
                brand_kit=kit,
            )
            for s in slides
        ]

    sem = asyncio.Semaphore(max_concurrent)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--font-render-hinting=none"])

            async def _one(slide: dict) -> bytes:
                async with sem:
                    html = _render_html(
                        template=slide.get("template", "fact"),
                        kit=kit,
                        slide_num=int(slide.get("slide_num", 1)),
                        text=slide.get("text", ""),
                        image_url=slide.get("image_url", ""),
                        transition=slide.get("transition_to_next"),
                        sub=slide.get("sub"),
                    )
                    return await _render_in_existing_browser(browser, html, slide.get("text", ""), kit)

            try:
                results = await asyncio.gather(*(_one(s) for s in slides))
            finally:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass

            return [apply_cinematic_pass(r, brand_kit=kit) for r in results]
    except Exception as exc:  # noqa: BLE001
        logger.warning("playwright_batch_failed", error=str(exc))
        return [
            apply_cinematic_pass(
                _pillow_fallback(s.get("text", ""), kit=kit),
                brand_kit=kit,
            )
            for s in slides
        ]


async def _render_in_existing_browser(browser, html: str, text_fallback: str, kit: BrandKit) -> bytes:
    """Fast path used by ``render_slides_concurrent`` — reuses one browser."""
    try:
        ctx = await browser.new_context(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page = await ctx.new_page()
        page.set_default_timeout(30_000)  # cap network/load waits at 30s
        try:
            await page.set_content(html, wait_until="networkidle")
        except Exception:  # noqa: BLE001
            # ``networkidle`` can time out on slow CDN images; ``load`` is enough.
            await page.set_content(html, wait_until="load")
        try:
            # Arrow-fn form so Playwright awaits the returned Promise.
            await page.evaluate("() => document.fonts.ready")
        except Exception:  # noqa: BLE001
            pass
        png = await page.screenshot(type="jpeg", quality=92, full_page=False)
        await ctx.close()
        return png
    except Exception as exc:  # noqa: BLE001
        logger.warning("playwright_page_failed", error=str(exc))
        return _pillow_fallback(text_fallback, kit=kit)


async def _render_via_browser_oneshot(html: str, *, text_fallback: str, kit: BrandKit) -> bytes:
    if os.getenv("ZERO_DISABLE_PLAYWRIGHT", "false").lower() in {"1", "true", "yes"}:
        return _pillow_fallback(text_fallback, kit=kit)
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return _pillow_fallback(text_fallback, kit=kit)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--font-render-hinting=none"])
            try:
                return await _render_in_existing_browser(browser, html, text_fallback, kit)
            finally:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("playwright_oneshot_failed", error=str(exc))
        return _pillow_fallback(text_fallback, kit=kit)


def _pillow_fallback(text: str, *, kit: BrandKit) -> bytes:
    """Brand-coloured 1080×1920 with the slide text centered.

    Takes ``text`` (the slide's visible string) directly — no HTML stripping,
    so we never paint CSS noise as visible text.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return b""

    img = Image.new("RGB", (1080, 1920), kit.bg)
    draw = ImageDraw.Draw(img)
    safe_text = _clean_for_render(text)[:200]
    font = _load_font(64)
    if safe_text:
        # Cheap word-wrap so long hooks don't overflow.
        wrapped = _wrap(safe_text, font=font, max_width=900, draw=draw)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=12)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.multiline_text(
            ((1080 - w) // 2, (1920 - h) // 2),
            wrapped,
            font=font,
            fill=kit.fg,
            spacing=12,
        )
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


def _load_font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSans-Bold.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _clean_for_render(text: str) -> str:
    """Strip HTML tags + whitespace + the [fact_id:N] citations so the
    fallback paints clean visible text.
    """
    if not text:
        return ""
    txt = re.sub(r"<[^>]+>", " ", text)
    txt = re.sub(r"\[fact_id:[A-Za-z0-9_-]+\]", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _wrap(text: str, *, font, max_width: int, draw) -> str:
    """Greedy word-wrap to fit ``max_width`` per line."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = bbox[2] - bbox[0]
        if width > max_width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return "\n".join(lines)
