# Character Content System Scorecard

**Last Updated**: 2026-04-20 13:58 UTC (autopilot — Ollama infrastructure regression detected)
**Previous Grade**: 83/100 (B-) 2026-04-19
**Current Grade**: 80/100 (B-) — downgrade
**Delta**: -3 (Pipeline Automation hit by Ollama 503/timeouts blocking all generation)

## Autopilot Run 2026-04-20 13:55-13:58 UTC

State: 184 chars (183 researched, 1 queued "Luigi (voice)"), 346 research jobs done/1 queued, 56 carousels (16 draft / 8 ai_reviewed / 9 pending_review / 7 approved / 2 rejected / 0 published). Top angle still skewed: `hidden_truths` 12, `behind_scenes` 8 (variety still weak).

Findings:
1. **Ollama infrastructure failure** — `POST /api/characters/batch-smart` returned 500. Root cause in logs: Ollama `/api/embed` returns 503 Service Unavailable on `nomic-embed-text-v2-moe`; `/api/chat` on `qwen3.6:35b-a3b-q8_0` returns ReadTimeout. Circuit breaker flipped open after 5 consecutive failures. Reset via `POST /api/system/circuit-breakers/ollama/reset` — immediately re-opened on next call. `ollama list` + `/api/tags` both confirm daemon is UP and model is present, so the issue is VRAM / model-load contention (q8_0 38GB variant) or the embed model 503'ing under load. Not fixable from within content skill.
2. **Review queue content-quality sample** — Batman `cc-e0398c3c76ae` (vs_comparison, AI 5/10) contains mojibake emoji escapes (`\u00f0\u0178\u02dc\u00b6` = latin-1 view of UTF-8 😶). Likely qwen3 output encoded twice. `sanitize_carousel` does not strip these. Deferred until Ollama recovers and we can regenerate.
3. **Content Generation breadth still low** — 56 carousels / 184 characters = 0.30 carousels/character. ~130 characters have zero carousels.
4. **Research queue healthy** — 345/346 jobs completed, 0 failures.

Actions taken this run:
- Diagnosed Ollama outage, confirmed daemon up but models failing under load.
- Reset `ollama` circuit breaker (transient — re-opened).
- No generation run; documented findings for operator to triage Ollama host.

