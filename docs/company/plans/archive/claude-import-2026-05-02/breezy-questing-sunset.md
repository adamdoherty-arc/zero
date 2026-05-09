# Wire TV Shows + Movies into the Auto-Generation Pipeline

## Context

The character content system has a fully automated loop: `character_auto_research` (every 2h) kicks off research, `character_content_generation` (every 4h) generates carousels, `character_auto_approval` approves, `character_auto_publish` schedules posting. This was verified end-to-end during this session — 10 carousels auto-generated in 4.5 min, 0 failures.

The **Media Content** subsystem (TV shows + movies) is a parallel entity model with its own router (`/api/media-content/*`), service, DB tables, and research pipeline. The user added 55 movies via the UI (Characters page → Movies tab at `localhost:5173/characters?tab=movies`). All 55 are `research_status=pending` with 0 facts and 0 carousels, because **the scheduler has zero jobs for the Media subsystem**. The 4-stage character pipeline does not apply to TV/movies.

Intended outcome: add two scheduler jobs so added titles flow automatically through research → carousel generation, matching the character pattern. The user instruction was "make sure we are accounting for this now."

## Approach

Two new scheduler jobs, implemented inside `backend/app/services/scheduler_service.py` (the existing pattern for character automation is self-contained in this file — no new modules or files needed).

### Files modified

- `backend/app/services/scheduler_service.py` — three edits:
  1. Add two config entries after `character_final_review_backfill` (around line 506).
  2. Add two handler registrations in the dispatcher dict after `character_final_review_backfill` (around line 845).
  3. Add two handler implementations after `_run_character_auto_research` (around line 2820), in a new `# MEDIA CONTENT AUTOMATION` section.

### Existing functions reused

- `app.services.media_content_service.get_media_content_service` — singleton accessor.
- `MediaContentService.list_media_titles(research_status=..., limit=...)` — at `backend/app/services/media_content_service.py:170`.
- `MediaContentService.research_media_title(media_title_id)` — at `backend/app/services/media_content_service.py:366`. Single-title synchronous research; 7 sources (SearXNG, Wikipedia, Fandom, Reddit, TV Tropes, IMDB, TMDB) via `media_research_sources.py`.
- `MediaContentService.generate_carousel(MediaCarouselCreate)` — at `backend/app/services/media_content_service.py:517`. Mirrors character `generate_carousel` but uses `MediaContentAngle` enum (16 values).
- `MediaCarouselCreate`, `MediaContentAngle` — from `app.models.media_content`.

### Job configs

| Job | Cron | Semantics |
|-----|------|-----------|
| `media_auto_research` | `*/15 * * * *` (every 15 min) | Pulls up to 3 `research_status=pending` titles, calls `research_media_title` on each. 55 titles / 3 per run = 18 runs ≈ 4.5h to drain the backlog — slower than characters (which use an in-memory queue with concurrency) but avoids fighting the character research queue for Ollama. |
| `media_content_generation` | `30 */4 * * *` (offset 30 min from `character_content_generation`) | Pulls up to 100 researched titles, sorts by `carousels_created` ascending (underserved-first), generates up to 10 carousels per run. Rotates `MediaContentAngle` deterministically via `(generated + hash(title.id)) % len(angles)`, same pattern as `_run_character_content_generation` at `scheduler_service.py:2496`. |

### Error handling

Both handlers use narrow exception tuples `(ValueError, RuntimeError, KeyError, AttributeError, TypeError)` on per-item failures so a single bad title does not kill the batch. The outer try/except catches anything else and logs `media_auto_research_failed` / `media_content_generation_failed` without propagating — matches how character handlers behave. Both handlers check `self._autopilot_disabled(job_name)` so the kill-switch honored by character jobs also applies here.

### What is deliberately *not* included (noted for later)

- **Stage 2 review + auto-approval for media carousels**: media carousels are saved to the same `CharacterCarousel` table, so `character_final_review_backfill` already covers them. `character_auto_approval` also reads from this table, so it covers media carousels too. No extra jobs needed.
- **Publishing**: `character_auto_publish` and `character_publish_backlog` read approved carousels from the shared table. Same coverage applies.
- **Hook/template rotation**: same gap as `character_content_generation` — only `angle` is passed. This is logged as P8 in IMPROVEMENT_PLAN.md and applies to media too.

## Status (as of this plan)

Code changes landed, container rebuilt with `docker compose -f docker-compose.sprint.yml build --no-cache zero-api` and started. Verification started but plan mode activated mid-verification:

- `scheduler_started` log confirms `media_auto_research` (cron `*/15 * * * *`) and `media_content_generation` (cron `30 */4 * * *`) are registered.
- `/api/system/scheduler/status` shows `next_run=2026-04-17T23:00:00Z` for `media_auto_research` and `next_run=2026-04-18T00:30:00Z` for `media_content_generation`.
- First scheduled fire already happened at 22:45:00 UTC. `media_auto_research_item_done` emitted for `Dune: Part Three` (22:45:45) and `Avengers: Endgame` (22:46:24).
- Pending count is dropping from 55.

## Verification (remaining)

1. Wait for first `media_auto_research_done` log line showing `researched=3, failed=0` (3 per run cap).
2. Trigger `media_content_generation` manually once at least one title is in `research_status=completed`:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     http://localhost:18792/api/system/scheduler/jobs/media_content_generation/trigger
   ```
   Expect `generated=N, failed=0` and carousel rows appearing via `GET /api/media-content/carousels`.
3. Confirm `MediaTitle.carousels_created` increments for the generated titles.
4. Leave the natural 15-min cron alone for 1 hour to confirm three auto-research ticks land an additional ~9 researched titles without manual intervention.
5. Update `.claude/skills/zero-character-content/knowledge/SCORECARD.md` to reflect that TV/movies are now part of the automated pipeline (bump Pipeline Automation 91 → 94).

## Why this approach over alternatives

- Considered: unify media into the character system. Rejected — different schema (`MediaTitle` vs `Character`), different research sources (TMDB, episode data), different angles (16 media-specific vs 17 character). Forcing unification would require a migration and loses domain fidelity.
- Considered: batch-research all 55 synchronously via `POST /api/media-content/batch-research`. Rejected as the primary fix — a one-shot manual call doesn't solve the structural gap for future additions. It's fine as a backfill accelerator if the user later wants to skip the 4.5h drain, but not required.
