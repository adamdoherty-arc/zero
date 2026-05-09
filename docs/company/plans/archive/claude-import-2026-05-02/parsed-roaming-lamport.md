# TV & Movie Content Development System

## Context

The Character Content system is a full TikTok content pipeline: research characters, generate carousels, AI review, human review queue, enhance/council vote, publish, learn from performance. The user wants an identical system for TV shows and movies, sharing the review queue and linking characters to their shows/movies. This creates a unified content engine where characters, TV shows, and movies all feed the same publishing pipeline.

## Architecture Decision: Discriminator Column on Existing Carousel Table

Rather than a separate `media_carousels` table, we add `content_type` + `media_title_id` to the existing `character_carousels` table. This means:
- The entire enhance/council vote/version history/render/publish pipeline works without changes
- The review queue automatically includes media carousels
- No code duplication for carousel operations

## Database Changes

### New Tables

**`media_titles`** - Core entity for TV shows and movies
- `id`, `media_type` (tv_show/movie), `title`, `year`, `end_year`, `genre[]`, `franchise`, `universe`
- `poster_url`, `backdrop_url`, `synopsis`, `tagline`
- TV-specific: `season_count`, `episode_count`, `network`, `show_status`
- Movie-specific: `runtime_minutes`, `budget_usd`, `box_office_usd`, `mpaa_rating`
- Research: `research_data`, `research_status`, `fact_bank`, `research_sources`, `research_depth_score`, `content_themes`
- External IDs: `tmdb_id`, `imdb_id`
- Stats: `carousels_created`, `total_views`, `total_likes`, `avg_engagement`

**`character_media_titles`** - Many-to-many join
- `character_id` FK, `media_title_id` FK, `role_name`, `role_type` (lead/supporting/recurring/guest/cameo), `actor_name`, `seasons_appeared[]`

**`media_images`** - Parallel to `character_images`
- `media_title_id` FK, `url`, `source`, `query_used`, `quality_score`, `usage_count`, `is_approved`

**`media_research_fragments`** - Parallel to `character_research_fragments`
- `media_title_id` FK, `source`, `content`, `relevance_score`, `fragment_type`

### Modified Tables

**`character_carousels`** - Add columns:
- `content_type VARCHAR(20) DEFAULT 'character'` (character/media)
- `media_title_id VARCHAR(64) FK -> media_titles.id` (nullable)
- Make `character_id` nullable (media-only carousels like "10 Plot Holes in Breaking Bad")

### Migration: `028_media_titles.py`

All additive. No existing data modified. `content_type` default of `'character'` auto-categorizes existing rows.

## Content Angles (16 media-specific)

| Angle | Description |
|-------|-------------|
| plot_holes | Plot inconsistencies and writing mistakes |
| best_episodes | Top episodes ranked |
| showrunner_secrets | Creator behind-the-scenes decisions |
| casting_stories | Almost-cast actors, audition stories |
| deleted_scenes | Cut content that changed the story |
| fan_theories | Popular theories (shared with characters) |
| sequel_predictions | What's coming next |
| box_office_analysis | Financial story and market context |
| cinematography | Visual storytelling, iconic shots |
| soundtrack_breakdown | Music choices and narrative purpose |
| season_ranking | Best to worst seasons |
| hidden_details | Easter eggs, foreshadowing |
| production_disasters | Troubled productions, on-set drama |
| cultural_impact | How it changed pop culture |
| adaptation_changes | Book/comic-to-screen differences |
| controversial_decisions | Divisive creative choices |

## Story Templates (12 media-specific)

episode_breakdown, season_arc_analysis, directors_vision, behind_the_scenes, cast_chemistry, franchise_timeline, remake_comparison, box_office_battle, genre_evolution, cliffhanger_ranking, iconic_scenes, writers_room

## Research Sources

- **TMDB API** (primary) - structured cast, crew, seasons, ratings, images
- **IMDB** via SearXNG - trivia, goofs, connections
- **Rotten Tomatoes** via SearXNG - critic/audience scores
- **Wikipedia** via REST API - production history, reception
- **Fandom Wiki** via SearXNG - universe-specific lore
- **Reddit** - r/television, r/movies, show subreddits

## Implementation Plan

