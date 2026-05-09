# Character Content — Typography, Color, Images, Brain Overhaul

## Context

The character content carousel pipeline is generating output, but a visual review of 5 recent carousels (Chani, Brie Larson Captain Marvel, Cammy, Billy Butcher) surfaced a cluster of quality problems that must be fixed before any TikTok posts go live:

**Current pain points (evidence from user screenshots + code exploration):**

1. **Monofont + boring** — every slide uses one weight (`font-black`). No visual differentiation between hooks, stats, quotes, hot takes. Text doesn't "stick out" because nothing contrasts.
2. **Color is deterministic** — accent palette is hash-locked per carousel ID. Every Chani carousel gets the same color forever. No randomization.
3. **Unnecessary line breaks** — hooks like "Chani went from desert warrior to Paul's moral compass. then to his greatest enemy. Here's her brutal evolution" break mid-phrase ("Paul's moral\ncompass") because the prompt enforces a rigid 3-line rhythm that should be inline for longer narrative hooks.
4. **Duplicate phrases across carousels** — Billy Butcher / Chani / Cammy slides repeat the same hook text verbatim on the final payoff slide. The 7-day angle-based dedup doesn't catch phrase repetition.
5. **Thin content** — some slides are 2-3 words, others are wall-of-text; no density floor/ceiling.
6. **Image duplicates / near-dupes** — image dedup is URL-only. Same Zendaya-as-Chani shot reappears across different slide queries with tiny crop differences.
7. **Image quality selection is invisible** — no human can review the 30+ candidate images the system sourced; only the top-scored one shows. No UI to pick alternates.
8. **Edit UI gap** — carousel editor has `Regenerate` and `Edit query`, but no way to pick from the existing pool, paste a URL, or upload a custom image.
9. **Narrow image sources** — only 4 free sources active (Fandom/Wikipedia/TMDB/SearXNG). Missing Bing, DuckDuckGo, YouTube thumbnails, Giphy, MediaWiki Commons, Reddit franchise subs, DeviantArt, ArtStation.
10. **Brain isn't producing enough for review** — scheduler generates 10 carousels / 4 hours. User wants vastly more output to review and learn from.

**Goal:** Before any post goes live, land a vast quality bump in typography, color variance, text density, image quality, image review UX, and learning loop throughput, informed by current best practices research.

## Decisions (confirmed with user)

- **Fonts:** Curated 4-font system — Anton (hooks), Bebas Neue (stats), Playfair Display Italic (quotes), Permanent Marker (hot takes), Inter Black retained as body fallback.
- **Image sources:** Add free scrapers (Bing, DuckDuckGo, YouTube thumbnails, Giphy, Reddit franchise subs) + free-key APIs (Giphy, Flickr, MediaWiki Commons, OMDb) + fan sources (DeviantArt, ArtStation).
- **Edit UI:** Image picker from candidate pool + paste URL + file upload.

---

## Phase 1 — Text, Typography & Color

### 1.1 Add 4 display fonts (frontend)

- **File:** [frontend/index.html](frontend/index.html) — add Google Fonts `<link>` for: Anton, Bebas Neue, Playfair Display (italic 700), Permanent Marker.
- **File:** [frontend/tailwind.config.js](frontend/tailwind.config.js) — extend `fontFamily` with `display-hook`, `display-stat`, `display-quote`, `display-hot`.
- **File:** [frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx) lines 138–206 — swap hardcoded `font-black` for a dispatch based on `slide.font_style` (new backend-assigned field, below).

### 1.2 Backend picks `font_style` per slide

