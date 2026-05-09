# Carousel Text Formatting Overhaul

## Context

Carousel text rendering has three problems visible in all 37 existing carousels:
1. **All white text** - `text_color: "#FFFFFF"` hard-coded for every slide, no visual hierarchy
2. **Unnecessary inline numbers** - LLM prompt says "Use numbered facts (1. 2. 3. etc.)" causing dense "1. fact 2. fact 3. fact 4. fact" blocks in single slides that wrap badly at 30 chars
3. **All yellow accents** - The frontend tokenizer highlights ALL 3+ char uppercase words as `bg-yellow-300` pills, plus lead labels get the same yellow. Every accent is yellow with zero variety
4. **Dense text** - Some slides cram 4 numbered facts into one block instead of clean short lines

## Plan

### Phase 1: Frontend Accent Color Variety + Tokenizer Fix
**File: [TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx)**

**1A. Add accent color palette** (near line 36)
- Define 6 accent palettes: yellow, rose, emerald, violet, orange, sky
- Add `accentForCarousel(id: string)` helper that hashes carousel ID to pick a consistent palette
- Each carousel gets its own accent color instead of always yellow

**1B. Tighten UPPERCASE "shout" detection** (line 198)
- Current regex: `/^[A-Z0-9!?.,'-]{3,}$/` catches normal words like "DELETED", "COMICS", "SCREEN"
- Change to: only match words 4+ chars that are ALL CAPS **and** don't look like normal content labels (e.g. skip words that appear after "SCENE" or section-header patterns)
- Simpler approach: raise threshold to 5+ chars and add a small skiplist of common false positives ("SCENE", "ORIGIN", "SHIFT", "CHANGE", "POLL", "TIME", "COMICS", "SCREEN")

**1C. Thread accent color through components**
- `CaptivatingText`: accept `accentClasses` prop, use it in `renderToken` for bold/shout pills instead of hard-coded `bg-yellow-300`
- `splitLeadLabel` pill (line 116): use same accent color
- `SlideView`: compute accent from carousel and pass down

### Phase 2: Backend Prompt Fixes
**File: [character_content_service.py](backend/app/services/character_content_service.py)**

**2A. Fix CAROUSEL_GENERATION_PROMPT** (lines 259-306)
- **Delete** line 293: `"Use numbered facts (1. 2. 3. etc.)"`
- **Replace** line 292: `"Text overlays: Bold white text on dark images, short punchy lines"` with `"Text overlays: Short punchy lines, 1-3 lines per slide. NO numbered lists."`
- **Update** the slide example (line 276) from `"1. First numbered fact..."` to `"A surprising fact in punchy language.\nA second dramatic detail."`
- **Add**: `"Use **word** sparingly to highlight 1-2 key words per slide (max 2 highlights per slide)."`
- **Remove** from FORMATTING RULES (line 305): the rule against markdown asterisks (we now want `**word**` for targeted emphasis)

**2B. Fix CAROUSEL_SYSTEM_PROMPT** (line 244)
- Change `"Slides 2-6: Numbered facts with bold, engaging text"` to `"Slides 2-6: 1-3 short punchy lines per slide. Each slide covers one idea."`

### Phase 3: Fix Backend Renderer
**File: [carousel_renderer_service.py](backend/app/services/carousel_renderer_service.py)**

**3A. Accept accent_color parameter** in `_render_slide` (line 174)
- Add `accent_color: str = "#FFD700"` param
- Use it for slide number badge (line 240) instead of hard-coded `#FFD700`

**3B. Strip `**` markers from PIL-rendered text**
- Before wrapping body text, strip `**` markers so they don't appear in rendered images
- Full per-word color rendering in PIL is out of scope for this change

**3C. Read accent_color from text_overlay_specs**
- In `render_carousel`, pass `spec.get("accent_color", "#FFD700")` to `_render_slide`

### Phase 4: Fix All 37 Existing Carousels
**File: [character_content_service.py](backend/app/services/character_content_service.py)**

**4A. Add `fix_carousel_formatting()` service method**
- Fetch all carousels
- For each carousel:
  - Clean inline numbered lists: regex `r'(\d+)\.\s+'` in slide text, convert to newline-separated lines
  - Add `accent_color` to each spec dict based on character universe
  - Strip any remaining em-dash artifacts (`\u2019` etc.)
- Save with versioning (snapshot before update)

**4B. Expose as endpoint**
- `POST /api/characters/fix-formatting` - one-time migration endpoint
- Returns summary: how many carousels updated, what changed

**4C. Add accent_color to text_overlay_specs generation** (lines 1411-1423)
- Universe-based accent color mapping for new carousels:
  - DC: `#A78BFA` (violet), Marvel: `#F87171` (rose), Star Wars: `#FBBF24` (amber)
  - Anime: `#34D399` (emerald), Default: `#FB923C` (orange)

### Phase 5: Rebuild + Verify
- Rebuild backend: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
- Run the fix-formatting endpoint to update existing carousels
- Verify in browser: check 5+ carousels show varied accent colors, no yellow overload, clean text without inline numbers

## Execution Order

1. Phase 1 (frontend) - immediate visual improvement, no rebuild needed
2. Phase 2 + 3 + 4 (backend) - all together, single rebuild
3. Phase 5 (verify)

## Critical Files
- [TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx) - accent colors + tokenizer
- [character_content_service.py](backend/app/services/character_content_service.py) - prompts + specs + migration
- [carousel_renderer_service.py](backend/app/services/carousel_renderer_service.py) - PIL accent color
- [character_content.py](backend/app/models/character_content.py) - model (likely no changes, specs are freeform JSON)

## Verification
1. Open Character Detail page, browse through carousels - each should have a distinct accent color
2. Uppercase words like "DELETED SCENE" should NOT all be yellow-pilled
3. Slide text should be clean short lines, not dense numbered paragraphs
4. Generate 1 new carousel - verify it follows new formatting rules
5. Check PIL-rendered images don't show `**` artifacts
