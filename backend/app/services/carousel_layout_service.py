"""Carousel layout + effect + sticker picker.

Given a carousel, its brand kit, and the font style per slide, pick per-slide:
  - layout (where the text sits on the slide)
  - text_effects (stroke, gradient, rotation, etc.)
  - stickers (0-2 sticker specs per slide)
  - image_treatment (which Pillow/OpenCV effect to apply)

The layout picker guarantees no two consecutive slides use the same layout,
and the hook + final slides get punchy layouts. All randomness is seeded on
carousel_id so re-renders are stable.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Layout catalog
# ---------------------------------------------------------------------------

LAYOUTS = [
    "center", "top", "bottom", "bottom_boxed", "top_boxed",
    "left", "right", "diagonal", "split_top", "split_bottom",
    "corner_tl", "corner_br", "full_overlay", "quote_card",
    "stat_hero", "minimal_tape",
]

# Layouts best for the hook slide (slide 1) — bigger, centered, punchy.
HOOK_LAYOUTS = ["center", "full_overlay", "top_boxed", "stat_hero", "quote_card"]

# Layouts best for the final slide — loops the viewer to rewatch.
FINAL_LAYOUTS = ["full_overlay", "bottom_boxed", "stat_hero", "center"]

# Layouts that pair well with stat-heavy slides.
STAT_LAYOUTS = ["stat_hero", "corner_tl", "corner_br", "split_top"]

# Layouts that pair well with quote slides.
QUOTE_LAYOUTS = ["quote_card", "center", "bottom_boxed"]


# ---------------------------------------------------------------------------
# Layout rotation picker
# ---------------------------------------------------------------------------


def pick_layout_rotation(
    slides: List[Dict[str, Any]],
    brand_kit: Optional[Dict[str, Any]],
    hook_style: Optional[str] = None,
    carousel_id: str = "",
) -> List[str]:
    """Return one layout name per slide.

    Rules:
      - slide 0 (hook) -> HOOK_LAYOUTS
      - slides classified as "stat" (font_style=display-stat/display-mono) -> STAT_LAYOUTS
      - slides classified as "quote" (font_style=display-quote/display-serif) -> QUOTE_LAYOUTS
      - final slide -> FINAL_LAYOUTS
      - no two consecutive slides share a layout
      - brand_kit.default_layout_rotation is used as the preferred pool
    """
    if not slides:
        return []

    rng = random.Random(f"layout:{carousel_id}")
    preferred_pool: List[str] = (
        (brand_kit or {}).get("default_layout_rotation")
        or list(LAYOUTS)
    )

    result: List[str] = []
    for i, slide in enumerate(slides):
        font_style = (slide.get("font_style") or "").lower()
        is_hook = (i == 0)
        is_final = (i == len(slides) - 1)

        if is_hook:
            pool = HOOK_LAYOUTS
        elif is_final:
            pool = FINAL_LAYOUTS
        elif font_style in ("display-stat", "display-mono"):
            pool = STAT_LAYOUTS
        elif font_style in ("display-quote", "display-serif", "display-slab"):
            pool = QUOTE_LAYOUTS
        else:
            pool = preferred_pool

        # Filter out the previous layout to avoid consecutive repeats.
        if result:
            filtered = [l for l in pool if l != result[-1]]
            if filtered:
                pool = filtered
        choice = rng.choice(pool)
        result.append(choice)

    return result


# ---------------------------------------------------------------------------
# Text effects picker
# ---------------------------------------------------------------------------

ALL_TEXT_EFFECTS = ["outline", "gradient_fill", "rotation", "redacted", "neon_glow"]


def pick_text_effects(
    layout: str,
    font_style: Optional[str],
    brand_kit: Optional[Dict[str, Any]],
    carousel_id: str = "",
    slide_num: int = 0,
) -> List[str]:
    """Return 0-2 text effects for a slide.

    - Brand kit's declared `text_effects` is the preferred pool.
    - Hook slides get a higher chance of effects than body slides.
    - Certain layouts auto-imply certain effects (e.g. diagonal -> rotation).
    """
    rng = random.Random(f"effects:{carousel_id}:{slide_num}")
    kit_effects = (brand_kit or {}).get("text_effects") or ["outline"]
    pool = [e for e in kit_effects if e in ALL_TEXT_EFFECTS]
    if not pool:
        pool = ["outline"]

    picks: List[str] = []

    # Auto-imply
    if layout == "diagonal" and "rotation" in ALL_TEXT_EFFECTS:
        picks.append("rotation")

    # Hook slides almost always get an outline for legibility; body slides 60%.
    threshold = 0.95 if slide_num == 0 else 0.6
    if "outline" in pool and "outline" not in picks and rng.random() < threshold:
        picks.append("outline")

    # 20% chance of layering a second effect (glow or gradient)
    if rng.random() < 0.2:
        extras = [e for e in pool if e not in picks]
        if extras:
            picks.append(rng.choice(extras))

    return picks


# ---------------------------------------------------------------------------
# Sticker picker
# ---------------------------------------------------------------------------

# Sticker library — types consumed by carousel_renderer_service.
_STICKER_HOOK_POOL = ["pill", "tape", "badge"]
_STICKER_MID_POOL  = ["circle_highlight", "tape", "badge", "polaroid_frame"]
_STICKER_FINAL_POOL = ["arrow", "redacted_bar", "tape", "badge"]

# Vibe-specific tape labels. Picked for flavor when a tape sticker fires.
TAPE_TEXT_BY_VIBE: Dict[str, List[str]] = {
    "chaos":    ["LEAKED", "CHAOS", "UNHINGED", "CLASSIFIED"],
    "noir":     ["EVIDENCE", "CASE CLOSED", "CONFIDENTIAL", "EXHIBIT A"],
    "heroic":   ["EXCLUSIVE", "HEADLINES", "NEW", "SPOTTED"],
    "gothic":   ["FORBIDDEN", "WARNING", "ARCANE", "SEALED"],
    "horror":   ["DO NOT OPEN", "WARNING", "WITNESSED", "EVIDENCE"],
    "fantasy":  ["CHRONICLE", "LEGEND", "SCROLL", "TOME"],
    "anime":    ["CANON", "SPOILER", "REVEALED", "ARC"],
    "tech":     ["ENCRYPTED", "DATA", "ACCESS", "SYS_READ"],
    "cosmic":   ["COSMIC", "BEYOND", "INFINITY"],
    "trickster":["MAYBE", "NEVER SAY", "OR IS IT?"],
    "minimal":  ["NEW", "HOT", "WATCH"],
}

BADGE_TEXT_BY_VIBE: Dict[str, List[str]] = {
    "chaos":    ["SPOILER", "UNHINGED", "NEW"],
    "noir":     ["LEAKED", "EVIDENCE", "EXCLUSIVE"],
    "heroic":   ["NEW", "HOT", "EXCLUSIVE"],
    "gothic":   ["RARE", "ANCIENT", "FORBIDDEN"],
    "horror":   ["CURSED", "WARNING", "BLOOD"],
    "fantasy":  ["LORE", "RARE", "OLD"],
    "anime":    ["CANON", "SHONEN", "ARC"],
    "tech":     ["v2.0", "BETA", "BUILD"],
    "cosmic":   ["LVL MAX", "GOD TIER"],
    "trickster":["MAYBE", "?"],
    "minimal":  ["NEW"],
}


def pick_stickers(
    slide_index: int,
    total_slides: int,
    brand_kit: Optional[Dict[str, Any]],
    carousel_id: str = "",
    layout: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return 0-2 sticker spec dicts for a slide.

    Sticker dict shape: {type, x, y, rotation, text, color, scale}
    Coordinates x,y are normalized 0-1 relative to the 1080x1350 canvas.
    The renderer dereferences them to pixels.
    """
    rng = random.Random(f"stickers:{carousel_id}:{slide_index}")
    kit = brand_kit or {}
    vibe = (kit.get("vibe") or "minimal").lower()
    style = (kit.get("sticker_style") or vibe or "minimal").lower()

    # Base trigger probability, boosted for chaos/noir/horror vibes.
    base_p = 0.35
    if vibe in ("chaos", "noir", "horror", "gothic"):
        base_p = 0.55
    elif vibe in ("minimal",):
        base_p = 0.2
    if rng.random() > base_p:
        return []

    is_hook = slide_index == 0
    is_final = slide_index == total_slides - 1
    if is_hook:
        pool = _STICKER_HOOK_POOL
    elif is_final:
        pool = _STICKER_FINAL_POOL
    else:
        pool = _STICKER_MID_POOL

    sticker_type = rng.choice(pool)

    palette = kit.get("palette") or {}
    accent = palette.get("primary") or "#FFD54F"

    # Build sticker spec by type
    spec: Dict[str, Any] = {
        "type": sticker_type,
        "scale": round(rng.uniform(0.85, 1.2), 2),
        "rotation": rng.choice([-8, -5, -3, 0, 3, 5, 8]),
        "color": accent,
    }

    # Corner positions (normalized). Avoid dead-center so stickers don't
    # collide with main text.
    corner = rng.choice([
        (0.08, 0.08), (0.82, 0.08), (0.08, 0.82), (0.82, 0.82),
        (0.5, 0.08), (0.5, 0.90), (0.08, 0.5), (0.82, 0.5),
    ])
    spec["x"], spec["y"] = corner

    if sticker_type == "tape":
        labels = TAPE_TEXT_BY_VIBE.get(vibe) or TAPE_TEXT_BY_VIBE["minimal"]
        spec["text"] = rng.choice(labels)
    elif sticker_type == "badge":
        labels = BADGE_TEXT_BY_VIBE.get(vibe) or BADGE_TEXT_BY_VIBE["minimal"]
        spec["text"] = rng.choice(labels)
    elif sticker_type == "pill":
        spec["text"] = (kit.get("name") or "").split(" ")[0].upper()[:10] or "NEW"
    elif sticker_type == "circle_highlight":
        spec["text"] = None
    elif sticker_type == "arrow":
        spec["text"] = None
    elif sticker_type == "redacted_bar":
        spec["text"] = "[REDACTED]"
    elif sticker_type == "polaroid_frame":
        spec["text"] = None
    elif sticker_type == "comic_panel_border":
        spec["text"] = None
    elif sticker_type == "torn_edge":
        spec["text"] = None

    # 25% chance of a second, smaller sticker (e.g. a pill + a small arrow).
    out = [spec]
    if rng.random() < 0.25:
        secondary_type = rng.choice([t for t in pool if t != sticker_type])
        out.append({
            "type": secondary_type,
            "scale": round(rng.uniform(0.6, 0.9), 2),
            "rotation": rng.choice([-6, -3, 0, 3, 6]),
            "color": (palette.get("accent_neon") or palette.get("secondary") or accent),
            "x": round(rng.uniform(0.1, 0.9), 2),
            "y": round(rng.uniform(0.1, 0.9), 2),
            "text": None,
        })
    return out


