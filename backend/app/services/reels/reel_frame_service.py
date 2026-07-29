"""Reel frame renderer — one 1080×1920 frame per scene, text baked in.

Self-contained (inline HTML/CSS via Playwright, Pillow fallback) so the
motivational typography is fully under our control and decoupled from the
franchise-specific carousel templates + brand kits. The baked text is why the
Phase-1 video-assembly stage needs no ASS/drawtext captions yet.

Background is a tasteful mood gradient by default; when a scene carries an
``image_url`` (AI/stock, Phase 2) it's used full-bleed under a legibility
scrim.
"""

from __future__ import annotations

import asyncio
import html
import io
import os
from typing import Optional, Sequence

import structlog

from app.models.reel import QuoteCard, ReelScene, SceneRole

logger = structlog.get_logger(__name__)


# Tasteful dark gradient palettes per mood (top, mid, bottom) — intentional,
# not "AI slop". Hex without the leading '#'.
MOOD_GRADIENTS = {
    "epic": ("0b1f3a", "0a1428", "000000"),
    "calm": ("1c2b33", "121d24", "05080a"),
    "hopeful": ("3a2a12", "241808", "0a0600"),
    "dark": ("16181c", "0c0d10", "000000"),
    "intense": ("3a0f12", "20080a", "070202"),
    "reflective": ("11302e", "0a1f1e", "030a09"),
    "uplifting": ("241a3a", "150f24", "05030a"),
}
_ACCENT = {
    "epic": "8ab4ff", "calm": "9fd0d6", "hopeful": "ffce85", "dark": "c9ccd6",
    "intense": "ff8a8a", "reflective": "7fd6c9", "uplifting": "b9a3ff",
}


def _grad(mood: str) -> tuple[str, str, str]:
    return MOOD_GRADIENTS.get(mood, MOOD_GRADIENTS["reflective"])


def _accent(mood: str) -> str:
    return _ACCENT.get(mood, "9fd0d6")


def _font_size_for(text: str, role: SceneRole) -> int:
    n = len(text)
    if role == SceneRole.HOOK:
        return 96 if n < 40 else (80 if n < 70 else 64)
    if role == SceneRole.CTA:
        return 78 if n < 40 else 62
    # quote / reveal / build
    return 104 if n < 30 else (88 if n < 60 else (72 if n < 100 else 58))


