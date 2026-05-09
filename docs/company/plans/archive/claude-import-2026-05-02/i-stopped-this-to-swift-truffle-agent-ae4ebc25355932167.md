# Brand-Kit + Layout-Variety System for Zero Character Content

## Goal

Give every character a distinct visual brand kit (palette, fonts, image treatments, stickers) so carousels feel on-theme: Joker = chaos neon, Batman = noir, Yoda = parchment. Within a single carousel, no two consecutive slides share a layout.

## Files to Create / Modify

### 1. NEW: `backend/app/services/character_brand_kit_service.py`

Static module (no DB, no async I/O).

**Public surface:**

- `BRAND_KITS: Dict[str, Dict]` — the registry, keyed by slug.
- `normalize_slug(name: str) -> str` — lowercase, strip non-alphanumerics to underscores.
- `get_brand_kit(character_name, universe=None, franchise=None, tags=None) -> Dict` — lookup with fallback chain.
- `enrich_brand_kit(base_kit, character_accent_seed) -> Dict` — deterministic palette nudge per character.
- `list_brand_kits() -> List[str]` — for introspection / tests.

**Kit schema:** name, vibe, palette {primary, secondary, accent_neon}, fonts {hook, body, stat}, image_treatments list, treatment_params dict, sticker_style, hook_bias list, text_effects list, default_layout_rotation list.

**Seeded kits (35 total, exceeds the 25 required):**

Heroes (8): `batman_noir`, `superman_classic`, `wonder_woman_heroic`, `spider_man_comic`, `captain_america_patriot`, `thor_nordic`, `iron_man_tech`, `hulk_rage`

Villains (7): `joker_chaos`, `thanos_cosmic`, `darth_vader_noir`, `voldemort_gothic`, `loki_trickster`, `magneto_regal`, `sauron_doom`

Anti-heroes (4): `wolverine_grit`, `deadpool_meta`, `punisher_noir`, `venom_black`

Fantasy (4): `gandalf_parchment`, `daenerys_fire`, `arya_shadow`, `frodo_humble`

Sci-fi (4): `rey_jedi`, `chewbacca_warmth`, `c3po_gold`, `groot_nature`

Anime (4): `goku_saiyan`, `naruto_ninja`, `luffy_pirate`, `eren_titan`

Horror (2): `pennywise_terror`, `freddy_nightmare`

Defaults (8): `_default_marvel`, `_default_dc`, `_default_star_wars`, `_default_anime`, `_default_fantasy`, `_default_scifi`, `_default_tv`, `_default_film`

**Lookup logic for `get_brand_kit`:**
1. Try normalized `character_name` against exact slug keys (also a name->slug alias map, e.g. `"joker"` -> `"joker_chaos"`, `"batman"` -> `"batman_noir"`).
2. Try franchise slug if provided.
3. Try `f"_default_{universe}"`.
4. Final fallback: `_default_film`.
5. All misses logged via structlog.

**`enrich_brand_kit`:** deep-copies base kit. Uses `random.Random(seed)` to nudge palette hex values by small HSL shifts (±8 deg hue, ±5% lightness). Returns new dict.

### 2. NEW: `backend/app/services/carousel_layout_service.py`

**Constants:**

```
LAYOUTS = ["center", "top", "bottom", "bottom_boxed", "top_boxed",
           "left", "right", "diagonal", "split_top", "split_bottom",
           "corner_tl", "corner_br", "full_overlay", "quote_card",
           "stat_hero", "minimal_tape"]
```

**Functions:**

- `pick_layout_rotation(slides, brand_kit, hook_style, carousel_id=None) -> List[str]`
  - Seeded RNG on `carousel_id` for stable re-renders.
  - Slide 0 restricted to {center, full_overlay, top_boxed, stat_hero, quote_card}. Biased by `hook_style` (hot_take -> full_overlay, etc.).
  - Uses `pick_font_style_for_slide` to classify each slide; stat-type -> prefer stat_hero/corner_tl; quote-type -> prefer quote_card/center.
  - Never places the same layout twice consecutively (retry-pick).
  - Final slide (index -1) forced into {full_overlay, bottom_boxed, stat_hero}.
  - Source pool biased by `brand_kit["default_layout_rotation"]`.

- `pick_text_effects(layout, font_style, brand_kit, seed=None) -> List[str]`
  - Pool: outline, gradient_fill, rotation, redacted, neon_glow.
  - Starts from `brand_kit["text_effects"]`, then 25% chance to drop one and 25% chance to add an unrelated one for variety.
  - `quote_card` layout drops `rotation`; `stat_hero` adds `gradient_fill` if absent.

- `pick_stickers(slide_index, total_slides, brand_kit, seed=None) -> List[Dict]`
  - Base chance 35%; bumped to 55% for vibes in {chaos, noir, horror}.
  - Hook slide types pool: pill, tape, badge.
  - Last slide pool: arrow, redacted_bar.
  - Middle pool: circle_highlight, tape, badge.
  - Max 2 stickers. Returns list of `{type, variant, position, rotation}` dicts.

