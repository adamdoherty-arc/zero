"""
Carousel image renderer service.

Renders carousel slides as 1080x1350 PNG images suitable for TikTok posting.
Takes a character image + text overlay specs + slide text and composites them
into ready-to-publish carousel slide images.
"""

import asyncio
import io
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

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
    ) -> Dict[str, Any]:
        """
        Render all slides of a carousel as PNG images.

        Returns dict with rendered file paths and metadata.
        """
        from PIL import Image, ImageDraw, ImageFont

        output_dir = RENDER_DIR / carousel_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Download character image(s) for background
        bg_image = None
        urls_to_try = []
        if character_image_url:
            urls_to_try.append(character_image_url)
        if character_image_urls:
            urls_to_try.extend(character_image_urls)

        for url in urls_to_try[:5]:
            bg_image = await self._download_image(url)
            if bg_image:
                break

        rendered_paths = []
        for i, slide in enumerate(slides):
            slide_num = i + 1
            slide_text = slide.get("text", "")
            slide_title = slide.get("title", "")

            # Find matching overlay spec
            spec = {}
            for s in text_overlay_specs:
                if s.get("slide_num") == slide_num:
                    spec = s
                    break

            # Render the slide
            img = self._render_slide(
                bg_image=bg_image,
                slide_num=slide_num,
                total_slides=len(slides),
                title_text=slide_title,
                body_text=slide_text,
                text_position=spec.get("text_position", "center"),
                font_weight=spec.get("font_weight", "bold"),
                bg_overlay=spec.get("background_overlay", 0.45),
                text_color=spec.get("text_color", "#FFFFFF"),
                text_shadow=spec.get("text_shadow", True),
            )

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
        )

        return {
            "carousel_id": carousel_id,
            "rendered_slides": len(rendered_paths),
            "paths": rendered_paths,
            "output_dir": str(output_dir),
            "dimensions": f"{SLIDE_WIDTH}x{SLIDE_HEIGHT}",
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
        bg_overlay: float = 0.45,
        text_color: str = "#FFFFFF",
        text_shadow: bool = True,
    ) -> Any:
        """Render a single carousel slide as a PIL Image."""
        from PIL import Image, ImageDraw, ImageFont

        # Create base image
        if bg_image:
            img = self._fit_background(bg_image.copy(), SLIDE_WIDTH, SLIDE_HEIGHT)
        else:
            # Gradient background when no image
            img = self._create_gradient(SLIDE_WIDTH, SLIDE_HEIGHT)

        draw = ImageDraw.Draw(img)

        # Apply dark overlay for text readability
        overlay = Image.new("RGBA", (SLIDE_WIDTH, SLIDE_HEIGHT), (0, 0, 0, int(255 * bg_overlay)))
        img = Image.alpha_composite(img.convert("RGBA"), overlay)
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
            wrapped_title = self._wrap_text(title_text, title_font, text_area_width, draw)
            for line in wrapped_title:
                if text_shadow:
                    draw.text((margin_x + 2, y + 2), line, fill="#00000080", font=title_font)
                draw.text((margin_x, y), line, fill=text_color, font=title_font)
                y += 62
            y += 20

        # Body text
        if body_text:
            wrapped_body = self._wrap_text(body_text, body_font, text_area_width, draw)
            for line in wrapped_body[:12]:  # Max 12 lines
                if text_shadow:
                    draw.text((margin_x + 2, y + 2), line, fill="#00000080", font=body_font)
                draw.text((margin_x, y), line, fill=text_color, font=body_font)
                y += 52

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

    def _wrap_text(self, text: str, font: Any, max_width: int, draw: Any) -> List[str]:
        """Wrap text to fit within max_width pixels."""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines

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