def _scene_html(scene: ReelScene, quote: QuoteCard, mood: str) -> str:
    top, mid, bot = _grad(mood)
    accent = _accent(mood)
    text = html.escape(scene.text or "")
    size = _font_size_for(scene.text or "", scene.role)

    if scene.image_url:
        bg = (
            f"background-image:linear-gradient(180deg, rgba(0,0,0,0.55), rgba(0,0,0,0.35) 40%, "
            f"rgba(0,0,0,0.75)), url('{html.escape(scene.image_url)}');"
            "background-size:cover;background-position:center;"
        )
    else:
        bg = f"background:linear-gradient(160deg,#{top} 0%,#{mid} 55%,#{bot} 100%);"

    # Role-specific extras.
    eyebrow = ""
    author_html = ""
    if scene.role == SceneRole.HOOK:
        eyebrow = f"<div class='eyebrow'>{html.escape((quote.sub_niche or 'motivation').replace('_',' ').upper())}</div>"
    if scene.role == SceneRole.QUOTE and quote.attribution.value == "verified" and quote.author:
        author_html = f"<div class='author'>— {html.escape(quote.author)}</div>"
    if scene.role == SceneRole.CTA:
        author_html = "<div class='swipe'>▲</div>"

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:1080px; height:1920px; overflow:hidden; }}
  .stage {{ width:1080px; height:1920px; {bg}
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    font-family:'Helvetica Neue',Arial,'DejaVu Sans',sans-serif; position:relative; }}
  .stage::after {{ content:''; position:absolute; inset:0;
    box-shadow:inset 0 0 320px 80px rgba(0,0,0,0.65); pointer-events:none; }}
  .eyebrow {{ color:#{accent}; font-size:34px; font-weight:700; letter-spacing:8px;
    margin-bottom:42px; opacity:0.92; }}
  .text {{ color:#f4f5f7; font-size:{size}px; font-weight:800; line-height:1.16;
    text-align:center; padding:0 96px; letter-spacing:-1px;
    text-shadow:0 4px 28px rgba(0,0,0,0.7); max-width:980px; }}
  .author {{ color:#{accent}; font-size:40px; font-weight:600; margin-top:54px;
    letter-spacing:1px; opacity:0.95; }}
  .swipe {{ color:#{accent}; font-size:54px; margin-top:60px; opacity:0.85;
    animation:none; }}
  .bar {{ position:absolute; left:0; right:0; bottom:0; height:10px;
    background:linear-gradient(90deg,#{accent},transparent); opacity:0.55; }}
</style></head>
<body><div class='stage'>{eyebrow}<div class='text'>{text}</div>{author_html}<div class='bar'></div></div></body></html>"""


async def render_scene_frames(
    scenes: Sequence[ReelScene], *, mood: str, quote: QuoteCard,
    max_concurrent: int = 4,
) -> list[bytes]:
    """Render each scene to a 1080×1920 JPEG. Playwright with Pillow fallback."""
    if not scenes:
        return []

    disable = os.getenv("ZERO_DISABLE_PLAYWRIGHT", "false").lower() in {"1", "true", "yes"}
    if not disable:
        try:
            frames = await _render_playwright(scenes, mood=mood, quote=quote,
                                              max_concurrent=max_concurrent)
            if frames and all(frames):
                return frames
        except Exception as exc:  # noqa: BLE001
            logger.warning("reel_frames_playwright_failed", error=str(exc))

    return [_pillow_frame(sc, quote, mood) for sc in scenes]


async def _render_playwright(
    scenes: Sequence[ReelScene], *, mood: str, quote: QuoteCard, max_concurrent: int,
) -> list[bytes]:
    from playwright.async_api import async_playwright

    sem = asyncio.Semaphore(max_concurrent)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--font-render-hinting=none"])
        try:
            async def _one(sc: ReelScene) -> bytes:
                async with sem:
                    ctx = await browser.new_context(
                        viewport={"width": 1080, "height": 1920}, device_scale_factor=1
                    )
                    page = await ctx.new_page()
                    page.set_default_timeout(30_000)
                    try:
                        try:
                            await page.set_content(_scene_html(sc, quote, mood),
                                                   wait_until="networkidle")
                        except Exception:  # noqa: BLE001
                            await page.set_content(_scene_html(sc, quote, mood),
                                                   wait_until="load")
                        try:
                            await page.evaluate("() => document.fonts.ready")
                        except Exception:  # noqa: BLE001
                            pass
                        png = await page.screenshot(type="jpeg", quality=92, full_page=False)
                        return png
                    finally:
                        await ctx.close()

            return await asyncio.gather(*(_one(s) for s in scenes))
        finally:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Pillow fallback — gradient + centered bold wrapped text + author.
# ---------------------------------------------------------------------------

def _hex(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _pillow_frame(scene: ReelScene, quote: QuoteCard, mood: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1080, 1920
    top, _mid, bot = (_hex(c) for c in _grad(mood))
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)

    draw = ImageDraw.Draw(img)
    size = _font_size_for(scene.text or "", scene.role)
    font = _load_font(size)
    text = scene.text or ""
    wrapped = _wrap(text, font=font, max_width=W - 200, draw=draw)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=14, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(((W - tw) // 2, (H - th) // 2), wrapped, font=font,
                        fill=(244, 245, 247), spacing=14, align="center")

    if scene.role == SceneRole.QUOTE and quote.attribution.value == "verified" and quote.author:
        afont = _load_font(40)
        atext = f"— {quote.author}"
        ab = draw.textbbox((0, 0), atext, font=afont)
        draw.text(((W - (ab[2] - ab[0])) // 2, (H + th) // 2 + 40), atext,
                  font=afont, fill=_hex(_accent(mood)))

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _load_font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _wrap(text: str, *, font, max_width: int, draw) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        bb = draw.textbbox((0, 0), cand, font=font)
        if bb[2] - bb[0] > max_width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return "\n".join(lines)
