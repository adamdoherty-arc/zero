# Character Content System - Improvement Plan

**Updated**: 2026-04-17
**Current Grade**: 82/100 (B-)
**Target Grade**: 90/100 (A-)
**Status**: P1-P6 COMPLETED in prior session. Content generation scaled this session.

## Critical Path to 85/100

### Priority 1: Wire Stage 2 Final Review (Biggest Single Win, +15 points)

The system has fully-implemented Stage 2 final review (`_final_review_carousel` in character_content_service.py around line 2009, with correct Minimax/Kimi/Ollama fallback via `character_content_review_final` task). But 0/15 carousels have ever received Stage 2. The code path exists only from the explicit `/review` endpoint, and `generate_carousel` never triggers it.

**Fix**:
1. At the end of `generate_carousel`, auto-invoke `ai_review_carousel(carousel_id)` (which already chains into `_final_review_carousel` if overall >= 7).
2. Optionally gate by a config flag `ZERO_CHARACTER_AUTO_REVIEW=true`.
3. Set `ZERO_MINIMAX_API_KEY` in `.env` OR explicitly document that Kimi/Ollama fallback is the intended path. Either is fine, but make it deliberate.
4. Add a database constraint check or scheduled backfill job that re-runs Stage 2 on any carousel with `ai_review_score >= 7 AND final_review_score IS NULL`.

Impact: Content Generation 62 to 82 (+3.0 weighted), Learning 60 to 75 (+1.5 weighted). Net +4.5 points.

### Priority 2: Close the Template Feedback Loop (+4 points)

All 10 story templates have `avg_score = 0.0`. After the two-stage review is working, feed `final_review_score` back into `story_templates.avg_score`.

**Fix**:
1. In `_final_review_carousel` success path, `UPDATE story_templates SET avg_score = (avg_score * uses + final_review_score) / (uses + 1), uses = uses + 1 WHERE name = :template`.
2. Add a weekly scheduler job `character_template_ranker` that re-computes avg_score across the last 30 days of carousels (to prevent drift).
3. Surface template avg_score in the Inspiration tab so humans see the ranking.

Impact: Learning 60 to 75 (+1.5 weighted), Strategy 72 to 80 (+0.8 weighted). Net +2.3 points, plus compounds with Priority 1.

### Priority 3: Fix Bare-Exception Regression (+4 points)

57 bare `except Exception` across 7 character service files. This is a real risk: silent failures in generation, research, or publishing hide root causes.

**Fix** (per service, prioritized by size):
1. character_content_service.py (29 instances): replace with `except (ValidationError, HTTPException, asyncio.TimeoutError, SQLAlchemyError) as e:` where applicable, `raise` where unrecoverable. Add structured logging with `error=str(e), error_type=type(e).__name__`.
2. character_discovery_service.py (7): typically LLM timeouts or network errors. Narrow to `httpx.HTTPError`, `asyncio.TimeoutError`, `json.JSONDecodeError`.
3. character_reference_video_service.py (6): download errors, ffmpeg errors. Narrow to `subprocess.CalledProcessError`, `httpx.HTTPError`, `OSError`.
4. reference_video_service.py, character_hook_service.py, publishing_service.py, character_prompt_seeds.py: audit in remaining 15 instances.

Impact: Code Quality 58 to 78 (+2.0 weighted).

### Priority 4: Populate Research `result_summary` (+3 points)

Research steps complete but never write `result_summary`. Blind spot for debugging research quality.

**Fix**:
1. In research_service.py step handlers, write `result_summary` JSON with `{fragments_found, sources_used, duration_ms, new_facts_count}` on each step completion.
2. Add a scheduler job `character_research_health` that alerts when `result_summary IS NULL` for >1 hour on a `completed` step (indicates pipeline bug).
3. Show result_summary in the Research tab for each character.

Impact: Research Quality 55 to 70 (+2.25 weighted).

### Priority 5: Improve Research Coverage (+3 points)

15/24 characters pending research. The backlog isn't draining.

**Fix**:
1. Increase `character_research_refresh` job frequency from 15 min to 5 min OR increase concurrency from 1 to 3.
2. Add a gap-audit scheduler job output surface: show "N characters with <20 facts" prominently on CharacterContentPage.
3. Re-process characters with 0 facts marked `completed` (pipeline bug - they should be re-queued).

Impact: Research Quality 55 to 70 (+2.25 weighted, overlaps with P4).

### Priority 6: Add Error UX to CharacterAutopilotPage (+2 points)

New 683-LOC page has 0 aria-labels and 0 InlineError usages. Feels inconsistent with the main page (46 aria-labels, 10 InlineError).

