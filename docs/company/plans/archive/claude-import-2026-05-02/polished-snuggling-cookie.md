# Character Content Review #3 — Execution Plan

## Context

Running the 3rd comprehensive audit of Zero's Character Content Creation system. Last review was Review #2 on 2026-04-15, which scored **61/100 (D)**. Since then, two significant commits landed:
- `e9fe2cb` — replaced bare `except Exception` with specific types (44 → 9 remaining)
- `131b2a0` — added `response_model` to all 21 previously untyped endpoints (now 46/46 = 100%)

This review will verify live API data, re-score all 8 dimensions, update the SCORECARD, and write a new history file.

## Phase 1: Collect Live API Data (~3 min)

Run these API calls against `localhost:18792` to get current system state:

```bash
TOKEN=$(grep ZERO_GATEWAY_TOKEN .env | cut -d= -f2)

# 1. Character stats
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/stats

# 2. All characters (count, completion status)
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:18792/api/characters/?limit=100"

# 3. Research queue status
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/research-queue

# 4. Source analytics
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/analytics/sources

# 5. All carousels (count, scores, statuses)
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:18792/api/characters/carousels?limit=100"

# 6. Template analytics
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/analytics/templates

# 7. Templates list (usage counts)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/templates

# 8. Music tracks (seeded count)
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:18792/api/characters/music?limit=100"
```

## Phase 2: Score All 8 Dimensions

### Pre-verified Metrics (from code exploration)

| Metric | Last Review | Current | Source |
|--------|------------|---------|--------|
| Bare `except Exception` | 44 | **9** | grep verified (7 main, 1 renderer, 1 inspiration) |
| Endpoints with `response_model` | 25/46 (54%) | **46/46 (100%)** | grep verified |
| Endpoints with auth | 0/46 | **0/46** | grep verified — STILL ZERO |
| Frontend `any` types | 0 | **0** | explore agent |
| Structlog adoption | 7/7 | **7/7** | explore agent |
| Timezone-unsafe datetime | 0 | **0** | explore agent |
| Backend tests | 0 | **0** | no test files found |
| Frontend tests | 0 | **0** | no test files found |
| Loading states | 6/6 tabs | **6/6 tabs** | explore agent |
| aria-labels | 4 | **~4** | explore agent |
| Services count | 7 | **7** | explore agent |
| Pydantic models | 26 | **26** | explore agent |
| ORM models | 8 | **8** | explore agent |
| Scheduler jobs | 3 | **3** | explore agent |

### Scoring per Dimension

**Dimension 1 — Research Quality (15% weight)**
Score using API data: source count, facts/char avg, images/char avg, depth scores, completion %, fragments with provenance, relationship mapping.
- Known: 3 sources active (fandom_wiki, reddit, tvtropes). IMDB/Quotes still missing.
- Need to verify: completion count, avg facts, depth scores from live API.

**Dimension 2 — Content Generation (15% weight)**
Score using API data: carousel count, template usage, hook quality, slide structure, overlay specs, multi-char, series, AI review avg, music, brain context.
- Known: At least 1 carousel (Loki, 8.5/10). Templates exist but were at 0 usage.
- Need to verify: total carousel count, avg AI score, template usage from live API.

**Dimension 3 — Pipeline Automation (15% weight)**
Score from code analysis + API: queue e2e, restart survival, batch gen, smart prioritization, cancel, retry, stuck reset, scheduler, progress tracking, error messages.
- Known: Queue working, 3 scheduler jobs, cancel/retry implemented, smart batch confirmed.
- Preliminary: ~80-85/100 (similar to last review, pipeline was already strong).

**Dimension 4 — Learning & Optimization (10% weight)**
Score from code analysis: content_learning_engine integration, episodic memory, A/B experiments, prompt evolution, brain context, performance insights, scheduler job, template tracking.
- Known: Infrastructure exists but character content doesn't actively call brain/outcome services.
- Preliminary: ~65/100 (code wired but not actively producing outcomes).

**Dimension 5 — UI/UX Experience (15% weight)**
Score from code analysis: 6 tabs, detail page, loading, errors, responsive, dark theme, accessibility.
- Known: 6 tabs, all loading states, page-level error boundary, 5/6 empty states, 0 accessibility, consistent dark theme.
- Preliminary: ~82/100 (unchanged — no UI changes since last review).

