# World-Class Carousel Playbook (2026)

> **NOTE (plan mode):** The user requested this file be written to
> `c:\code\zero\.claude\skills\zero-character-content\knowledge\WORLD_CLASS_PLAYBOOK.md`.
> Plan mode only permits writing to this plan file. Once exited, copy the content below to the target path verbatim.
> Research sources compiled from 14 parallel web searches covering carousel pros, render engines, typography,
> VFX, asset libraries, fandom APIs, and 2026 hook formulas.

---

## 1. Layout Library (18 named layouts)

Each layout is a reusable slide archetype. Carousels should **rotate** layouts — never repeat the same layout twice back-to-back.

### 1.1 `HOOK_MEGA` — slide 1 only
```
+---------------------+
|                     |
|   BIG BOLD CLAIM    |  <- 140-180pt, all-caps, stroke+fill
|   IN 3 LINES MAX    |
|                     |
|  [face peeks up]    |  <- character photo cropped bottom 30%
+---------------------+
```
Use: opener. Font: Monument Extended Black + Anton fallback. Stroke 6px black, fill white, drop shadow 8px.

### 1.2 `TOP_BAND` — caption sits above a full-bleed hero
Text ribbon 20% top, character image 80% bottom. Text fg: white on black band with 90% opacity.

### 1.3 `BOTTOM_BAND` — mirror of above; subtitle / stat at bottom 18%

### 1.4 `SPLIT_DIAGONAL` — diagonal seam 15° cut
Left: portrait. Right: solid accent color with stat or quote. Torn-paper edge mask along seam.

### 1.5 `SPLIT_VERTICAL_60_40` — 60% hero image, 40% info panel with bullet list

### 1.6 `CENTER_HERO_FLOAT` — character cut out (no background), floats on a colored gradient. Text wraps around silhouette.

### 1.7 `CAPTION_BUBBLE` — speech/thought bubble from character's mouth containing the text

### 1.8 `POLAROID_STACK` — 3 polaroid frames at slight rotations (-8°, +3°, -5°), stacked with shadows

### 1.9 `COMIC_PANEL_3UP` — 3 equal panels with black gutters, different moments/expressions

### 1.10 `EVIDENCE_BOARD` — "conspiracy wall": taped polaroids, red string connector lines, handwritten scrawls, tape strips labeled LEAKED/CLASSIFIED

### 1.11 `STAT_HERO` — massive number (1200pt), tiny label beneath. Number uses duotone gradient. Character faded into background at 25% opacity.

### 1.12 `QUOTE_CARD` — center-aligned quote in Fraunces Italic, attribution bottom-right in Caveat, muted portrait left-column

### 1.13 `LIST_STACK` — 5-7 bullets, each numbered in circled badge, character thumbnail at top-right corner

### 1.14 `VS_SPLIT` — head-to-head comparison, "VS" glyph in center (Rubik Glitch or Druk), two images flank

### 1.15 `REDACTED_DOC` — fake classified document aesthetic: typewriter font (VT323), several lines blacked out, stamps

### 1.16 `TICKER_REVEAL` — marquee-style text strip along middle, high-contrast moving feel even when static

### 1.17 `CTA_FINAL` — last slide: "SWIPE UP" or "FOLLOW @x", big arrow, call-out sticker

### 1.18 `FRAME_BROADCAST` — fake news broadcast lower-third, chyron with logo, "BREAKING" tag, timestamp

---

## 2. Typography Stack (34 fonts)

### Primary display (headlines)

| Font | Source | Best for | Pair with | Avoid |
|---|---|---|---|---|
| Monument Extended | Pangram (free personal) | Ultra-wide hook titles | Inter / Migra | tiny captions |
| Anton | Google | Tall condensed punches | Inter | long paragraphs |
| Bebas Neue | Google | All-caps headlines | DM Sans | decorative use |
| Druk Wide | Commercial | Editorial impact | Fraunces | under 40pt |
| Aktiv Grotesk | Commercial | Clean neutral modern | Caveat accents | cluttered layouts |
| Neue Haas Grotesk | Commercial | Swiss precision | Fraunces Italic | playful tone |
| Helvetica Now Variable | Commercial | Every size, one file | self | licensing on free tier |
| Obviously Variable | OHNO | Fashion TikTok | Migra | tech niches |
| Migra | Pangram | Editorial serif contrast | Monument | all-caps |
| PP Editorial New | Pangram | Elegant serif hook | Inter | gritty themes |
| Fraunces Variable | Google | Sophisticated variable serif | Inter | horror/action |

