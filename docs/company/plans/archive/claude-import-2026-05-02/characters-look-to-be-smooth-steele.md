# Character Content: Image Quality, Cast Linkage, and Deep Links

## Context

The character content system has three connected problems visible in the UI:

1. **Character list is capped at 100** while the research queue shows 415 entities. The Characters tab only ever displays 100 because `GET /characters` defaults to `limit=100` ([backend/app/routers/character_content.py:1162](backend/app/routers/character_content.py#L1162)) and the frontend never passes a larger limit.
2. **Many tiles have no image, and some characters (e.g., Thor) have wrong images.** `image_source_service.py` validates resolution, faces, perceptual-hash duplication, and source tier — but it has **no character-relevance check**. A high-res face from a stock photo or a different Marvel character passes the gate.
3. **Movies/TV shows and characters are siloed.** The DB junction `character_media_titles` exists ([backend/app/db/models.py:2076](backend/app/db/models.py#L2076)) but is empty — the system never scrapes TMDB cast credits, so there is no "appears in" / "cast" navigation, and orphan characters can't be cross-referenced against the 84 movies and 81 TV shows already researched.

This plan addresses all three end-to-end: surface every character, raise the bar on image relevance, populate cast linkage from TMDB, and add the deep-link UI.

## Approach

### 1. Surface all characters (remove the 100 cap)

- **Backend**: change [backend/app/routers/character_content.py:1162](backend/app/routers/character_content.py#L1162) default from `limit=100` to `limit=500` and raise the `le` ceiling to `2000`. Add an `offset: int = Query(0, ge=0)` param. Extend `list_characters()` in [backend/app/services/character_content_service.py:630](backend/app/services/character_content_service.py#L630) to apply `.offset(offset)` and return a total-count alongside the rows.
- **Frontend**: update `useCharacters()` in [frontend/src/hooks/useCharacterContentApi.ts:346](frontend/src/hooks/useCharacterContentApi.ts#L346) to pass `?limit=1000`. Defer infinite-scroll until needed — a single 1000-row payload is fine for the current scale.

### 2. Image relevance via Gemini Vision (top-N validate during discovery)

Add a vision-based "is this actually {character}?" check to the existing image discovery pipeline. Validate the **top 8** candidates after the quality sort but **before** pHash dedup, so a high-res image of the wrong character gets demoted before it can crowd out a correct lower-res image.

- **New service**: `backend/app/services/character_image_relevance_service.py`
  ```python
  async def score_relevance(
      image_url: str,
      character_name: str,
      universe: str,
      franchise: Optional[str],
      description: Optional[str] = None,
  ) -> dict  # {"score": 0.0-1.0, "is_match": bool, "reason": str}
  ```
  Uses `UnifiedLLMClient.chat()` with `model="gemini-3.1-flash"` (per [CLAUDE.md](CLAUDE.md) routing through shared LiteLLM at `host.docker.internal:4444`). Multimodal message: `[{"type":"text","text":<prompt>}, {"type":"image_url","image_url":{"url":<url>}}]`. Prompt asks for JSON: `match` (bool), `confidence` (0–1), `reason` (≤20 words). Reject generic stock photos, wrong characters, watermarks, multi-figure comic panels. On any exception return `{"score": 0.5, "reason": "vision_unavailable"}` so a vision outage never blocks discovery.

- **Wire into discovery** at [backend/app/services/image_source_service.py:337](backend/app/services/image_source_service.py#L337):
  After the quality-score sort, take `validated[:8]`, run `score_relevance` in parallel under an `asyncio.Semaphore(3)`, attach `relevance_score` and `relevance_reason` to each img dict. Then run pHash dedup as today.

- **Update scoring** in `compute_quality_score()` (same file, ~line 95–186) — add an optional `relevance: Optional[float] = None` parameter. New formula:
  ```python
  rel_factor = relevance if relevance is not None else 0.7
  return round(min(1.0, base_score * (0.4 + 0.6 * rel_factor)), 3)
  ```
  Multiplicative with a floor at 0.4 — a fully-irrelevant image keeps 40% of its prior score (correctly demoted but not zeroed if vision is uncertain), a perfect match keeps 100%. This is what fixes the Thor failure mode: a sharp 1080p photo of the wrong character drops below a softer correct one.

- **Persistence**: when `relevance < 0.3`, set `is_valid=False` on `CharacterImageModel` and stamp `feedback_reason="vision_rejected: <reason>"`. Do **not** auto-add to `blocked_image_urls` — that field stays human-curated to preserve existing semantics ([character_content_service.py:3341](backend/app/services/character_content_service.py#L3341)).

### 3. Backfill existing characters without nuking good images

- **New method** in [character_content_service.py](backend/app/services/character_content_service.py) near line 2400: `revalidate_existing_images(character_id: str, dry_run: bool = False) -> dict`. Iterates `CharacterImageModel` rows where `is_valid=True AND (feedback_reason IS NULL OR feedback_reason NOT LIKE 'vision_%')`, scores each, updates `quality_score` and (for rejects) `is_valid=False` + `feedback_reason`.

- **Primary-image safety**: if the current `image_url` (primary) fails relevance, **first** check whether any still-valid image scores higher. If yes, demote the current primary and promote the best remaining. If no, leave the primary in place and stamp `CharacterModel.notes = "primary_image_pending_review"`. Guarantee: a vision miss never leaves a character imageless.

- **Refill empties**: for any character where `len(image_urls) < 5`, re-run `discover_images()` so the relevance-aware pipeline gets fresh candidates from all sources. This is the answer to "many tiles do not have pictures."

- **Admin endpoint**: `POST /character-content/admin/revalidate-images?character_id=...&dry_run=true` returning a per-image diff so we can audit a few before mass-running. Add `&all=true` for full backfill.

### 4. TMDB cast scraping → populate `character_media_titles`

- **New service**: `backend/app/services/media_cast_sync_service.py`
  ```python
  async def sync_cast_for_title(media_title_id: str, top_n: int = 15) -> dict
  async def sync_all_cast(universe: Optional[str] = None) -> dict
  ```
  Reuses the TMDB key already plumbed into [media_research_sources.py:192](backend/app/services/media_research_sources.py#L192). Hits `/movie/{tmdb_id}/credits` for movies and `/tv/{tmdb_id}/aggregate_credits` for TV (aggregate captures all-season cast). Sort by TMDB `order` ascending, take top 15 to avoid cameo pollution.

- **Matching strategy** (franchise-scoped, fuzzy):
  1. Exact `lower(name) == lower(character_name)` within `universe = title.universe AND (franchise IS NULL OR franchise = title.franchise)`.
  2. If miss, `rapidfuzz.fuzz.token_set_ratio >= 90` within the same scope (`rapidfuzz` is already in [backend/requirements.txt](backend/requirements.txt)).
  3. If still no match AND `order <= 5` (top-billed only): auto-create a stub with `status="pending"`, `notes="auto-imported from TMDB cast of {title}"`, scoped franchise/universe. Cameos (`order > 5`) are **skipped** — only existing-character matches create junction rows. This prevents "Asgardian Soldier #3" pollution while still rescuing top-billed orphans like Heimdall.

- **Idempotent upsert** into `CharacterMediaTitleModel` — the existing `UniqueConstraint("character_id", "media_title_id")` ([db/models.py:2076](backend/app/db/models.py#L2076)) makes re-runs safe.

- **Trigger points**:
  - Admin endpoint: `POST /media-content/admin/sync-cast?media_title_id=...` plus `?all=true` for full backfill of all 165 titles.
  - Hook into existing `/titles/{id}/research` flow at [backend/app/routers/media_content.py](backend/app/routers/media_content.py) so newly-researched titles auto-sync cast.

### 5. Deep-link UI surface (extend, don't add)

- **Backend**:
  - Extend `GET /character-content/characters/{id}` in [backend/app/routers/character_content.py:1172](backend/app/routers/character_content.py#L1172) — add `appears_in: List[{media_title_id, title, media_type, year, role_type, role_name, poster_url}]` joined from `character_media_titles` + `media_titles`.
  - The endpoint `GET /media-content/titles/{id}/characters` already exists. Extend its serializer to return `image_url`, `role_type`, `role_name` from the junction so the cast list can render character thumbnails.

- **Frontend**:
  - On the character card in [frontend/src/pages/CharacterContentPage.tsx:454](frontend/src/pages/CharacterContentPage.tsx#L454), add an "Appears in: [Movie 1] [Show 2] +N" chip row. Each chip routes to the media detail page.
  - On the media detail view ([frontend/src/pages/MediaContentPage.tsx](frontend/src/pages/MediaContentPage.tsx)), add a Cast section consuming `/titles/{id}/characters`. Each cast tile clickable → character page.
  - Add a small "Auto-imported from cast" badge on cards where `status="pending"` so review of TMDB-created stubs is visible.

## Files

**Modified:**
- [backend/app/services/image_source_service.py](backend/app/services/image_source_service.py) — add relevance hook, update `compute_quality_score` signature
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — add `revalidate_existing_images`, primary-image safety logic, extend serializer with `appears_in`
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) — bump `limit` default to 500, add `offset`, add admin revalidate endpoint
- [backend/app/routers/media_content.py](backend/app/routers/media_content.py) — admin `sync-cast` endpoint, extend cast serializer
- [backend/app/services/media_content_service.py](backend/app/services/media_content_service.py) — wire cast sync into research completion
- [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) — pass `?limit=1000`
- [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) — "appears in" chips on cards
- [frontend/src/pages/MediaContentPage.tsx](frontend/src/pages/MediaContentPage.tsx) — cast section on detail view

**New:**
- `backend/app/services/character_image_relevance_service.py`
- `backend/app/services/media_cast_sync_service.py`

## Order of Operations

1. **Plumbing**: build `character_image_relevance_service.py`. Verify the LiteLLM router accepts multimodal `image_url` blocks for `gemini-3.1-flash` against 5 known-good and 5 known-bad fixtures. If the router rejects multimodal, fall back to base64-encoded `image_data` blocks (single-file change).
2. **Wire relevance into discovery**: modify `compute_quality_score` and the `discover_images` flow. Run end-to-end for one test character; verify the `is_valid=False` cascade.
3. **Backfill images**: implement `revalidate_existing_images`, dry-run on 5 characters, audit, then full ~100. Confirm no character ends up imageless.
4. **TMDB cast sync**: build `media_cast_sync_service`, dry-run on one movie + one TV show, audit auto-creates, then run all 165 titles.
5. **UI surface**: extend the two existing endpoints, add chip row + cast section, raise the list limit. Ship.
6. **Background hooks**: wire cast sync into media research completion; wire relevance into the existing periodic `discover_images` job at [character_content_service.py:2419](backend/app/services/character_content_service.py#L2419).
7. **Rebuild + restart** `zero-api` per CLAUDE.md post-change deployment rule:
   ```bash
   docker compose -f docker-compose.sprint.yml build --no-cache zero-api && \
   docker compose -f docker-compose.sprint.yml up -d zero-api
   ```

## Risks & Mitigations

- **Vision cost**: ~100 chars × 8 candidates = 800 calls; gemini-3.1-flash ≈ $0.0003/call → ~$0.25 total backfill. Negligible.
- **LiteLLM multimodal compatibility**: the only real unknown. Test against the router before committing to the integration; isolate the call so swapping providers is trivial.
- **Auto-created stubs polluting the list**: top-5-billing rule + `status="pending"` keeps them visible-but-segregated. Add a "pending review" filter chip in the UI if volume is high.
- **rapidfuzz cross-franchise false positives**: the franchise/universe scoping in step 1 of the matcher is the guard — do not skip it.

## Verification

- **Hits the original problems:**
  - `curl localhost:18792/api/characters?limit=1000 | jq 'length'` should return >100.
  - Spot-check Thor: `GET /api/characters/{thor_id}` — `image_urls` should be all relevant; `feedback_reason` set on rejects.
  - `GET /api/characters/{thor_id}` should return `appears_in` with multiple Marvel movies populated.
  - `GET /api/media-content/titles/{endgame_id}/characters` should return Thor, Iron Man, etc., with `role_type` and thumbnails.
- **UI**: Characters tab shows >100 cards; clicking a movie chip on a character card navigates to the movie; cast section on a movie page navigates back to characters.
- **Idempotency**: re-run `sync-cast?all=true` — second run should produce zero new junction rows (unique constraint enforces).
- **No data loss**: after `revalidate-images?all=true`, every character with an existing image still has a non-null `image_url` (run a SQL check: `SELECT COUNT(*) FROM characters WHERE image_url IS NULL AND id IN (SELECT character_id FROM character_images)` — must be 0 unless it was 0 before).
- **Logs**: `docker logs zero-api | grep -E "vision_rejected|cast_sync|image_phash_dedup"` shows the new flows firing.
