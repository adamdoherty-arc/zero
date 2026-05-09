# Zero Brain: World-Class Content Generation Upgrade (Revised)

## Context

Original plan was based on a stale repo snapshot. Survey of current state shows **significant chunks are already shipped**:

- Migration 028 built `media_titles`, `character_media_titles`, `media_images`, `media_research_fragments`; added `content_type` + `media_title_id` to `character_carousels`.
- [backend/app/services/media_content_service.py](backend/app/services/media_content_service.py) — full media carousel service.
- [backend/app/services/media_research_sources.py](backend/app/services/media_research_sources.py) — research pipeline.
- [backend/app/routers/media_content.py](backend/app/routers/media_content.py) — CRUD + generation.
- Scheduler jobs `media_auto_research` + `media_content_generation` registered.
- [backend/app/services/character_discovery_service.py](backend/app/services/character_discovery_service.py) pulls TMDB trending, Wikipedia pageview trending, Reddit fandom trending, SearXNG trending (4 funnels live).
- Hook-style persistence: already in `character_content_service.py:1502-1519` (writes `hook_style` + `content_format` into `generation_metadata`).
- Migrations at revision **030**; next is **031**.

Target stays the same: lift brain score from 63-64 -> 85+ by building a world-class 24/7 content employee.

## Revised Gaps (what's actually missing)

1. **Release-calendar-aware triggering.** Discovery pulls TMDB weekly trending but doesn't track *release_date*. No "prep 7-14 days before a Marvel/Netflix drop" logic.
2. **Multi-agent content swarm.** Generation is monolithic single-LLM. Council + agent_company services exist but aren't wired into carousel generation.
3. **Prompt breeder.** `prompt_variants` table collects scores but no automated mutation/retirement job.
4. **Competitor content scraper.** No ingestion of winning external TikTok/IG/YouTube hooks.
5. **Brain benchmark dimensions.** Missing `trending_alignment`, `swarm_consensus_quality`, `calibration_per_agent`.
6. **Per-style engagement reporting.** `hook_style` persisted; no job computes engagement lift per style.
7. **Content Employee Dashboard frontend.**
8. **Tool caching + concurrency wrappers.**

## Revised Phase Plan (3 weeks)

### Phase 1 — Trend + Release Intelligence (days 1-4)

Make Zero proactively aware of what the world is about to watch, and route that into *existing* character/media pipelines.

**Migration 031_trending_signals.py**
```sql
trending_signals(
  id TEXT PK,
  source TEXT (imdb|tmdb|tvmaze|google|reddit|tiktok|youtube),
  signal_type TEXT (release|trending|viral),
  title TEXT,
  franchise TEXT NULL,
  universe TEXT NULL,
  release_date DATE NULL,                -- for release signals
  signal_strength FLOAT,                 -- 0-100 LLM-scored
  metadata JSONB,
  external_id TEXT NULL,                 -- tmdb_id, imdb_id, etc
  linked_character_ids JSONB DEFAULT '[]',
  linked_media_title_ids JSONB DEFAULT '[]',
  processed_at TIMESTAMPTZ NULL,
  discovered_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ                  -- 30-day decay (ADA pattern)
)
CREATE INDEX idx_signals_release_date ON trending_signals(release_date)
CREATE INDEX idx_signals_source_discovered ON trending_signals(source, discovered_at)
```

**New [backend/app/services/trend_intelligence_service.py](backend/app/services/trend_intelligence_service.py)**
- `fetch_tmdb_upcoming(days=30)` — `/movie/upcoming` + `/tv/on_the_air` from TMDB (key already present per char discovery).
- `fetch_tvmaze_schedule(days=14)` — free, no key: `api.tvmaze.com/schedule`.
- `fetch_google_trends_pulse(niches)` — SearXNG over `trends.google.com` (existing pattern in char discovery).
- `fetch_reddit_rising()` — reuse char discovery's Reddit scraping.
- `score_signal(title, metadata)` — LLM-judged viewer-interest score via existing `llm_router`.
- `link_signal_to_characters(signal_id)` — match `franchise` against existing characters; write `linked_character_ids`.
- `link_signal_to_media_titles(signal_id)` — match against existing `media_titles`; also create `MediaTitleModel` rows for new upcoming releases.

