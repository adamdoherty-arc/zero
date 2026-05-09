# Carousel Renderer Massive Upgrade — Plan

**Target:** `c:\code\zero\backend\app\services\carousel_renderer_service.py` (extend, do not rewrite).

All new behavior is **optional** — slides without the new spec fields render identically to today.

---

## 1. Module-level additions (top of file, after existing constants, ~line 60)

### 1a. Font registry

```python
FONT_ASSETS_DIR = Path("/app/backend/assets/fonts")

FONT_REGISTRY: Dict[str, str] = {
    "display-hook":        "Anton-Regular.ttf",
    "display-stat":        "BebasNeue-Regular.ttf",
    "display-quote":       "PlayfairDisplay-BlackItalic.ttf",
    "display-hot":         "PermanentMarker-Regular.ttf",
    "display-shout":       "Bangers-Regular.ttf",
    "display-block":       "Staatliches-Regular.ttf",
    "display-body":        "Inter-Black.ttf",
    "display-condensed":   "Oswald-Bold.ttf",
    "display-archivo":     "ArchivoBlack-Regular.ttf",
    "display-mono":        "RubikMonoOne-Regular.ttf",
    "display-slab":        "AbrilFatface-Regular.ttf",
    "display-gothic":      "UnifrakturMaguntia-Regular.ttf",
    "display-scifi":       "Orbitron-Black.ttf",
    "display-cyberpunk":   "RubikGlitch-Regular.ttf",
    "display-horror":      "Creepster-Regular.ttf",
    "display-neon":        "Monoton-Regular.ttf",
    "display-terminal":    "VT323-Regular.ttf",
    "display-handwritten": "ShadowsIntoLight-Regular.ttf",
    "display-brush":       "CaveatBrush-Regular.ttf",
    "display-serif":       "Fraunces-Black.ttf",
    "display-bold":        "Inter-Black.ttf",
    "display-fatface":     "AbrilFatface-Regular.ttf",
}

# Cache loaded ImageFont objects keyed by (style_or_weight, size) to avoid
# re-opening TTFs per slide.
_FONT_CACHE: Dict[Tuple[str, int], Any] = {}

# Default palette for extract_palette_from_image failure fallback.
_DEFAULT_PALETTE = ["#111111", "#FFFFFF", "#FFD700", "#E63946", "#457B9D"]
```

### 1b. Haar cascade path (lazy-loaded in `_apply_image_treatment`)

Reuse `haarcascade_frontalface_default.xml` pattern from
`backend/app/services/image_source_service.py:149-165`.

---

## 2. New / extended methods on `CarouselRendererService`

### 2a. Extend `_get_font(size, weight="bold", style=None)` (line 356)

Signature change: add `style: Optional[str] = None` (default None → old behavior).

Behavior:
1. If `style` provided and in `FONT_REGISTRY`: try `FONT_ASSETS_DIR / file`; on success cache + return.
2. Log `logger.warning("carousel_font_missing", style=..., path=...)` on fallback.
3. Fall through to existing DejaVu/Arial chain.
4. Cache every resolved font by `(style or weight, size)` in `_FONT_CACHE`.

### 2b. `_apply_image_treatment(self, img, treatment, params) -> Image`

Dispatcher that returns a new RGB PIL Image. Guarded by try/except — on any
failure, log `logger.warning("treatment_failed", treatment=..., error=...)` and
return `img` unchanged. Params is a dict with defaults per treatment.

Sub-functions (private static methods or nested):
- `_treat_none(img, p)` → img
- `_treat_duotone(img, p)` → `ImageOps.grayscale` + `ImageOps.colorize(shadow=shadow_hex, highlight=highlight_hex)`
- `_treat_cinematic(img, p)` → `ImageEnhance.Contrast(1.15)` + `ImageEnhance.Color(0.85)` + per-channel LUT via `Image.point` (shadows → +teal on B, highlights → +orange on R)
- `_treat_grain(img, p)` → numpy random uniform noise * amount, `Image.blend`
- `_treat_vignette(img, p)` → build radial alpha mask via numpy, multiply; intensity defaults 0.6
- `_treat_face_zoom(img, p)` → OpenCV Haar cascade detect on grayscale, take largest face bbox, expand to 80% frame around center of face, crop + resize. No face → center-crop 80%.
- `_treat_desaturate(img, p)` → `ImageEnhance.Color(1.0 - amount)`
- `_treat_halftone(img, p)` → downscale to 1/6, upscale nearest, `ImageOps.posterize(bits=3)`
- `_treat_radial_blur_bg(img, p)` → gaussian-blurred copy + radial mask keeps center sharp
- `_treat_split_tone(img, p)` → per-pixel: shadows blend toward cool_hex, highlights toward warm_hex via luminance mask

