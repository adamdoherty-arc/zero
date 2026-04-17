# /character-content-review

Comprehensive audit, grading, and improvement planner for Zero's Character Content Creation system. Reviews all dimensions of the content pipeline. Research quality, generation output, UI/UX, code quality, automation, and content strategy. Then researches best practices and produces an actionable improvement plan.

> **This skill is for STRATEGIC AUDIT** (READ-ONLY analysis: "assess and plan"). For day-to-day content creation, character management, or fixing a specific problem, use `/character-content` instead. This skill produces a scorecard and prioritized improvement backlog; it never modifies source code.

## Usage

```
/character-content-review                       # Full review (all 8 dimensions, ~30 min)
/character-content-review --quick               # Quick scan (code quality + API health, ~10 min)
/character-content-review --content             # Content quality only (research depth, carousel quality, ~15 min)
/character-content-review --grade               # Just display current grades from last run (~2 min)
/character-content-review --research            # Research industry best practices + gaps (~20 min)
/character-content-review --plan                # Generate improvement plan from last review (~5 min)
/character-content-review --carousel-visual-qa  # Visual QA on one carousel or all carousels for a character (~5 min)
```

## Knowledge Files

```
.claude/skills/character-content-review/knowledge/
  SCORECARD.md                          # Current grades across all 8 dimensions
  IMPROVEMENT_PLAN.md                   # Prioritized improvement backlog
  INDUSTRY_RESEARCH.md                  # What world-class content systems do
  history/
    YYYY-MM-DD-review.md                # Per-run audit documents
```

Rendering rules used by `--carousel-visual-qa` live in a sibling file:
[RENDERING_RULES.md](./RENDERING_RULES.md) (rules R1-R6 with checks, severity,
and ready-to-run fix commands).

## Mode: `--carousel-visual-qa`

Focused visual audit for one carousel or all carousels of a character. Unlike
the other modes, this one is designed to be run frequently (after each generation
batch, before each publish) instead of as a scheduled deep-audit.

**Inputs (one of)**:
- `--carousel-id ccr-<12>`           single carousel
- `--character-id cch-<12>`          every non-archived carousel for that character
- no input                           most recent 10 carousels across all characters

**Execution** (~30s per carousel):
1. `GET /api/characters/carousels/{id}` - fetch full row including
   `generation_metadata.render_warnings`, `slides`, `hook_text`, `caption`,
   `hashtags`, `status`, and `character_name`.
2. Evaluate each rule from [RENDERING_RULES.md](./RENDERING_RULES.md) in the
   order specified there (R4 first, short-circuit on contrast).
3. Build a findings list: `[ {rule, severity, detail, fix_command} ]`.
4. Emit per-carousel report using the output format from `RENDERING_RULES.md`.
5. Aggregate: carousels reviewed, total findings, severity breakdown, and the
   Content Generation dimension penalty (high: -5, medium: -3, low: -1, capped
   at -20 per carousel).
6. DO NOT apply any fixes. The output is a list of copy-paste commands the user
   can run from the CLI or the editor at `/characters/<id>/carousels/<cid>/edit`.

**Output target**: `knowledge/history/YYYY-MM-DD-visual-qa.md`. If the same
carousel fails the same rule on two consecutive runs, append a note to
`IMPROVEMENT_PLAN.md` recommending a systemic fix (e.g. tune the renderer's
overlay strength curve, add a compound term to the character profile's
`no_break_terms`, ban another hook template).

## 8 Scoring Dimensions

| # | Dimension | Weight | What It Measures |
|---|-----------|--------|-----------------|
| 1 | Research Quality | 15% | Source depth, fact accuracy, image coverage, multi-source research |
| 2 | Content Generation | 15% | Template variety, hook quality, carousel structure, text overlays |
| 3 | Pipeline Automation | 15% | Batch processing, queue management, scheduling, error recovery |
| 4 | Learning & Optimization | 10% | Brain integration, A/B testing, outcome tracking, prompt evolution |
| 5 | UI/UX Experience | 15% | Review workflow, preview quality, progress visibility, analytics |
| 6 | Code Quality | 10% | Error handling, type safety, logging, async patterns, response models |
| 7 | Content Strategy | 10% | Angle diversity, series support, music, inspiration, competitor analysis |
| 8 | Publishing & Distribution | 10% | TikTok integration, scheduling, cross-platform, caption optimization |

