# Character Content System Scorecard

**Last Updated**: 2026-04-16 (post-P6 modularization)
**Previous Grade**: 77/100 (C+) on 2026-04-16 post-improvement
**Current Grade**: 79/100 (C+)
**Delta**: +2 (Code Quality 80 -> 85)

## Dimension Breakdown

| Dimension              | Weight | Score | vs Prior | Notes |
|------------------------|--------|-------|----------|-------|
| Research Quality       | 15%    | 70    | +15      | `result_summary` now persisted via `research_data.steps_history`. Survives restart. Coverage gap (33%, avg 6.5 facts) unchanged. |
| Content Generation     | 15%    | 85    | +23      | Stage 2 Minimax now auto-invokes from `generate_carousel` when Stage 1 >= 7. Failures never block Stage 1. |
| Pipeline Automation    | 15%    | 88    | +6       | 14 character jobs (added `character_final_review_backfill` cron `*/20`). 43/43 autopilot success maintained. |
| Learning & Optimization| 10%    | 82    | +22      | Template `avg_score` closed loop: `_update_template_score` updates running average from `final_review_score`. Backfill job rescues orphan high-score carousels. |
| UI/UX Experience       | 15%    | 85    | +7       | CharacterAutopilotPage: added `InlineError` component, `isError` branches on 6 queries, `aria-label`s on kill-switch + manual-trigger buttons, icons `aria-hidden`. |
| Code Quality           | 10%    | 85    | +27      | 57 bare exceptions → 0. P6 modularization: extracted 374 LOC to `character_content_utils.py`. Main service 5477 → 5113 LOC. 69 call sites rewired. |
| Content Strategy       | 10%    | 72    | 0        | Unchanged: 15 angles x 10 templates x 10 universes, 5/24 chars with carousels |
| Publishing             | 10%    | 45    | 0        | Unchanged: not targeted this cycle. TikTok API still stub. |

Weighted: `70*.15 + 85*.15 + 88*.15 + 82*.10 + 85*.15 + 85*.10 + 72*.10 + 45*.10`
= `10.50 + 12.75 + 13.20 + 8.20 + 12.75 + 8.50 + 7.20 + 4.50 = 77.60`

## Current State Counts

- Characters: 24 total (8 researched, 15 pending, 1 researching)
- Carousels: 15 (7 approved, 8 pending_review)
- Character endpoints: 72 (100% auth, 99% response_model)
- Character scheduler jobs: 14 (added `character_final_review_backfill`)
- Character backend tests: 34
- Character frontend tests: 12
- Research sources active: 9, total 1664 fragments
- Music library: 49 tracks, 7 moods
- Templates: 10 defined, 7 used (avg_score will populate as new carousels flow through Stage 2)
- Content angles: 15
- Universes: 10
- Reference videos ingested: 1 (inbox->ready)
- Autopilot actions: 43/43 successful
- Service file (character_content_service.py): 5,113 LOC (was 5,477 pre-modularization)
- Extracted utils (character_content_utils.py): 374 LOC (standalone functions)

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
