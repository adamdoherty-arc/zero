# Character Content System - Major Upgrade

## Context

The Character Content pipeline (Phase 1) is deployed and working end-to-end: 24 seeded characters, research pipeline (SearXNG + Firecrawl + LLM synthesis), carousel generation, AI review, and human review queue. However, the user clicked on a "completed" character card and **couldn't see anything** — there's no character detail page. The grid cards show minimal info with no drill-down.

**User's request**: "I should be able to click on each character and get taken to a new page that has tons of photos, information, history, movies/TV shows, and entire database filled with facts to keep developing this further and further. This needs to be in the skill to build upon this over several iterations."

This upgrade transforms the system from a carousel generation tool into a **rich character encyclopedia + content studio** with deep detail pages, multi-source image sourcing, and a Claude Code skill for iterative improvement.

---

## Phase 1: Character Detail Page (Frontend)

### New file: `frontend/src/pages/CharacterDetailPage.tsx`

Rich detail page modeled after [ProductDetailPage.tsx](frontend/src/pages/ProductDetailPage.tsx) (738 lines). Sections:

**Hero Section**
- Large primary image with dark gradient overlay
- Character name, real name, universe badge, franchise
- Research status indicator, last researched timestamp
- Action buttons: Research, Generate Carousel, Edit

**Photo Gallery** (horizontal scroll or grid)
- All images from `character_images` table
- Click to enlarge (lightbox)
- "Source More Images" button triggers image search
- Shows source badge (searxng, firecrawl, manual)

**Biography & Overview**
- `research_data.bio` rendered as formatted text
- First appearance, notable arcs
- Key relationships displayed as linked cards
- Powers/abilities as badges

**Filmography / Appearances**
- New `research_data` fields: `filmography` (array of {title, year, role, type: movie/tv/comic})
- Rendered as timeline or table
- Sourced during research pipeline enhancement

**Fact Bank** (the core database)
- Sortable/filterable table of all facts
- Columns: text, category, surprise_score, source, verified
- Category filter chips (origin, powers, hidden_details, etc.)
- Inline edit capability
- "Add Fact" button for manual additions
- Color-coded surprise scores (green 8-10, yellow 5-7, red 1-4)

**Carousels Tab**
- List of all carousels created for this character
- Status badges, AI review scores
- Quick actions: review, approve, generate new

**Performance Stats**
- Posts created, total views, likes, engagement rate
- Per-carousel performance breakdown

### Modify: `frontend/src/App.tsx`
- Add route: `/characters/:characterId` -> `CharacterDetailPage`

### Modify: `frontend/src/pages/CharacterContentPage.tsx`
- Character cards become clickable links to `/characters/${char.id}`
- Add `useNavigate` for navigation

### Modify: `frontend/src/hooks/useCharacterContentApi.ts`
- Add `useCharacter(id)` query (single character fetch)
- Add `useCharacterImages(id)` query
- Add `useCharacterCarousels(id)` query (carousels filtered by character)
- Add `useAddFact` mutation
- Add `useSourceImages` mutation (triggers image search)
- Add `useUpdateFact` mutation
- Add new TypeScript interfaces for filmography, relationships, etc.

---

## Phase 2: Enhanced Research Pipeline (Backend)

### Modify: `backend/app/services/character_content_service.py`

**Richer research_data structure** — enhance `_synthesize_research()` prompt to extract:
```json
{
  "bio": "2-3 paragraph biography",
  "powers": ["power1", "power2"],
  "key_relationships": [{"name": "char", "relation": "type", "details": "context"}],
  "first_appearance": "comic/movie/show and year",
  "notable_arcs": [{"name": "arc", "description": "what happened", "year": "when"}],
  "filmography": [
    {"title": "The Avengers", "year": 2012, "role": "supporting", "type": "movie"},
    {"title": "Loki", "year": 2021, "role": "lead", "type": "tv_series"}
  ],
  "fun_facts": ["fact1", "fact2"],
  "controversies": ["controversial thing 1"],
  "behind_the_scenes": ["production detail 1"],
  "abilities_detail": {"strength": "description", "speed": "description"},
  "quotes": [{"text": "quote", "source": "movie/comic"}],
  "alternate_versions": ["variant1", "variant2"],
  "created_by": "creator name",
  "first_comic_appearance": "issue #",
  "aliases": ["alias1", "alias2"]
}
```