**Formula**: `Overall = Sum(Dimension * Weight)`

**Grade Scale**: A+ (97-100), A (93-96), A- (90-92), B+ (87-89), B (83-86), B- (80-82), C+ (77-79), C (73-76), C- (70-72), D (60-69), F (0-59)

## Source Files to Audit

### Backend Services
| File | Purpose | LOC |
|------|---------|-----|
| `services/character_content_service.py` | Core pipeline, research, generation, review | ~2100 |
| `services/character_research_sources.py` | 5-source deep research (Fandom, Reddit, TVTropes, IMDB, Quotes) | ~510 |
| `services/content_inspiration_service.py` | Viral content discovery & pattern extraction | ~410 |
| `services/story_template_service.py` | 10 story templates with prompt engineering | ~500 |
| `services/music_library_service.py` | Music mood library & carousel-music pairing | ~320 |
| `services/content_learning_engine.py` | Brain integration, A/B testing, performance tracking | ~330 |

### Backend Infrastructure
| File | Purpose |
|------|---------|
| `routers/character_content.py` | 43 REST endpoints |
| `models/character_content.py` | 25+ Pydantic models, 9 enums |
| `db/models.py` | 9 ORM models (Character, Carousel, Image, Fragment, etc.) |
| `migrations/versions/017_character_content.py` | DB schema |

### Frontend
| File | Purpose | LOC |
|------|---------|-----|
| `pages/CharacterContentPage.tsx` | 6-tab main page (Characters, Research Queue, Studio, Review, Inspiration, Analytics) | ~1380 |
| `pages/CharacterDetailPage.tsx` | Character detail with research data, facts, images, carousels | ~720 |
| `hooks/useCharacterContentApi.ts` | 40 React Query hooks, 23 TypeScript interfaces | ~715 |

## Execution Phases

### Phase 0: Load Previous Run (1 min)
1. Read `SCORECARD.md` for last scores
2. Read `IMPROVEMENT_PLAN.md` for in-progress items
3. Note what's been fixed since last review

### Phase 1: Research Quality Audit (5 min)
Score the depth and quality of character research.

**Data Collection**:
```bash
TOKEN=$(grep ZERO_GATEWAY_TOKEN .env | cut -d= -f2)
# Get all characters with research stats
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/?limit=100
# Get research queue status
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/research-queue
# Get source analytics
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/analytics/sources
```

**Scoring Criteria** (start at 0, add points):
- +10 per active research source (max 70 for 7 sources: SearXNG, Wikipedia, Fandom, Reddit, TVTropes, IMDB, Quotes)
- +5 if average facts_found >= 20 per character
- +5 if average images_found >= 10 per character
- +5 if research_depth_score averages >= 70
- +5 if > 80% of characters have completed research
- +5 if research fragments are stored with provenance (URLs, source types)
- +5 if cross-character relationship mapping exists and is populated

**Key Questions**:
- Are all 7 research sources actually returning data? (check research_sources field on completed characters)
- Are fact banks diverse? (mix of categories: hidden_details, powers, relationships, behind_scenes, trivia)
- Are images high-quality? (not broken URLs, relevant to character)
- Is Firecrawl (deep scraping) working? Check if fandom_wiki and tvtropes fragments exist
- How many characters have < 15 facts? (target: 0)

### Phase 2: Content Generation Audit (5 min)
Score the quality of generated carousels.

**Data Collection**:
```bash
# Get all carousels
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/carousels?limit=100
# Get templates
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/templates
# Get template analytics
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/analytics/templates
```

**Scoring Criteria**:
- +15 if 10 story templates exist and are seeded
- +10 if templates have been used (times_used > 0)
- +10 if carousel hooks are engaging (sample 5, check hook_text length > 20 chars, uses pattern like "X things..." or "The REAL...")
- +10 if slides have proper structure (5-8 slides, each with text)
- +10 if text_overlay_specs are generated per slide
- +10 if multi-character carousels work (check multi_character_ids)
- +10 if series generation works (check series_id linkage)
- +10 if AI review scores average >= 6/10
- +5 if music auto-assigned to carousels
- +10 if brain context is injected into generation (check brain_context_used field)
- +10 if two-stage review is active: Stage 1 Ollama (free) + Stage 2 Minimax M2.7 for high scorers. Check `final_review_score`, `final_review_model` populated on any carousel. Minimax failures should fall back to Kimi K2.5 via the `character_content_review_final` router task.
- +5 if `final_review_model` distribution shows expected routing (mostly `minimax`, Kimi on budget/circuit events)

