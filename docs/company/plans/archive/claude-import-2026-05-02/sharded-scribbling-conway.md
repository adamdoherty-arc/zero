# Image Pipeline Overhaul for Character Content Carousels

## Context

Carousel images look terrible. The root cause is a fundamentally broken image pipeline with 6 compounding failures:

1. **Single source**: Only SearXNG image search. Returns thumbnails, watermarked stock photos, irrelevant results.
2. **Zero validation**: Every URL stored as `is_valid=True`. No checks for resolution, broken links, format, or content type.
3. **Random assignment**: Images assigned to slides sequentially by `usage_count`. The LLM generates a specific `image_query` per slide but it is **completely ignored**.
4. **Broken rotation**: `usage_count` is never incremented, so the rotation strategy does nothing.
5. **No feedback loop**: No quality scores, no image approve/reject, carousel approval doesn't record outcomes to the brain.
6. **Renderer ignores per-slide images**: `carousel_renderer_service.py` uses ONE background image for ALL slides. Per-slide `image_url` values are never read.

## Plan (6 Phases)

---

### Phase 1: Image Validation + Bug Fixes (Quick Wins)
**Files:**
- [character_content_service.py](backend/app/services/character_content_service.py) - `_source_images()` (line 862), `_assign_slide_images()` (line 1169)

**Changes:**

**1a. Add `_validate_image_url()` method** (~30 lines)
- HTTP HEAD to check URL returns 200 + `image/*` content-type
- Download first 64KB, use Pillow to extract dimensions
- Reject images < 800px wide (too small for TikTok 1080px slides)
- Modeled on existing `tiktok_shop_service.py:1440` pattern

**1b. Validate during `_source_images()`** (modify lines 880-907)
- Call `_validate_image_url()` before storing each image
- Store `width`, `height` in CharacterImageModel (fields already exist but never populated)
- Skip invalid/small images instead of storing everything blindly
- Log validation stats: `images_tested`, `images_valid`, `images_rejected`

**1c. Fix `usage_count` increment** (modify lines 1169-1184)
- After assigning an image to a slide, increment its `usage_count` in DB
- This makes the rotation strategy actually work

**1d. Add validate-all endpoint** (new endpoint in router)
- `POST /api/characters/images/validate-all?limit=100`
- Iterates existing images where `width IS NULL`, validates each, marks `is_valid=False` for broken ones
- One-time cleanup of existing bad images

---

### Phase 2: Smart Image-to-Slide Matching (Core Fix)
**Files:**
- [character_content_service.py](backend/app/services/character_content_service.py) - `_assign_slide_images()` (line 1169)
- [carousel_renderer_service.py](backend/app/services/carousel_renderer_service.py) - `render_carousel()` (line 39)

**Changes:**

**2a. Rewrite `_assign_slide_images()` with 3-tier strategy:**
1. **Keyword match**: Compare slide's `image_query` (from LLM) against `query_used` on existing images. Pick best keyword overlap, avoiding already-used images.
2. **On-demand search**: If no good match, run SearXNG search with the slide's `image_query` + validate result. Store new image and assign.
3. **Fallback**: If search fails, fall back to least-used existing image (current behavior, but with usage_count working).

**2b. Fix renderer to use per-slide images** (modify lines 65-95)
- Each slide already has `image_url` in its dict. Use it.
- Download per-slide `image_url` as that slide's background
- Keep current `character_image_url` as fallback when a slide has no `image_url`
- Use semaphore to limit concurrent downloads (max 3)

---

### Phase 3: Multi-Source Image Discovery
**Files:**
- **NEW**: [image_source_service.py](backend/app/services/image_source_service.py) (~250 lines)
- [character_content_service.py](backend/app/services/character_content_service.py) - `_source_images()`
- [character_research_sources.py](backend/app/services/character_research_sources.py)
- [config.py](backend/app/infrastructure/config.py)

**Changes:**

**3a. Create `ImageSourceService`** with parallel multi-source discovery:

| Source | How | Quality | Cost |
|--------|-----|---------|------|
| **Fandom Wiki** | MediaWiki API `prop=pageimages\|images` + `imageinfo` for dimensions | High (official art, screenshots) | Free |
| **Wikipedia** | REST API `/api/rest_v1/page/media-list/{title}` | High (curated) | Free |
| **TMDB** | `/3/search/multi` + `/3/movie/{id}/images` for backdrops/stills | Very High (1920x1080 stills, official posters) | Free (1000 req/day) |
| **SearXNG** | Existing image search (improved queries) | Medium | Free |

**3b. Improve SearXNG queries:**
- Add character's actor name to queries (e.g., "Robert Downey Jr Iron Man still")
- Add "HD", "4K", "official" qualifiers
- Search for scene-specific images matching slide content

**3c. Quality scoring formula:**
```
quality_score = (
    resolution_score(width, height) * 0.4 +   # 1080+ = 1.0, 800-1080 = 0.7, <800 = 0
    source_tier(source) * 0.3 +                 # tmdb=1.0, fandom=0.9, wiki=0.8, searxng=0.5
    aspect_ratio_score(w, h) * 0.3              # ~3:4 (portrait) = 1.0, landscape = 0.6
)
```

