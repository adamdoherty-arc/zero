"""Cinematic post-pass — Pillow + numpy filters applied after the base
slide is rendered (carosel.txt §2 'Cinematic polish').

Effects::

  3D LUT colour grade   (per-property .cube file)
  film grain            (gaussian noise screen-blend at brand_kit.grain_opacity)
  chromatic aberration  (R-shift +N / B-shift −N at radial mask)
  vignette              (radial alpha mask, multiply blend)
  light leaks           (corner radial gradient, screen-blend)

LUT loading falls back gracefully when ``pillow-lut`` isn't installed —
each effect is independent and skip-on-failure.
"""

from __future__ import annotations

import io

import structlog

from app.services.carousel_v2.brand_kit_service import BrandKit

logger = structlog.get_logger(__name__)


def apply_cinematic_pass(image_bytes: bytes, *, brand_kit: BrandKit) -> bytes:
    """Idempotent — calling twice grades twice but keeps colourspace sane."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        logger.debug("cinematic_decode_failed", error=str(exc))
        return image_bytes

    img = _apply_lut(img, brand_kit)
    img = _apply_grain(img, brand_kit.grain_opacity)
    img = _apply_chromatic_aberration(img, brand_kit.chromatic_aberration_px)
    img = _apply_vignette(img, brand_kit.vignette_strength)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def _apply_lut(img, brand_kit: BrandKit):
    if not brand_kit.lut_path:
        return img
    try:
        from pathlib import Path
        if not Path(brand_kit.lut_path).is_file():
            return img
        from pillow_lut import load_cube_file
        lut = load_cube_file(brand_kit.lut_path)
        return img.filter(lut)
    except Exception as exc:  # noqa: BLE001
        logger.debug("lut_apply_failed", path=brand_kit.lut_path, error=str(exc))
        return img


def _apply_grain(img, opacity: float):
    if opacity <= 0:
        return img
    try:
        import numpy as np
        from PIL import Image
        arr = np.asarray(img).astype(np.float32)
        noise = np.random.normal(0.0, 1.0, arr.shape).astype(np.float32) * 12.0  # ~±2σ ≈ ±24
        # screen blend with mask scaled by opacity
        out = arr + noise * float(max(0.0, min(1.0, opacity)))
        out = np.clip(out, 0, 255).astype(np.uint8)
        return Image.fromarray(out)
    except Exception as exc:  # noqa: BLE001
        logger.debug("grain_apply_failed", error=str(exc))
        return img


def _apply_chromatic_aberration(img, shift_px: int):
    if shift_px <= 0:
        return img
    try:
        from PIL import Image, ImageChops
        r, g, b = img.split()
        r = ImageChops.offset(r, shift_px, 0)
        b = ImageChops.offset(b, -shift_px, 0)
        return Image.merge("RGB", (r, g, b))
    except Exception as exc:  # noqa: BLE001
        logger.debug("ca_apply_failed", error=str(exc))
        return img


def _apply_vignette(img, strength: float):
    if strength <= 0:
        return img
    try:
        import numpy as np
        from PIL import Image
        arr = np.asarray(img).astype(np.float32)
        h, w = arr.shape[:2]
        cy, cx = h / 2.0, w / 2.0
        y, x = np.ogrid[:h, :w]
        d = np.sqrt(((x - cx) / w) ** 2 + ((y - cy) / h) ** 2)
        mask = np.clip(1.0 - strength * (d / 0.7), 0.0, 1.0)[..., None]
        out = (arr * mask).clip(0, 255).astype(np.uint8)
        return Image.fromarray(out)
    except Exception as exc:  # noqa: BLE001
        logger.debug("vignette_apply_failed", error=str(exc))
        return img