**New [backend/app/routers/trend_intelligence.py](backend/app/routers/trend_intelligence.py)**
- `GET /api/trends/signals` — list (filter by source, active, days)
- `GET /api/trends/upcoming-releases` — sorted by release_date
- `POST /api/trends/refresh` — manual sync trigger
- `GET /api/trends/signal/{id}` — detail with linked characters/media

**Scheduler jobs** in `scheduler_service.py`:
- `trend_release_calendar_sync` (every 6h) — TMDB upcoming + TVMaze schedule -> trending_signals rows.
- `trend_reddit_pulse` (every 2h)
- `trend_google_pulse` (every 4h)
- `trend_linker` (every 2h) — for each unprocessed signal, call link_signal_to_characters + link_signal_to_media_titles.
- `character_release_prep` (daily 5am) — for trending_signals with release_date in [today+3, today+14] AND linked_character_ids non-empty, if `research_status=completed` and no recent carousel, queue 3-carousel burst via `character_content_service.generate_carousel()` with angles `behind_scenes`, `hidden_truths`, `power_secrets`. Writes `generation_metadata.release_triggered_by = signal_id`.
- `media_release_prep` (daily 5am) — same for media_titles. Uses `media_content_service` with angles `pre_release_hype`, `top_5_facts`, `cast_trivia`.
- `trend_signal_cleanup` (daily 3am) — mark expired signals.

**Extend CharacterDiscoveryService** — add `from_trend_signal(signal_id)` method (create characters with `discovery_source="trend_release"`, `discovery_evidence={release_date, franchise, signal_id}`, set `priority_tier="trending"`).

**MCP tool additions** in `mcp_servers/zero_api_mcp.py`:
- `query_trending_signals(source?, days_ahead?, min_strength?)`
- `query_upcoming_releases(days_ahead=14)`

### Phase 2 — Multi-Agent Content Swarm (days 5-10)

Replace monolithic carousel generation with LangGraph swarm reusing agent_company + council.

**Migration 032_agent_predictions.py**
```sql
agent_predictions(
  id TEXT PK,
  carousel_id TEXT NOT NULL,
  content_type TEXT (character|media),
  role_name TEXT,                           -- TrendScout, Researcher, etc.
  predicted_engagement FLOAT,               -- 0-100
  confidence FLOAT,                         -- 0-1
  vote TEXT (accept|hold|reject),
  reasoning TEXT,
  weight FLOAT,                             -- role weight used
  created_at TIMESTAMPTZ DEFAULT now(),
  outcome_engagement FLOAT NULL,
  outcome_recorded_at TIMESTAMPTZ NULL,
  calibration_error FLOAT NULL              -- |predicted - outcome|
)
```