**Dimension 6 — Code Quality (10% weight)**
Score from grep counts: bare excepts, large functions, response_model, tests, any types, structlog, async, timezone, pydantic, DI.
- Known: Major improvements — excepts 44→9, response_model 0→100%. Still 0 tests, 0 auth.
- Formula: Start 100, -2×9 excepts = -18, -5×1 large func = -5, -0 response_model, -20 no tests, +5 structlog, +5 async, +5 timezone, +3 pydantic, +5 DI = **80/100**

**Dimension 7 — Content Strategy (10% weight)**
Score from code analysis: angles, rotation, music, inspiration, competitor analysis, universes, cross-char, calendar, trending, hashtags.
- Known: 15 angles, 50 music tracks, 10 templates, 10 universes. No trending integration.
- Preliminary: ~60/100 (unchanged — no strategy changes since last review).

**Dimension 8 — Publishing & Distribution (10% weight)**
Score from code analysis: TikTok API, rendering, captions, hashtags, cross-platform, scheduling, A/B captions, post-publish analytics, watermarking.
- Known: CarouselRendererService works. No TikTok publishing pipeline. No cross-platform.
- Preliminary: ~20/100 (unchanged — no publishing changes since last review).

### Preliminary Overall Calculation

```
Overall = (Research × 0.15) + (Generation × 0.15) + (Pipeline × 0.15) +
          (Learning × 0.10) + (UI/UX × 0.15) + (Code × 0.10) +
          (Strategy × 0.10) + (Publishing × 0.10)

Using preliminary scores (API data may adjust Research + Generation):
= (50 × 0.15) + (55 × 0.15) + (82 × 0.15) +
  (65 × 0.10) + (82 × 0.15) + (80 × 0.10) +
  (60 × 0.10) + (20 × 0.10)
= 7.50 + 8.25 + 12.30 + 6.50 + 12.30 + 8.00 + 6.00 + 2.00
= 62.85 → ~63/100

With Code Quality jump from 62→80, minimum improvement = +1.8 weighted points.
If API data shows more carousels/research progress, could reach 65-70.
```

**Expected range: 63-70/100 (D to D+)**

The code quality improvements are the biggest confirmed delta (+18 raw points on Code Quality dimension).

## Phase 3: Write Deliverables

### 3.1 Update SCORECARD.md
- `.claude/skills/character-content-review/knowledge/SCORECARD.md`
- Update all 8 dimension scores with evidence
- Calculate new weighted average
- Update "What Changed Since Last Review" section
- Update "Path to C" roadmap

### 3.2 Write History File
- `.claude/skills/character-content-review/knowledge/history/2026-04-15-review-3.md`
- Score changes table with deltas
- Key findings (positive + negative)
- API data snapshot
- User concern tracking

### 3.3 Update IMPROVEMENT_PLAN.md
- `.claude/skills/character-content-review/knowledge/IMPROVEMENT_PLAN.md`
- Mark completed items (response_model fix, bare except reduction)
- Re-prioritize remaining work
- Add new items discovered

## Phase 4: Output Summary

Print the standard review output format:
```
Character Content Review — Grade: XX/100 (Letter) [+/-X from last run]

  Research Quality:       XX/100  (...)
  Content Generation:     XX/100  (...)
  Pipeline Automation:    XX/100  (...)
  Learning & Optimization: XX/100  (...)
  UI/UX Experience:       XX/100  (...)
  Code Quality:           XX/100  (...)
  Content Strategy:       XX/100  (...)
  Publishing:             XX/100  (...)

  Top 3 Improvements:
  1. [Dimension] Description (+X pts, ~Xh effort)
  2. ...
  3. ...
```

## Key Files to Read/Modify

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/services/character_content_service.py` | Read | Verify bare except count, brain integration |
| `backend/app/routers/character_content.py` | Read | Verify response_model, auth counts |
| `frontend/src/pages/CharacterContentPage.tsx` | Read | Verify UI/UX metrics |
| `frontend/src/hooks/useCharacterContentApi.ts` | Read | Verify hook counts, types |
| `.claude/skills/character-content-review/knowledge/SCORECARD.md` | **Write** | Update scores |
| `.claude/skills/character-content-review/knowledge/IMPROVEMENT_PLAN.md` | **Write** | Update plan |
| `.claude/skills/character-content-review/knowledge/history/2026-04-15-review-3.md` | **Write** | New history entry |

## Verification

After writing all deliverables:
1. Read back SCORECARD.md to confirm calculation correctness
2. Verify history file has all score deltas
3. Confirm improvement plan reflects completed items
4. Print summary to user in standard format
