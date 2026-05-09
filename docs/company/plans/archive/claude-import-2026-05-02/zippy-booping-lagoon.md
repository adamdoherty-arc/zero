# Plan: Parallelize Character Research Queue

## Context
The research queue processes characters one at a time (`BATCH_SIZE = 1` in `_run_research_queue`). The frontend already supports displaying parallel progress (shows "X characters in parallel" when `queue.researching > 1`). The LLM overload concern that motivated `BATCH_SIZE = 1` is already handled by a global `_LLM_SEMAPHORE = asyncio.Semaphore(4)` in `unified_llm_client.py`, which throttles concurrent LLM calls regardless of how many characters are processing. This means we can safely increase parallelism since I/O-heavy steps (web search, Wikipedia, deep sources, image search) will overlap while LLM steps (synthesis, fact mining) naturally serialize through the semaphore.

## Change

**File:** [character_content_service.py:2072](backend/app/services/character_content_service.py#L2072)

Single line change:
```python
# Before
BATCH_SIZE = 1

# After
BATCH_SIZE = 3
```

That's it. The `asyncio.gather()` call on line 2134 already handles concurrent execution of batch items. The frontend already displays "X characters in parallel" when `queue.researching > 1`. No other changes needed.

## Why 3?
- 3 characters overlapping I/O steps provides ~2-3x throughput improvement
- With 7 steps per character and only 2 using the LLM, most time is spent on network I/O that parallelizes well
- The global LLM semaphore (4 slots) can handle 3 characters hitting synthesis/fact_mining with room to spare
- Queue of 24 characters: ~24 min at BATCH_SIZE=1, ~8-10 min at BATCH_SIZE=3

## Verification
1. Rebuild backend: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
2. Go to Character Content > Research Queue
3. Click "Start Research" - should see 3 characters in "researching" state simultaneously
4. Frontend should display "3 characters in parallel" in the progress bar area
5. Confirm queue completes faster than before
