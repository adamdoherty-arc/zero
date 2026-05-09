# Character Content 24/7 Autopilot

## Context

Zero's character content system was designed as a 24/7 creative engine but operates as a reactive pipeline. Today, 7 scheduler jobs run (research refresh, content generation, performance sync, auto-publish, learning, reference video processor, reference video cleanup), yet the user observes the feature is not autonomous:

1. New characters only appear when manually created or seeded; there is no discovery loop even though 4 free sources are available (TikTok reference videos, Wikipedia + TMDB trending, Reddit trending, SearXNG trend scan).
2. Existing characters are not continuously improved. Gaps in image count, content angle coverage, fact bank depth, and hook quality persist indefinitely because `smart_batch_generate()` is manual only.
3. Publishing stalls because `character_auto_publish` only handles `status='approved'` carousels, and nothing transitions carousels from `review` to `approved` without a human click.
4. MiniMax is the default for Stage 2 carousel review on every carousel (no budget cap), burning spend that could be local.
5. Weak hooks (`ai_review.hook_strength < 6`) are scored but never regenerated.

The user wants: aggressive discovery beyond Marvel/DC, overnight gap-filling on existing characters, captivating hooks and the right images, local-first with MiniMax reserved for high-value escalation, and auto-approval at `final_review_score >= 85`.

This plan delivers a closed-loop autopilot: discovery -> research -> carousel generation -> gap fill -> hook polish -> Ollama Stage 2 -> optional MiniMax escalation -> auto-approve at 85+ -> publish. Each layer has a human kill-switch.

## Architecture Summary

Six new scheduler jobs stacked onto the existing seven, forming a nightly chain and continuous daytime polish:

```
01:00 character_discovery           (Wikipedia + TMDB + Reddit + SearXNG)
02:00 character_gap_audit           (images + angles + facts + hooks)
03:00 character_research_refresh    (existing)
06:00 character_hook_audit          (every 6h: regenerate weak hooks)
10/14/18:00 character_auto_publish  (existing)
every 30m character_auto_approval   (score >= 85 -> approved)
every 2h  character_publish_backlog (maintain 6 approved-queued)
every 15m character_discovery_refvideos (promote proposed chars from ref videos)
every 12h character_content_generation (existing)
every 6h  character_performance_sync (existing)
every 4h  character_content_learning (existing)
every 1m  character_reference_video_processor (existing)
04:00 character_reference_video_cleanup (existing)
```

Two new service files, one migration, one frontend page, one router extension. Everything else reuses existing primitives.

## Phase 1: MiniMax Guardrails