**New [backend/app/services/content_swarm_service.py](backend/app/services/content_swarm_service.py)**
Roles (weights sum to 100% across voters; Scriptwriter executes, doesn't vote):
| Role | Weight | Duty |
| --- | --- | --- |
| TrendScout | 15% | Confirms cultural relevance + decay window |
| Researcher | 20% | Fact-depth, credibility |
| Strategist | 20% | Angle + hook style + template (reads competitor_samples + prompt_variants) |
| Scriptwriter | — | Produces carousel (Kimi plans, Gemma executes via existing router) |
| Editor | 15% | Polish + tighten |
| CriticVoter | 15% veto | Brand fit, safety, accuracy |
| ValuePredictor | 15% | Predicts engagement + confidence |

- `generate_via_swarm(character_id|media_title_id, angle, template)` — orchestrates with LangGraph handoffs. Each voter records an `AgentPrediction` before the vote. Final decision = weighted sum; threshold 0.65 with CriticVoter hard veto.
- Reuses `character_content_service._select_prompt_variant()` + `_record_prompt_run_safe()`.
- On publish, 24h/7d performance flows back to `agent_predictions.outcome_engagement` for calibration.

**Feature flag**: `character_swarm_enabled` config (default false, flip after 10 test runs). Both paths coexist.

**Seed content roles** into `agent_roles` table via idempotent seed call at startup (mirrors existing pattern for CEO/Researcher/Analyst/Engineer/Validator).

### Phase 3 — Learning Accelerators (days 8-14, parallel with Phase 2)

**3a. Prompt Breeder — [backend/app/services/prompt_breeder_service.py](backend/app/services/prompt_breeder_service.py)**
- Nightly `brain_prompt_breed` (2:30am): per `task_type`, select top-3 variants by `avg_score`, ask Kimi to generate 2 mutations each (structural + tone) = 6 children. Children: `generation = parent.generation + 1`, `is_active=true`, `total_uses=0`. Retire bottom-3 variants (set `is_active=false`, never delete). Guardrail: skip retirement if variant has fewer than 20 runs.
- New endpoint `POST /api/brain/prompts/breed?task_type=...` for manual trigger.

**3b. Competitor Content Scraper — [backend/app/services/competitor_content_service.py](backend/app/services/competitor_content_service.py)**
- Migration 033 adds `competitor_content_samples` table (niche, platform, hook_text, caption, engagement_rate, retrieved_at, expires_at DEFAULT now()+30d).
- SearXNG + Firecrawl over public TikTok/IG/YouTube pages for the niches Zero already targets.
- Scheduler `competitor_scrape` (every 12h per niche).
- Strategist role in Phase 2 swarm reads top competitor samples as style exemplars.
- Prompt breeder mutator also reads top samples to inform mutations.

**3c. Per-style engagement report**
- Scheduler `character_hook_style_report` (weekly Sun 4am): query `character_carousels` joined to performance, group by `generation_metadata->>'hook_style'`, compute avg engagement. Store as episodic memory with importance=70 + write to `benchmark_scores`.

**3d. Brain benchmark dimensions** — extend [backend/app/services/employee_benchmark_service.py](backend/app/services/employee_benchmark_service.py) `DIMENSIONS` dict (line 30):
- `trending_alignment` (8% weight) — % of last-7d content with `generation_metadata.release_triggered_by` OR `linked_signal_id` set.
- `swarm_consensus_quality` (7% weight) — avg weighted-consensus score on approved carousels in last 7d.
- `calibration_per_agent` (5% weight) — `100 - (avg MAE of agent_predictions.calibration_error * 5)`.
Rebalance: reduce `knowledge_growth` from 5% -> 0% (remove), reduce `learning_velocity` 15% -> 10%. Total stays 100%.

### Phase 4 — Content Employee Dashboard (days 12-17)

**Backend**: add endpoints in [backend/app/routers/brain.py](backend/app/routers/brain.py):
- `GET /api/brain/employee/overview` — live stats (content units last 24h, avg calibration, swarm decisions in flight, benchmark dimension sparklines)
- `GET /api/brain/employee/agent-stats` — per-role win rate, calibration MAE, last 10 decisions
- `GET /api/brain/employee/trending` — active signals feed
- `GET /api/brain/employee/cost` — cost per content unit rolling 7d

**Frontend**: new page [frontend/src/pages/BrainEmployeePage.tsx](frontend/src/pages/BrainEmployeePage.tsx) + hook [frontend/src/hooks/useBrainEmployeeApi.ts](frontend/src/hooks/useBrainEmployeeApi.ts). Sidebar entry under "Brain". Reuses existing React Query + shadcn patterns.

### Phase 5 — 24/7 Infrastructure Hardening (days 15-21)

**Tool caching + concurrency** in [mcp_servers/zero_api_mcp.py](mcp_servers/zero_api_mcp.py) — wrapper util `cached_tool(ttl_seconds)` + shared `asyncio.Semaphore(5)` for external APIs. Apply to trending_signals (5min), media_titles (24h), competitor_samples (5min), deep_research results (30min).

**Skill updates** — edit `.claude/skills/zero-brain/SKILL.md` adding `--trending`, `--releases`, `--swarm` modes. Edit `.claude/skills/zero-character-content/knowledge/IMPROVEMENT_PLAN.md` to mark closed items and add v2 roadmap.

**Legion sprint** — create "Content Brain v2" sprint in Legion project_id=8 with one task per phase.

## Files Created / Modified

### Created
- `backend/app/migrations/versions/031_trending_signals.py`
- `backend/app/migrations/versions/032_agent_predictions.py`
- `backend/app/migrations/versions/033_competitor_content_samples.py`
- `backend/app/services/trend_intelligence_service.py`
- `backend/app/services/content_swarm_service.py`
- `backend/app/services/prompt_breeder_service.py`
- `backend/app/services/competitor_content_service.py`
- `backend/app/routers/trend_intelligence.py`
- `backend/app/models/trending_signals.py` (Pydantic)
- `backend/app/models/agent_predictions.py`
- `frontend/src/pages/BrainEmployeePage.tsx`
- `frontend/src/hooks/useBrainEmployeeApi.ts`
- `frontend/src/hooks/useTrendIntelligenceApi.ts`

### Modified
- `backend/app/services/character_discovery_service.py` — add `from_trend_signal()`
- `backend/app/services/character_content_service.py` — optional `use_swarm` param routes to `content_swarm_service`; write `release_triggered_by` when set
- `backend/app/services/media_content_service.py` — same hook for release_triggered_by
- `backend/app/services/employee_benchmark_service.py` — extend DIMENSIONS, add scorer functions
- `backend/app/services/scheduler_service.py` — add 8 jobs
- `backend/app/routers/brain.py` — employee endpoints
- `backend/app/main.py` — register new routers
- `backend/app/db/models.py` — ORM models for new tables
- `mcp_servers/zero_api_mcp.py` — cache/semaphore util + new tools
- `frontend/src/App.tsx` — register `/brain/employee`, `/trends`
- `.claude/skills/zero-brain/SKILL.md`
- `.claude/skills/zero-character-content/knowledge/IMPROVEMENT_PLAN.md`

## Reuse Map

| Need | Reuse | Location |
| --- | --- | --- |
| Prompt variant select + record | `_select_prompt_variant`, `_record_prompt_run_safe` | `character_content_service.py:77,95` |
| Council voting | `council_service.run_council()` | `council_service.py` |
| STORM research | `deep_research_service.run_research()` | `deep_research_service.py` |
| Role registry | `agent_company_service.AgentRole` | `agent_company_service.py` |
| LangGraph handoffs | existing usage | `tiktok_agent_graph.py` |
| TMDB API key + client | already used | `character_discovery_service.py` |
| SearXNG + Firecrawl | wired | `character_research_sources.py` |
| LLM routing (Kimi plans / Gemma executes) | `llm_router` | `infrastructure/llm_router.py` |
| Episodic memory + outcome recording | existing services | `brain/` |
| Discovery evidence schema | `discovery_source`, `discovery_evidence` | `CharacterModel` |
| Media content pipeline | exists, extend with `release_triggered_by` | `media_content_service.py` |
| Hook_style persistence | already done | `character_content_service.py:1502-1519` |

## Verification

**Phase 1:**
```bash
docker compose -f docker-compose.sprint.yml exec zero-api alembic upgrade head
curl -s http://localhost:18792/api/trends/signals -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" | python -m json.tool
# expect >= 20 signals after first sync cycle
curl -s "http://localhost:18792/api/trends/upcoming-releases?days_ahead=14" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
# expect sorted list by release_date
```

**Phase 2:**
```bash
curl -sX POST http://localhost:18792/api/characters/{id}/carousels \
  -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" \
  -d '{"angle":"hidden_truths","use_swarm":true}'
# response includes generation_metadata.swarm_votes (5 role votes + weighted_consensus)
curl -s http://localhost:18792/api/brain/employee/agent-stats -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
# per-role calibration appears after 10+ carousels
```

**Phase 3:**
```bash
curl -sX POST "http://localhost:18792/api/brain/prompts/breed?task_type=carousel_generation" \
  -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
# 6 child variants created, 3 retired
docker logs zero-api 2>&1 | grep competitor_scrape | tail -5
# competitor_scrape completes without 429s
```

**Phase 4/5:**
- Browse `http://localhost:5173/brain/employee` -> live agent stats + trending feed.
- `curl /api/brain/benchmark` shows `trending_alignment`, `swarm_consensus_quality`, `calibration_per_agent`.

**End-to-end success:** within 7 days of landing Phase 4, at least one auto-generated carousel published via the release-triggered pipeline with swarm votes logged and outcomes feeding calibration. `trending_alignment` dimension >= 30%.

## Open Questions

- TMDB API key is already in the codebase per char discovery; no new secret needed.
- TikTok publishing remains stubbed (out of scope here).
- Competitor scraping: public pages only, respect robots.txt.
- Cost: swarm adds ~7x LLM calls. Mitigated by Kimi-plans-Gemma-executes. If `cost_efficiency` dimension drops below 60, auto-fallback via feature flag.