- `pick_image_treatment(slide_index, brand_kit, seed=None) -> Tuple[str, Dict]`
  - Treatment = `brand_kit["image_treatments"][slide_index % len(...)]`.
  - Params = copy of `brand_kit["treatment_params"].get(treatment, {})`.
  - Hook slide (index 0) gets strength bump: numeric params multiplied ~1.25, clamped.

All four functions log at debug via structlog on entry/exit with kit name + inputs.

### 3. MODIFY: `backend/app/services/character_content_service.py`

**Imports (near top, around line 68-70):**

```python
from app.services.character_brand_kit_service import get_brand_kit
from app.services.carousel_layout_service import (
    pick_layout_rotation,
    pick_text_effects,
    pick_stickers,
    pick_image_treatment,
)
```

**Inside carousel generation block (around lines 1524-1558):**

After `palette = pick_accent_palette(universe, carousel_id)` but before the per-slide loop, add:

```python
try:
    brand_kit = get_brand_kit(
        name,
        universe=universe,
        franchise=getattr(char, "franchise", None) if "char" in dir() else None,
        tags=getattr(char, "tags", None) if "char" in dir() else None,
    )
except Exception:
    logger.warning("brand_kit_lookup_failed", name=name, exc_info=True)
    brand_kit = None
```

After the per-slide normalization loop builds `normalized_slides`, compute layouts once (requires the normalized list, so we split the loop into: first pass = normalize + font_style + accent; second pass = overlay_specs with layouts). Simpler: do normalization first, then:

```python
if brand_kit:
    try:
        layouts = pick_layout_rotation(normalized_slides, brand_kit, hook_style, carousel_id=carousel_id)
    except Exception:
        logger.warning("layout_rotation_failed", exc_info=True)
        layouts = []
else:
    layouts = []
```

Then re-loop over `normalized_slides` to build `text_overlay_specs` with the new fields:

```python
layout_name = layouts[i] if i < len(layouts) else ("center" if i == 0 else "bottom")
effects = pick_text_effects(layout_name, s_clean["font_style"], brand_kit) if brand_kit else []
stickers = pick_stickers(i, len(normalized_slides), brand_kit) if brand_kit else []
treatment_name, treatment_params = (
    pick_image_treatment(i, brand_kit) if brand_kit else ("none", {})
)

# Override font_style from brand kit if available
if brand_kit:
    fonts = brand_kit.get("fonts", {})
    if i == 0 and fonts.get("hook"):
        s_clean["font_style"] = fonts["hook"]
    elif s_clean["font_style"] == "display-stat" and fonts.get("stat"):
        s_clean["font_style"] = fonts["stat"]
    elif fonts.get("body"):
        # Only override the generic display-body case
        if s_clean["font_style"] == "display-body":
            s_clean["font_style"] = fonts["body"]

# Override palette accents if brand_kit has richer palette
if brand_kit:
    bk_palette = brand_kit.get("palette", {})
    if bk_palette.get("primary"):
        s_clean["accent_color"] = bk_palette["primary"] if (i % 2 == 0) else bk_palette.get("secondary", bk_palette["primary"])
        s_clean["accent_secondary"] = bk_palette.get("secondary", s_clean["accent_color"])

text_overlay_specs.append({
    "slide_num": slide_num,
    "text_position": "center" if i == 0 else "bottom",
    "font_weight": "bold",
    "font_style": s_clean["font_style"],
    "max_chars_per_line": 30,
    "background_overlay": 0.5,
    "text_color": "#FFFFFF",
    "accent_color": s_clean["accent_color"],
    "accent_secondary": s_clean["accent_secondary"],
    "text_shadow": True,
    # NEW fields
    "layout": layout_name,
    "text_effects": effects,
    "stickers": stickers,
    "image_treatment": treatment_name,
    "treatment_params": treatment_params,
    "brand_kit_name": brand_kit["name"] if brand_kit else None,
})
```

All brand-kit paths wrapped in try/except so that a missing/malformed kit never breaks carousel generation. On any exception we log and fall back to legacy behavior.

## Validation

Syntax-check all three files:

```bash
python -c "import ast; ast.parse(open('backend/app/services/character_brand_kit_service.py').read())"
python -c "import ast; ast.parse(open('backend/app/services/carousel_layout_service.py').read())"
python -c "import ast; ast.parse(open('backend/app/services/character_content_service.py').read())"
```

## Deployment

Backend is COPY'd in Docker, so after edits:

```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api
docker compose -f docker-compose.sprint.yml up -d zero-api
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
```

## Constraints Met

- structlog logging in every new function.
- Safe fallback on lookup failure (wrapped try/except, legacy flow preserved).
- No DB migration — static code only.
- 35 brand kits seeded (requirement: >=25).
- 16 layouts exactly matching renderer agent list.
- No two consecutive slides share a layout.
- Hook + final slide layout constraints enforced.

## Deliverable Report (written after implementation)

~300-word report covering seeded kit names, integration points, layout list, and parse confirmation.