Stop MiniMax from being the default reviewer. Make it a promotion path for high-value carousels only. Wire the `daily_budget_usd` and `current_spend_usd` fields in [llm.py:131-132](backend/app/models/llm.py#L131-L132) that are defined but unused.

**Modify [backend/app/models/llm.py](backend/app/models/llm.py) (lines 124-129)**
- Flip `character_content_review_final` to local-first:
  - `model="ollama/gemma4:31b"` (matches ai_company default, already warmed)
  - `fallbacks=["ollama/qwen3-coder-next:latest", "kimi/kimi-k2.5", "minimax/MiniMax-M2.7"]`
- Add new task `character_content_review_escalated`:
  - `model="minimax/MiniMax-M2.7"`, fallback `kimi/kimi-k2.5`.
- Add new task `character_hook_regen`:
  - `model="ollama/gemma4:31b"`, fallback `kimi/moonshot-v1-8k`.

**Modify [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) (`_run_final_review`, lines 1866-2021)**
- After the Stage 2 call (now Ollama) parses successfully, run `_should_escalate_to_minimax(character, stage1_review, stage2_parsed) -> bool`. Escalate only when:
  - Stage 2 `overall_score >= 80` (settings: `character_minimax_min_stage2_score`)
  - Character `priority_tier` is `priority` or `probation` (new or proven winners, not mid-tier duds)
  - Today's MiniMax spend below cap
- On escalation, call `client.chat(task_type="character_content_review_escalated", ...)`. Overwrite `final_review_score`, `final_review_model`; preserve both rounds under `final_review["rounds"]` for audit.

**Modify [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py)**
- Add `async def get_daily_spend(provider: str) -> float` and `async def record_spend(provider: str, usd: float)` backed by the new `llm_daily_spend` table.
- Add `async def is_budget_exceeded(provider: str, daily_cap_usd: float) -> bool`.
- In the existing `chat()` path, after a successful provider call, compute `tokens * price_per_1m` using the pricing already declared in each provider module (e.g., `minimax_provider.py:25-28`) and call `record_spend`.

**Modify [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py)**
- `character_autopilot_enabled: bool = True`
- `character_minimax_daily_cap_usd: float = 2.0`
- `character_minimax_min_stage2_score: float = 80.0`
- `character_auto_approve_threshold: float = 85.0`
- `character_discovery_enabled: bool = True`
- `character_discovery_daily_cap: int = 10`

**Migration [backend/app/migrations/versions/023_character_autopilot.py](backend/app/migrations/versions/023_character_autopilot.py) (new, single file for all phases)**
- `CREATE TABLE llm_daily_spend (provider text, day date, spend_usd numeric default 0, primary key(provider, day))`

## Phase 2: Auto-Approval + Publishing Backlog

Close the `review -> approved` loop so the existing auto-publisher at 10/14/18:00 has content to ship.

**Modify [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)**
- New method `async def auto_approve_eligible(limit: int = 20) -> int`:
  - SELECT carousels where `status='review'` AND `final_review_score >= 85` AND `auto_approved IS NULL` AND character.`autonomous_disabled = false`.
  - Set `status='approved'`, `auto_approved=true`, `auto_approved_at=now()`, `auto_approve_reason='final_review_score>=85'`, `publish_status='queued'`.
  - Carousels scoring 75-84 remain in `review` for human decision.
  - Carousels scoring below 75 move to `status='needs_work'` (new state).
- New method `async def ensure_publish_backlog(target: int = 6) -> Dict`:
  - Count carousels where `status='approved'` AND `publish_status='queued'`.
  - If below target, call existing `smart_batch_generate(count=target-current, prefer_priority_tier=True)` then `auto_approve_eligible()` on new carousels.

**Modify [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) (follow pattern at lines 2387-2506)**
- `_run_character_auto_approval` every 30 min. Gated on `settings.character_autopilot_enabled`.
- `_run_character_publish_backlog` every 2 hours with target of 6.

**Migration additions (023)**
- `ALTER TABLE character_carousels ADD COLUMN auto_approved boolean`
- `ALTER TABLE character_carousels ADD COLUMN auto_approved_at timestamptz`
- `ALTER TABLE character_carousels ADD COLUMN auto_approve_reason text`

## Phase 3: Gap-Filling Audit

Nightly loop that audits every active character for all four gap types and enqueues fix work. Reuses `ImageSourceService.discover_images()` at [image_source_service.py:89](backend/app/services/image_source_service.py#L89), `CharacterResearchSources.refresh_research()`, and existing carousel generation.

**Modify [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)**
- `async def audit_character_gaps(character_id: str) -> Dict`:
  ```python
  return {
      "image_gap": max(0, 10 - validated_image_count),
      "angle_gap": [a for a in ContentAngle if a not in used_angles],
      "fact_gap": max(0, 20 - verified_fact_count),
      "weak_hooks": [cid for c in carousels if c.ai_review.hook_strength < 6],
  }
  ```
- `async def fill_character_gaps(character_id: str, caps: Dict) -> Dict`:
  - Images: `ImageSourceService.discover_images(character, max_images=image_gap)` (max 5 per run).
  - Angles: `generate_carousel(angle=missing[i])` for up to 3 missing angles, then `ai_review_carousel` (Ollama Stage 2 via Phase 1 changes).
  - Facts: `CharacterResearchSources.refresh_research(character, target_fact_count=20)` pulls from unused sources (WikiQuote, IMDB trivia, TV Tropes).
  - Weak hooks: calls Phase 5's `CharacterHookService.regenerate_hook` on each; skip-with-log if Phase 5 not yet deployed.
- `async def update_priority_tier(character_id: str)`:
  - `priority` if `avg_engagement >= 0.05` OR `total_views >= 10_000` OR `discovery_hits >= 3`.
  - `probation` if `posts_created >= 5` AND `avg_engagement < 0.01`.
  - `standard` otherwise.

**Modify [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py)**
- `_run_character_gap_audit` at 2 AM daily. Iterates active characters with `autonomous_disabled=false`, priority tier first, global cap of 20 characters per run. After each character audit, calls `update_priority_tier`.

**Migration additions (023)**
- `ALTER TABLE characters ADD COLUMN autonomous_disabled boolean default false`
- `ALTER TABLE characters ADD COLUMN priority_tier text default 'standard'`

## Phase 4: Character Discovery

Four autonomous funnels feeding `status='active', research_status='pending'` characters into the existing 3 AM research refresh. Dedup is central since the same trending name can appear in multiple sources.

**New file [backend/app/services/character_discovery_service.py](backend/app/services/character_discovery_service.py)**
- `class CharacterDiscoveryService`:
  - Shared `async def propose_character(name, universe, source, evidence) -> Optional[CharacterModel]`:
    1. Normalize name (lowercase, strip `(character)`, strip titles).
    2. SELECT existing WHERE `LOWER(name)=normalized OR LOWER(real_name)=normalized`. If found, increment `discovery_hits`, return existing (no-op).
    3. Otherwise INSERT with `discovery_source`, `discovery_evidence`, `research_status='pending'`. The existing 3 AM `character_research_refresh` job picks it up (or Phase 3's gap audit if it arrives earlier).
  - `async def discover_from_reference_videos(limit: int = 5)`: reads rows in `character_reference_videos` where `proposed_character` is populated but no character exists yet. Reuses `character_reference_video_service._analyze_discovery` output already in place.
  - `async def discover_from_wikipedia(limit: int = 10)`: calls Wikipedia pageviews REST (`/api/rest_v1/metrics/pageviews/top/...`, no auth), filters to entries whose Wikipedia page category includes "Fictional characters".
  - `async def discover_from_tmdb(limit: int = 5)`: reuses existing `TMDB_API_KEY`, hits `/trending/movie/week` + `/trending/tv/week`, then `/movie/{id}/credits` to extract top-billed character name.
  - `async def discover_from_reddit(limit: int = 5)`: public JSON `reddit.com/r/{sub}/top.json?t=day&limit=25` for r/marvelstudios, r/anime, r/gaming, r/dccomics. Extracts character names via Kimi `moonshot-v1-8k` NER (cheap).
  - `async def discover_from_searxng(limit: int = 5)`: reuses local SearXNG at `http://searxng:8080/search?q=trending+character+2026&format=json`. Entity extraction via Kimi.
  - Rate limits via `asyncio.Semaphore(2)` per source + `tenacity` retry/backoff (same pattern used by `character_research_sources.py`).
  - Global daily cap from `settings.character_discovery_daily_cap` (default 10 new characters per day).

**Modify [backend/app/services/character_reference_video_service.py](backend/app/services/character_reference_video_service.py)**
- No code change required. `_analyze_discovery` and `promote_to_character` already exist; Phase 4 only adds an automated caller.

**Modify [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py)**
- `_run_character_discovery` at 1 AM daily. Runs all four source methods, logs source breakdown to `scheduler_audit_log` via existing `_log_scheduler_run` helper.
- `_run_character_discovery_refvideos` every 15 min, max 5 per cycle (cheap, DB-only).

**Migration additions (023)**
- `ALTER TABLE characters ADD COLUMN discovery_source text`
- `ALTER TABLE characters ADD COLUMN discovery_evidence jsonb`
- `ALTER TABLE characters ADD COLUMN discovery_hits integer default 0`

## Phase 5: Hook Quality Service

Dedicated service that scores hooks and regenerates weak ones before auto-approval gets a chance to evaluate.

**New file [backend/app/services/character_hook_service.py](backend/app/services/character_hook_service.py)**
- `class CharacterHookService`:
  - `async def score_hook(hook_text, slides, character) -> Dict`: returns `{strength, issues, style_match}`. Uses `task_type="character_hook_regen"` (Ollama `gemma4:31b`, free).
  - `async def regenerate_hook(carousel_id, strategy="pattern_interrupt") -> str`: strategies are `pattern_interrupt`, `specific_stat`, `contrarian`, `question`, `list_tease`. Generates 5 candidates via Kimi `moonshot-v1-8k` (~$0.0001 per call), ranks via local `score_hook`, picks best. Pushes old hook to `carousel.generation_metadata["previous_hooks"]` for learning. Re-runs `ai_review_carousel` so `hook_strength` reflects the new hook.
  - `async def audit_weak_hooks(threshold=6.0, limit=20)`: scans carousels where `ai_review.hook_strength < threshold` AND `status in ('draft','review')`. Calls `regenerate_hook` on each.

**Modify [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py)**
- `_run_character_hook_audit` every 6 hours. Runs before auto-approval so a weak-hook carousel gets one shot at rewrite before being gated to human review.

## Frontend: Character Autopilot Dashboard

Observability for what the system did overnight. Without this, the user cannot see the autopilot working.

**New page [frontend/src/pages/CharacterAutopilotPage.tsx](frontend/src/pages/CharacterAutopilotPage.tsx)**
- Top row: 4 KPI tiles. Characters discovered (24h), carousels auto-approved (24h), gaps filled (24h), MiniMax spend today vs. cap.
- Middle: last 20 autopilot actions from `scheduler_audit_log` filtered to character_* jobs.
- Right panel: "Human Queue" showing carousels at 75-84 score needing human decision, ordered by priority tier.
- Global kill switch (toggles `character_autopilot_enabled`).
- Per-character toggle switch for `autonomous_disabled`.

**New hook [frontend/src/hooks/useCharacterAutopilotApi.ts](frontend/src/hooks/useCharacterAutopilotApi.ts)**
- Wraps new endpoints: `GET /autopilot/stats`, `GET /autopilot/actions`, `POST /autopilot/toggle`, `POST /{character_id}/autonomous/toggle`.

**Modify [frontend/src/components/layout/AppSidebar.tsx](frontend/src/components/layout/AppSidebar.tsx)**
- Add "Character Autopilot" nav under the existing Character section.

**Modify [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)**
- Add `Auto-approved` badge next to carousels where `auto_approved=true`.

**Modify [backend/app/routers/character_content.py](backend/app/routers/character_content.py)**
- `GET /autopilot/stats` returns 24h counts and today's MiniMax spend from `llm_daily_spend`.
- `GET /autopilot/actions?limit=20` returns rows from `scheduler_audit_log WHERE job_name LIKE 'character_%'`.
- `POST /autopilot/toggle` flips `character_autopilot_enabled`.
- `POST /{character_id}/autonomous/toggle` flips `autonomous_disabled`.

## Critical Files Touched

- [backend/app/models/llm.py](backend/app/models/llm.py) (Phase 1 default swap, 2 new task types)
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) (new methods: `auto_approve_eligible`, `ensure_publish_backlog`, `audit_character_gaps`, `fill_character_gaps`, `update_priority_tier`, plus `_should_escalate_to_minimax` helper)
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) (6 new `_run_character_*` methods following pattern at lines 2387-2506)
- [backend/app/services/character_discovery_service.py](backend/app/services/character_discovery_service.py) (new)
- [backend/app/services/character_hook_service.py](backend/app/services/character_hook_service.py) (new)
- [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py) (spend tracking)
- [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py) (6 new settings)
- [backend/app/migrations/versions/023_character_autopilot.py](backend/app/migrations/versions/023_character_autopilot.py) (new)
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) (4 new endpoints)
- [frontend/src/pages/CharacterAutopilotPage.tsx](frontend/src/pages/CharacterAutopilotPage.tsx) (new)
- [frontend/src/hooks/useCharacterAutopilotApi.ts](frontend/src/hooks/useCharacterAutopilotApi.ts) (new)
- [frontend/src/components/layout/AppSidebar.tsx](frontend/src/components/layout/AppSidebar.tsx)
- [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) (badge)

