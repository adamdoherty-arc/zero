# /character-content

Comprehensive character content pipeline management skill for TikTok character development posts. Use when asked to improve characters, generate content, review carousels, add new characters, research characters, source images, or optimize the character content system.

> **This skill is for OPERATIONS** (tactical: "do the work"). For system audit, grading, and improvement planning, use `/character-content-review` instead. That skill is READ-ONLY analysis and produces a scorecard with prioritized improvements. If you want to create content, manage characters, or fix a specific problem, stay here.

## Startup Protocol

Every time this skill is invoked:
1. `GET /api/characters/stats` to understand current pipeline state
2. `GET /api/characters/research-queue` to check research progress
3. `GET /api/characters/review-queue` to check pending reviews
4. `GET /api/characters/?research_status=pending` to find unresearched characters
5. Apply learnings from previous runs

## Available API Endpoints

### Core Character CRUD
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/` | GET | List characters (filter: universe, status, research_status) |
| `/api/characters/` | POST | Create new character |
| `/api/characters/{id}` | GET | Get character with full research data + fact bank |
| `/api/characters/{id}` | PATCH | Update character details |
| `/api/characters/{id}` | DELETE | Delete character and all content |
| `/api/characters/seed` | POST | Seed 24 iconic characters |
| `/api/characters/stats` | GET | Pipeline statistics |

### Research Pipeline
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/research` | POST | Trigger background research pipeline |
| `/api/characters/batch-research` | POST | Research all unresearched characters (body: {universe, limit}) |
| `/api/characters/research-queue` | GET | Current research queue status with per-character progress |
| `/api/characters/research-queue/start` | POST | Start batch research with real-time progress tracking |
| `/api/characters/research-queue/cancel` | POST | Cancel running research queue |

### Images & Facts
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/images` | GET | List sourced images |
| `/api/characters/{id}/images` | POST | Add image manually |
| `/api/characters/{id}/source-images` | POST | Re-run image search with fresh queries |
| `/api/characters/{id}/facts` | POST | Add a single fact to fact bank |
| `/api/characters/{id}/facts/{index}` | PATCH | Update a fact by index |

### Enhancement & Image Refresh
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/enhance` | POST | Deep-enhance character: refresh research, add images, regenerate weak carousels (body: {refresh_research, add_images, regenerate_weak_carousels, weak_threshold}) |
| `/api/characters/carousels/{id}/reimage` | POST | Refresh ALL slide images on a carousel |
| `/api/characters/carousels/{id}/slides/{slide_index}/reimage` | POST | Refresh a SINGLE slide's image (body: {query} optional) |
| `/api/characters/carousels/{id}/reimage-with-fresh-sources` | POST | Source NEW images for the character first, THEN re-match all slides |

### Carousel Generation & Management
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/carousel` | POST | Generate carousel (body: {angle, story_template, multi_character_ids, slide_count}) |
| `/api/characters/{id}/carousel/series` | POST | Generate multi-part series (body: {angle, story_template, parts}) |
| `/api/characters/carousels` | GET | List carousels (filter: character_id, status) |
| `/api/characters/carousels/{id}` | GET | Get carousel detail |
| `/api/characters/carousels/{id}` | PATCH | Edit carousel content |
| `/api/characters/carousels/{id}/review` | POST | Trigger AI review |
| `/api/characters/carousels/{id}/approve` | POST | Human approve |
| `/api/characters/carousels/{id}/reject` | POST | Human reject (body: {reason}) |
| `/api/characters/carousels/{id}/music` | POST | Assign music track (body: {track_id}) |

### Batch Operations & Smart Review
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/batch-generate` | POST | Generate carousels for multiple characters |
| `/api/characters/batch-smart` | POST | Smart batch generation with priority scoring (body: {count}) |
| `/api/characters/review-queue` | GET | Carousels pending human review |
| `/api/characters/review-queue/smart` | GET | Priority-sorted review queue |