### Stat/display numerals
| Font | Use |
|---|---|
| Big Shoulders Display | Huge numbers |
| Unbounded | Rounded-modern numbers |
| Archivo Black | Blocky stat slabs |
| Oswald | Condensed numeric |
| Bowlby One | Cartoon stats |

### Body / UI
| Font | Notes |
|---|---|
| Inter Variable | Workhorse. 9 weights from one file |
| DM Sans | Caption-optimized geometric |
| Space Grotesk Variable | Slight quirk, tech-adjacent |
| Outfit Variable | Warm, rounded |
| Recursive Variable | Mono + sans axis, great for mixed |
| Bricolage Grotesque Variable | Width axis for narrow captions |

### Handwritten / "leaked insider"
| Font | Vibe |
|---|---|
| Caveat | Quick notes |
| Homemade Apple | Letter-written |
| Shadows Into Light | Intimate feminine |
| Caveat Brush | Markery underline |
| Kalam | Indian handwriting |
| Permanent Marker | Loud sharpie |

### Themed / decorative
| Font | Theme |
|---|---|
| UnifrakturMaguntia | Medieval/gothic |
| Pirata One | Vampire/horror |
| Orbitron | Sci-fi/futuristic |
| Rubik Glitch | Cyberpunk |
| Creepster | Horror titles |
| Monoton | Neon outline |
| VT323 | Terminal/redacted doc |
| Silkscreen | Pixel retro |
| Press Start 2P | Arcade |
| Bungee | Signage impact |

### 2025-2026 Google Fonts drops worth using
- **TikTok Sans** (Google) — platform-native feel
- **Geist / Geist Mono** — Vercel's 2024-2025 drop, clean
- **Onest Variable** — softer Inter alternative
- **Funnel Display** — editorial-modern hybrid

---

## 3. Text Effects Catalog (22 effects)

| # | Effect | Pillow/OpenCV recipe (sketch) |
|---|---|---|
| 1 | Outline stroke + fill | `draw.text(xy, t, font=f, fill=white, stroke_width=6, stroke_fill=black)` |
| 2 | Drop shadow single | Draw text offset (+6,+6) in black 50% alpha, then text on top |
| 3 | Drop shadow stack (3D) | Loop 1..20 offsets (+i,+i) lightening toward accent |
| 4 | Neon glow | Draw text to mask, `GaussianBlur(radius=12)`, paste colored blurred layer twice, then crisp text on top |
| 5 | Gradient fill | Render text to mask; create vertical gradient image; composite gradient masked by text |
| 6 | Dual-color split | Mask top 50% of text in color A, bottom 50% in color B |
| 7 | Multi-color highlights | Render per-word, alternate colors for keywords |
| 8 | Text rotation tilt | `Image.rotate(angle=-3, resample=BICUBIC, expand=True)` on text layer |
| 9 | Arc baseline | PIL per-glyph placement along polar coordinates |
| 10 | Typewriter reveal (video) | Frame-by-frame substring render |
| 11 | Glitch VHS | RGB channel separation +2px X offset on R, -2px on B, add scanlines |
| 12 | Redacted bar | `draw.rectangle` black over text span |
| 13 | Handwritten underline | Overlay SVG squiggle asset beneath keyword |
| 14 | Handwritten circle | Overlay SVG ink circle rotated random 5-15° around face/word |
| 15 | Tape-over-text | Overlay semi-transparent tape PNG across a word |
| 16 | Highlighter streak | Draw translucent yellow rectangle behind word, slight rotation |
| 17 | Chromatic aberration text | Same as glitch but lighter split (+1px R, -1px B) |
| 18 | Emboss | Pillow `ImageFilter.EMBOSS` on text mask, then tint |
| 19 | Outlined hollow | Only stroke, no fill (`fill=(0,0,0,0)`) |
| 20 | Text inside image | Image masked by text shape — `im.paste(photo, mask=text_alpha)` |
| 21 | Ticker marquee strip | Horizontal band colored, text in contrast, optional diagonal stripes |
| 22 | Distressed/grunge | Blend text mask with noise texture in multiply mode |