**3d. Wire into `_source_images()`**: Replace current inline SearXNG logic with `ImageSourceService.discover_images()`. Store quality_score per image.

**3e. Config**: Add `ZERO_TMDB_API_KEY` to settings (optional; system works without it, just fewer sources).

---

### Phase 4: DB Schema + Feedback Loop + Brain Integration
**Files:**
- **NEW**: [020_image_quality_feedback.py](backend/app/migrations/versions/020_image_quality_feedback.py)
- [models.py](backend/app/db/models.py) - `CharacterImageModel`
- [character_content.py](backend/app/models/character_content.py) - `CharacterImage` Pydantic model
- [character_content_service.py](backend/app/services/character_content_service.py) - `approve_carousel()`, `reject_carousel()`
- [character_content.py router](backend/app/routers/character_content.py)

**Changes:**

**4a. Migration** - add columns to `character_images`:
- `quality_score` (Float, default 0.0) - computed during discovery
- `content_type` (String(50)) - image/jpeg, image/png, etc.
- `file_size` (Integer) - bytes
- `is_approved` (Boolean, nullable) - null=unreviewed, true=good, false=bad
- `feedback_reason` (Text) - why image was rejected
- `validated_at` (DateTime with timezone)
- Index: `(character_id, quality_score)` for fast sorted queries

**4b. Update ORM + Pydantic models** with new fields.

**4c. Brain outcome recording** - wire into `approve_carousel()` and `reject_carousel()`:
- Call `brain.record_outcome()` with carousel metadata (angle, character, template, image sources used)
- This lets the learning system correlate image sources with approval rates

**4d. Per-image feedback endpoints:**
- `POST /{character_id}/images/{image_id}/approve`
- `POST /{character_id}/images/{image_id}/reject?reason=...`
- Sets `is_approved` + `feedback_reason`, records to brain

**4e. Image-aware AI review** - add `image_relevance` score to AI review prompt so the LLM evaluates whether slide images match content.

---

### Phase 5: Frontend UI Improvements
**Files:**
- [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)
- [useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts)

**Changes:**

**5a. Image quality badges** on carousel slide previews:
- Green badge for quality_score > 0.7
- Yellow for 0.4-0.7
- Red for < 0.4 or missing image
- Show dimensions tooltip on hover

**5b. Per-image approve/reject buttons** in character image grid (thumbs up/down)

**5c. "Re-search image" button** per slide in review queue:
- Triggers SearXNG search with that slide's `image_query`
- Shows results in a picker modal
- User selects replacement image

**5d. TypeScript interface updates** for new `CharacterImage` fields (quality_score, is_approved, etc.)

**5e. New hooks**: `useApproveImage()`, `useRejectImage()`, `useValidateAllImages()`

---

### Phase 6: Bulk Re-Process Existing Carousels
**Files:**
- [character_content_service.py](backend/app/services/character_content_service.py)
- [character_content.py router](backend/app/routers/character_content.py)

**Changes:**

**6a. Validate all existing images** - run Phase 1d endpoint to purge broken URLs and mark dimensions.

**6b. Re-source images for all characters** - trigger `source_images_on_demand()` for each character using the new multi-source pipeline.

**6c. Bulk re-image endpoint** - `POST /api/characters/carousels/bulk-reimage?status=draft&limit=20`:
- For each carousel: re-source character images if < 6 valid, then re-assign using smart matching.
- Returns count of updated carousels.

**6d. Scheduler job** - every 12 hours, validate random sample of 50 images. Mark broken ones `is_valid=False`. Re-source replacements.

---

## Implementation Order

```
Phase 1 (1-2h)  -->  Phase 4a (migration, 30min)  -->  Phase 2 (2-3h)
                                                         |
                                                    Phase 3 (3-4h)
                                                         |
                                              Phase 4b-e + 5 + 6 (3-4h)
```

Phase 4a (migration) should be done early since Phases 2-3 benefit from `quality_score` column.

Total estimated: ~12 hours across all phases.

## Verification

After each phase, verify by:
1. **Phase 1**: Run `POST /api/characters/images/validate-all`. Check that images now have width/height populated and invalid ones are marked.
2. **Phase 2**: Generate a new carousel. Verify each slide has a different, relevant image (not just sequential). Check rendered PNGs use per-slide images.
3. **Phase 3**: Run `POST /{character_id}/source-images`. Verify images come from multiple sources (fandom, wiki, tmdb, searxng) with quality scores.
4. **Phase 4**: Approve/reject a carousel. Check brain outcome recorded. Approve/reject an image. Check `is_approved` field.
5. **Phase 5**: Open Character Content page. Verify quality badges, approve/reject buttons, re-search modal work.
6. **Phase 6**: Run `POST /api/characters/carousels/bulk-reimage`. Verify existing carousels get better images assigned.

Final validation: Generate 3 new carousels for different characters. All slides should have high-quality, relevant, unique images from multiple sources.
