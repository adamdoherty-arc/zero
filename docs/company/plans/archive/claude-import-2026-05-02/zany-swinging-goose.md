# Image Delete + Blocklist + 3 New Image Sources

## Context

Character images can be rejected (thumbs down) but not truly deleted. Rejected images get re-imported when "Source More" is clicked because `_source_images()` doesn't check for previously rejected URLs. Additionally, we only have 4 image sources and want to expand to 7.

**Problems solved:**
1. Delete button that removes an image AND prevents re-import via per-character blocklist
2. Fix deduplication so re-sourcing doesn't create duplicate DB rows
3. Add Pexels, Unsplash, Pixabay as new image sources (all free APIs)

## Current Image Sources

| Source | Quality Tier | Status |
|--------|-------------|--------|
| TMDB | 1.0 | Existing |
| Fandom Wiki | 0.9 | Existing |
| Wikipedia | 0.8 | Existing |
| **Pexels** | **0.7** | **NEW** |
| **Unsplash** | **0.7** | **NEW** |
| **Pixabay** | **0.6** | **NEW** |
| SearXNG | 0.5 | Existing |

Firecrawl is integrated for text scraping only (character research), not image discovery.

---

## Phase 1: Migration

**New file**: `backend/app/migrations/versions/021_image_blocklist.py`

- Add `blocked_image_urls JSONB DEFAULT '[]'` to `characters` table
- Add unique constraint on `character_images(character_id, url)` to prevent duplicate rows
- Handle existing duplicates: DELETE duplicate rows (keep earliest `created_at`) before adding constraint

## Phase 2: DB + Pydantic Models

**Modify**: [backend/app/db/models.py](backend/app/db/models.py)
- Add `blocked_image_urls: Mapped[Optional[list]]` to `CharacterModel` (after `content_themes`, ~line 248)
- Add `UniqueConstraint('character_id', 'url', name='uq_character_image_url')` to `CharacterImageModel`

**Modify**: [backend/app/models/character_content.py](backend/app/models/character_content.py)
- Add `blocked_image_urls: List[str] = []` to `Character` Pydantic model

## Phase 3: Config - Add API Keys

**Modify**: [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py)
- Add after TMDB config (~line 97):
```python
# Free image APIs
pexels_api_key: Optional[str] = None
unsplash_access_key: Optional[str] = None
pixabay_api_key: Optional[str] = None
```

**Modify**: [.env.example](.env.example)
- Add `ZERO_PEXELS_API_KEY=`, `ZERO_UNSPLASH_ACCESS_KEY=`, `ZERO_PIXABAY_API_KEY=`

## Phase 4: Backend Service - `delete_image()` + Fix Dedup

**Modify**: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)

**Add `delete_image(character_id, image_id)`** (after `reject_image`, ~line 1575):
1. Load the `CharacterImageModel` row, get its URL
2. Delete the row from `character_images` table
3. Add the URL to `blocked_image_urls` on the `CharacterModel`
4. Remove the URL from `image_urls` JSONB list on the character
5. If deleted image was the primary `image_url`, reassign to next available or set None
6. Return `{"deleted": True, "blocked_url": url}`

**Fix `_source_images()`** (~line 908):
1. Before inserting, load `blocked_image_urls` from the character
2. Load existing URLs from `character_images` table: `SELECT url FROM character_images WHERE character_id = ?`
3. Build `skip_urls = set(blocked_urls) | set(existing_urls)`
4. Skip any image whose URL is in `skip_urls`
5. Catch `IntegrityError` (from unique constraint) as fallback dedup

**Update `_character_to_pydantic()`**: Map `blocked_image_urls` field.

## Phase 5: Backend Router - DELETE Endpoint

**Modify**: [backend/app/routers/character_content.py](backend/app/routers/character_content.py)

Add after the reject endpoint (~line 707):
```python
@router.delete("/{character_id}/images/{image_id}", response_model=dict)
async def delete_image(character_id: str, image_id: str, ...):
```

## Phase 6: New Image Sources - Pexels, Unsplash, Pixabay

**Modify**: [backend/app/services/image_source_service.py](backend/app/services/image_source_service.py)

**Add to `SOURCE_TIERS`** (~line 36):
```python
"pexels": 0.7,
"unsplash": 0.7,
"pixabay": 0.6,
```

