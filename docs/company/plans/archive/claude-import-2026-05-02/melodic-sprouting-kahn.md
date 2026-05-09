# Carousel Editor + AI Enhancement + Council Voting

## Context

Character carousels look unfinished in the UI:
- Hook text appears "duplicated" (triple text-shadow + WebkitTextStroke in `TikTokPhonePreview.tsx` creates ghosting).
- "The Hammer Lie" still shows on old carousels. Banned pattern guards fire only on GENERATION, never on existing rows.
- "Black Widow" gets mentioned 3x on one slide while another slide omits the character entirely. No coverage checks.
- "The MCU" wraps to a new line. `_wrap_text` naively splits on spaces with no compound-term awareness.
- Aquaman's slide is "all white" because the static `bg_overlay=0.45` is too thin for dark images.
- The Edit button dumps users into the Review tab list (`/characters?tab=review&focus=<id>`) instead of a dedicated editor.

The fix is a dedicated carousel editor with per-slide AI enhancement (Local Ollama / Kimi / MiniMax), version history with revert, and Council of Agents voting on variants. The existing `character-content-review` skill audits architecture but never inspects rendered output, so visual bugs slip through. We add a new `--carousel-visual-qa` mode with rendering rules.

Outcome: carousels become editable, enhanceable on one click, reversible, and aesthetically captivating. The user can pick any model to improve any field, or hand the decision to the Council.

---

## Phase 1 - Backend

### 1.1 New table `character_carousel_versions`

New migration [backend/app/migrations/versions/027_character_carousel_versions.py](backend/app/migrations/versions/027_character_carousel_versions.py):
- `id` (str PK, `ccv-<uuid12>`)
- `carousel_id` FK -> `character_carousels.id` CASCADE, indexed
- `version_number` int (compute `MAX(version_number)+1 per carousel`)
- `parent_version_id` str nullable (mirrors `PromptVariantModel.parent_id`)
- Full mutable-field snapshot: `hook_text`, `slides` JSONB, `caption`, `hashtags` JSONB, `title`, `human_notes`, `music_track` JSONB, `text_overlay_specs` JSONB
- `source` (`manual_edit` | `enhance` | `council_vote` | `restore` | `backfill`)
- `source_metadata` JSONB (`target`, `provider`, `model`, `instruction`, `variant_rank`, `council_decision_id`)
- `created_by` (str), `created_at` (tz-aware)
- Index `(carousel_id, version_number DESC)`

Also add `current_version_id` nullable column on `character_carousels`.

### 1.2 ORM + Pydantic

[backend/app/db/models.py](backend/app/db/models.py) - add `CharacterCarouselVersionModel` after `CharacterCarouselModel` (~line 1657); add `current_version_id` column.

[backend/app/models/character_content.py](backend/app/models/character_content.py) - add:
- `CarouselVersion` response
- `EnhanceCarouselRequest(target: Literal['hook','slide','caption','hashtags','all'], slide_num: int | None, provider: str | None, model: str | None, instruction: str | None, n_variants: int = 1)`
- `CouncilVoteRequest(target, n_variants: int = Field(3, ge=2, le=5), providers: list[str] | None)`
- `RestoreVersionResponse`

### 1.3 Auto-snapshot on PATCH

