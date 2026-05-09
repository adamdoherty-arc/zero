# Persist Research Queue Progress Across Restarts

## Context

The research queue processes 20-90 characters through a 7-step pipeline (web search, wiki, deep sources, synthesis, fact extraction, image sourcing, save). When the container restarts, all queue state is lost because it lives in a global `_research_queue` dict in memory. Characters mid-research get stuck in "researching" status and must be manually restarted. The existing auto-resume in `main.py:144-169` resets stuck characters to "pending" and restarts the queue, but loses queue order and per-step progress, causing expensive steps (LLM synthesis, fact extraction) to re-run unnecessarily.

**Partial skip logic already exists**: Steps 4 (synthesis) and 5 (fact extraction) check if `research_data.bio` and `fact_bank` exist in the DB and skip if so. But steps 1-3 always re-run even when their output (synthesis) already exists, and step 6 (image sourcing) always re-runs even when images are already saved.

## Approach

Enhance the existing `characters` table with a `research_completed_steps` JSONB column to track per-step completion, and add a lightweight `research_queue_state` table to persist queue membership/order. On startup, rebuild the in-memory queue from DB state and skip already-completed steps.

## Changes

### 1. Migration: `backend/app/migrations/versions/029_research_queue_persistence.py`

New migration adding:
- `research_queue_state` table: `id` (serial PK), `character_id` (varchar, unique), `queue_position` (int), `job_id` (varchar), `queued_at` (timestamptz)
- `characters.research_completed_steps` column: JSONB, default `'[]'`

### 2. DB Model: `backend/app/db/models.py`

- Add `ResearchQueueStateModel` class (~line 1845, after `CharacterResearchStepStatModel`)
- Add `research_completed_steps` column to `CharacterModel` (~line 1593)

### 3. Service: `backend/app/services/character_content_service.py`

**3a. Persist queue on start** (~line 3082, after building jobs):
- After populating `_research_queue["jobs"]` and `["order"]`, INSERT rows into `research_queue_state`
- Clear any stale rows first

**3b. Remove from queue on completion** (in `_run_research_queue`, ~line 3230):
- After each job finishes (completed or failed), DELETE its `research_queue_state` row

**3c. Track step completion in DB** (in `_update_step`, ~line 3305):
- When a step status becomes "completed", fire-and-forget append the step name to `character.research_completed_steps`

**3d. Skip already-completed steps** (in `_research_pipeline_tracked`, ~line 3330):
- At pipeline start, read `research_completed_steps` from DB
- If synthesis is in completed steps, skip steps 1-3 entirely (their output only feeds synthesis)
- Steps 4-5 already have skip logic via `research_data`/`fact_bank` checks; no change needed
- If image_sourcing is in completed steps AND images exist in DB, skip step 6

**3e. Reset completed_steps on fresh start** (in `start_batch_research_async`, ~line 3030):
- When resetting stuck characters to "pending", also clear `research_completed_steps = []`

**3f. Clear queue state on cancel** (in `cancel_research_queue`, ~line 3089):
- DELETE all `research_queue_state` rows for un-started jobs

### 4. Startup: `backend/app/main.py` (~line 144)

Replace the existing crude auto-resume logic with:
- Query `research_queue_state` ordered by `queue_position`
- If rows exist, rebuild `_research_queue` in-memory from DB state
- For each queued character, read `research_completed_steps` to set step statuses (completed vs pending)
- Launch `_run_research_queue()` as background task
- If NO queue rows exist, fall back to existing behavior (reset stuck chars, count pending)

### 5. Pydantic model: `backend/app/models/character_content.py`

- No changes needed; `ResearchJob` and `ResearchJobStep` already have all needed fields

## Key Files

| File | Action |
|------|--------|
| [029_research_queue_persistence.py](backend/app/migrations/versions/029_research_queue_persistence.py) | CREATE - migration |
| [models.py](backend/app/db/models.py) | EDIT - add model + column |
| [character_content_service.py](backend/app/services/character_content_service.py) | EDIT - persist/load/skip logic |
| [main.py](backend/app/main.py) | EDIT - smarter auto-resume |

## Verification

1. Start research queue with 5+ characters, let 2 complete
2. `docker compose -f docker-compose.sprint.yml restart zero-api`
3. Check UI: queue should auto-resume with remaining characters, completed ones stay completed
4. Verify completed characters don't re-run any steps
5. Check DB: `SELECT * FROM research_queue_state` should show only remaining jobs
6. Check DB: `SELECT research_completed_steps FROM characters WHERE research_status = 'completed'` should show all 7 steps