---

## 4. Image Treatment Catalog (12 presets)

| Preset | Pillow/OpenCV recipe |
|---|---|
| **Duotone (Spotify)** | `ImageOps.grayscale` → `ImageOps.colorize(gray, black="#38046C", white="#FFCB00")` |
| **Teal-Orange cinematic** | LAB split: shift shadows to cyan/teal, highlights to orange. `cv2.LUT` with 3D LUT file. |
| **Kodak film emulation** | Gamma 0.9 + +8 saturation + slight warm cast (R+5, B-3) + soft S-curve |
| **Grain overlay** | Generate Gaussian noise array, blend with original at 15-25% opacity |
| **Vignette** | Gaussian 2D kernel multiplied against luminance channel, darkening edges |
| **Radial blur behind face** | MediaPipe face detect → mask face → `GaussianBlur(radius=30)` on background only |
| **Split-tone gradient bg** | Radial gradient from accent to dark, character composited on top |
| **Face-crop zoom** | `face_recognition` or MediaPipe → crop to 80% frame centered on eyes |
| **BG-removal + flat fill** | rembg → composite on flat color or gradient |
| **Double exposure** | Blend mode `screen` between two aligned images |
| **Halftone dots** | Floyd-Steinberg dither at low threshold, colored |
| **Chromatic aberration edges** | Split RGB, shift R channel +3px right, B channel +3px left, merge |