# ---------------------------------------------------------------------------
# Image treatment picker
# ---------------------------------------------------------------------------


def pick_image_treatment(
    slide_index: int,
    brand_kit: Optional[Dict[str, Any]],
    carousel_id: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Pick the image treatment + params for a slide.

    Rotates through the kit's `image_treatments` pool by (slide_index + hash).
    Hook slides get a slightly stronger param tweak where applicable.
    """
    kit = brand_kit or {}
    pool: List[str] = kit.get("image_treatments") or ["cinematic"]
    if not pool:
        return ("none", {})
    rng = random.Random(f"treatment:{carousel_id}:{slide_index}")
    # Start from a seeded offset so different carousels don't always pick the
    # same first treatment for slide 0.
    offset = rng.randint(0, max(0, len(pool) - 1))
    treatment = pool[(slide_index + offset) % len(pool)]
    base_params = (kit.get("treatment_params") or {}).get(treatment, {}) or {}
    params = dict(base_params)

    # Strengthen hook-slide treatments a touch.
    if slide_index == 0:
        if treatment == "vignette" and "intensity" in params:
            params["intensity"] = min(0.85, float(params["intensity"]) + 0.1)
        if treatment == "grain" and "amount" in params:
            params["amount"] = min(0.14, float(params["amount"]) + 0.02)
        if treatment == "desaturate" and "amount" in params:
            params["amount"] = max(0.0, float(params["amount"]) - 0.1)

    return (treatment, params)