### Phase 1: Database + Models
Files to create/modify:
- `backend/app/db/models.py` - Add MediaTitleModel, CharacterMediaTitleModel, MediaImageModel, MediaResearchFragmentModel. Add content_type + media_title_id to CharacterCarouselModel. Make character_id nullable.
- `backend/app/migrations/versions/028_media_titles.py` - Migration for all new tables + column additions
- `backend/app/models/media_content.py` - Pydantic models: MediaType, MediaContentAngle, MediaStoryTemplate enums. MediaTitleCreate/Update/Response, MediaCarouselCreate, CharacterMediaLink models
- `backend/app/models/character_content.py` - Add content_type, media_title_id, media_title_name fields to CharacterCarousel model

### Phase 2: Research Sources
- `backend/app/services/media_research_sources.py` (~600 lines) - TMDB API client, research pipeline adapted from character_research_sources.py. Steps: tmdb_metadata, wikipedia, imdb_trivia, rotten_tomatoes, fandom_wiki, reddit, entertainment_articles

### Phase 3: Core Service
- `backend/app/services/media_content_service.py` (~2500 lines) - CRUD for media_titles, research pipeline, carousel generation with media-specific prompts and angles. Delegates shared carousel ops (enhance, council, versions, publish) to character_content_service
- `backend/app/services/character_content_service.py` - Modify list_review_queue to join media_titles when content_type='media'. Handle nullable character_id in approve/reject
- `backend/app/services/character_content_utils.py` - Add media_title_to_pydantic(), update carousel_to_pydantic() for content_type

### Phase 4: Router
- `backend/app/routers/media_content.py` (~600 lines) - REST API at `/api/media-content/` with CRUD, research, generate, character linking, TMDB search, batch operations
- `backend/app/main.py` - Register media_content router

### Phase 5: Frontend Hooks
- `frontend/src/hooks/useMediaContentApi.ts` (~600 lines) - React Query hooks for all media-content endpoints. Types for MediaTitle, MediaType, MediaContentAngle

### Phase 6: Frontend UI
- `frontend/src/layouts/CharacterContentLayout.tsx` - Add `{ value: 'tv-movies', label: 'TV & Movies', icon: Tv }` tab (Tv from lucide-react)
- `frontend/src/components/media-content/MediaTitleCard.tsx` - Poster, title, year, type badge, research status, carousel count
- `frontend/src/components/media-content/TMDBSearchModal.tsx` - Search TMDB, preview results, import button
- `frontend/src/pages/MediaContentPage.tsx` (~1200 lines) - Tab content for TV & Movies: browse grid, add title, research status. Inline in CharacterContentPage as tab === 'tv-movies'
- `frontend/src/pages/MediaDetailPage.tsx` (~800 lines) - Poster header, fact bank, linked characters, carousels, generate button with angle/template selectors

### Phase 7: Integration
- `frontend/src/App.tsx` - Add routes: `media/:mediaId` and `media/:mediaId/carousels/:carouselId/edit` under `/characters`
- `frontend/src/pages/CharacterContentPage.tsx` - Add tv-movies tab rendering, add content type filter to ReviewQueueTab
- `frontend/src/components/character-content/CarouselCard.tsx` - Content type badge, handle media_title_name when character_name is null
- `frontend/src/pages/CarouselEditorPage.tsx` - Handle mediaId param, load media title context
- `frontend/src/pages/CharacterDetailPage.tsx` - "Appears In" section showing linked media titles

### Phase 8: Deploy + Verify
- Rebuild backend: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
- Restart frontend: `docker compose -f docker-compose.sprint.yml restart zero-ui`
- Verify: containers healthy, new tab visible, CRUD works, carousel generation works, review queue shows both types

## Shared Infrastructure (No Changes Needed)
- unified_llm_client / llm_router (generation)
- content_learning_engine (outcome tracking)
- prompt_evolution_service (variant selection)
- carousel_renderer_service (image rendering)
- music_library_service (music recommendations)
- council_service (multi-agent voting)
- publishing_service (publish pipeline)
- character_hook_service (hook scoring/regen)

## Verification
1. Create a media title via API, trigger research, verify fact_bank populated
2. Generate a carousel for the media title, verify it appears in review queue alongside character carousels
3. Approve/reject media carousels through shared review queue
4. Open carousel editor for media carousel, verify enhance/council/versions work
5. Check "TV & Movies" tab in frontend shows titles with correct filtering
6. Check MediaDetailPage shows linked characters and carousels
7. Check CharacterDetailPage "Appears In" section shows linked media
