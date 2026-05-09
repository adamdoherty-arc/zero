# Character Research Queue: Smart Batching + Step Stats + ETA + Qwen-Coder

## Context

The Research Queue UI shows 34 characters (24 done, 1 running, 9 queued) with Charlie Cannon "stuck" on AI Synthesis for 3m 5s. Two problems:

1. **User expected batch processing, but only 1 character runs at a time.** Code at [backend/app/services/character_content_service.py:2806](backend/app/services/character_content_service.py#L2806) sets `BATCH_SIZE = 1` with comment "Process one at a time to avoid Ollama contention". The infrastructure already uses `asyncio.gather()` (line 2868) so the throttle is the only blocker.
2. **Charlie isn't necessarily stuck.** Synthesis and fact-extraction both call Ollama `qwen3.5:35b-a3b` with a 900s timeout. The "stuck" badge fires at 120s, but these slow steps routinely exceed that. The user has no ETA or step-duration stats to know what's normal.
3. **Model swap requested.** Synthesize + fact-extract should move from `qwen3.5:35b-a3b` → `qwen3-coder-next:latest` (already pulled locally, 51 GB). Coder models are better at the structured-JSON output these prompts demand.

Goal: smart batching (parallelize cheap I/O steps across up to 3 characters, but serialize the Ollama LLM step), persist per-step timings for every completed job, compute running averages, and surface real ETA on the queue + each card. Swap the LLM constant while we're in there.

## Design Summary

### 1. Swap LLM constant
- [backend/app/services/character_content_service.py:122](backend/app/services/character_content_service.py#L122): `RESEARCH_LLM_MODEL = "qwen3.5:35b-a3b"` → `"qwen3-coder-next:latest"`
- Used in 11 call sites (synthesis, fact extraction, and 6 other prompts). Single constant change covers all.
- Do NOT change [backend/app/infrastructure/config.py:25](backend/app/infrastructure/config.py#L25) `ollama_model` default. That's the generic default used elsewhere.

### 2. Parallelize the three "cheap" I/O steps inside each character
The current pipeline awaits sequentially at [character_content_service.py:2910-2961](backend/app/services/character_content_service.py#L2910-L2961):
- searxng_search (5 parallel web searches)
- wiki_scrape (Wikipedia REST)
- deep_research (Firecrawl, Reddit, TV Tropes, IMDB, Quotes)

None of these depend on each other. Wrap them in `asyncio.gather()` and update their step statuses concurrently. Dependencies after:
- synthesis needs all three (unchanged)
- fact_extraction needs synthesis (unchanged)
- image_sourcing only needs name/universe/franchise (already independent of synthesis, but currently sequential)
- save_results needs everything (unchanged)

Additional parallelization: run `image_sourcing` in parallel with `fact_extraction`. image_sourcing is pure SearXNG image queries; fact_extraction is an Ollama call. They're independent after synthesis.

### 3. Smart cross-character batching with an Ollama semaphore
- Change `BATCH_SIZE = 1` to `BATCH_SIZE = 3` at [character_content_service.py:2806](backend/app/services/character_content_service.py#L2806).
- Add a module-level `asyncio.Semaphore(1)` named `_OLLAMA_SEMAPHORE` in the same file.
- Wrap every `self._ollama.chat(...)` call site in `character_content_service.py` (synthesis + fact-extraction + other 4) with `async with _OLLAMA_SEMAPHORE:`.
- Effect: 3 characters race through the cheap I/O steps in parallel; when they hit synthesis/fact-extract, they queue behind the semaphore so only one 35B-class Ollama call runs at a time. GPU safe.
- The queue UI already handles "N characters in parallel" text at [CharacterContentPage.tsx:522-525](frontend/src/pages/CharacterContentPage.tsx#L522-L525).

### 4. Persist per-step timings (new table)
Current timings live only in the in-memory `_research_queue` dict and are lost on restart. We need historical data for averages.

New migration: `backend/app/migrations/versions/026_research_step_stats.py`
```python
CREATE TABLE character_research_step_stats (
    id BIGSERIAL PRIMARY KEY,
    character_id UUID NOT NULL,
    job_id VARCHAR(64) NOT NULL,
    step_name VARCHAR(64) NOT NULL,        -- searxng_search, wiki_scrape, etc
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,            -- completed | failed
    model VARCHAR(64),                      -- which LLM was used (for synthesis/fact_extraction)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_step_stats_step ON character_research_step_stats(step_name);
CREATE INDEX ix_step_stats_char ON character_research_step_stats(character_id);
```

Record each step on successful `_update_step("...", "completed", ...)` by calling a new helper `_record_step_stat(character_id, job_id, step_name, started_at, completed_at, status, model)`. The helper just inserts via `async with get_session() as session:` and swallows DB errors (never blocks the pipeline).

### 5. Step-duration averages + ETA
New service methods in `character_content_service.py`:

- `async def get_step_duration_averages() -> dict[str, dict]` — returns `{step_name: {avg_ms, p50_ms, p95_ms, n}}` from last 200 successful rows per step. Cache in `_step_stats_cache` with 60s TTL so per-request cost stays low.
- ETA computation in `get_research_queue_status()`:
  - Per job in `queued` state: `eta_seconds = sum(avg_ms per remaining step) / 1000`
  - Per job currently running: for completed steps, use their actual duration; for running step, use `max(0, avg_ms - elapsed_so_far)`; for pending steps, use avg_ms. Sum.
  - Queue-level `estimated_completion`: `now + ceil(remaining_jobs / BATCH_SIZE) * avg_job_duration` where `avg_job_duration = sum(avg per step)`. Return as ISO datetime so the existing frontend renderer at [CharacterContentPage.tsx:531-535](frontend/src/pages/CharacterContentPage.tsx#L531-L535) just works.

Extend response models in `backend/app/models/character_content.py`:
- Add `ResearchJob.eta_seconds: Optional[int]`
- Add `ResearchJobStep.avg_duration_ms: Optional[int]` (so UI can show "avg 45s" next to running steps)

### 6. Frontend ETA + avg display
- Queue-level ETA already displays from `queue.estimated_completion` at [CharacterContentPage.tsx:531-535](frontend/src/pages/CharacterContentPage.tsx#L531-L535) once backend populates it. No change needed there.
- Per-card ETA: add next to the elapsed badge at [CharacterContentPage.tsx:723-734](frontend/src/pages/CharacterContentPage.tsx#L723-L734). Show `ETA ~2m 15s` when `job.eta_seconds` present and status is `queued` or `researching`.
- Per-step hint: in `ResearchStepStepper` (around line 900-1060), show `avg 45s` under step name when `avg_duration_ms` present. Helps user see "synthesis usually takes 4 min, don't panic".
- Update types in [frontend/src/types/index.ts](frontend/src/types/index.ts) or wherever `ResearchJob` is declared (likely inferred from API).

### 7. Parallelization opportunities identified (for plan completeness)
Beyond the two above:
- `searxng_search` already runs 5 queries in parallel internally. No change.
- `deep_research` calls 5 sources serially through `sources_svc.research_from_all_sources`. Worth parallelizing internally in `character_research_sources.py`, but out of scope for this plan since it risks SearXNG/Firecrawl rate limits. Flag as follow-up.
- Image validation (PIL min-800px check) is synchronous CPU. Running in `asyncio.to_thread` exists? Quick check during implementation.

## Files to Modify

Backend:
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — main changes
  - L122: LLM constant swap
  - L2806: BATCH_SIZE 1 → 3
  - New module-level `_OLLAMA_SEMAPHORE` and `_step_stats_cache`
  - L761, 990, 1007, 1338, 1355, 1770, 4189: wrap `self._ollama.chat` calls with semaphore
  - L2910-2961: parallelize steps 1/2/3 via `asyncio.gather`
  - L3026-3056: parallelize fact_extraction + image_sourcing via `asyncio.gather`
  - New: `_record_step_stat()`, `get_step_duration_averages()`, ETA calc in `get_research_queue_status()`
- [backend/app/models/character_content.py](backend/app/models/character_content.py)
  - Extend `ResearchJob` with `eta_seconds`
  - Extend `ResearchJobStep` with `avg_duration_ms`
- [backend/app/db/models.py](backend/app/db/models.py) — add `CharacterResearchStepStat` ORM model
- [backend/app/migrations/versions/026_research_step_stats.py](backend/app/migrations/versions/026_research_step_stats.py) — NEW migration

Frontend:
- [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)
  - Per-card ETA badge in `ResearchJobCard` (L723-734 area)
  - Per-step "avg 45s" hint in `ResearchStepStepper` (L900-1060)

## Existing Utilities to Reuse
- `get_session()` from infrastructure for DB writes
- `self._ollama.chat(...)` client (already has timeout/retry)
- `ResearchJobStep`, `ResearchJob`, `ResearchQueueStatus` Pydantic models
- React Query polling in [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) already refreshes every 2-3s
- `useLiveTimer()` hook at [CharacterContentPage.tsx:644-651](frontend/src/pages/CharacterContentPage.tsx#L644-L651) for animated countdown

## Verification

1. **Rebuild + migrate**:
   ```
   docker compose -f docker-compose.sprint.yml build --no-cache zero-api
   docker compose -f docker-compose.sprint.yml up -d zero-api
   docker exec zero-api alembic upgrade head
   ```

2. **Model swap live**: `docker logs zero-api | grep qwen3-coder-next` should appear on next synthesis call.

3. **Batch behavior**: Start a fresh research queue with 5+ queued characters. UI should show "3 characters in parallel" at [CharacterContentPage.tsx:522-525](frontend/src/pages/CharacterContentPage.tsx#L522-L525). `docker logs zero-api | grep research_queue_batch_start` should show `size=3`.

4. **Ollama serialization**: During a batch of 3, only one `_synthesize_research` or `_extract_facts` log entry should be "running" at any moment. `docker exec zero-api nvidia-smi` (or host) should show a single active Ollama model load.

5. **Stats table populated**: After 2-3 completed characters:
   ```sql
   SELECT step_name, COUNT(*), AVG(duration_ms)::int
   FROM character_research_step_stats GROUP BY step_name;
   ```

6. **ETA populated**: `curl -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" http://localhost:18792/api/characters/research-queue | jq '.estimated_completion, .jobs[0].eta_seconds'` returns non-null values.

7. **UI smoke test**: Open `/characters` → Research Queue tab. Confirm:
   - Queue header shows "ETA: HH:MM:SS" based on averages
   - Each running/queued card shows `ETA ~Xm Ys`
   - Running step shows `avg 45s` hint (synthesis/fact-extraction especially)
   - Charlie Cannon retry works and completes through synthesis using qwen3-coder-next

8. **Regression check**: Existing completed characters unchanged. `pytest backend/tests/test_character_content.py` passes.

## Risks & Notes
- `qwen3-coder-next:latest` is 51 GB vs 23 GB for old model. First run will be slower (cold load). Confirm GPU has headroom (`nvidia-smi`). If VRAM is tight, fall back to `qwen3-coder:30b` or similar.
- Semaphore is per-process. In the current single-container deployment that's fine. If we ever scale zero-api to multiple replicas, serialize via DB advisory lock or Redis.
- Migration 026 number assumes no conflict with pending work; verify against `backend/app/migrations/versions/` before running.
- Averages bootstrap slowly. First ~5 completed jobs will have weak ETAs. Fallback: if `n < 3` for a step, use a hardcoded prior (`searxng_search: 15s`, `wiki_scrape: 8s`, `deep_research: 30s`, `synthesis: 240s`, `fact_extraction: 180s`, `image_sourcing: 45s`, `save_results: 2s`) so the UI has something reasonable day-one.
