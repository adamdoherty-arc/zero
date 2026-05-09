# TikTok Shop Affiliate Marketing - Make Zero Actually Work

## Context

Zero has an impressive TikTok Shop codebase (~5,000+ lines, 10 services, 13 scheduler jobs, a 7-node LangGraph pipeline, 5 video templates, full frontend with 7 tabs) but **none of it works end-to-end** because:

1. **No TikTok credentials** - `ZERO_TIKTOK_CLIENT_KEY`/`ZERO_TIKTOK_CLIENT_SECRET` not set
2. **AIContentTools client has wrong endpoints** - AIContentTools IS running (port 8085, healthy) but Zero's client calls `/api/generate` which doesn't exist. Correct endpoints: `/api/video/generate`, `/api/video/jobs/{job_id}`, `/api/repurpose/carousel`. Also has carousel creation, publishing, and TikTok platform support built in.
3. **No affiliate-specific features** - Products are discovered but there's no way to get affiliate links, commission rates, or TikTok Shop marketplace listings
4. **Unknown pipeline health** - SearXNG may not be running, scheduler may not be executing

**User situation**: Has TikTok account with <1K followers. Wants fully automated affiliate marketing with Zero handling product discovery, content generation, and posting. No niche preference - let the system discover what's profitable.

**Goal**: Get Zero's TikTok pipeline running end-to-end for affiliate marketing with practical content creation that doesn't depend on missing services.

---

## Phase 1: Get the Existing Pipeline Running (Diagnostics + Fixes)

### 1.1 Verify infrastructure health
- Check `docker ps` for `zero-api`, `zero-ui`, `zero-postgres`, `zero-searxng` status
- Test SearXNG: `curl http://localhost:8888/search?q=test&format=json`
- If SearXNG down: `docker compose -f docker-compose.searxng.yml up -d`
- Check scheduler status via `/api/system/scheduler/status`

### 1.2 Trigger a manual research cycle
- Call `POST /api/tiktok-shop/research/cycle` to test the full discovery pipeline
- Check `docker logs zero-api` for `tiktok_shop_research_cycle_complete`
- Verify products appear in the database

### 1.3 Fix any startup issues
- If research cycle fails, debug SearXNG connectivity (container must be on `zero-network`)
- Verify LLM router is working (Kimi for product extraction/scoring)

**Files involved**: No code changes needed, just diagnostic commands.

---

## Phase 2: Fix AIContentTools Client Endpoint Mismatches

The client exists at `ai_content_tools_client.py` but calls wrong endpoints. AIContentTools v4.0 API:
- Video generation: `/api/video/generate` (not `/api/generate`)
- Job status: `/api/video/jobs/{job_id}` (not `/api/batch/status/{job_id}`)
- Video download: `/api/video/jobs/{job_id}/download`
- Carousel: `/api/repurpose/carousel` (POST, needs `image_ids`, `platform`, `caption`, `hashtags`)
- Publishing: `/api/publishing/publish` (correct)
- Personas: `/api/personas/` (correct)
- Strategy: `/api/strategy/generate` (not `/api/strategy/recommend`)
- Video templates: `/api/video/templates` (social_reel_fashion, product_showcase, etc.)

### 2.1 Fix `ai_content_tools_client.py` endpoints
- `generate_content()`: Change `/api/generate` to `/api/video/generate`, update payload to match `VideoGenerateRequest` schema
- `get_job_status()`: Change `/api/batch/status/{job_id}` to `/api/video/jobs/{job_id}`
- `get_strategy_recommendations()`: Change `/api/strategy/recommend` to `/api/strategy/generate`
- Add new methods: `get_video_download_url()`, `create_carousel()`, `list_video_templates()`

### 2.2 Fix `tiktok_video_service.py` queue_for_generation
- Update to use correct `generate_content()` with proper params
- Add `video_type="text_to_video"` parameter
- Use TikTok-appropriate video settings (9:16, 1080x1920)

### 2.3 Fix publishing_service.py video URL retrieval
- Use `/api/video/jobs/{job_id}/download` for completed video URLs instead of performance endpoint
- Add fallback for manual video URL entry

### 2.4 Add new DB columns for enhanced tracking
- `video_url` (String, nullable) on ContentQueueModel
- `content_format` (String, default "video") on ContentQueueModel
- `carousel_data` (JSON, nullable) on ContentQueueModel

---

## Phase 3: Add Photo Carousel Content (Lowest-Effort Fully Automated Content)

Photo carousels are the killer feature for automated affiliate marketing:
- No video editing needed
- Just 2-10 product images + text overlays + trending audio
- High conversion for product discovery
- Can be fully auto-generated from product data + images

### 3.1 Add carousel template to FACELESS_TEMPLATES
**File**: `backend/app/services/tiktok_video_service.py` (line 34-159)

Add `"photo_carousel"` template:
```python
"photo_carousel": {
    "name": "Photo Carousel",
    "description": "2-10 product images with text overlays. No video editing needed.",
    "duration": 0,
    "sections": ["hook_slide", "feature_1", "feature_2", "feature_3", "price_cta"],
    "prompt_template": "Create a TikTok photo carousel for {product_name}..."
}
```

