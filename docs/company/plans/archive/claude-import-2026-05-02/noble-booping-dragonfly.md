# Research Queue: Concurrency Fix, Auto-Pipeline, and Newer Character Focus

## Context

The research queue has `BATCH_SIZE = 3` but uses `asyncio.gather()` which waits for **all 3 to finish** before starting the next batch. When one character gets stuck (like Frodo on Fact Mining in the screenshot), it blocks the entire pipeline. Meanwhile, characters are discovered daily by the scheduler (TMDB, Wikipedia, Reddit, SearXNG at 1 AM) but there's **no auto-trigger for research** on newly discovered characters -- you have to manually click "Start Research." Finally, the seed list is all classic/iconic characters; the user wants to prioritize characters from newer shows and movies.

Three changes:

---

## 1. Fix Concurrency: Sliding Window Instead of Fixed Batches

**Problem**: `asyncio.gather(*batch)` at [character_content_service.py:3109](backend/app/services/character_content_service.py#L3109) blocks the entire batch if one character is stuck. Characters 4-90 wait even though slots are free.

**Fix**: Replace the batch loop with a `asyncio.Semaphore(3)` sliding window. Each character gets its own task; when one finishes, the next starts immediately. Add a per-character timeout (e.g. 30 min) so stuck characters fail gracefully instead of blocking forever.

**File**: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)

**Changes to `_run_research_queue()` (lines 3038-3113)**:
- Replace the `while idx` / `batch_ids` / `asyncio.gather` loop with:
  ```python
  CONCURRENCY = 3
  TIMEOUT_SEC = 30 * 60  # 30 min per character
  sem = asyncio.Semaphore(CONCURRENCY)

  async def _process_with_limit(job_id):
      async with sem:
          try:
              await asyncio.wait_for(_process_one(job_id), timeout=TIMEOUT_SEC)
          except asyncio.TimeoutError:
              job = _research_queue["jobs"][job_id]
              job["status"] = "failed"
              job["error"] = "timeout_30m"
              # update DB status too

  tasks = []
  for jid in order:
      if _research_queue["cancel_requested"]:
          break
      job = _research_queue["jobs"].get(jid)
      if job and job["status"] == "queued":
          tasks.append(asyncio.create_task(_process_with_limit(jid)))
  
  await asyncio.gather(*tasks)
  ```
- This means 3 characters are always in-flight. When one finishes, the semaphore releases and the next starts immediately. No more batch blocking.

---

## 2. Auto-Start Research After Discovery

**Problem**: `character_discovery` runs at 1 AM daily and creates characters with `research_status="pending"`, but nothing auto-triggers research on them. The user must manually click "Start Research."

**Fix**: Add a new scheduler job `character_auto_research` that runs every 2 hours. It checks for pending characters and auto-starts a batch research run if any exist and no research is currently running.

**Files**:
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) -- add job definition (~line 496) and handler
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) -- reuse existing `start_batch_research_async()`

**New scheduler job**:
```python
"character_auto_research": {
    "cron": "0 */2 * * *",  # Every 2 hours
    "description": "Auto-start research for pending characters if queue is idle",
    "enabled": True
},
```

**Handler** (`_run_character_auto_research`):
- Check `_research_queue["running"]` -- skip if already running
- Count pending characters -- skip if none
- Call `svc.start_batch_research_async(limit=24)` to kick off the queue

---

## 3. Focus on Newer Characters (Trending/Upcoming)

**Problem**: Seed list is 80+ classic characters. Discovery does pull from TMDB trending weekly, but doesn't specifically target upcoming releases or recently premiered shows. The user wants characters from newer content.

**Changes**:

### 3a. Add TMDB "Now Playing" + "Upcoming" discovery sources

**File**: [backend/app/services/character_discovery_service.py](backend/app/services/character_discovery_service.py)

Extend `discover_from_tmdb()` (line 240) to also hit:
- `GET /3/movie/now_playing` -- movies currently in theaters
- `GET /3/movie/upcoming` -- movies coming soon
- `GET /3/tv/airing_today` -- TV shows airing today
- `GET /3/tv/on_the_air` -- TV shows currently on air

These endpoints supplement the existing `/trending/movie/week` and `/trending/tv/week`. Same logic: fetch credits, extract top-billed character names, propose them.

### 3b. Priority ordering in research queue

**File**: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)

In `start_batch_research_async()` (line 2869), change the ordering so recently-discovered characters (those with `discovery_source` set and recent `created_at`) are queued first, before older seed characters. Currently it just does `list_characters(research_status="pending")` with no ordering preference.

Add ordering: `order_by(CharacterModel.created_at.desc())` so newest characters research first.

### 3c. Increase discovery daily cap

**File**: [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py)

Bump `character_discovery_daily_cap` default from 10 to 20. More new shows/movies means more characters to discover daily.

---

## Files to Modify

| File | Changes |
|------|---------|
| `backend/app/services/character_content_service.py` | Sliding window concurrency, per-character timeout, priority ordering |
| `backend/app/services/character_discovery_service.py` | Add now_playing/upcoming/airing TMDB endpoints |
| `backend/app/services/scheduler_service.py` | Add `character_auto_research` job + handler |
| `backend/app/infrastructure/config.py` | Bump discovery daily cap default |

## Verification

1. **Concurrency**: Start research with 6+ characters queued. Confirm logs show 3 concurrent `researching` statuses. If one gets stuck, confirm the others continue and the stuck one times out after 30 min.
2. **Auto-research**: Add a pending character manually, wait for the scheduler tick (or trigger manually), confirm research starts automatically.
3. **Newer characters**: Trigger discovery manually (`svc.run_all_sources()`), confirm characters from current movies/shows are proposed. Confirm they appear first in the research queue.
4. Check `docker logs zero-api` for `research_queue_batch_start` and `character_discovered` log entries.