**Add 3 new source methods** (pattern matches existing `source_fandom_images`, `source_tmdb_images`, etc.):

### `source_pexels_images(name, universe, franchise)`
- Endpoint: `GET https://api.pexels.com/v1/search`
- Header: `Authorization: {PEXELS_API_KEY}`
- Params: `query="{name} {franchise}", per_page=15`
- Extract: `photo["src"]["large2x"]` for URL, `photo["width"]`, `photo["height"]`
- Skip if `pexels_api_key` is None

### `source_unsplash_images(name, universe, franchise)`
- Endpoint: `GET https://api.unsplash.com/search/photos`
- Header: `Authorization: Client-ID {UNSPLASH_ACCESS_KEY}`
- Params: `query="{name} {franchise}", per_page=15`
- Extract: `result["urls"]["regular"]` for URL, `result["width"]`, `result["height"]`
- Skip if `unsplash_access_key` is None

### `source_pixabay_images(name, universe, franchise)`
- Endpoint: `GET https://pixabay.com/api/`
- Params: `key={PIXABAY_API_KEY}, q="{name} {franchise}", per_page=15, image_type=photo, min_width=800`
- Extract: `hit["largeImageURL"]` for URL, `hit["imageWidth"]`, `hit["imageHeight"]`
- Skip if `pixabay_api_key` is None

**Update `discover_images()`** (~line 94): Add the 3 new sources to the `tasks` list (conditionally, only if API key is configured):
```python
settings = get_settings()
if settings.pexels_api_key:
    tasks.append(self._safe_source(self.source_pexels_images, name, universe, franchise))
if settings.unsplash_access_key:
    tasks.append(self._safe_source(self.source_unsplash_images, name, universe, franchise))
if settings.pixabay_api_key:
    tasks.append(self._safe_source(self.source_pixabay_images, name, universe, franchise))
```

## Phase 7: Frontend Hook

**Modify**: [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts)

Add `useDeleteImage()` mutation hook:
- Method: `DELETE /api/characters/${characterId}/images/${imageId}`
- Invalidates `['characters', characterId, 'images']` on success

## Phase 8: Frontend UI - Delete Button

**Modify**: [frontend/src/pages/CharacterDetailPage.tsx](frontend/src/pages/CharacterDetailPage.tsx)

In the Media tab image grid (~line 794-818):
- Import `Trash2` from lucide-react
- Add `deleteImgMut = useDeleteImage()`
- Add a red trash button next to approve/reject in the hover overlay
- On click: `window.confirm("Delete this image? It will be blocked from re-import.")`
- On confirm: `deleteImgMut.mutate({ characterId, imageId })`
- Show blocked count near "Image Library" heading if `character.blocked_image_urls?.length > 0`

---

## Files Summary

| File | Change |
|------|--------|
| `backend/app/migrations/versions/021_image_blocklist.py` | **NEW** - migration |
| `backend/app/db/models.py` | Add `blocked_image_urls` + unique constraint |
| `backend/app/models/character_content.py` | Add field to Pydantic model |
| `backend/app/infrastructure/config.py` | Add 3 API key settings |
| `.env.example` | Add 3 env var placeholders |
| `backend/app/services/character_content_service.py` | Add `delete_image()`, fix `_source_images()` dedup |
| `backend/app/routers/character_content.py` | Add DELETE endpoint |
| `backend/app/services/image_source_service.py` | Add 3 new source methods + update `discover_images()` + update `SOURCE_TIERS` |
| `frontend/src/hooks/useCharacterContentApi.ts` | Add `useDeleteImage` hook |
| `frontend/src/pages/CharacterDetailPage.tsx` | Add delete button + confirmation + blocked count |

## Verification

1. Run migration: `docker exec zero-api alembic upgrade head`
2. Rebuild backend: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
3. Restart frontend: `docker compose -f docker-compose.sprint.yml restart zero-ui`
4. Navigate to a character's Media tab
5. Delete an image (trash icon) - confirm dialog, image disappears
6. Click "Source More" - deleted image does NOT reappear
7. If API keys configured in .env: verify new sources appear (check source badges on new images)
8. Verify approve/reject buttons still work
9. Check `docker logs zero-api` for `image_discovery_complete` showing new source names