## Reused Utilities (No Changes Needed)

- `ImageSourceService.discover_images` at [image_source_service.py:89](backend/app/services/image_source_service.py#L89). 7 free sources, dedup via `uq_character_image_url`.
- `CharacterResearchSources.refresh_research` at [character_research_sources.py:298](backend/app/services/character_research_sources.py#L298). 8 free sources including WikiQuote, IMDB trivia, TV Tropes.
- `CharacterContentService.smart_batch_generate` at [character_content_service.py:3530](backend/app/services/character_content_service.py#L3530). Existing gap-filling primitive, used by Phase 2's backlog filler.
- `CharacterContentService.ai_review_carousel` at [character_content_service.py:1723](backend/app/services/character_content_service.py#L1723). Stage 1 Ollama review, reused unchanged.
- `CharacterReferenceVideoService._analyze_discovery` and `promote_to_character`. Already extract `ProposedCharacter`; Phase 4 only adds the caller.
- `_log_scheduler_run` helper in scheduler_service. All 6 new jobs write observable audit rows for free.
- `StoryTemplateService` for hook-style hints in Phase 5.

## Migration 023 Summary

Single file, all columns added in one transaction:

```
ALTER TABLE characters
  ADD COLUMN autonomous_disabled boolean default false,
  ADD COLUMN priority_tier text default 'standard',
  ADD COLUMN discovery_source text,
  ADD COLUMN discovery_evidence jsonb,
  ADD COLUMN discovery_hits integer default 0;

ALTER TABLE character_carousels
  ADD COLUMN auto_approved boolean,
  ADD COLUMN auto_approved_at timestamptz,
  ADD COLUMN auto_approve_reason text;

CREATE TABLE llm_daily_spend (
  provider text,
  day date,
  spend_usd numeric default 0,
  primary key(provider, day)
);
```

## Phase Ordering

1. Phase 1 first. Stopping unnecessary MiniMax spend is the one irreversible harm. Deploy the default swap and budget cap before anything runs at higher frequency.
2. Phase 2 next. Unlocks the visible outcome (posts actually going out) with minimal new code. Just wires existing signals to the existing publisher.
3. Phase 3 third. Adds depth to existing characters. Compounding value, bounded scope.
4. Phase 4 fourth. Expands the roster. Highest operational risk due to external APIs and rate limits; deploying last means Phase 1-3 observability catches runaway creation.
5. Phase 5 last. Hook polish. Could ship before Phase 4 but grouping it last keeps cost surfaces contained until discovery is proven stable.

## Verification

End-to-end, after all phases deployed:

1. Rebuild backend: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
2. Verify migration: `docker exec zero-api alembic current` should show `023_character_autopilot`
3. Confirm new scheduler jobs running: `curl -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" http://localhost:18792/api/system/scheduler` and check for the 6 new job names.
4. Confirm MiniMax default swap: `GET /api/llm/tasks` should show `character_content_review_final` pointing at `ollama/gemma4:31b`.
5. Trigger discovery manually: `POST /api/characters/autopilot/trigger?job=character_discovery` and wait 60s. Check `SELECT name, discovery_source, discovery_evidence FROM characters WHERE discovery_source IS NOT NULL ORDER BY created_at DESC LIMIT 20`.
6. Trigger gap audit manually on one character: `POST /api/characters/{id}/audit_gaps`. Check returned gap dict and confirm new images, carousels, or facts appear within 60s.
7. Submit a carousel that scores >=85 on Stage 2. Within 30 min, `character_auto_approval` should flip it to `status='approved', auto_approved=true`.
8. Within 2 hours, `character_publish_backlog` should report `approved_queued_count >= 6` in logs.
9. Open the frontend at `/characters/autopilot`. KPI tiles should show nonzero numbers within 24 hours.
10. Flip global kill switch. Verify all 6 new jobs log `autopilot_disabled_skip` on next tick.
11. Monitor MiniMax spend daily: `SELECT * FROM llm_daily_spend WHERE provider='minimax' ORDER BY day DESC LIMIT 7`. Should remain below `character_minimax_daily_cap_usd` (default 2.0).
12. Register the Legion sprint for this work and create tasks per phase before implementation starts (per CLAUDE.md mandatory requirement, project_id=8).
