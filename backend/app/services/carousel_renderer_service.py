"""
Carousel image renderer service.

Renders carousel slides as 1080x1350 PNG images suitable for TikTok posting.
Takes a character image + text overlay specs + slide text and composites them
into ready-to-publish carousel slide images.
"""

import asyncio
import io
import os
import re
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Iterable, Set

import aiohttp
import aiofiles
import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger()

# TikTok carousel dimensions
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350

# Output directory
RENDER_DIR = Path("/app/workspace/content/rendered")

# Non-breaking space used to hold compound terms together during text wrap.
_NBSP = "\u00A0"

# Compound terms that should never wrap across lines regardless of character.
_DEFAULT_NO_BREAK_TERMS: Tuple[str, ...] = (
    "The MCU",
    "Marvel Cinematic Universe",
    "Iron Man",
    "Captain America",
    "Black Widow",
    "Peter Parker",
    "Tony Stark",
    "Bruce Wayne",
    "Clark Kent",
    "Harley Quinn",
    "Doctor Strange",
    "X-Men",
    "Avengers: Endgame",
    "Infinity War",
    "Age of Ultron",
    "Star Wars",
    "Star Trek",
)

# Minimum WCAG AA contrast for normal text (4.5:1) and large text (3:1).
_WCAG_AA_NORMAL = 4.5
_WCAG_AA_LARGE = 3.0