**Key Questions**:
- Are carousels actually being generated? (count > 0)
- What's the average AI review score?
- Are hooks varied or repetitive? (sample 10 hooks, check uniqueness)
- Do slides have image URLs assigned?
- Are text overlays properly formatted for TikTok?

### Phase 3: Pipeline Automation Audit (5 min)
Score the batch processing and queue infrastructure.

**Scoring Criteria**:
- +15 if research queue works end-to-end (start -> progress -> complete)
- +10 if research queue survives container restarts (DB-backed fallback)
- +10 if batch generation works (POST /batch-smart returns results)
- +10 if smart prioritization works (characters scored by content potential)
- +10 if cancel functionality works
- +10 if failed characters are auto-retried
- +10 if stuck "researching" characters are auto-reset on queue start
- +5 if scheduler jobs exist for character content (check scheduler_service.py)
- +10 if progress tracking shows real-time step-by-step status
- +10 if error messages are captured and displayed in queue UI

**Key Questions**:
- Has the research queue successfully processed characters?
- Does the queue show accurate status after container restart?
- Are there any stuck characters?
- Is batch generation using smart scoring?

### Phase 4: Learning & Optimization Audit (5 min)
Score the feedback loop and continuous improvement.

**Scoring Criteria**:
- +15 if content_learning_engine.py integrates with outcome_learning_service
- +15 if episodic memory records carousel performance
- +15 if A/B experiments are tracked (content_experiments table)
- +10 if prompt evolution is registered for carousel generation
- +15 if brain context actually appears in generation metadata
- +10 if performance insights are queryable (posting time, angle performance)
- +10 if scheduler job runs to process outcomes (character_brain_learn)
- +10 if template performance tracking works (times_used, avg_score updated)

### Phase 5: UI/UX Experience Audit (5 min)
Score the frontend experience for content creators.

Read CharacterContentPage.tsx and CharacterDetailPage.tsx:

**Scoring Criteria**:
- +10 if Characters tab shows all characters with status, images, fact counts
- +10 if Research Queue tab shows real-time progress with step visualization
- +10 if Content Studio tab has template selector, angle picker, slide count
- +10 if Review Queue tab supports approve/reject with AI scores visible
- +10 if Inspiration tab allows URL analysis and pattern discovery
- +10 if Analytics tab shows source effectiveness, template performance, engagement
- +5 if Character Detail page shows research data, fact bank, images, carousels
- +5 if loading states present on all data-fetching components
- +5 if error states handled gracefully
- +5 if responsive design works (md: and lg: breakpoints)
- +10 if dark theme is consistent (bg-gray-*, no bg-zinc-*)
- +10 if accessibility (aria-labels, semantic HTML)

### Phase 6: Code Quality Audit (5 min)
Score using the /zero-deep-review methodology.

**Run 3 parallel scans**:

Agent 1 — Backend Quality:
- Count bare `except Exception` across all 6 services
- Count `datetime.now()` without timezone
- Count functions > 100 lines
- Check structlog adoption
- Count endpoints with/without response_model

Agent 2 — Frontend Quality:
- Count `: any` / `as any` in .tsx files
- Check React Query adoption (should be 100%)
- Count error boundaries
- Check TypeScript interfaces (should be in hooks file)

Agent 3 — Test Coverage:
- Check backend/tests/ for character content tests
- Check frontend/src/tests/ for character content tests
- Run any existing tests

**Scoring Formula** (start at 100, deduct):
- -2 per bare `except Exception`
- -5 per function > 100 lines
- -3 per endpoint missing response_model
- -10 per `: any` in frontend
- -20 if no tests exist
- +5 if structlog used consistently

### Phase 7: Content Strategy Audit (5 min)
Score the strategic depth of the content system.