### 3.2 Add `VideoTemplateType.PHOTO_CAROUSEL` enum value
**File**: `backend/app/models/tiktok_content.py`

### 3.3 Generate carousel packages
**New method** in `TikTokVideoService`:
```python
async def generate_carousel_package(self, product_id: str) -> dict:
    """Generate a carousel content package: slide order, text per slide, caption, hashtags."""
```

Uses LLM to create:
- Slide-by-slide text overlay content (hook slide, feature slides, CTA slide)
- Caption with emojis and hooks
- 5-8 hashtags
- Suggested trending audio mood

### 3.4 Add carousel publish endpoint
**File**: `backend/app/infrastructure/tiktok_api_client.py`

Add `create_photo_post()` method using TikTok's photo post API endpoint (simpler than video):
```python
async def create_photo_post(self, photo_urls: List[str], caption: str, privacy_level: str = "SELF_ONLY") -> Optional[Dict]:
```

### 3.5 Update frontend to show carousel content
**File**: `frontend/src/pages/TikTokShopPage.tsx`

- In the Content tab, show carousel packages alongside video scripts
- Add "Copy Caption" and "Copy Hashtags" buttons for manual posting
- Show product images in slide order with text overlays

---

## Phase 4: Enhance Product Discovery for Affiliate Marketing

### 4.1 Add affiliate-specific search queries
**File**: `backend/app/services/tiktok_shop_service.py` (function `_get_search_queries()`, line 35)

Add queries:
```python
f"tiktok shop affiliate marketplace best commission products {year}",
f"tiktok shop high commission rate products for creators",
f"tiktok shop sample products free for creators {year}",
f"kalodata tiktok shop best sellers commission {year}",
f"shoplus tiktok trending products sales volume {year}",
f"tiktok shop creator pilot program eligible products {year}",
```

### 4.2 Extract commission data in LLM analysis
**File**: `backend/app/services/tiktok_shop_service.py` (method `_llm_analyze_product()`)

Enhance the LLM prompt to extract:
- `estimated_commission_rate` (e.g. "10-20%")
- `sample_availability` (boolean - free creator samples)
- `content_difficulty` ("easy"/"medium"/"hard")
- `affiliate_marketplace_listed` (boolean)

Store in existing `commission_rate` Float field and `llm_analysis` JSONB.

### 4.3 Adjust scoring weights for affiliate products
**File**: `backend/app/services/tiktok_shop_service.py` (method `_heuristic_score()`)

- Boost products with commission signals ("commission", "affiliate", "sample", "creator program")
- Penalize products requiring inventory
- Weight commission rate data higher in final score

### 4.4 Auto-search for TikTok Shop listings
**New method** in `TikTokShopService`:
```python
async def _find_tiktok_shop_listing(self, product_id: str, product_name: str):
    """Search SearXNG for this product's TikTok Shop page to get the affiliate link."""
```

Populates existing `tiktok_shop_url` and `affiliate_link` fields on `TikTokProductModel`.

---

## Phase 5: Auto-Discover Reference Content from Successful Sellers

### 5.1 Add batch reference discovery
**File**: `backend/app/services/reference_video_service.py`

New method:
```python
async def auto_discover_references(self, product_id: str, max_refs: int = 5) -> List[ReferenceVideo]:
    """For an approved product, search for existing TikTok videos promoting it."""
```

- Search SearXNG for `tiktok.com "{product_name}" review`
- Extract TikTok video URLs from results
- Auto-create reference videos and trigger oEmbed + LLM analysis
- Generate "copy this style" scripts automatically

### 5.2 Wire reference discovery into the LangGraph pipeline
**File**: `backend/app/services/tiktok_agent_graph.py`

Add a new `reference_discovery_node` between `approval_check` and `content_planning`:
- For each newly approved product, run `auto_discover_references()`
- Use the best-performing reference style to generate scripts

### 5.3 Add scheduler job for reference discovery
**File**: `backend/app/services/scheduler_service.py`

New job `tiktok_reference_discovery` (every 6 hours):
- Find approved products without reference videos
- Auto-discover references for up to 5 products per cycle

---

## Phase 6: Manual Posting Support (Until TikTok API is Set Up)

Since TikTok Developer App audit takes 5-10 business days (and may be rejected for small apps), we need a practical posting workflow now.

### 6.1 Add "mark as published" endpoint
**File**: `backend/app/routers/tiktok_shop.py`

```python
@router.post("/review/{queue_id}/mark-published")
async def mark_manually_published(queue_id: str, tiktok_url: str = Query(...)):
    """After manually posting to TikTok, paste the URL here to track it."""
```

### 6.2 Add "export for posting" endpoint
**File**: `backend/app/routers/tiktok_shop.py`

```python
@router.get("/review/{queue_id}/export")
async def export_for_posting(queue_id: str):
    """Get everything needed for manual posting: caption, hashtags, image URLs, script."""
```