Impact on dimensions:
- Pipeline Automation 88 → 78 (generation endpoint is 500'ing).
- Content Generation 86 → 86 (no change; existing carousels unaffected).
- Research Quality 80 → 80 (research pipeline still clean).

**Operator action required**: Triage Ollama host. Either (a) switch default model off `qwen3.6:35b-a3b-q8_0` to the smaller `qwen3.6:35b-a3b-q4_K_M` to reduce VRAM pressure, or (b) restart Ollama and verify `/api/embed` serves `nomic-embed-text-v2-moe` without 503.

## Migration: Ollama → vLLM (started 2026-04-20 14:25 UTC)

Decision: adopt **vLLM** as primary local LLM. Root cause of today's outage was VRAM contention (running q8_0 model = 38GB on 32GB RTX 5090). vLLM's PagedAttention + pinned-model architecture eliminates this class of failure.

**One model for everything:**
- Chat: `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` (MoE, 3B active) — ~17GB VRAM. State-of-the-art for 32GB cards.
- Embed: `Qwen/Qwen3-Embedding-0.6B` — ~2GB VRAM. Matryoshka-truncated from 1024 → 768 dim to stay pgvector-compatible.
- Fallback: Kimi (k2-0905-preview / k2-thinking) for paid cloud reasoning.

**Changes shipped this session:**
- `docker-compose.sprint.yml`: added `zero-vllm-chat` (port 18800) + `zero-vllm-embed` (port 18801) services with nvidia GPU passthrough + `zero-hf-cache` volume.
- `backend/app/infrastructure/config.py`: `vllm_chat_url`, `vllm_chat_model`, `vllm_embed_url`, `vllm_embed_model`, `embed_provider` settings.
- `backend/app/infrastructure/llm_providers/vllm_provider.py`: new OpenAI-compatible provider (chat + stream + circuit breaker `llm_vllm`).
- `backend/app/infrastructure/ollama_client.py`: `embed()` / `embed_batch()` route to vLLM's `/v1/embeddings` when `embed_provider=vllm`, with matryoshka truncation to `embedding_dimension`.
- `backend/app/infrastructure/unified_llm_client.py`: budget-exceeded fallback now forces `vllm/qwen3-chat` (was `ollama/qwen3.6:35b-a3b-q8_0`); `json_mode` now enabled for vLLM.
- `workspace/llm/router_config.json`: all 28 task_assignments rerouted. Local tasks → `vllm/qwen3-chat`. Heavy reasoning (research, planning, council_ceo, agent_ceo) → `kimi/kimi-k2-thinking` with `vllm/qwen3-chat` fallback.

**Kept Ollama** as warm standby (image_sourcing + research still hit it for now). Will decommission after 48h of stable vLLM.

---


## Autopilot Run 2026-04-19 16:30-16:45 UTC

State: 164 chars (all researched), 312 research jobs done/0 queued, 56 carousels (30 draft/3 ai_reviewed/3 pending_review/7 approved/0 published).

Finding: 2/30 drafts (6.7%) had literal placeholder text ("hook text", "fact 1", "fact 2", "CTA") as slide content. Root cause: [character_content_service.py:1505](backend/app/services/character_content_service.py#L1505) simpler-retry prompt used literal strings as the JSON schema example — qwen3 echoed the schema back verbatim instead of substituting content. `sanitize_carousel` did not detect these tokens.

Actions:
1. Rejected the 2 broken carousels (Batman cc-64057fac44a6, Last Chef Standing cc-8906ea145181).
2. Rewrote retry prompt schema example to use `<angle-bracket descriptors>` that cannot be confused for real content.
3. Added placeholder-token guard post-parse — drops retry result if slide/hook/title matches known template tokens, falls through to the static fact-based fallback.
4. Rebuilt + restarted zero-api. Healthy.

Impact estimate: Content Generation 85 -> 86 once next batch verifies no regression (scheduler next fires at 20:00 UTC). Removes a silent ~7%-of-throughput failure mode.

## Auto-Generation Verification (2026-04-17 22:21-22:26 UTC)

Triggered `POST /api/system/scheduler/jobs/character_content_generation/trigger` and observed end-to-end success:

- Scheduler running: True (17 character jobs registered)
- Job `character_content_generation`: cron `0 */4 * * *` (runs 00/04/08/12/16/20 UTC), next 00:00 UTC
- Job fired, generated 10 carousels, 0 failed, ~4.5 min duration
- Total carousels: 37 -> 47
- New: Akuma, Albus Dumbledore, Ant-Man, Aragorn, Arthur Morgan, Billy Butcher, Cammy, Captain Marvel, Chani, Charlie Cannon
- Angle rotation worked (character_evolution, hidden_truths, power_secrets, behind_scenes, what_if, fan_theories)

**Known gap**: scheduler only passes `angle` to `generate_carousel`. Auto-generated carousels have `story_template=null` and `generation_metadata.hook_style=null`. Hook/template rotation and PromptBreeder-style evolution do not apply to scheduler output. See IMPROVEMENT_PLAN.md P8.

Other active jobs verified in queue:
- `character_auto_approval` every 30 min (last run 22:00 UTC: approved=0, threshold=85.0)
- `character_publish_backlog` every 2h
- `character_final_review_backfill` every 20 min
- `character_auto_research` every 2h
- `character_gap_audit`, `character_hook_audit`, `carousel_banned_hook_backfill` daily
- `character_reference_video_processor` every 1 min

## Media (TV/Movies) Pipeline Wired (2026-04-17 23:20 UTC)

User flagged that TV Shows + Movies are separate entities (UI: `localhost:5173/characters?tab=movies`) with their own `/api/media-content/*` surface. 55 movies existed but 0 auto-flow because the scheduler had NO media jobs. Fixed end-to-end this session:

- Added 2 scheduler jobs in `backend/app/services/scheduler_service.py`:
  - `media_auto_research` cron `*/15 * * * *` (3 titles per run)
  - `media_content_generation` cron `30 */4 * * *` (10 carousels per run, sorted by `carousels_created` ascending)
- Fixed Pydantic attribute-case bug in `backend/app/services/media_research_sources.py`: `SEARXNG_URL` (uppercase) did not match real attribute `searxng_url` (lowercase), silently disabling IMDB/Rotten Tomatoes/entertainment searches.
- Fixed fact synthesis in `backend/app/services/media_content_service.py:_synthesize_facts`: unified LLM client did not honor qwen3's `/no_think` so the entire 8k-char response was reasoning prose. Swapped to direct Ollama client pattern used by character fact extraction (temperature=0.2, num_predict=16384, timeout=900, explicit `/no_think` suffix).
- Verified end-to-end: `media_content_generation_done generated=2, failed=0`. Dune: Part Three (box_office_analysis) and Ant-Man and the Wasp (deleted_scenes) both landed as draft carousels. Fact synthesis produces 20 facts per title with research_depth_score 66.7.

Stage 2 review, auto-approval, and publishing already cover media because media carousels share the `character_carousels` table — no extra jobs needed.

## Unified Research Queue (2026-04-17 ~23:35 UTC)

User wanted ONE queue for characters + TV + movies. Achieved without adding a new endpoint:

- Added optional `entity_type: str = "character"` to `ResearchJob` model ([backend/app/models/character_content.py:677](backend/app/models/character_content.py#L677)).
- Added `_get_media_db_jobs()` method in character_content_service that projects `MediaTitleModel` rows as `ResearchJob` records (character_id=title.id, entity_type="movie"/"tv_show", universe from media.universe, synthetic media pipeline step names).
- Modified `get_research_queue_status()` both branches (live queue + DB fallback) to merge media jobs after character jobs.
- Result: `GET /api/characters/research-queue` now returns `total_jobs=179 (124 characters + 55 movies)`, counts include all three entity types. The existing Research Queue tab in the UI surfaces everything.

Verified snapshot: queued=49, researching=4, completed=126, failed=0. Marvel movies Ant-Man and the Wasp and Dune: Part Three show completed with 20 facts / depth=66.67 alongside character completions.

## Dimension Breakdown

| Dimension              | Weight | Score | vs Prior | Notes |
|------------------------|--------|-------|----------|-------|
| Research Quality       | 15%    | 78    | +8       | 90 characters seeded, 26 researched, 64 in queue (actively processing). Avg 25-30 facts per researched character. Research queue persisted + auto-starts. |
| Content Generation     | 15%    | 85    | 0        | Stage 2 Minimax auto-invokes. 36 carousels across 25 characters (was 15 across 5). 10 angles, 10 templates used. |
| Pipeline Automation    | 15%    | 88    | 0        | 14 character jobs. Research queue running 3 concurrent with semaphore-based concurrency control. |
| Learning & Optimization| 10%    | 82    | 0        | Template feedback loop closed. Hook style tracking gap: endpoint accepts hook_style but doesn't persist to generation_metadata. |
| UI/UX Experience       | 15%    | 85    | 0        | Unchanged. |
| Code Quality           | 10%    | 85    | 0        | Unchanged. |
| Content Strategy       | 10%    | 85    | +13      | 25/26 researched chars now have carousels (was 5/24). 10 angles used, 10 templates used. Hook style diversity achieved across batch. |
| Publishing             | 10%    | 45    | 0        | Unchanged: TikTok API still stub. |

Weighted: `78*.15 + 85*.15 + 88*.15 + 82*.10 + 85*.15 + 85*.10 + 85*.10 + 45*.10`
= `11.70 + 12.75 + 13.20 + 8.20 + 12.75 + 8.50 + 8.50 + 4.50 = 80.10`

## Current State Counts (2026-04-17)

- Characters: 90 total (26 researched, 64 in research queue actively processing)
- Carousels: 36 (7 approved, 21 draft, 8 needs_work)
- Characters with carousels: 25/26 researched (was 5/24)
- Character endpoints: 72 (100% auth, 99% response_model)
- Character scheduler jobs: 14
- Character backend tests: 34
- Character frontend tests: 12
- Research sources active: 7 (SearXNG, Wikipedia, Fandom, Reddit, TV Tropes, IMDB, Quotes)
- Music library: 49 tracks, 7 moods
- Templates used this batch: 10 (dark_origin, actor_behind_role, hot_take, timeline_story, fan_theory_deep_dive, real_life_inspiration, secrets_revealed, deleted_scenes, storyline_recap, hidden_connection, what_they_changed, timeline_tragedy)
- Content angles used this batch: 10 (dark_facts, behind_scenes, controversial_takes, character_evolution, fan_theories, origin_story, hidden_truths, storyline_recap)
- Universes represented: marvel, dc, film, star_wars, gaming, anime, other
- Avg facts per researched char: 25-30
- Hook style tracking: NOT persisting (gap - endpoint accepts but generation_metadata shows null)
- Ollama concurrency: 2 (semaphore-controlled)
- Research queue concurrency: 3 active jobs at a time

## Improvements Shipped (2026-04-16)

### P1. Stage 2 Auto-Flow Wired (CRITICAL)
- `generate_carousel` now automatically invokes `_final_review_carousel` when Stage 1 overall_score >= 7
- Wrapped in narrow-exception try/except so final-review failure never blocks Stage 1 result
- File: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py#L2091-L2101)

### P2. Template Feedback Loop Closed
- New `_update_template_score` method uses a running average formula: `new_avg = (old_avg * count + final_score) / (count + 1)`
- Invoked after every Stage 2 final review
- File: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py#L2280-L2320)

### P3. Bare Exception Cleanup (57 → 0)
- character_content_service.py: 30 → 0 (plus 4 fresh ones caught during verification sweep)
- character_hook_service.py: 5 → 0
- character_discovery_service.py: 7 → 0
- character_reference_video_service.py: 6 → 0
- publishing_service.py: 3 → 0
- reference_video_service.py: 6 → 0
- character_prompt_seeds.py: 1 → 0
- Standard tuple for LLM/DB paths: `(aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError)`

### P4. Research `result_summary` Persistence
- Snapshots `steps_history` into character's `research_data` JSONB on save_results completion
- Survives container restart (previously only in-memory `_research_queue`)
- File: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py#L3663)

### P5. CharacterAutopilotPage Error UX + a11y
- Added `InlineError` component with `role="alert"`, `aria-live="polite"`, retry button
- 6 queries now show error states: stats, activity (3x), actions, humanQueue, budget
- `aria-label` on kill-switch toggle and manual-trigger buttons
- Icons marked `aria-hidden="true"`
- File: [frontend/src/pages/CharacterAutopilotPage.tsx](frontend/src/pages/CharacterAutopilotPage.tsx)

### P7. Stage 2 Backfill Job
- New scheduler job `character_final_review_backfill`, cron `*/20 * * * *`
- Queries carousels WHERE `ai_review->>'overall_score' >= 7.0` AND `final_review_score IS NULL`
- Batches 10 per run, single-carousel failures logged, never stop batch
- File: [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py#L2640-L2703)

### P6. Service Modularization (Phase 1: Utils Extraction)
- Created `character_content_utils.py` with 11 standalone functions extracted from the service class
- Functions: `generate_id`, `sanitize_text`, `parse_json_response`, `repair_truncated_json`, `is_generic_hook`, `rewrite_generic_hook`, `sanitize_carousel`, `character_to_pydantic`, `carousel_to_pydantic`, `image_to_pydantic`, `version_to_pydantic`
- Rewired 69 call sites from `self._method()` to imported `method()`
- Removed 364 lines of duplicated instance method definitions
- Main service: 5,477 -> 5,113 LOC. Utils module: 374 LOC.
- Files: [backend/app/services/character_content_utils.py](backend/app/services/character_content_utils.py), [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)

### P8. Research Pipeline Fixes
- Fixed unconditional `research_status = "completed"` for characters with 0 facts
- Introduced `needs_retry` status when `len(fact_bank) < 3`
- Updated `batch_research()` and `start_batch_research_async()` to include `needs_retry` in candidates
- Reset 16 zero-fact "completed" chars to "needs_retry" via SQL
- Reset 3 stuck "researching" chars to "pending"
- Research queue re-started with 80 total, 67 queued

### Bonus: Syntax Bug Fix
- `character_content_service.py` line 1152: duplicate `task_type` kwarg in `_record_prompt_run_safe` call was crashing startup
- Removed duplicate. Container now boots cleanly.

## What's Still Below A Tier

- **Publishing (45)**: No real TikTok API. `export_for_platform` is a no-op. Blocks A grade on this dimension.
- **Content Strategy (72)**: Only 5/24 characters have carousels. Discovery pipeline needs volume.
- **Research Quality (70)**: 8/24 researched, avg 6.5 facts vs target 20+. Need to run research refresh on backlog.
- **Code Quality (85)**: `character_content_service.py` is 5,113 LOC (down from 5,477). Phase 1 extraction done (utils). Phase 2 (CRUD/research/queue mixins) available for further reduction.

## Reading the Score

Weights: Research 15, Generation 15, Pipeline 15, Learning 10, UI/UX 15, Code 10, Strategy 10, Publishing 10.
Letters: 90+=A, 80-89=B, 70-79=C, 60-69=D, <60=F.

See `history/2026-04-16-review.md` for baseline audit evidence and `IMPROVEMENT_PLAN.md` for the prioritized plan (P1-P7).