OpenCV and numpy imported lazily inside the treatment functions that need them
(mirrors existing lazy PIL imports).

### 2c. `_pick_text_anchor(layout, slide_w, slide_h, text_bbox) -> Tuple[int, int]`

Returns `(x, y)` for the top-left of the rendered text block. Supported layouts:

| layout | anchor |
|---|---|
| `center` | horizontally centered, vertically centered |
| `top` | centered x, y=120 |
| `bottom` | centered x, y = slide_h − text_h − 180 |
| `bottom_boxed` | like bottom, but caller also draws a semi-transparent box |
| `top_boxed` | like top + box |
| `left` | x=80, vertically centered |
| `right` | x = slide_w − text_w − 80, vertically centered |
| `diagonal` | center, but text layer also rotated ~10° (handled in effect) |
| `split_top` | centered, y = slide_h*0.25 − text_h/2 |
| `split_bottom` | centered, y = slide_h*0.75 − text_h/2 |
| `corner_tl` | x=80, y=80 |
| `corner_br` | x=slide_w − text_w − 80, y=slide_h − text_h − 80 |
| `full_overlay` | centered + band drawn behind |
| `quote_card` | centered card with inner padding + border lines |
| `stat_hero` | centered, caller uses giant font size |

Unknown layout → log `logger.info("layout_unknown_fallback_center", layout=...)`
and return centered coords.

### 2d. `_apply_text_effects(draw, img, text_lines, font, x, y, fill, effects, spec) -> None`

Reads `effects` list. Order: `outline` → `gradient_fill` → `neon_glow` → `redacted` → `rotation` (last, applied to assembled text layer).

- `outline`: use PIL `stroke_width=3, stroke_fill=spec.get("outline_color", "#000000")` in `draw.text`.
- `gradient_fill`: render each line to a luminance mask (new `L` image), create vertical linear gradient (`accent_color` → `#FFFFFF`), composite via mask onto main image with `Image.composite`.
- `rotation`: render text to transparent RGBA layer, `layer.rotate(spec.get("rotation_deg", -3), resample=BICUBIC, expand=True)`, paste onto main.
- `redacted`: for each word in `spec["redacted_words"]`, measure bbox of that word inside the line and draw a filled black rectangle with 2px padding over it.
- `neon_glow`: render text in glow color to separate layer, apply `ImageFilter.GaussianBlur(radius=10)`, alpha_composite behind the crisp text.

All effects wrapped in try/except with warning log on failure; crisp text still drawn as fallback.

### 2e. `_compose_stickers(self, img, stickers) -> Image`

For each sticker dict, dispatch on `type`. All drawn onto the main image AFTER text. Each has `x, y, rotation, text, color, scale` plus type-specific fields.

Implementations (all pure PIL):
- `tape`: rotated rect with slight noise fill + 2 dark edge lines + centered uppercase text.
- `pill`: `rounded_rectangle` fill + label text.
- `circle_highlight`: `ellipse` stroke-only + small arrow line to `target_x/y`.
- `arrow`: polygon with shaft + head.
- `torn_edge`: jagged polygon across full width (random y zig-zag).
- `polaroid_frame`: 40px white border via `ImageOps.expand` applied to a cropped copy and repasted.
- `redacted_bar`: filled black rect with optional "[REDACTED]" text.
- `badge`: rounded pill with bold label (accepts "NEW"/"EXCLUSIVE"/"SPOILER").
- `comic_panel_border`: 14px black frame around entire slide.

Sticker spec is forgiving: unknown type → log warning, skip.

### 2f. `extract_palette_from_image(img, n=5) -> List[str]`

Standalone module-level function (not on the class):
1. Downscale to 100×100 thumbnail.
2. Convert to numpy array, reshape to (N, 3).
3. Try `from sklearn.cluster import KMeans`; on ImportError, use numpy-only: pick `n` random centroids, run 10 iterations of assign + mean update.
4. Convert cluster centers → hex; sort by cluster size desc.
5. On any exception log warning and return `_DEFAULT_PALETTE`.