Returns a structured package the user can copy-paste into TikTok.

### 6.3 Add performance tracking for published content
**File**: `backend/app/routers/tiktok_shop.py`

```python
@router.post("/review/{queue_id}/performance")
async def update_performance(queue_id: str, views: int, likes: int, comments: int, shares: int):
    """Manually enter performance metrics for published content."""
```

### 6.4 Update frontend with posting workflow
**File**: `frontend/src/pages/TikTokShopPage.tsx`

In the Review tab:
- Add "Copy Caption" button
- Add "Copy Hashtags" button
- Add "Mark as Published" button with TikTok URL input
- Add performance entry form (views, likes, comments, shares)
- Show export package with all content ready for posting

---

## Phase 7: Update Setup Guide

### 7.1 Rewrite setup guide for affiliate workflow
**File**: `backend/app/routers/tiktok_shop.py` (lines 274-330)

Update steps:
1. "Join TikTok Shop as Affiliate" (not Seller) at seller-us.tiktok.com
2. "Enable Product Showcase" in TikTok app settings
3. "Browse Affiliate Marketplace" to find products (Zero will also auto-discover)
4. "Review Zero's Product Recommendations" in the Approval Queue
5. "Generate Content" - Zero auto-creates carousel and video scripts
6. "Post to TikTok" - Copy content from Zero, paste into TikTok (or auto-post when API connected)
7. "Track Performance" - Enter metrics to improve future content

---

## Database Migration

**New migration file**: `backend/app/migrations/versions/016_tiktok_affiliate_enhancements.py`

Changes:
- Add `video_url` (String, nullable) to `content_queue` table
- Add `content_format` (String, default "video") to `content_queue` table
- Add `carousel_data` (JSON, nullable) to `content_queue` table
- Add `manually_published_url` (String, nullable) to `content_queue` table
- Add `performance_views` (Integer, nullable) to `content_queue` table
- Add `performance_likes` (Integer, nullable) to `content_queue` table
- Add `performance_comments` (Integer, nullable) to `content_queue` table
- Add `performance_shares` (Integer, nullable) to `content_queue` table

---

## Files to Modify (Summary)

| File | Changes |
|------|---------|
| `backend/app/services/tiktok_video_service.py` | Remove AIContentTools dep, add carousel template, add carousel package generation |
| `backend/app/services/tiktok_agent_graph.py` | Fix content_generation_node, add reference_discovery_node |
| `backend/app/services/publishing_service.py` | Remove AIContentTools video URL requirement, support manual posting |
| `backend/app/services/tiktok_shop_service.py` | Add affiliate search queries, commission extraction, TikTok Shop URL lookup |
| `backend/app/services/reference_video_service.py` | Add auto_discover_references() batch method |
| `backend/app/services/scheduler_service.py` | Fix content_generation_check, add reference_discovery job |
| `backend/app/infrastructure/tiktok_api_client.py` | Add create_photo_post() for carousel publishing |
| `backend/app/routers/tiktok_shop.py` | Add mark-published, export, performance endpoints; update setup guide |
| `backend/app/models/tiktok_content.py` | Add PHOTO_CAROUSEL to VideoTemplateType enum |
| `backend/app/db/models.py` | Add new columns to ContentQueueModel |
| `frontend/src/pages/TikTokShopPage.tsx` | Add copy buttons, mark-published flow, performance entry, carousel display |
| New: `backend/app/migrations/versions/016_tiktok_affiliate_enhancements.py` | Migration for new columns |

---

## Verification

1. **Phase 1**: `docker ps` shows all containers healthy; manual research cycle discovers products
2. **Phase 2**: Content pipeline no longer fails with "AIContentTools unavailable"; queue items get `script_ready` status
3. **Phase 3**: Can generate carousel packages for products; carousel data shows in frontend
4. **Phase 4**: New affiliate-specific products discovered; commission data populated
5. **Phase 5**: Reference videos auto-discovered for approved products; "copy style" scripts generated
6. **Phase 6**: Can export content for manual posting; mark as published works; performance entry works
7. **Phase 7**: Setup guide shows affiliate-specific steps

End-to-end test: Run `POST /api/tiktok-shop/pipeline/run?mode=full` and verify it discovers products, scores them, auto-approves high-confidence ones, discovers reference videos, generates carousel + video scripts, and queues them for review with caption/hashtags ready to copy.

---

## User Action Items (Manual Steps - Cannot Be Automated)

1. **Grow TikTok to 1K followers** (or use seller account bypass by registering at seller-us.tiktok.com)
2. **Join TikTok Shop Affiliate Program** at seller-us.tiktok.com (choose Affiliate)
3. **Enable Product Showcase** in TikTok app (Settings > Creator tools > TikTok Shop)
4. **Optionally**: Register at developers.tiktok.com for Content Posting API (enables auto-posting, but takes 5-10 days for audit)
5. **Post content**: Use Zero's exported content packages to manually create posts until API auto-posting is configured