**Fix**:
1. Wrap all React Query hooks with `<InlineError>` component for error state.
2. Add aria-labels to action buttons (Approve, Reject, Run Now, Pause).
3. Add loading skeletons where missing.

Impact: UI/UX 78 to 85 (+1.05 weighted).

### Priority 7: Modularize character_content_service.py (+2 points)

4,653 LOC is too large. 14 functions over 80 lines. 5 over 140.

**Fix** (phased, low-risk):
1. Extract Stage 1+2 review into `character_review_service.py` (roughly 400 LOC).
2. Extract carousel generation into `character_carousel_service.py` (roughly 800 LOC).
3. Extract publishing helpers into existing `publishing_service.py`.
4. Keep enhance_character and research orchestration in main service.
5. Target: main service <2,000 LOC, no function over 120 lines.

Impact: Code Quality 58 to 78 (+2.0 weighted, overlaps with P3).

## Stretch Goals to 95/100

### Real Publishing (10 points) - High Value, High Effort

Current state: `publish_carousel` renders PNGs locally and marks `published` without any upload. Android share flow is the only real path.

Needed:
- TikTok Business API integration (the infra exists at `tiktok_api_client.py`, just not wired to character content).
- Post-publish engagement sync (views/likes/comments to 24h, 7d windows).
- Close the outcome learning loop via `record_outcome_by_source`.

Effort: Significant. 8-15 hours. Worth it.

### Multi-Character & Series Content (3 points)

Endpoints exist but 0 usage. Build UI to compose multi-char carousels and series threads.

### A/B Caption Testing (2 points)

`generate_caption_variants` produces variants but none are ranked or tested. Add `caption_outcomes` table and pick winners after 48h.

### Priority 8: Thread hook_style + story_template through the scheduler (+1.5 points)

Verified 2026-04-17 22:21-22:26: `character_content_generation` job auto-generates 10 carousels every 4h, 0 failures. But `_run_character_content_generation` only passes `angle` to `generate_carousel`. Auto-generated carousels land with `story_template=null` and `generation_metadata.hook_style=null`, which breaks hook-style performance tracking (7 styles) and template ranking for ~80% of future carousels.

**Fix**:
1. In `_run_character_content_generation` ([scheduler_service.py:2470-2518](backend/app/services/scheduler_service.py#L2470-L2518)), rotate `story_template` (15 options) and `hook_style` (7 options) alongside `angle`, picked by `(generated + hash(char.id)) % N` for determinism.
2. On the service side in `generate_carousel`, ensure `hook_style` arg lands in `generation_metadata.hook_style` on save. Today the endpoint accepts the param but the service doesn't persist it (known bug surfaced in EVOLUTION_LOG).
3. Add unit test: scheduler-generated carousel has non-null `story_template` and `generation_metadata.hook_style`.

Impact: Learning 82 -> 90 (+0.8 weighted), Strategy 85 -> 88 (+0.3 weighted). Unblocks PromptBreeder hook/template evolution for the dominant carousel source.

## Summary Table

| Priority | Item                                 | Points | Hours |
|----------|--------------------------------------|--------|-------|
| 1        | Wire Stage 2 Final Review            | +4.5   | 2-3   |
| 2        | Template Feedback Loop               | +2.3   | 2-3   |
| 3        | Fix Bare Exceptions (57 -> <10)      | +2.0   | 4-6   |
| 4        | Populate result_summary              | +2.25  | 2     |
| 5        | Research Coverage                    | +2.25  | 2     |
| 6        | Autopilot Page Error UX              | +1.05  | 1-2   |
| 7        | Modularize service file              | +2.0   | 4-6   |
| 8        | Thread hook_style + template in scheduler | +1.5 | 1-2 |
| **Total Path to 85/100**             |        | **17.75** | **18-26h** |

Stretch to 95:
- Real TikTok publishing: +10 points, 8-15h
- Multi-char / series UI: +3 points, 4-6h
- A/B caption testing: +2 points, 2-3h

## Why the Regression From 92 Was Expected

Previous review scored a small, stable system. Since then:
- Service file doubled (2,100 to 4,653 LOC)
- Endpoints grew 50% (48 to 72)
- Jobs grew 160% (5 to 13)
- Two new subsystems added (Autopilot, Reference Videos)
- Prior claims of "0 bare excepts" and "two-stage review active" did not match production data; they reflected either aspirational targets or a brief clean window

This review resets the baseline to actual observed behavior. The system's capability surface grew; its discipline did not keep pace. Priorities 1-5 restore discipline; 6-7 polish new surfaces.