### Character-aware grade routing
- Hero/noble: Teal-Orange cinematic
- Villain/chaos: Desaturated + grain + vignette
- Romance: Warm duotone (#FF6B9D + #FFE0B2)
- Sci-fi: Cyan duotone (#00E5FF + #311B92)
- Horror: Monochrome + grain + heavy vignette
- Comedy: High saturation + halftone

---

## 5. Sticker / Asset Library Spec (56 assets)

All SVG-based, tintable via CSS/PIL mask. Source from Vecteezy / FreeSVG (CC0) or generate.

### Arrows (8)
- Handwritten curved arrow (3 variations)
- Neon arrow (straight, curved, zigzag)
- Taped paper arrow
- Comic book "POW" arrow

### Circles/highlights (6)
- Ink circle rough (3 strokes)
- Double-ink circle
- Oval highlight
- Pulse/ripple ring
- Spotlight cone
- Starburst "NEW" badge

### Tape strips (10)
- EVIDENCE, LEAKED, CLASSIFIED, TOP SECRET, CONFIDENTIAL, EXCLUSIVE, NEW, HOT, SPOILER, BREAKING
- Style: masking tape beige, black text, torn edges, slight rotation

### Speech/thought bubbles (5)
- Comic speech, thought cloud, whisper dotted, shout jagged, tweet rectangle

### Redacted / censored (4)
- Solid black bar, REDACTED stamp, classified stamp, pixelated blur

### Badges (8)
- NEW, EXCLUSIVE, BREAKING, TRENDING, VIRAL, OFFICIAL, WARNING, UPDATE

### Frames (6)
- Polaroid, polaroid with tape, torn paper edge, comic panel border, CRT TV frame, phone lock-screen frame

### Stickers (9)
- Reaction (shock/cry/laugh/fire), franchise insignia placeholders, emoji cutouts, star, heart, flag

---

## 6. Brand Kit Schema (character-level styling)

```json
{
  "character_brand_kit": {
    "character_id": "joker_dc",
    "primary_palette": ["#2E7D32", "#AD1457", "#111111"],
    "accent_palette": ["#FFD600", "#FFFFFF"],
    "image_grade": "desaturated_grain_vignette",
    "mood": "chaos|noir|romance|hero|horror|sci-fi|comedy",
    "hook_fonts": ["Creepster", "Monument Extended"],
    "body_fonts": ["Inter Variable"],
    "accent_fonts": ["Caveat Brush"],
    "sticker_whitelist": ["REDACTED", "LEAKED", "WARNING", "joker_card"],
    "layout_preferences": ["REDACTED_DOC", "EVIDENCE_BOARD", "SPLIT_DIAGONAL"],
    "text_effects_whitelist": ["glitch_vhs", "chromatic_aberration", "redacted_bar"],
    "avoid": ["pastel", "polaroid_stack", "romance_pink"],
    "tone_keywords": ["chaos", "unhinged", "why-so-serious"],
    "signature_motif_svg": "assets/joker/card.svg"
  }
}
```

Stored at `backend/app/services/character_brand_kits/<character_slug>.json`. Loader merges per-character overrides onto global defaults.

---

## 7. Expanded Image Sources (11 new, beyond Zero's existing 11)

| Source | Auth | Endpoint | Coverage |
|---|---|---|---|
| **ComicVine** | free key | `https://comicvine.gamespot.com/api/characters/?api_key=X&format=json` | Canonical comic characters, high-res cover art |
| **TheTVDB v4** | paid/subscription | `https://api4.thetvdb.com/v4/` | TV stills, episode imagery |
| **Fanart.tv** | free key | `http://webservice.fanart.tv/v3/movies/{tmdb_id}?api_key=X` | Curated fan-art, movie logos, character art |
| **Giant Bomb** | free key | `https://www.giantbomb.com/api/characters/?api_key=X` | Game character art |
| **Jikan (MyAnimeList)** | NO KEY | `https://api.jikan.moe/v4/characters/{id}/pictures` | Anime characters, unlimited |
| **AniList GraphQL** | NO KEY | `https://graphql.anilist.co` | Anime/manga with rich metadata |
| **MangaDex** | NO KEY | `https://api.mangadex.org/cover` | Manga covers |
| **SuperHero API** | free key | `https://superheroapi.com/api/{key}/search/{name}` | Hero stats + images |
| **PokeAPI** | NO KEY | `https://pokeapi.co/api/v2/pokemon/{name}` | Pokemon sprites + artwork |
| **Pexels Videos** | free key | `https://api.pexels.com/videos/search` | Video backgrounds for eventual video mode |
| **Unsplash** | free key | `https://api.unsplash.com/search/photos` | Mood/background imagery |

**Recommended integration order:** Jikan + AniList (no-key, huge anime coverage), ComicVine (free, canonical comics), Fanart.tv (free, curated quality), PokeAPI, SuperHero API.

**Avoid:** TheTVDB v4 (now paid/user-sub). Use TMDB for TV instead (already have).

---

## 8. New Hook Formulas (2026) — 10 beyond the existing 15

| # | Formula | Example |
|---|---|---|
| 16 | "They don't want you to know X" | "They don't want you to know Bruce Wayne failed this test 3 times" |
| 17 | "You were lying to about X" | "You were lied to about who really killed Gwen Stacy" |
| 18 | "POV: you just realized X" | "POV: you just realized Sauron has been watching the whole time" |
| 19 | "The one [X] that changed everything" | "The one Joker line that broke Batman's moral code" |
| 20 | "I can't stop thinking about X" | "I can't stop thinking about this one panel" |
| 21 | "Ranking [X] from worst to best" (ranked list drives swipe to end) | "Ranking every Spider-Man suit worst to best" |
| 22 | "Nobody talks about X but" | "Nobody talks about the fact Tony Stark was 21 when..." |
| 23 | "Tell me you [character] without telling me" | "Tell me you're a Slytherin without telling me" |
| 24 | "X happened and no one noticed" | "A background character in ep 3 is actually..." |
| 25 | "Signs you're secretly X" | "5 signs you're secretly a Venom sympathizer" |

Combine with existing 15 → **25-formula rotation** prevents fatigue.

---

## 9. Variety Engine (avoid template fatigue)

Enforce at render time via a `SlideVarietyChecker`:

1. **Layout rotation rule:** No layout repeats within N-1 slides (N = carousel length). Weight by slide_role.
2. **Slide role schema:** Each slide assigned one of: `HOOK → CONTEXT → TWIST → EVIDENCE → ESCALATION → REVEAL → PAYOFF → CTA`. Role determines eligible layout pool.
3. **Font rotation:** Primary + accent font can change mid-carousel at TWIST/REVEAL slides (signals narrative shift).
4. **Color temperature curve:** Slide 1 warm → slide 3 cool → slide 5 warm → slide 7 cool. Prevents flat color palette.
5. **Scale variance:** Alternate "big-text small-image" slides with "big-image small-text" slides (at least 40/60 mix).
6. **Sticker budget:** Max 3 stickers per slide, min 1 sticker every 3 slides.
7. **Hash check:** Compute perceptual hash of each slide; reject if Hamming distance < 12 from previous slide.

Implementation: `character_content_utils.py` `validate_carousel_variety(slides)` returns `(ok, reasons)`.

---

## 10. Render Engine Architecture

```
  [Character Content Request]
        ↓
  [Slide Spec JSON] ← character_brand_kit overlay
  (role, layout, text, image_id, effects, stickers)
        ↓
  [Asset Resolver] ── fetches: image (11 sources), fonts, SVG stickers
        ↓
  [Pillow Compositor]
   ├── 1. Base canvas (1080x1350 IG / 1080x1920 TT)
   ├── 2. Background grade (duotone/cinematic/grain/vignette)
   ├── 3. Hero image placement (crop, face-detect, zoom)
   ├── 4. Overlay layers (gradients, split-tones)
   ├── 5. Text layers (stroke + fill + shadow stack + rotation)
   ├── 6. SVG stickers (tinted, rotated, positioned by layout)
   └── 7. Chromatic/grain final pass
        ↓
  [Visual QA Gate]
   ├── Text contrast ratio check (WCAG AA 4.5:1)
   ├── Face not occluded by text (MediaPipe mask intersect)
   ├── Perceptual hash variety check vs prior slides
   ├── Aspect ratio + safe-zone check (20px margin)
   └── Regenerate failed slide up to 3x
        ↓
  [Final PNG] → /workspace/character_content/<char>/<post>/slide_N.png
```

Key files to touch:
- `backend/app/services/character_content_service.py` — orchestrates
- `backend/app/services/character_content_utils.py` — helpers
- **NEW** `backend/app/services/carousel_renderer.py` — Pillow compositor
- **NEW** `backend/app/services/slide_layouts.py` — 18 layout functions
- **NEW** `backend/app/services/image_treatments.py` — 12 grade presets
- **NEW** `backend/app/services/text_effects.py` — 22 effects
- **NEW** `backend/app/services/asset_library/` — SVG assets + loader
- **NEW** `backend/app/services/character_brand_kits/` — JSON kits
- **NEW** `backend/app/services/visual_qa.py` — QA gate

---

## 11. Top Carousel Accounts — Teardown (pattern synthesis)

Direct breakdown of named accounts was not retrievable in research; instead, pattern synthesis from aggregated viral-carousel studies:

1. **Fandom-fact accounts** (screenrant, fandomspot, marvelfacts style):
   - Slide 1: HOOK_MEGA or TOP_BAND with character face + 1-line claim
   - Slide 2-6: LIST_STACK or alternating CENTER_HERO_FLOAT + QUOTE_CARD
   - Slide 7: CTA_FINAL with "follow for more"
   - Typography: Bebas Neue / Anton + Inter body
   - Grade: Cinematic teal-orange, heavy vignette

2. **Cinema/clip accounts** (cinemabites, movieclipsofficial):
   - COMIC_PANEL_3UP showing 3 moments from a scene
   - Typography: Monument Extended hook + VT323 timestamp captions
   - Grade: Kodak film emulation + grain

3. **Comic/superhero facts** (comicbookfactsdaily, dcfactsofficial):
   - EVIDENCE_BOARD + REDACTED_DOC layouts over-index
   - Heavy sticker use: tape strips, redacted bars, "CLASSIFIED"
   - Duotone grades matched to hero colors (Batman noir, Superman red/blue)

4. **Everyday habits/psychology** (thebalancinghabit, everything.daily):
   - QUOTE_CARD + STAT_HERO alternation
   - Fraunces + Inter, pastel duotones
   - Minimal stickers, high negative space

5. **Breaking/leak accounts** (beatbreak style):
   - FRAME_BROADCAST layout (fake chyron)
   - LEAKED tape strip mandatory
   - Glitch/VHS text effect on hook

---

## 12. Prioritized Implementation Order (top 20, ranked by impact)

| # | Item | Impact | Effort |
|---|---|---|---|
| 1 | Build `slide_layouts.py` with 8 core layouts (HOOK_MEGA, TOP_BAND, SPLIT_DIAGONAL, STAT_HERO, QUOTE_CARD, LIST_STACK, EVIDENCE_BOARD, CTA_FINAL) | Massive | M |
| 2 | Ship `character_brand_kit` schema + 10 seed kits (top characters) | Massive | M |
| 3 | Layout rotation rule + slide role schema (variety engine) | Massive | S |
| 4 | Add 6 text effects: stroke+fill, shadow stack, gradient fill, rotation tilt, redacted bar, tape overlay | Huge | M |
| 5 | Add 5 image treatments: duotone, teal-orange cinematic, grain, vignette, face-crop zoom | Huge | M |
| 6 | Expand font stack: Monument Extended, Bebas Neue, Anton, Inter Var, Fraunces Var, Caveat, VT323 | Huge | S |
| 7 | Integrate Jikan + AniList (no-key anime sources) | High | S |
| 8 | Integrate ComicVine + Fanart.tv (free keys) | High | S |
| 9 | SVG sticker library: tape strips (10), arrows (4), badges (5), redacted bar | High | M |
| 10 | Visual QA gate: contrast + face-occlusion + variety hash | High | M |
| 11 | Add 10 new hook formulas into `character_prompt_seeds.py` | High | S |
| 12 | Chromatic aberration + glitch VHS text effect (signature look) | Med-High | M |
| 13 | Polaroid, comic panel, broadcast frame layouts | Med | M |
| 14 | BG-removal (rembg) + flat fill composite | Med | S |
| 15 | Color temperature curve enforcement | Med | S |
| 16 | Double-exposure blend mode for special slides | Med | S |
| 17 | SuperHero API + PokeAPI integration | Med | S |
| 18 | Pexels Videos integration (prep for video mode) | Low-Med | M |
| 19 | Halftone dots effect | Low | S |
| 20 | Arc/curved text baseline | Low | M |

---

## Top 5 Highest-Impact Recommendations

1. **Slide role schema + layout rotation engine** — prevents "every slide looks the same" which is Zero's single biggest visual weakness. Enforce via variety engine in render pipeline.
2. **Character brand kit JSON schema** — per-character palette/fonts/layouts/stickers. Joker never looks like Cinderella. This is the difference between "generic template" and "branded creator".
3. **Typography upgrade to 2026 stack** (Monument Extended, Bebas Neue, Fraunces Var, VT323, Caveat) + text effects (stroke+fill, shadow stack, gradient fill, redacted bar, tape overlay). Instant visual lift.
4. **Image treatments as first-class citizens** — duotone + teal-orange cinematic + grain + vignette + face-crop. Raw TMDB stills should never hit the canvas ungraded.
5. **Free fandom API expansion** (Jikan, AniList, ComicVine, Fanart.tv, PokeAPI) — 5 free sources add massive character coverage with zero new paid keys.

---

**Word count:** ~2,950 words (dense tables + code recipes). File ready for copy to target path once plan mode exits.

## Sources
- https://www.socialhabitmarketing.com/article-posts/the-ultimate-guide-to-designing-a-perfect-instagram-carousel
- https://postnitro.ai/blog/post/viral-instagram-carousels-strategies-2025
- https://www.truefuturemedia.com/articles/instagram-carousel-strategy-2026
- https://typographysmith.com/font-recommendations/top-10-social-media-fonts
- https://www.typewolf.com/google-fonts
- https://blitzcutai.com/blog/best-caption-fonts-tiktok
- https://fonts.google.com/specimen/TikTok%2BSans
- https://predis.ai/instagram-carousel-maker/
- https://www.aicarousels.com/
- https://pangrampangram.com/products/monument-extended
- https://www.pythoninformer.com/python-libraries/pillow/imageops-colour-effects/
- https://github.com/carloe/duotone-py
- https://jdhao.github.io/2020/08/18/pillow_create_text_outline/
- https://comicvine.gamespot.com/api/documentation
- https://github.com/fanart-tv/fanart.tv-api
- https://docs.api.jikan.moe/
- https://www.thetvdb.com/api-information
- https://www.opus.pro/blog/tiktok-hook-formulas
- https://sendshort.ai/guides/tiktok-hooks/
- https://www.postwaffle.com/blog/tiktok-carousel-hooks
- https://github.com/ssloth1/real-time-video-effects
- https://www.vecteezy.com/free-vector/ripped-paper
- https://fonts.google.com/specimen/Caveat
- https://fonts.google.com/specimen/Shadows%2BInto%2BLight