**More image search queries** — enhance `_source_images()`:
- Add 4-5 more search queries: promotional stills, comic panels, cosplay, fan art
- Validate images with HTTP HEAD check (status 200, content-type image/*)
- Target: 8-15 images per character minimum
- Store image dimensions when available from SearXNG response

**New endpoint: source more images on demand**
- `POST /api/characters/{id}/source-images` — re-runs image search with fresh queries
- Called from the detail page "Source More Images" button

**New endpoint: add/update individual facts**
- `POST /api/characters/{id}/facts` — add a single fact to the fact bank
- `PATCH /api/characters/{id}/facts/{index}` — update a fact in the fact bank

### Modify: `backend/app/routers/character_content.py`
- Add `POST /{character_id}/source-images` endpoint
- Add `POST /{character_id}/facts` endpoint
- Add `PATCH /{character_id}/facts/{fact_index}` endpoint

---

## Phase 3: Batch Research All Characters

### Modify: `backend/app/services/character_content_service.py`

**New method: `batch_research(universe?, limit?)`**
- Research multiple characters sequentially (not parallel — avoid overwhelming SearXNG/LLM)
- Add 2-second delay between characters to avoid rate limits
- Track progress, skip already-researched characters
- Return count of researched characters

### Modify: `backend/app/routers/character_content.py`
- Add `POST /api/characters/batch-research` endpoint

### Modify: `frontend/src/hooks/useCharacterContentApi.ts`
- Add `useBatchResearch` mutation

### Modify: `frontend/src/pages/CharacterContentPage.tsx`
- Add "Research All" button that triggers batch research
- Show research progress indicator

---

## Phase 4: Claude Code Skill

### New file: `.claude/skills/character-content.md`

Iterative improvement skill following the pattern in [tiktok-shop-manager.md](.claude/skills/tiktok-shop-manager.md):

```markdown
# Character Content Pipeline Manager

Comprehensive character content pipeline management skill. Use when asked to improve characters,
generate content, review carousels, add new characters, or optimize the character development system.

## Startup Protocol

Every time this skill is invoked:
1. GET /api/characters/stats to understand current pipeline state
2. GET /api/characters/?research_status=pending to find unresearched characters
3. GET /api/characters/review-queue to check pending reviews
4. Apply learnings from previous runs

## Available API Endpoints

[Table of all endpoints]

## Workflows

### Workflow 1: Research & Build Character Database
1. Check which characters lack research (research_status = pending)
2. Trigger research for each: POST /api/characters/{id}/research
3. After research completes, verify fact_bank has 15+ facts
4. If fact_bank is thin, trigger re-research or manually add facts
5. Source more images: POST /api/characters/{id}/source-images
6. Verify each character has 5+ images

### Workflow 2: Content Generation Cycle
1. Pick characters with completed research
2. Generate carousels with varied angles
3. Trigger AI review
4. Present review queue items to user for approval/rejection

### Workflow 3: Quality Improvement
1. Review characters with low fact counts
2. Re-research stale characters (>7 days old)
3. Check image validity (broken URLs)
4. Identify underused content angles

### Workflow 4: Add New Characters
1. User suggests characters or themes
2. Create character profiles
3. Run research pipeline
4. Generate initial carousels

## Decision Framework

- Characters with < 10 facts: needs re-research
- Characters with 0 images: priority image sourcing
- Carousels scoring < 7 on AI review: needs revision before human review
- Characters with > 3 published carousels: vary angles, avoid repetition

## Learning Loop

After each session, note:
- Which characters performed best (most engagement)
- Which content angles got highest AI review scores
- Common AI review feedback patterns
- Image sourcing success rates by query type
```

---

## Phase 5: Run Initial Research Batch

After all code changes are deployed:
1. Trigger batch research for all 24 seeded characters
2. Verify images are being sourced
3. Generate sample carousels for 3-5 top characters
4. Run AI review on generated carousels

---

## Files to Create
1. `frontend/src/pages/CharacterDetailPage.tsx` — Rich character detail page (~500-700 lines)
2. `.claude/skills/character-content.md` — Iterative improvement skill

## Files to Modify
1. `frontend/src/App.tsx` — Add `/characters/:characterId` route
2. `frontend/src/pages/CharacterContentPage.tsx` — Make cards clickable, add batch research button
3. `frontend/src/hooks/useCharacterContentApi.ts` — Add detail queries + new mutations
4. `backend/app/services/character_content_service.py` — Enhanced research, batch research, new endpoints, richer data
5. `backend/app/routers/character_content.py` — Add 4 new endpoints (source-images, facts CRUD, batch-research)

## Reuse from Existing Codebase
- [ProductDetailPage.tsx](frontend/src/pages/ProductDetailPage.tsx) — Rich detail page pattern (hero, image carousel, tabs, scores)
- [useTikTokShopApi.ts](frontend/src/hooks/useTikTokShopApi.ts) — React Query hook patterns with mutations
- [tiktok-shop-manager.md](.claude/skills/tiktok-shop-manager.md) — Skill format with workflows, decision framework, learning loop
- `get_unified_llm_client()` from [unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py) for LLM calls
- `get_searxng_service()` from [searxng_service.py](backend/app/services/searxng_service.py) for image search
- Existing `_source_images()`, `_synthesize_research()`, `_extract_facts()` methods (enhance, don't replace)

---

## Verification

1. **Backend builds**: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api`
2. **Frontend builds**: `docker compose -f docker-compose.sprint.yml build --no-cache zero-ui`
3. **Navigate to `/characters`**: Grid of character cards loads
4. **Click any character**: Navigates to `/characters/{id}` detail page with sections
5. **Detail page shows**: Hero section, photo gallery, biography, fact bank, carousels tab
6. **Source images button**: Triggers image search, gallery updates
7. **Batch research**: "Research All" button starts research for unresearched characters
8. **New endpoints work**: Test fact CRUD and source-images via API
9. **Skill file exists**: `.claude/skills/character-content.md` with complete workflows