class CarouselRendererService:
    """Renders carousel slides as ready-to-publish images."""

    def __init__(self):
        RENDER_DIR.mkdir(parents=True, exist_ok=True)

    async def render_carousel(
        self,
        carousel_id: str,
        slides: List[Dict[str, Any]],
        text_overlay_specs: List[Dict[str, Any]],
        character_image_url: Optional[str] = None,
        character_image_urls: Optional[List[str]] = None,
        no_break_terms: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """
        Render all slides of a carousel as PNG images.

        Returns dict with rendered file paths and metadata including
        per-slide render_warnings (compound breaks, contrast failures).
        """
        from PIL import Image, ImageDraw, ImageFont

        output_dir = RENDER_DIR / carousel_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Download fallback character image for slides without per-slide images
        fallback_bg = None
        urls_to_try = []
        if character_image_url:
            urls_to_try.append(character_image_url)
        if character_image_urls:
            urls_to_try.extend(character_image_urls)

        for url in urls_to_try[:5]:
            fallback_bg = await self._download_image(url)
            if fallback_bg:
                break

        # Download semaphore to limit concurrent image fetches
        dl_sem = asyncio.Semaphore(3)

        no_break_set = self._build_no_break_set(no_break_terms)

        rendered_paths = []
        render_warnings: List[Dict[str, Any]] = []
        for i, slide in enumerate(slides):
            slide_num = i + 1
            slide_text = slide.get("text", "")
            slide_title = slide.get("title", "")

            # Per-slide image: try slide.image_url first, then fallback
            slide_bg = None
            slide_image_url = slide.get("image_url")
            if slide_image_url:
                async with dl_sem:
                    slide_bg = await self._download_image(slide_image_url)
            if not slide_bg:
                slide_bg = fallback_bg

            # Find matching overlay spec
            spec = {}
            for s in text_overlay_specs:
                if s.get("slide_num") == slide_num:
                    spec = s
                    break

            # Render the slide (collects per-slide warnings).
            slide_warnings: List[Dict[str, Any]] = []
            img = self._render_slide(
                bg_image=slide_bg,
                slide_num=slide_num,
                total_slides=len(slides),
                title_text=slide_title,
                body_text=slide_text,
                text_position=spec.get("text_position", "center"),
                font_weight=spec.get("font_weight", "bold"),
                bg_overlay=spec.get("background_overlay"),
                text_color=spec.get("text_color", "#FFFFFF"),
                text_shadow=spec.get("text_shadow", True),
                no_break_terms=no_break_set,
                warnings_out=slide_warnings,
            )
            for w in slide_warnings:
                w.setdefault("slide_num", slide_num)
                render_warnings.append(w)

            # Save
            filename = f"slide_{slide_num:02d}.png"
            filepath = output_dir / filename
            img.save(str(filepath), "PNG", optimize=True)
            rendered_paths.append(str(filepath))

            logger.debug("slide_rendered", carousel_id=carousel_id, slide=slide_num, path=str(filepath))

        logger.info(
            "carousel_rendered",
            carousel_id=carousel_id,
            slides=len(rendered_paths),
            output_dir=str(output_dir),
            warnings=len(render_warnings),
        )

        return {
            "carousel_id": carousel_id,
            "rendered_slides": len(rendered_paths),
            "paths": rendered_paths,
            "output_dir": str(output_dir),
            "dimensions": f"{SLIDE_WIDTH}x{SLIDE_HEIGHT}",
            "render_warnings": render_warnings,
        }

    def _render_slide(
        self,
        bg_image: Optional[Any],
        slide_num: int,
        total_slides: int,
        title_text: str,
        body_text: str,
        text_position: str = "center",
        font_weight: str = "bold",
        bg_overlay: Optional[float] = None,
        text_color: str = "#FFFFFF",
        text_shadow: bool = True,
        no_break_terms: Optional[Set[str]] = None,
        warnings_out: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """Render a single carousel slide as a PIL Image.

        If `bg_overlay` is None the renderer computes a brightness-aware
        overlay so dark images get a light overlay and washed-out images
        get a stronger one (fixes the "all white" Aquaman case).
        """
        from PIL import Image, ImageDraw, ImageFont

        # Create base image
        if bg_image:
            img = self._fit_background(bg_image.copy(), SLIDE_WIDTH, SLIDE_HEIGHT)
        else:
            # Gradient background when no image
            img = self._create_gradient(SLIDE_WIDTH, SLIDE_HEIGHT)

        img_rgba = img.convert("RGBA")

        # Dynamic overlay strength based on text region luminance.
        text_region = self._text_region_for(text_position)
        computed_overlay, region_lum = self._compute_overlay_strength(img_rgba, text_region)
        effective_overlay = computed_overlay if bg_overlay is None else float(bg_overlay)
        effective_overlay = max(0.0, min(0.85, effective_overlay))

        overlay = Image.new("RGBA", (SLIDE_WIDTH, SLIDE_HEIGHT), (0, 0, 0, int(255 * effective_overlay)))
        img = Image.alpha_composite(img_rgba, overlay)
        draw = ImageDraw.Draw(img)

        # Load fonts
        title_font = self._get_font(size=52, weight="bold")
        body_font = self._get_font(size=40, weight=font_weight)
        number_font = self._get_font(size=64, weight="bold")
        counter_font = self._get_font(size=28, weight="normal")

        # Calculate text areas based on position
        margin_x = 80
        text_area_width = SLIDE_WIDTH - (margin_x * 2)

        if text_position == "top":
            y_start = 120
        elif text_position == "bottom":
            y_start = SLIDE_HEIGHT - 500
        else:  # center
            y_start = 280

        y = y_start

        # Slide number badge (large, left-aligned)
        if slide_num > 0:
            num_text = str(slide_num)
            if text_shadow:
                draw.text((margin_x + 2, y + 2), num_text, fill="#00000080", font=number_font)
            draw.text((margin_x, y), num_text, fill="#FFD700", font=number_font)
            y += 80

        # Title text (if present)
        if title_text:
            wrapped_title = self._wrap_text(
                title_text, title_font, text_area_width, draw,
                no_break_terms=no_break_terms, warnings_out=warnings_out,
            )
            for line in wrapped_title:
                if text_shadow:
                    draw.text((margin_x + 2, y + 2), line, fill="#00000080", font=title_font)
                draw.text((margin_x, y), line, fill=text_color, font=title_font)
                y += 62
            y += 20

        # Body text
        if body_text:
            wrapped_body = self._wrap_text(
                body_text, body_font, text_area_width, draw,
                no_break_terms=no_break_terms, warnings_out=warnings_out,
            )
            for line in wrapped_body[:12]:  # Max 12 lines
                if text_shadow:
                    draw.text((margin_x + 2, y + 2), line, fill="#00000080", font=body_font)
                draw.text((margin_x, y), line, fill=text_color, font=body_font)
                y += 52

        # Contrast validation (simulates the final composited text area luminance).
        try:
            composited_lum = self._region_luminance(img.convert("RGBA"), text_region)
            contrast = self._contrast_ratio(text_color, composited_lum)
            passes = contrast >= _WCAG_AA_NORMAL
            if warnings_out is not None:
                warnings_out.append({
                    "type": "contrast",
                    "contrast_ratio": round(contrast, 2),
                    "region_luminance_before": round(region_lum, 1),
                    "region_luminance_after": round(composited_lum, 1),
                    "effective_overlay": round(effective_overlay, 2),
                    "passes_wcag_aa": passes,
                })
        except (ValueError, ZeroDivisionError, AttributeError):
            pass

        # Slide counter at bottom
        counter_text = f"{slide_num} / {total_slides}"
        bbox = draw.textbbox((0, 0), counter_text, font=counter_font)
        counter_w = bbox[2] - bbox[0]
        draw.text(
            ((SLIDE_WIDTH - counter_w) // 2, SLIDE_HEIGHT - 60),
            counter_text,
            fill="#FFFFFF80",
            font=counter_font,
        )

        # Watermark / branding at bottom-right
        watermark_font = self._get_font(size=18, weight="normal")
        watermark_text = "Created by Zero"
        wm_bbox = draw.textbbox((0, 0), watermark_text, font=watermark_font)
        wm_w = wm_bbox[2] - wm_bbox[0]
        draw.text(
            (SLIDE_WIDTH - wm_w - 20, SLIDE_HEIGHT - 30),
            watermark_text,
            fill="#FFFFFF60",
            font=watermark_font,
        )

        return img.convert("RGB")

    def _fit_background(self, img: Any, width: int, height: int) -> Any:
        """Resize and crop image to fill the target dimensions."""
        from PIL import Image

        # Scale to fill
        img_ratio = img.width / img.height
        target_ratio = width / height

        if img_ratio > target_ratio:
            # Image is wider — fit height, crop width
            new_height = height
            new_width = int(height * img_ratio)
        else:
            # Image is taller — fit width, crop height
            new_width = width
            new_height = int(width / img_ratio)

        img = img.resize((new_width, new_height), Image.LANCZOS)

        # Center crop
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        img = img.crop((left, top, left + width, top + height))

        return img

    def _create_gradient(self, width: int, height: int) -> Any:
        """Create a dark gradient background."""
        from PIL import Image

        img = Image.new("RGB", (width, height))
        pixels = img.load()
        for y in range(height):
            r = int(15 + (y / height) * 25)
            g = int(10 + (y / height) * 15)
            b = int(30 + (y / height) * 40)
            for x in range(width):
                pixels[x, y] = (r, g, b)
        return img

    def _get_font(self, size: int = 40, weight: str = "bold") -> Any:
        """Get a font, falling back to default if system fonts unavailable."""
        from PIL import ImageFont

        # Try common system fonts
        font_candidates = []
        if weight == "bold":
            font_candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
        else:
            font_candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]

        for path in font_candidates:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)

        # Fallback to default
        return ImageFont.load_default(size=size)

    def _wrap_text(
        self,
        text: str,
        font: Any,
        max_width: int,
        draw: Any,
        no_break_terms: Optional[Set[str]] = None,
        warnings_out: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Wrap text to fit within max_width pixels.

        Preserves compound terms (e.g. "The MCU", "Black Widow") on one
        line by substituting an NBSP during split. If a compound cannot
        fit on any line, falls back to splitting and records a warning.
        """
        protected = self._protect_compounds(text, no_break_terms)
        words = protected.split()
        lines: List[str] = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line.replace(_NBSP, " "), font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            elif _NBSP in word and draw.textbbox((0, 0), word.replace(_NBSP, " "), font=font)[2] > max_width:
                # Compound term is alone too wide to fit: must break it.
                if current_line:
                    lines.append(current_line.replace(_NBSP, " "))
                broken = word.replace(_NBSP, " ")
                if warnings_out is not None:
                    warnings_out.append({
                        "type": "compound_break",
                        "term": broken,
                        "reason": "exceeds_line_width",
                    })
                # Fall back to naive word split for this compound.
                sub_line = ""
                for sub in broken.split():
                    test_sub = f"{sub_line} {sub}".strip()
                    b = draw.textbbox((0, 0), test_sub, font=font)
                    if b[2] - b[0] <= max_width:
                        sub_line = test_sub
                    else:
                        if sub_line:
                            lines.append(sub_line)
                        sub_line = sub
                current_line = sub_line
            else:
                if current_line:
                    lines.append(current_line.replace(_NBSP, " "))
                current_line = word

        if current_line:
            lines.append(current_line.replace(_NBSP, " "))

        return lines

    # ---------- helpers (compound wrap + dynamic overlay + contrast) ----------

    @staticmethod
    def _build_no_break_set(extras: Optional[Iterable[str]]) -> Set[str]:
        combined: Set[str] = set(_DEFAULT_NO_BREAK_TERMS)
        if extras:
            for term in extras:
                if isinstance(term, str) and term.strip():
                    combined.add(term.strip())
        return combined

    @staticmethod
    def _protect_compounds(text: str, terms: Optional[Set[str]]) -> str:
        """Replace spaces inside known compound terms with NBSP."""
        if not terms or not text:
            return text
        out = text
        # Longer terms first so "The MCU" beats "MCU" etc.
        for term in sorted(terms, key=len, reverse=True):
            if " " not in term:
                continue
            nb_term = term.replace(" ", _NBSP)
            out = re.sub(re.escape(term), nb_term, out, flags=re.IGNORECASE)
        return out

    @staticmethod
    def _text_region_for(position: str) -> Tuple[int, int, int, int]:
        """Return (left, top, right, bottom) of the expected text region."""
        if position == "top":
            return (0, 100, SLIDE_WIDTH, 600)
        if position == "bottom":
            return (0, SLIDE_HEIGHT - 520, SLIDE_WIDTH, SLIDE_HEIGHT - 100)
        return (0, 260, SLIDE_WIDTH, 900)

    @staticmethod
    def _region_luminance(img: Any, region: Tuple[int, int, int, int]) -> float:
        """Average perceived luminance (0-255) of a cropped region."""
        from PIL import ImageStat
        crop = img.crop(region).convert("RGB")
        stat = ImageStat.Stat(crop)
        r, g, b = stat.mean[:3]
        # Rec. 709 luma.
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _compute_overlay_strength(
        self, img: Any, region: Tuple[int, int, int, int]
    ) -> Tuple[float, float]:
        """Brightness-aware overlay. Darker regions need less overlay.

        Returns (overlay_alpha_0_to_1, region_luminance_0_to_255).
        """
        lum = self._region_luminance(img, region)
        # Map: lum=0  -> 0.35, lum=255 -> 0.70
        overlay = 0.35 + (lum / 255.0) * 0.35
        return overlay, lum

    @staticmethod
    def _srgb_to_linear(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    @classmethod
    def _relative_luminance(cls, hex_color: str) -> float:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        try:
            r = int(h[0:2], 16)
            g = int(h[2:4], 16)
            b = int(h[4:6], 16)
        except (ValueError, IndexError):
            r, g, b = 255, 255, 255
        return (
            0.2126 * cls._srgb_to_linear(r)
            + 0.7152 * cls._srgb_to_linear(g)
            + 0.0722 * cls._srgb_to_linear(b)
        )

    @classmethod
    def _contrast_ratio(cls, text_hex: str, bg_luminance_0_255: float) -> float:
        """WCAG contrast ratio between text color and a background luminance."""
        text_l = cls._relative_luminance(text_hex)
        bg_l = cls._srgb_to_linear(bg_luminance_0_255)
        lighter = max(text_l, bg_l)
        darker = min(text_l, bg_l)
        return (lighter + 0.05) / (darker + 0.05)

    async def _download_image(self, url: str) -> Optional[Any]:
        """Download an image from URL and return as PIL Image."""
        from PIL import Image

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
                    return Image.open(io.BytesIO(data))
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
            logger.debug("image_download_failed", url=url[:80], error=str(e))
            return None

    async def list_rendered(self, carousel_id: str) -> List[str]:
        """List rendered slide paths for a carousel."""
        output_dir = RENDER_DIR / carousel_id
        if not output_dir.exists():
            return []
        return sorted([str(p) for p in output_dir.glob("slide_*.png")])


@lru_cache()
def get_carousel_renderer() -> CarouselRendererService:
    """Get cached renderer instance."""
    return CarouselRendererService()
