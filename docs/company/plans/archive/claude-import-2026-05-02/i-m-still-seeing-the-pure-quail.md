# Carousel Text Formatting Overhaul v2

## Context

User committed [0e25771](https://github.com/) ("feat: carousel text formatting overhaul") to add accent colors, reduce highlighting, and expand hashtags. They're still seeing flat, boring carousels (screenshots: Billy Butcher, Cammy, Chani) and want the generation improved AND all existing carousels regenerated.

**Root cause we missed last time**: [character_content_utils.py:46](backend/app/services/character_content_utils.py#L46) strips `**bold**` markers from every slide at sanitization. `TikTokPhonePreview.tsx:138` disables UPPERCASE shout-detection on body slides. Result: **even brand-new carousels have zero emphasis on body slides**. The last overhaul improved prompts but the emphasis was being wiped between the LLM and the DOM. This explains why the screenshots show plain white body text with only a colored slide-number badge.

**Expected outcome**: body slides render with colored pills on key nouns/numbers, 3-line rhythm with a payoff line, and existing carousels are restyled in-place via an extended migration endpoint.

---

## Task 1 — Stop stripping `**bold**` from slide text (biggest win, do first)

Edit [backend/app/services/character_content_utils.py](backend/app/services/character_content_utils.py#L40-L49): add `preserve_emphasis: bool = False` kwarg to `sanitize_text`. When true, skip the `\*{1,3}([^*]+)\*{1,3}` strip but still normalize single `*italic*` → plain and 3+ asterisks → 2.

Flip the flag to `True` at slide/hook call sites, keep `False` for captions/titles/facts:
- [character_content_utils.py:309](backend/app/services/character_content_utils.py#L309) `hook_text` → preserve
- [character_content_utils.py:314](backend/app/services/character_content_utils.py#L314) `slide["text"]` → preserve
- [character_content_utils.py:373](backend/app/services/character_content_utils.py#L373) (`carousel_to_pydantic` slides) → preserve
- [character_content_utils.py:375](backend/app/services/character_content_utils.py#L375) (`carousel_to_pydantic` hook) → preserve
- Lines 307, 311, 389, 392 (title/caption) → keep `False`
- [character_content_service.py:905,910](backend/app/services/character_content_service.py#L905) (fact bank) → keep `False`
- [character_content_service.py:1906,1908,2080,2081](backend/app/services/character_content_service.py#L1906) (review overwrites) → preserve for hook/slides, strip for caption
- Lines 5711, 5760-5793 (edit/polish endpoints) → preserve for hook/slide text

PIL renderer at [carousel_renderer_service.py:258-260](backend/app/services/carousel_renderer_service.py#L258) already strips `**` for image output — leave it.

## Task 2 — Sharpen the generation prompt

Edit `CAROUSEL_GENERATION_PROMPT` in [character_content_service.py:283](backend/app/services/character_content_service.py#L283):

Replace the vague "1-3 short punchy lines per slide" rule with a 3-line rhythm spec (setup / twist / payoff) and add **BEFORE/AFTER examples** so the LLM has a visual model:

```
BEFORE (flat): "He ruled Asgard for years disguised as Odin and nobody noticed."
AFTER:
He ruled Asgard for **7 years**.
Disguised as **Odin**.
Nobody noticed. 👁️
```

Add requirement: final line of every body slide must be 2-5 word payoff. Exactly one `**bold**` per slide (noun, number, or payoff word).

Extend `_final_review_carousel` at [character_content_service.py:2009+](backend/app/services/character_content_service.py#L2009) with a rhythm check and a new `final_slides` field so the reviewer can replace flat slides (not just flag them). Apply with `sanitize_text(..., preserve_emphasis=True)`.

Register as new Thompson-sampled variant `carousel_v2_rhythm` via `get_prompt_evolution_service().register_variant(...)` — mirrors `seed_character_prompt_variants` pattern at [character_prompt_seeds.py:230](backend/app/services/character_prompt_seeds.py#L230). This lets the system A/B the v2 prompt against baseline rather than blindly replacing it.

## Task 3 — Frontend preview polish

Edit [frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx):

- **Wire DB accent_color** (line 49 `accentForCarousel`): prefer `carousel.text_overlay_specs[0].accent_color` when present, fall back to hash palette. Switch pill rendering at lines 254-260 to inline `style={{ backgroundColor: accent, color: '#000' }}`. Also update `TextOverlaySpec` in [useCharacterContentApi.ts:201-211](frontend/src/hooks/useCharacterContentApi.ts#L201) to include `accent_color?: string`.
- **Re-enable body-slide shouts with skiplist** (line 138): flip `enableShouts` to `true` for body slides; rely on existing `SHOUT_SKIPLIST` (lines 59-63) + the stricter 4+ char / 2+ uppercase regex to keep noise low. Gives old carousels some pill treatment without regeneration.
- **Payoff-line styling** in `CaptivatingText` (lines 102-163): when a body slide has `>=3` lines, add `font-black tracking-tight text-[20px]` to the last line. Bump hook to `text-[26px]`, body to `text-[19px]`.
- **Skew consistency**: add `-skew-x-3` to body pills to match hook pill styling.

## Task 4 — Regeneration endpoint for existing carousels

Extend (do NOT replace) the existing migration at [character_content_service.py:2530-2646](backend/app/services/character_content_service.py#L2530) `fix_carousel_formatting`:

- Add `restyle: bool = False`, `limit: int = 200`, `character_id: str | None = None`, `force: bool = False` params.
- When `restyle=True`, add a new helper `_restyle_slides_llm(name, universe, slides)` that sends existing slides to the LLM with a "reformat only, do NOT invent facts" prompt at `temperature=0.3`. Use `get_unified_llm_client().chat(task_type="character_carousel_generation")` — the same router, budget, and model config.
- Wrap in `asyncio.Semaphore(4)` for concurrency (200 carousels × 1 call ≈ $1-3).
- Reuse existing `_snapshot_carousel` (line 2627) for rollback.
- Write `generation_metadata["restyled_at"]` as idempotency marker; skip already-restyled unless `force=True`.
- Apply returned slides via `sanitize_text(..., preserve_emphasis=True)` to preserve new `**bold**` markers (depends on Task 1).

Expose at [character_content.py:313](backend/app/routers/character_content.py#L313): extend the existing `/fix-formatting` endpoint with the new query params. Default behavior (no flags) unchanged.

## Task 5 — Wiring verification

Verify new prompts actually run in all three generation paths:
- **Interactive**: [character_content_service.py:1150](backend/app/services/character_content_service.py#L1150) → `_select_prompt_variant` at line 1264. ✓ picks up Task 2 automatically.
- **Scheduler**: [scheduler_service.py:2567](backend/app/services/scheduler_service.py#L2567) calls the same service method. ✓
- **Template-based**: [character_content_service.py:1248-1262](backend/app/services/character_content_service.py#L1248) uses `template_prompt` from DB `story_templates` instead of `CAROUSEL_GENERATION_PROMPT`. **Append** a new `RHYTHM_STYLE_SUFFIX` module constant (holding the rhythm + BEFORE/AFTER block from Task 2) after the `.format(...)` call so all templates inherit the rules without touching the DB.

## Verification

1. **Unit**: `sanitize_text("He ruled for **7 years**", preserve_emphasis=True)` returns the text with `**` preserved. Default strips.
2. **Deploy**: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`. Frontend is volume-mounted, just restart: `docker compose -f docker-compose.sprint.yml restart zero-ui`.
3. **Smoke test one new carousel**: generate a Marvel character carousel (e.g. Loki) via the UI. Expected: body slides break across 2-3 lines with a rose-colored pill on one noun/number per slide, payoff line larger than setup lines, `slide_XX.png` from PIL renderer shows rose slide-number badge and `**` stripped from body.
4. **Batch dry-run**: `curl -X POST "http://localhost:18792/api/characters/fix-formatting?restyle=true&limit=5&character_id=loki"` with auth header. Spot-check the 5 snapshots in DB for: no factual drift, improved rhythm, preserved hashtags/accent_color.
5. **Full restyle**: once happy, `curl -X POST "http://localhost:18792/api/characters/fix-formatting?restyle=true"` to process all 200.
6. **Visual diff**: reload Billy Butcher, Cammy, Chani carousels in the frontend. Expected: colored pills on body-slide key words, not just the slide-number badge.

## Risks

- Preserve-emphasis leaking `**` into captions → keep `False` default, flip only on hook/slide paths.
- Restyle hallucinates new facts → explicit "do not add" prompt + `temperature=0.3` + snapshot-before-mutate + existing final-review drift check.
- DB accent color kills hash palette variety → universe map is only ~8 colors, but that IS the user's stated request. Revertible to hash fallback.
- Regeneration cost ~$1-3 for 200 carousels, one-time, acceptable.

## Reuse (do NOT reinvent)

- `get_unified_llm_client()` for the restyle LLM call
- `_snapshot_carousel` for rollback
- `register_variant` for Thompson Sampling A/B
- Existing `/fix-formatting` endpoint + `sanitize_text` (add kwarg, don't fork)
- Existing `tokenize` / `renderToken` in `TikTokPhonePreview` (extend, don't rewrite)
- Existing `_final_review_carousel` (add `final_slides` field, don't add a third LLM pass)

## Critical files

- [backend/app/services/character_content_utils.py](backend/app/services/character_content_utils.py)
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)
- [backend/app/services/character_prompt_seeds.py](backend/app/services/character_prompt_seeds.py)
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py)
- [frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx)
- [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts)