[backend/app/services/character_content_service.py:2482-2494](backend/app/services/character_content_service.py#L2482-L2494) `update_carousel`: load row, call new `_snapshot_carousel(...)` before mutations when content fields change, apply `setattr`, set `row.current_version_id`, commit once.

Debounce: if last version is `manual_edit` within 60s on overlapping fields, overwrite it instead of inserting new (prevents UI auto-save spam).

### 1.4 New service methods (same file)

- `_snapshot_carousel(session, row, source, source_metadata, created_by)` - inserts version row, returns id. Uses `SELECT ... FOR UPDATE` to avoid lost updates.
- `enhance_carousel_piece(carousel_id, target, slide_num, provider, model, instruction, n_variants) -> list[variant]` - builds target-specific prompt, calls `unified_llm_client.chat(model=f"{provider}/{model}", temperature=0.7-0.9)` N times for diversity. Returns variants without applying.
- `apply_enhance_variant(carousel_id, target, slide_num, new_text, provider, model)` - snapshots as `enhance`, patches field, returns carousel.
- `run_council_on_carousel(carousel_id, target, n_variants=3)` - generates N variants across Kimi + MiniMax + Ollama via cheap `moonshot-v1-32k`, feeds to `council_service.propose()` then `run_rounds()` with `context={'variants': [...], 'original': ..., 'character': {...}}`. Votes escalate to `kimi-k2.5`. Returns `{decision_id, winning_variant, winning_rank, votes, reasoning}`. Does NOT auto-apply.
- `list_versions(carousel_id)` - ORDER BY version_number DESC LIMIT 50.
- `restore_version(carousel_id, version_id)` - snapshots current as `restore` first, copies version fields, commits.
- `backfill_banned_hooks(limit, dry_run)` - reuses `_is_generic_hook` + `_rewrite_generic_hook` at [character_content_service.py:361-444](backend/app/services/character_content_service.py#L361-L444). Only runs on `status in ('draft','review','approved')`, never `published`.

### 1.5 Strengthen banned pattern check

[character_content_service.py:361-383](backend/app/services/character_content_service.py#L361-L383) `_is_generic_hook`: normalize with `re.sub(r'[^a-z0-9\s]+', '', hook.strip().lower())` then collapse whitespace before regex. Applied in both generation and backfill.

### 1.6 New endpoints

[backend/app/routers/character_content.py](backend/app/routers/character_content.py) near line 441:

```
POST  /api/characters/carousels/{id}/enhance                 -> {variants: [...]}
POST  /api/characters/carousels/{id}/enhance/apply           -> CharacterCarousel
POST  /api/characters/carousels/{id}/council-vote            -> {decision_id, winning_variant, votes, reasoning}
POST  /api/characters/carousels/{id}/council-vote/apply      -> CharacterCarousel
GET   /api/characters/carousels/{id}/versions                -> list[CarouselVersion]
POST  /api/characters/carousels/{id}/versions/{vid}/restore  -> RestoreVersionResponse
POST  /api/characters/carousels/backfill-banned-hooks        -> {scanned, flagged, rewritten}
```

All carry `response_model=` and `Depends(require_auth)` per existing pattern.

### 1.7 Renderer fixes

[backend/app/services/carousel_renderer_service.py](backend/app/services/carousel_renderer_service.py):
- `_wrap_text` at [lines 303-322](backend/app/services/carousel_renderer_service.py#L303-L322): accept `no_break_terms` set with defaults (`"The MCU", "Black Widow", "Iron Man", "Captain America", "Peter Parker", "Bruce Wayne", "Harley Quinn", "Doctor Strange", "X-Men", "Avengers: Endgame"`, pulled from character profile). Substitute NBSP (`\u00A0`) within compounds before splitting; reverse on join.
- New `_compute_overlay_strength(img)` - `PIL.ImageStat` average luminance weighted toward bottom-third crop. Map to `0.35 + (avg_lum/255) * 0.35` (dark images get 0.35, bright get 0.70). Replace static 0.45 at [line 157-160](backend/app/services/carousel_renderer_service.py#L157-L160).
- New `_validate_contrast(img, text_region)` - attaches `contrast_ratio`, `passes_wcag_aa` to `generation_metadata.render_warnings`.
- When `_wrap_text` has to break a compound, record warning to `render_warnings` for the review skill.

### 1.8 Backfill scheduler job

[backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) - add `carousel_banned_hook_backfill` cron (daily 4am, `limit=50`).

### 1.9 Risks

- **Version explosion** - 60s debounce + cap 50 rows/carousel (prune oldest).
- **Council spend** - variants via cheap `moonshot-v1-32k`, only voting uses `kimi-k2.5`; respects daily budget via `unified_llm_client`. Add `max_council_votes_per_day=20` setting.
- **MiniMax fallback** - provider at [backend/app/infrastructure/llm_providers/minimax_provider.py](backend/app/infrastructure/llm_providers/minimax_provider.py) is new. `unified_llm_client` fallback chain drops to Kimi automatically if it errors.
- **Published carousels** - reject restore + backfill if `status='published'` unless `force=true` (409).

---

## Phase 2 - Frontend

### 2.1 New route

[frontend/src/App.tsx](frontend/src/App.tsx) - register above existing tabbed `/characters` route:
```
/characters/:characterId/carousels/:carouselId/edit -> CarouselEditorPage
```

### 2.2 New page `frontend/src/pages/CarouselEditorPage.tsx`

12-col grid on `lg`, stacked on mobile.

**Sticky header (bg-gray-900/80 blur):** breadcrumb; right cluster: Save, Run Council Vote (indigo), Version History toggle, Approve (green), Reject (red ghost).

**Left col-span-5 sticky top-20:** live `TikTokPhonePreview` bound to local `draft` state.

**Right col-span-7:** tabbed editor (`Slides | Caption | Metadata`), `shadcn/ui` style.

**Slides tab:** accordion per slide (first open). Per-slide fields: hook (slide 0 only), body textarea, position radio (top/center/bottom), bg_overlay slider (default `auto`). Action row: `[Sparkle] Enhance` button with model dropdown (`Local Ollama` / `Kimi K2.5` / `MiniMax M2.7`), `Regenerate Image`, `Preview Variants` drawer (N returned variants with inline Apply).

**Caption tab:** textarea, hashtag chip editor, `Enhance Caption` button with same picker.

**Metadata tab:** music picker (reuse `MusicPickerModal`), story template badge, read-only generation metadata, human_notes.

**Right drawer (Version History):** per-version badge (source), timestamp, author, field diff summary, Preview (temp-loads version into preview), Restore (confirm modal).

**Aesthetic:** `bg-gray-900` page, `bg-gray-800/50 border border-gray-700 rounded-xl` cards, indigo-500 primary, yellow-300 label pills matching TikTok. `framer-motion` for accordion, drawer, sparkle-pulse on enhance. Auto-save debounced 1.5s + toast. Keyboard: Ctrl+S save, Ctrl+Z local undo (20 deep) before hitting server versions.

### 2.3 Hooks

[frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) - add:
- `useEnhanceCarouselPiece()`
- `useApplyEnhanceVariant()`
- `useCarouselCouncilVote()` + `useApplyCouncilWinner()`
- `useCarouselVersions(carouselId)` (10s stale)
- `useRestoreCarouselVersion()`

Use `['characters','carousels', carouselId, 'versions']` key factory pattern.

### 2.4 Fix `CarouselCard.tsx`

[frontend/src/components/character-content/CarouselCard.tsx:152](frontend/src/components/character-content/CarouselCard.tsx#L152):
- Edit route -> `/characters/${carousel.character_id}/carousels/${carousel.id}/edit`.
- Add `[Sparkle] Enhance` icon button next to Edit. Opens popover: model dropdown + `Enhance All`; calls `useEnhanceCarouselPiece({target:'all'})` then refreshes. Fans out via `CarouselCard` usage in `CharacterDetailPage`, `CharacterContentPage`, `CharacterAutopilotPage`, `MobileReviewPage`.

### 2.5 Fix the "duplicated" text rendering

[frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx):
- [Line 54-55](frontend/src/components/character-content/TikTokPhonePreview.tsx#L54-L55): replace `TEXT_SHADOW_STRONG` with single-layer `'0 2px 6px rgba(0,0,0,0.85)'`.
- [Line 90](frontend/src/components/character-content/TikTokPhonePreview.tsx#L90): remove `WebkitTextStroke: '0.4px rgba(0,0,0,0.55)'` (source of ghosting). Keep 0 stroke on label pills.
- Optional `filter: drop-shadow(0 1px 2px rgba(0,0,0,0.6))` on container.
- Gate via `renderMode` prop (`clean` default, `stroked` legacy) so old screenshots stay reproducible.

### 2.6 Risks

- **Large carousels 10+ slides** - lazy mount accordion contents.
- **Concurrent council vote + edits** - disable Save during vote; show inline role-avatar progress.
- **Version drawer** - cap 25, `Load older` button.
- **Model picker persistence** - `localStorage['zero.carousel.lastModel']`.
- **Keystroke performance** - memoize `CaptivatingText` tokens; don't re-render entire phone frame.
- **Mobile** - drawer becomes bottom sheet via `MobileLayout`.

---

## Phase 3 - Review Skill Update

### 3.1 New reference

[.claude/skills/character-content-review/RENDERING_RULES.md](.claude/skills/character-content-review/RENDERING_RULES.md):
- **R1 Duplication** - flag if `hook_text` equals `slides[0].text` (case-insensitive, whitespace-collapsed).
- **R2 Compound wrap** - read `generation_metadata.render_warnings` for broken compounds.
- **R3 Character coverage** - count `character.name` + first-name mentions across hook + slides + caption. Flag `> 1.5 * slide_count` (over-saturated) or `== 0` on slides > 1 (under-mentioned). Per-character allowlist for multi-token names (e.g. `Spider-Man`).
- **R4 Contrast** - read `contrast_ratio`; flag `< 4.5:1` (WCAG AA).
- **R5 Banned hooks on existing rows** - run normalized regex against `hook_text` and `slides[0].text`.
- **R6 Text density** - words per slide (excluding hook); flag `< 3` or `> 40`.

### 3.2 New mode in SKILL.md

[.claude/skills/character-content-review/SKILL.md](.claude/skills/character-content-review/SKILL.md) - add `--carousel-visual-qa` mode:
- Input: `carousel_id` or `character_id`.
- Fetches carousel + render metadata, evaluates rules, emits findings + fix commands (exact `POST /api/characters/carousels/{id}/enhance` payloads per rule).

---

## Phase 4 - Ship

### 4.1 Deploy

```bash
docker exec -it zero-api alembic upgrade head
docker compose -f docker-compose.sprint.yml build --no-cache zero-api
docker compose -f docker-compose.sprint.yml up -d zero-api
docker compose -f docker-compose.sprint.yml restart zero-ui
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
```

### 4.2 One-shot cleanup

```
POST /api/characters/carousels/backfill-banned-hooks {"limit":500,"dry_run":false}
```

### 4.3 Legion sprint

Create sprint `Carousel Editor + Enhancement` on project_id=8; seed tasks per phase; update via `LegionClient.update_task()`.

---

## Verification

1. Create a carousel via existing generate endpoint -> version 1 auto-created.
2. Open `/characters/<id>/carousels/<cid>/edit` -> preview renders, tabs work.
3. PATCH hook in UI -> version 2 `source=manual_edit`.
4. Enhance hook with Kimi, apply variant -> version 3 `source=enhance`.
5. Enhance slide 3 with MiniMax, apply -> version 4.
6. Run Council Vote (n=3), apply winner -> version 5 `source=council_vote`.
7. Version drawer -> restore version 2 -> version 6 `source=restore`, content equals v2.
8. Render an Aquaman-style dark slide -> `bg_overlay ~= 0.4`, contrast passes.
9. Render MCU slide -> "The MCU" stays on one line; `render_warnings` empty.
10. Click `Enhance` on a CarouselCard from `CharacterContentPage` -> round-trip succeeds.
11. Run `--carousel-visual-qa` skill against any old carousel containing "The Hammer Lie" -> flagged, backfill rewrites, re-run returns zero findings.
12. Visually: hook text looks crisp, no ghosting from multi-shadow.

---

## Critical Files

Backend:
- [backend/app/db/models.py](backend/app/db/models.py) (new version model, new column)
- [backend/app/models/character_content.py](backend/app/models/character_content.py) (new request/response models)
- [backend/app/migrations/versions/027_character_carousel_versions.py](backend/app/migrations/versions/027_character_carousel_versions.py) (new)
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) (snapshot, enhance, council, versions, backfill, normalized pattern check)
- [backend/app/services/carousel_renderer_service.py](backend/app/services/carousel_renderer_service.py) (compound-aware wrap, brightness overlay, contrast validation)
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) (7 new endpoints)
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) (daily backfill job)
- [backend/app/services/council_service.py](backend/app/services/council_service.py) (reuse `propose` + `run_rounds`)
- [backend/app/infrastructure/unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py) (reuse explicit `model="provider/id"`)

Frontend:
- [frontend/src/App.tsx](frontend/src/App.tsx) (new route)
- [frontend/src/pages/CarouselEditorPage.tsx](frontend/src/pages/CarouselEditorPage.tsx) (new)
- [frontend/src/components/character-content/TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx) (shadow/stroke fix)
- [frontend/src/components/character-content/CarouselCard.tsx](frontend/src/components/character-content/CarouselCard.tsx) (edit route + Enhance button)
- [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) (5 new hooks)

Skill:
- [.claude/skills/character-content-review/SKILL.md](.claude/skills/character-content-review/SKILL.md) (new mode)
- [.claude/skills/character-content-review/RENDERING_RULES.md](.claude/skills/character-content-review/RENDERING_RULES.md) (new)