**Scoring Criteria**:
- +10 if 15 content angles available (hidden_truths through timeline_deep_dive)
- +10 if angle rotation strategy exists (avoid repeating angles per character)
- +10 if 50+ music tracks seeded with mood mapping
- +10 if inspiration pattern extraction works
- +10 if competitor analysis (discover_carousel_creators) returns results
- +10 if multi-universe support (Marvel, DC, Star Wars, LOTR, TV, Film, etc.)
- +10 if cross-character storylines are supported (hidden_connection, versus_breakdown)
- +10 if content calendar/scheduling capability exists
- +10 if trending topic integration exists (adapt to current events)
- +10 if hashtag optimization is data-driven

### Phase 8: Publishing & Distribution Audit (5 min)
Score readiness for actual TikTok publishing.

**Scoring Criteria**:
- +15 if TikTok API integration exists (upload, schedule)
- +15 if image rendering pipeline exists (text overlay on character images)
- +10 if caption optimization uses engagement data
- +10 if hashtag strategy is data-driven (trending + niche)
- +10 if cross-platform support (Instagram Reels, YouTube Shorts)
- +10 if scheduling system allows time-of-day optimization
- +10 if A/B caption testing is supported
- +10 if post-publish analytics sync exists
- +10 if watermarking/branding is applied

## Grade Calculation

After all phases, compute:

```
Overall = (Research * 0.15) + (Generation * 0.15) + (Pipeline * 0.15) +
          (Learning * 0.10) + (UI/UX * 0.15) + (Code * 0.10) +
          (Strategy * 0.10) + (Publishing * 0.10)
```

## Improvement Plan Generation

After grading, generate prioritized improvements:

1. **Quick Wins** (< 1 hour, +5 platform points each)
2. **Medium Effort** (1-4 hours, +10 platform points each)
3. **Major Features** (4+ hours, +15 platform points each)

Categorize each improvement by:
- Dimension it improves
- Estimated effort
- Expected point increase
- Dependencies (what must be done first)
- Files to modify

## Industry Research Protocol

When `--research` flag is used or as part of full review:

1. Search for latest TikTok carousel best practices (2025-2026)
2. Research what tools like Canva, Later, Hootsuite, ContentStudio offer
3. Find viral carousel format analysis (everything.daily, character facts accounts)
4. Research AI content creation trends (GPT-4 image gen, video synthesis)
5. Look for A/B testing frameworks for social media content
6. Research TikTok algorithm optimization strategies
7. Find engagement benchmarks for character/fan content niche

Store findings in `knowledge/INDUSTRY_RESEARCH.md`.

## Output Format

```
Character Content Review — Grade: XX/100 (Letter) [+/-X from last run]

  Research Quality:       XX/100  (X sources active, avg X facts/char)
  Content Generation:     XX/100  (X templates, avg X/10 AI score)
  Pipeline Automation:    XX/100  (queue works: Y/N, batch: Y/N)
  Learning & Optimization: XX/100  (brain integration: Y/N, A/B: Y/N)
  UI/UX Experience:       XX/100  (X/6 tabs, loading: Y/N, errors: Y/N)
  Code Quality:           XX/100  (X bare excepts, X tests)
  Content Strategy:       XX/100  (X angles, X music tracks)
  Publishing:             XX/100  (TikTok API: Y/N, render: Y/N)

  Top 3 Improvements:
  1. [Dimension] Description (+X pts, ~Xh effort)
  2. [Dimension] Description (+X pts, ~Xh effort)
  3. [Dimension] Description (+X pts, ~Xh effort)

  Since Last Review:
  - [IMPROVED] Dimension: what changed (+X pts)
  - [REGRESSED] Dimension: what broke (-X pts)
  - [NEW] Feature added
```

## Rules

- **NEVER modify source code** during review — this skill is READ-ONLY analysis
- Always read knowledge files FIRST to detect trends
- Always WRITE updated SCORECARD.md and history file at end of every run
- Score based on HARD DATA (API responses, grep counts, test results), not subjective judgment
- When scoring, be consistent with previous runs so trends are meaningful
- If an API endpoint returns 500, that's a -5 penalty AND a high-priority fix item
- Always include actionable next steps, not just grades
- Research industry best practices at least once per month
- Compare to last run — **delta matters more than absolute score**
