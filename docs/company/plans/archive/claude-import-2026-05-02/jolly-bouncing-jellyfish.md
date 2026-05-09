# Fix `file_titles` UnboundLocalError and Retry Failed Character Research Runs

## Context

The Research Queue UI at Character Content shows 8 failed research runs (Charlie Cannon, Dakota, Ira Slitz, Larissa Cannon, Lisa Fields, Luigi (voice), plus 2 more). All 7 pipeline steps are marked failed and the error surfaced on the "Saving" row is:

```
cannot access local variable 'file_titles' where it is not associated with a value
```

This is a Python `UnboundLocalError`. Despite the UI showing it on the Saving row, the bug actually lives in the **Image Search** step (step 6), inside `source_fandom_images()`. When the Image Search step raises this error, the pipeline aborts, the job is marked failed, and the single captured exception is rendered against the last-listed row in the table. The error needs one-line fix, then all eight failed runs need to be retried.

## Root Cause

File: [backend/app/services/image_source_service.py](backend/app/services/image_source_service.py)

At [image_source_service.py:237](backend/app/services/image_source_service.py#L237), `file_titles` is defined inside two nested conditions:
- Inside `if resp.status == 200:` (line 232)
- Inside `for page in pages.values():` (line 235)

But at [image_source_service.py:246](backend/app/services/image_source_service.py#L246), `file_titles` is referenced **outside** both of those scopes (still inside `async with aiohttp.ClientSession() as http:` but at the same indent as the `async with http.get(...)` block above it).

```python
async with http.get(api_url, params=params, timeout=...) as resp:
    if resp.status == 200:                      # <-- conditional
        data = await resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():             # <-- also conditional on pages existing
            page_images = page.get("images", [])
            file_titles = [ ... ]               # line 237 - only assigned here

# Get actual URLs for the image files
for batch_start in range(0, len(file_titles), 5):   # line 246 - UNBOUND if resp != 200
    ...
```

Whenever the Fandom API returns non-200 (rate limit, 404 for characters not on a wiki, timeout, network blip, or even a 200 with no `pages`), `file_titles` is never bound and Python raises `UnboundLocalError` the moment line 246 executes. Since these characters probably don't all have Fandom wikis (several have `universe="Other"`), this is hit reliably.

## Fix

Single-line change: initialize `file_titles` as an empty list before the `async with http.get(...)` block so line 246 always has a bound name. If the API call fails or returns no pages, the `for` loop simply iterates zero times and the function returns whatever images were already collected (e.g. the page-image from the earlier block at lines 203-218).

### File to modify

[backend/app/services/image_source_service.py](backend/app/services/image_source_service.py) around [line 220](backend/app/services/image_source_service.py#L220):

```python
        # Get all images on the page
        file_titles: List[str] = []   # <-- ADD THIS LINE
        params = {
            "action": "query",
            "titles": wiki_name,
            "prop": "images",
            "imlimit": "20",
            "format": "json",
        }
        async with http.get(
            api_url, params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                ...
```

No other changes required. The rest of the function already handles empty input gracefully (the `for batch_start in range(0, len(file_titles), 5):` loop does nothing when `file_titles` is empty, and `images` is separately populated by the earlier pageimage block).

## Deploy

Backend code is COPY'd into the container (not volume-mounted), so a rebuild is mandatory per [CLAUDE.md](CLAUDE.md):

```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && \
  docker compose -f docker-compose.sprint.yml up -d zero-api
```

Verify healthy:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero-api
```

## Retry the 8 Failed Runs

Router: [backend/app/routers/character_content.py](backend/app/routers/character_content.py), mounted at `/api/characters` (see [backend/app/main.py:347](backend/app/main.py#L347)).

Endpoint: `POST /api/characters/research-queue/retry/{character_id}` ([character_content.py:234](backend/app/routers/character_content.py#L234)). Service method `retry_research_job()` resets the character's `research_status` to `pending`, resets the 7 steps, and enqueues at the front of the queue. If the queue isn't running it auto-starts.

```bash
TOKEN=$(grep '^ZERO_GATEWAY_TOKEN=' .env | cut -d= -f2)
BASE="http://localhost:18792"

# 1) List failed jobs and their character_ids
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/characters/research-queue" | \
  jq -r '.jobs[] | select(.status=="failed") | "\(.character_id)\t\(.character_name)"'

# 2) Retry each failed job
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/characters/research-queue" | \
  jq -r '.jobs[] | select(.status=="failed") | .character_id' | \
  while read -r cid; do
    echo "retrying $cid"
    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
      "$BASE/api/characters/research-queue/retry/$cid" > /dev/null
    sleep 1
  done
```

## Verification

1. Container healthy after rebuild (`docker ps`).
2. Hit the queue endpoint once to confirm the 8 jobs moved from `failed` -> `queued`/`researching`:
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/characters/research-queue" | \
     jq '{queued, researching, completed, failed, current_character, current_step}'
   ```
3. Tail backend logs during retries; no more `UnboundLocalError: file_titles`:
   ```bash
   docker logs -f zero-api 2>&1 | grep -iE "file_titles|image_source_failed|research_pipeline"
   ```
4. Open the Research Queue UI (Character Content page) and confirm Image Search rows now go green (or skip cleanly when a character has no Fandom wiki) and Saving completes.
5. Re-run the `jq` status query after a few minutes. `failed` count should be 0 and `completed` should have grown by 8.

## Critical Files Referenced

- [backend/app/services/image_source_service.py](backend/app/services/image_source_service.py) (the fix, lines ~220-246)
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py#L234) (retry endpoint)
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) (`retry_research_job`, queue runner)
- [backend/app/main.py:347](backend/app/main.py#L347) (router mount: `/api/characters`)
- [docker-compose.sprint.yml](docker-compose.sprint.yml) (rebuild target `zero-api`)

## Out of Scope (noted, not fixing)

- Inside the same function, `file_titles` is reassigned per-page in the `for page in pages.values():` loop, so only the last page's titles survive. In practice Fandom `action=query&titles=<one_title>` returns a single page, so this is harmless here. Leaving as-is to keep the change minimal.
- The UI attaches the single pipeline-wide error to the last step row ("Saving") regardless of which step raised it. Misleading but cosmetic. Not fixing in this pass.