---

## 3. Plug-in points inside `_render_slide` (lines 175-314)

### 3a. After line 201 (`img = self._fit_background(...)`)

```python
treatment = spec.get("image_treatment") if isinstance(spec, dict) else None
if treatment and treatment != "none":
    img = self._apply_image_treatment(
        img, treatment, spec.get("image_treatment_params", {}) or {}
    )
```

This means `_render_slide` needs access to the `spec` dict — extend its
signature with `spec: Optional[Dict[str, Any]] = None` (default None keeps it
backward compatible) and pass `spec=spec` from the caller at line 131.

### 3b. Replace font loads at lines 219-222

```python
title_style = spec and spec.get("title_font_style")
body_style  = spec and spec.get("body_font_style")
title_font = self._get_font(size=spec.get("title_size", 52) if spec else 52,
                            weight="bold", style=title_style)
body_font  = self._get_font(size=spec.get("body_size", 40) if spec else 40,
                            weight=font_weight, style=body_style)
```

### 3c. Replace positional math at lines 228-235 with layout-aware anchor

Compute the full text block bbox (title + body wrapped lines), then call
`_pick_text_anchor(spec.get("layout", text_position), SLIDE_WIDTH, SLIDE_HEIGHT, bbox)`.
Use returned `(x, y)` as the starting draw cursor. If layout is
`full_overlay`/`quote_card`/`bottom_boxed`/`top_boxed`, draw the
semi-transparent band/card first.

Old `text_position` string still honored when no `layout` key is present.

### 3d. Replace crisp `draw.text(...)` calls at lines 253-254 and 270-271

Route through `_apply_text_effects(...)` when `spec.get("text_effects")` is a
non-empty list; otherwise keep the current shadow + text drawing.

### 3e. After body text draw (after line 272), before contrast check

```python
stickers = spec.get("stickers") if spec else None
if stickers:
    img = self._compose_stickers(img, stickers)
    draw = ImageDraw.Draw(img)  # re-bind draw (img object may be replaced)
```

### 3f. Update `render_carousel` call site (line 131)

Pass `spec=spec` into `_render_slide`.

---

## 4. Logging

Every non-trivial branch logs via structlog:
- `carousel_font_missing` (style, size)
- `carousel_font_loaded` (style, path) at debug
- `treatment_applied` (treatment) at info, `treatment_failed` at warning
- `layout_unknown_fallback_center` (layout)
- `text_effect_failed` (effect, error)
- `sticker_unknown_type` (type), `sticker_render_failed` (type, error)
- `palette_extract_fallback` (reason)
- `face_zoom_no_face` at info

---

## 5. Safety / compatibility

- All new spec keys (`image_treatment`, `image_treatment_params`, `layout`, `title_font_style`, `body_font_style`, `title_size`, `body_size`, `text_effects`, `rotation_deg`, `outline_color`, `redacted_words`, `stickers`) are **optional**. Missing → today's behavior.
- `_render_slide` signature gains one optional trailing arg (`spec`). All existing callers unaffected.
- `render_carousel` public signature unchanged.
- Canvas stays 1080×1350.
- Every treatment/effect/sticker wrapped in try/except with warning log; failure never aborts the slide.

---

## 6. Verification

After edits, run:

```bash
python -c "import ast; ast.parse(open('backend/app/services/carousel_renderer_service.py').read())"
```

Then rebuild:

```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && \
docker compose -f docker-compose.sprint.yml up -d zero-api
```

Smoke-test one existing carousel to confirm identical output when no new spec
fields are set (byte-diff a render before vs after the change on a slide with
the old schema).

---

## 7. Expected line impact

- ~15 lines of new module-level constants (font registry + palette default).
- ~60 lines: `_get_font` extension + font cache.
- ~220 lines: `_apply_image_treatment` + 10 treatment helpers.
- ~70 lines: `_pick_text_anchor` + layout band/card helpers.
- ~120 lines: `_apply_text_effects` (5 effects).
- ~180 lines: `_compose_stickers` + 9 sticker drawers.
- ~40 lines: `extract_palette_from_image`.
- ~20 lines: modifications inside `_render_slide` plug-in points.

Final file ≈ 1300 lines. No rewrites of existing code paths.