### Content Inspiration
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/inspirations/discover` | POST | Discover viral carousel creators (body: {niche}) |
| `/api/characters/inspirations` | GET | List analyzed content inspirations |
| `/api/characters/inspirations/analyze` | POST | Analyze a specific carousel URL (body: {url}) |
| `/api/characters/inspirations/patterns` | GET | Get extracted winning patterns |

### Story Templates
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/templates` | GET | List all story templates |
| `/api/characters/templates` | POST | Create custom story template |
| `/api/characters/templates/seed` | POST | Seed 10 built-in story templates |

### Music Library
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/music` | GET | Browse music library (filter: mood) |
| `/api/characters/music` | POST | Add a track to music library |
| `/api/characters/music/seed` | POST | Seed 49 curated tracks |
| `/api/characters/music/trending` | GET | Search for trending TikTok sounds (query: niche) |

### Analytics
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/analytics/sources` | GET | Research source effectiveness analytics |
| `/api/characters/analytics/templates` | GET | Template performance leaderboard |

## Research Pipeline Architecture

The research pipeline uses **7 sources** (all free):
- **SearXNG web search** — general web results
- **Wikipedia REST API** — direct scraping for structured bio data
- **Fandom Wiki** — via Firecrawl at `host.docker.internal:3002` (marvel.fandom.com, dc.fandom.com, etc.)
- **Reddit** — public JSON API targeting r/FanTheories, r/MovieDetails, franchise subs
- **TV Tropes** — via Firecrawl for narrative archetypes and trope patterns
- **IMDB Trivia** — via Firecrawl for behind-the-scenes facts
- **Quotes** — via SearXNG for famous/memorable lines

**LLM**: Ollama `qwen3.6:35b-a3b-q8_0` for research synthesis + fact extraction (free).
**Creative content** (carousels, AI review): Also Ollama for zero cost.

Each character research takes ~3-5 minutes. Batch research runs sequentially to avoid GPU overload. Research queue provides real-time progress tracking via `/research-queue` endpoint.

## 10 Story Templates

| Template | Hook Pattern |
|----------|-------------|
| `secrets_revealed` | "X Things They Don't Tell You About {name}..." |
| `hidden_connection` | "{name} and {name2} are connected in a way nobody noticed..." |
| `dark_origin` | "The REAL origin of {name} is darker than you think..." |
| `fan_theory_deep_dive` | "This fan theory about {name} changes EVERYTHING..." |
| `actor_behind_role` | "{actor} almost WASN'T {name}..." |
| `versus_breakdown` | "{name} vs {name2}: Here's who ACTUALLY wins..." |
| `timeline_tragedy` | "The complete timeline of {name}'s suffering..." |
| `what_they_changed` | "The comics version of {name} is COMPLETELY different..." |
| `real_life_inspiration` | "{name} was based on a REAL person..." |
| `deleted_scenes` | "These deleted scenes of {name} would have changed EVERYTHING..." |

## Workflow 1: Research & Build Character Database

Goal: Ensure every character has rich research data, 15+ facts, and 5+ images.

1. Check research queue status:
   ```
   GET /api/characters/research-queue
   ```
2. If no queue running, start batch research:
   ```
   POST /api/characters/research-queue/start
   Body: {"limit": 24}
   ```
3. Monitor progress via the queue endpoint (shows per-character step progress)
4. After completion, verify each character:
   - `fact_bank` has 15+ facts (if < 10, re-research or add manually)
   - `research_data` has bio, powers, relationships, filmography
   - 5+ images sourced
5. For thin fact banks, manually add facts:
   ```
   POST /api/characters/{id}/facts
   Body: {"text": "...", "category": "hidden_details", "surprise_score": 7}
   ```

## Workflow 2: Content Generation Cycle

Goal: Create high-quality carousel content ready for publishing.