- **File:** [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — carousel generation path. When composing `text_overlay_specs[]`, assign `font_style` per slide:
  - Hook slide → `display-hook` (Anton)
  - Slides with numeric stats / age / years → `display-stat` (Bebas Neue)
  - Quote slides (detected by starting/ending quotes) → `display-quote` (Playfair italic)
  - Hot-take slides (from `hot_take` hook style) → `display-hot` (Permanent Marker)
  - Fallback → `display-body` (Inter Black, current)
- Add helper `pick_font_style_for_slide(slide_text, slide_index, hook_style)` in [backend/app/services/character_content_utils.py](backend/app/services/character_content_utils.py).

### 1.3 Randomize accent colors

- **File:** [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — replace the single `UNIVERSE_ACCENT_COLORS` lookup with a per-carousel random choice from an expanded palette of 12 universe-appropriate colors (3–4 hues per universe). Seed with `carousel_id + slide_index` so each slide can also roll a secondary accent for pill/highlight words while still being deterministic for re-renders.
- **File:** [frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx) lines 41–64 — keep the fallback palette but honor new `slide.accent_color` and `slide.accent_secondary` fields from the backend.

### 1.4 Fix broken line wrapping + density floor/ceiling

- **File:** [backend/app/services/character_prompt_seeds.py](backend/app/services/character_prompt_seeds.py) lines 78–111 — relax the mandatory 3-line rhythm. New rule:
  - If slide total word count ≤ 8 → inline (no newlines)
  - If 9–14 words → 2 lines
  - If 15+ words → 3 lines, but never break a compound noun or possessive phrase
- Add **post-generation validator** in `character_content_utils.py`: `normalize_slide_text(text)` that:
  - Strips newlines inside possessive phrases ("Paul's moral\ncompass" → inline)
  - Enforces min 6 words / max 22 words per body slide; flags violations for regeneration
  - Uses a stoplist of bad break points (after `'s`, before `and/or/to/with`, mid-proper-noun).

### 1.5 Phrase-level carousel dedup

- **File:** [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — extend the existing 7-day angle dedup with a phrase-level check:
  - Compute trigram hash of every slide body
  - Reject a new carousel where ≥2 slides match trigram hashes of any carousel posted for that character in the last 14 days
  - Log `carousel_phrase_dupe_skip` with diffs so the breeder learns

---

## Phase 2 — Image Quality, Dedup & Review

### 2.1 Perceptual dedup (near-duplicate killer)

- Add dependency: `imagehash` (pHash) in `backend/requirements.txt`.
- **File:** [backend/app/services/image_source_service.py](backend/app/services/image_source_service.py) lines 89–160 — after URL dedup, compute pHash per image, drop any image within Hamming distance ≤ 6 of an earlier image. Store `phash` on the image row.
- **Migration:** add `phash TEXT` column to `character_images` table.

### 2.2 Image quality review + "pick best" flow

- **File:** `backend/app/services/image_source_service.py` — extend `compute_quality_score()` with:
  - Face-present bonus (use `opencv` Haar cascade — already a common Python dep; fall back gracefully if missing)
  - Centered-subject bonus (simple saliency: darker edges vs. center)
  - Text-overlay-safe-zone bonus (bottom-third low-variance = good for caption overlay)
- Expose a new endpoint `GET /api/characters/carousels/{id}/slides/{index}/image-candidates` returning top 20 candidates ranked by quality, each with `{url, phash, score, source, width, height}`.
- New endpoint `PATCH /api/characters/carousels/{id}/slides/{index}/image` to swap to a chosen URL (existing `/reimage` regenerates).

### 2.3 New image sources

Add to `image_source_service.py`:
- **Free scrapers:** Bing Images (SearXNG Bing engine tuning), DuckDuckGo Images, YouTube thumbnails (via `yt-dlp` metadata search), Reddit franchise subs (existing `reddit_service.py` — extend to image posts), Giphy public search.
- **Free APIs:** Giphy API, Flickr API (MediaWiki Commons via Wikipedia API is already partly there — expand), OMDb API for movie stills.
- **Fan sources:** DeviantArt public search API, ArtStation public JSON search. Both have structured JSON endpoints — no HTML scraping fragility.
- Each new source becomes a tier in `SOURCE_TIERS` with a conservative score (0.5–0.7).
- Add an opt-in flag in character settings: `fan_art_allowed: bool` (default false; must toggle on per character to avoid legal issues with fan work on branded characters).

---

## Phase 3 — Edit UI: Image Picker + URL + Upload

### 3.1 Candidate pool picker

- **File:** [frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx) lines 682–740 — expand the per-slide edit section:
  - Button "Change image" opens a modal
  - Modal tabs: **Pool** (fetches `/image-candidates` endpoint above) | **URL** (paste field) | **Upload** (file input, POST to new `/slides/{index}/image/upload`)
  - Pool tab shows 4-column grid of thumbnails with score badge + source tag
  - Click a thumbnail → PATCH to `/slides/{index}/image`; close modal; phone preview updates

### 3.2 Backend upload

- New router endpoint `POST /api/characters/carousels/{id}/slides/{index}/image/upload` — accept multipart file, store to `backend/uploads/character_images/{character_id}/` (or S3 if configured), compute pHash, insert into `character_images` with `source=user_upload` tier 1.0, swap into slide.

---

## Phase 4 — Brain: More Carousels, Better Review

### 4.1 Crank generation throughput

- **File:** [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) lines 2565–2627 — change `character_content_generation` job:
  - Cadence: every 4h → every 1h
  - Batch: 10 → 25 carousels
  - Require variety: no more than 3 of the same hook style per batch (existing rule — enforce in scheduler not just prompt)
  - Prioritize characters with <5 recent carousels

### 4.2 Per-slide scoring

- **File:** [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) lines 1897–2041 — extend the Stage-1 AI review to score each slide individually on `text_punch`, `image_fit`, `font_style_fit` (0–10). Persist in `ai_review.slides[]`.
- The breeder ([backend/app/services/prompt_breeder_service.py](backend/app/services/prompt_breeder_service.py) lines 78–162) already mutates top variants; add a mutation style "tighten_rhythm" that targets low `text_punch` slides.

### 4.3 Industry research → knowledge file

- Launch one more Explore agent during execution (not in this plan) to compile `INDUSTRY_RESEARCH.md` under the skill knowledge folder, covering what top TikTok character-content creators actually do (Beat Break, FandomSpot, WhatCulture style guides). Feed key findings back as new prompt variants via `prompt_breeder_service.seed_from_research()`.

---

## Files to modify (summary)

| Area | File | Why |
|---|---|---|
| Fonts — HTML | frontend/index.html | Load Google Fonts |
| Fonts — Tailwind | frontend/tailwind.config.js | Register font families |
| Fonts — Render | frontend/src/components/character-content/TikTokPhonePreview.tsx | Dispatch on `font_style` |
| Fonts — Assign | backend/app/services/character_content_service.py + character_content_utils.py | Pick per slide |
| Colors | backend/app/services/character_content_service.py + TikTokPhonePreview.tsx | Randomize + per-slide secondary |
| Line breaks | backend/app/services/character_prompt_seeds.py + character_content_utils.py | New rhythm + normalizer |
| Phrase dedup | backend/app/services/character_content_service.py | Trigram check |
| Image pHash | backend/app/services/image_source_service.py + migration | Near-dupe kill |
| Image scoring | backend/app/services/image_source_service.py | Face / saliency / safe zone |
| New sources | backend/app/services/image_source_service.py (+ new scrapers) | 7 new sources |
| Candidate endpoint | backend/app/routers/character_content.py | List + swap + upload |
| Edit UI | frontend/src/components/character-content/TikTokPhonePreview.tsx + new modal | Picker + URL + upload |
| Scheduler throughput | backend/app/services/scheduler_service.py | 1h / 25 carousels |
| Per-slide scoring | backend/app/services/character_content_service.py | Slide-level feedback |
| Breeder mutation | backend/app/services/prompt_breeder_service.py | "tighten_rhythm" mutator |

## Reused existing code

- Prompt variant selection / Thompson sampling — [backend/app/services/prompt_evolution_service.py](backend/app/services/prompt_evolution_service.py) lines 89–300
- Prompt breeder genetic loop — [backend/app/services/prompt_breeder_service.py](backend/app/services/prompt_breeder_service.py) lines 78–162
- Content learning outcome recording — [backend/app/services/content_learning_engine.py](backend/app/services/content_learning_engine.py)
- Image quality score skeleton — [backend/app/services/image_source_service.py:52](backend/app/services/image_source_service.py#L52)
- Reddit image post fetching — existing `reddit_service.py`

## Verification

1. **Fonts:** visit `/character-content` in the UI, open any carousel preview, confirm 4 different typefaces appear across slides, hook slide uses Anton, stat slide uses Bebas Neue.
2. **Colors:** regenerate the same character twice, confirm accent palette differs between the two carousels; within one carousel, confirm pill highlights use a secondary color.
3. **Line breaks:** find the Chani "Paul's moral compass" hook; confirm possessive phrase no longer splits across lines.
4. **Phrase dedup:** call `POST /api/characters/{id}/carousel` twice with same angle; second call returns existing carousel or a new one that does NOT share slide body trigrams.
5. **Image dedup:** seed images for one character, confirm `phash` column populated, confirm near-duplicate Zendaya crops collapse to one representative.
6. **Image picker:** open carousel editor, click "Change image" on a slide, see pool tab with ≥15 candidates ranked by score; click one, phone preview updates.
7. **Upload:** upload a JPEG, see it appear in the pool and get selected.
8. **Throughput:** wait 1h, confirm scheduler generated ≥20 new carousels, no more than 3 per hook style.
9. **Per-slide scoring:** inspect `ai_review.slides[]` on a reviewed carousel, confirm 3 sub-scores per slide.
10. **Rebuild:** after backend changes `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`. Frontend is volume-mounted except for Google Fonts which are CDN-loaded, so a simple `docker compose -f docker-compose.sprint.yml restart zero-ui` is sufficient unless new npm deps are added.

## Execution order

1. Phase 1.1–1.3 (fonts + colors) — visible win fast, low risk.
2. Phase 1.4–1.5 (line breaks + phrase dedup) — biggest quality lift.
3. Phase 2.1 (pHash dedup) — foundation for everything image.
4. Phase 2.2–2.3 (quality scoring + new sources) — can parallelize.
5. Phase 3 (edit UI) — depends on 2.2 endpoint existing.
6. Phase 4.1 (scheduler) — land last so the breeder feeds off the improved generator, not the old one.
7. Phase 4.2–4.3 (per-slide scoring + research ingestion) — continuous improvement.