1. Pick characters with completed research and good fact banks
2. Choose content angle + story template:
   ```
   POST /api/characters/{id}/carousel
   Body: {"angle": "hidden_truths", "story_template": "secrets_revealed", "slide_count": 6}
   ```
3. For multi-character carousels:
   ```
   Body: {"angle": "vs_comparison", "story_template": "versus_breakdown", "multi_character_ids": ["id1", "id2"]}
   ```
4. For series (multi-part):
   ```
   POST /api/characters/{id}/carousel/series
   Body: {"story_template": "timeline_tragedy", "parts": 3}
   ```
5. Trigger AI review (two-stage):
   ```
   POST /api/characters/carousels/{carousel_id}/review
   ```
   Stage 1 runs Ollama (free, fast). If `overall_score >= 7`, Stage 2 automatically runs Minimax M2.7 (`character_content_review_final` task type) for viral-instinct polish. On Minimax failure or budget breach, the router falls back to Kimi K2.5. The final output is stored in `final_review`, `final_review_score`, and `final_review_model` on the carousel.
6. Check review scores. If overall_score >= 7 and final_review_score >= 7, present for approval
7. If Stage 1 score < 7, regenerate with different angle/template or edit
8. If Stage 1 passes but final_review has polish suggestions, apply `final_hook` / `final_caption` from the final_review payload

## Workflow 3: Smart Batch Production

Goal: Generate 10-15 carousels efficiently with smart prioritization.

1. Run smart batch:
   ```
   POST /api/characters/batch-smart
   Body: {"count": 12}
   ```
2. This auto-selects best characters, angles, and templates
3. Check smart review queue:
   ```
   GET /api/characters/review-queue/smart
   ```
4. Review top-scored carousels first
5. Bulk approve/reject as needed

## Workflow 4: Add New Characters

1. Create character:
   ```
   POST /api/characters/
   Body: {"name": "...", "universe": "marvel", "franchise": "...", "real_name": "..."}
   ```
2. Start research immediately
3. Source images
4. Generate initial carousel with best template for that universe
5. Run AI review

## Workflow 5: Enhance Character + Regenerate Weak Carousels

Goal: Take a character with thin facts, missing images, or low-scoring carousels and rebuild it to production quality.

1. Identify candidates. Look for any of these signals:
   - `fact_bank` has < 15 facts
   - Fewer than 5 sourced images
   - `research_depth_score < 60`
   - Carousels with `ai_review_score < 7`
2. Trigger enhance pipeline:
   ```
   POST /api/characters/{id}/enhance
   Body: {
     "refresh_research": true,
     "add_images": 8,
     "regenerate_weak_carousels": true,
     "weak_threshold": 7.0
   }
   ```
3. The pipeline runs sequentially:
   - Re-runs `_research_pipeline()` with deeper queries, merges new facts into `fact_bank` (deduped by similarity)
   - Tops up images via `_source_images()` with higher limits (approved images are preserved)
   - Re-extracts facts using the freshest research_data
   - Scans all carousels for this character with `ai_review_score < weak_threshold` AND `status in (draft, ai_reviewed, rejected)`
   - Regenerates each weak carousel with the same angle/template but new facts
   - Archives the old weak carousels (`status = archived`)
   - Schedules Stage 2 (Minimax) final review on the new carousels via the scheduler (not inline, to avoid long-running requests)
4. Response shape:
   ```json
   {
     "character_id": "...",
     "facts_added": 12,
     "images_added": 6,
     "carousels_regenerated": 3,
     "carousels_archived": 3,
     "research_depth_delta": 18
   }
   ```
5. Verify: `GET /api/characters/{id}` confirms fact/image growth. `GET /api/characters/carousels?character_id={id}&status=archived` shows the old weak carousels.

## Workflow 6: Refresh Carousel Images

Goal: Fix bad or off-brand images on an existing carousel without regenerating the text.

Three refresh modes, pick based on how bad the images are:

**Mode A - Refresh ALL slides using existing image pool** (fastest, cheap):
```
POST /api/characters/carousels/{carousel_id}/reimage
```
Re-runs the 3-tier image matcher on all slides using the character's current image pool. Use when you just want different picks from what's already sourced.

**Mode B - Refresh a SINGLE slide** (surgical):
```
POST /api/characters/carousels/{carousel_id}/slides/{slide_index}/reimage
Body: {"query": "Walter White blue meth lab close up"}  # optional override
```
Replaces only the specified slide's image. The optional `query` override lets you hand-tune the search string if the auto-generated `image_query` is off.

**Mode C - Source NEW images THEN rematch** (deepest fix):
```
POST /api/characters/carousels/{carousel_id}/reimage-with-fresh-sources
```
Calls `_source_images()` first to grow the character's image library with fresh SearXNG queries, then re-matches all slides against the expanded pool. Use when the existing pool is too small or stale.

Decision guide:
| Symptom | Mode |
|---------|------|
| 1 slide has a bad image | B (per-slide) |
| Multiple slides feel off but character has 10+ images | A (rematch all) |
| Character only has 3-4 images, or images look outdated | C (fresh sources + rematch) |

## Content Angle Strategy

15 available angles — rotate to avoid repetition per character:

**High engagement**: hidden_truths, dark_facts, fan_theories, controversial_takes, actor_secrets
**Unique content**: behind_scenes, easter_eggs, crossover_connections, what_if
**Foundation**: origin_story, character_evolution, underrated_moments, vs_comparison, power_secrets, timeline_deep_dive

## Decision Framework

| Condition | Action |
|-----------|--------|
| Character has < 10 facts | Re-research or manually add facts |
| Character has 0 images | Priority: source images immediately |
| Carousel AI score < 7 | Regenerate with different angle/template or edit |
| Character has > 3 published carousels | Vary angles, avoid repetition |
| Research status = "failed" | Retry research, check SearXNG/Firecrawl health |
| Research status = "researching" stuck > 30min | Cancel and restart queue |
| Stale research (> 7 days) | Re-research to get fresh data |

## Character Universes

marvel, dc, star_wars, lotr, harry_potter, anime, tv, film, gaming, other

## Seeded Characters (~60 total after Phase 5)

**Marvel (10)**: Iron Man, Thor, Loki, Spider-Man, Black Widow, Thanos, Doctor Strange, Wolverine, Deadpool, Scarlet Witch
**DC (8)**: Batman, Superman, Joker, Wonder Woman, Aquaman, The Flash, Harley Quinn, Green Lantern
**Prestige TV (tv)**: Walter White, Tony Soprano, Tyrion Lannister, Jon Snow, Daenerys Targaryen, Don Draper, Logan Roy, Saul Goodman, Eleven (Stranger Things), Wednesday Addams, Jack Bauer, Michael Scott
**Fantasy (lotr, harry_potter, star_wars)**: Gandalf, Aragorn, Legolas, Frodo; Harry Potter, Hermione Granger, Severus Snape, Voldemort, Albus Dumbledore; Darth Vader, Yoda, Obi-Wan Kenobi, Luke Skywalker, Rey, Grogu
**Anime (anime)**: Naruto Uzumaki, Goku, Monkey D. Luffy, Eren Yeager, Light Yagami, Levi Ackerman, Sukuna, Gojo Satoru, Geralt of Rivia (The Witcher anime/games)
**Gaming (gaming)**: Master Chief, Kratos, Lara Croft, Mario, Link, Solid Snake, Arthur Morgan, Joel (TLOU), Ellie
**Film (film)**: John Wick, The Joker (Heath Ledger), Vito Corleone, Michael Corleone, Hannibal Lecter, Tyler Durden, Neo, Indiana Jones

## Scheduler Jobs

- `character_research_refresh` — Every 6 hours, re-researches stale characters
- `character_content_generation` — Every 4 hours, generates carousels for researched characters
- `character_performance_sync` — Daily, syncs performance metrics from published content
