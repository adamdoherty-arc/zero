# Plan: .env Setup, MiniMax Integration & Project Cleanup

## Context

You don't see a `.env` file because **none exists at the project root** — only [.env.example](.env.example) and a partial `backend/.env`. Docker Compose loads `.env` from the project root by default, so without it secrets like `ANTHROPIC_API_KEY`, `KIMI_API_KEY`, `GEMINI_API_KEY` etc. never reach the containers.

The "sprint json files" you're seeing (`sprint1.json`, `sprint11.json`, `all_sprints.json`, `final_sprints.json`, plus ~20 more like `s7_start.json`, `task43.json`, `openapi_dump.json`, `dashboard.json`) are **orphaned artifacts** — API response dumps captured during testing on March 7, 2026. **Zero code reads them.** The real sprint system is fully DB-driven via the `Sprint` model in [backend/app/models/sprint.py](backend/app/models/sprint.py) and the API in [backend/app/api/sprints.py](backend/app/api/sprints.py).

The repo is also accidentally tracking **14,103 `.mypy_cache/` files** (≈338 MB) because [.gitignore](.gitignore) is missing `.mypy_cache/` and `.ruff_cache/`. These would land in your next commit if untouched.

You said you'll add a **MiniMax** key. MiniMax is a *separate* Chinese AI provider from Kimi/Moonshot — not currently wired into FortressOS. We'll add it as a new provider alongside Kimi using the OpenAI-compatible endpoint (`https://api.minimaxi.com/v1`).

This plan delivers four things:
1. Create a working root `.env` with all current providers + MiniMax
2. Add MiniMax as a new LLM provider in backend + router + docker-compose
3. Fix `.gitignore` and untrack the cache directories
4. Delete orphan JSON dumps and stale root docs

---

## Step 1 — Create root `.env`

**File:** `c:\code\fortressOS\.env` (new — already gitignored)

Use values that match what `docker-compose.yml` expects and what [backend/app/core/config.py](backend/app/core/config.py) reads. Critical: use the **postgres credentials from docker-compose** (`superman` / `kryptonite_proof_2024`), not the stale ones in [.env.example](.env.example).

```env
# === Database (must match docker-compose superman creds) ===
POSTGRES_HOST=pgbouncer
POSTGRES_PORT=6432
POSTGRES_USER=superman
POSTGRES_PASSWORD=kryptonite_proof_2024
POSTGRES_DB=fortress_db

# === Redis / Celery ===
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# === LLM Provider Selection ===
LLM_PROVIDER=ollama

# === Ollama (local, default) ===
OLLAMA_HOST=http://host.docker.internal:11434
OLLAMA_MODEL=gemma4:e4b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text-v2-moe

# === Claude (Anthropic) — optional ===
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-5-20250929

# === Kimi K2.5 (Moonshot) — optional ===
KIMI_API_KEY=
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=kimi-k2.5

# === Gemini — optional ===
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# === MiniMax (new) — paste your key here ===
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M2

# === Security ===
SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=1440

# === Misc ===
LOG_LEVEL=INFO
ENABLE_GMAIL_SCANNING=true
ENABLE_LINKEDIN_POSTING=false
```

Then **delete** `c:\code\fortressOS\backend\.env` so there's a single source of truth.

Also **update [.env.example](.env.example)** so it matches the new shape (add MiniMax block, fix postgres creds to `superman`).

---

## Step 2 — Add MiniMax as a new LLM provider

MiniMax exposes an OpenAI-compatible chat completions API, so the integration mirrors [backend/app/infrastructure/kimi_client.py](backend/app/infrastructure/kimi_client.py) almost exactly.

### 2a. Extend Settings

**File:** [backend/app/core/config.py](backend/app/core/config.py)

Add after the Kimi block:

```python
# MiniMax (OpenAI-compatible cloud LLM)
minimax_api_key: str = ""
minimax_base_url: str = "https://api.minimaxi.com/v1"
minimax_model: str = "MiniMax-M2"
minimax_timeout: int = 120
```

### 2b. Create MiniMaxClient

**New file:** `backend/app/infrastructure/minimax_client.py`

Mirror the Kimi pattern: `AsyncOpenAI(base_url=settings.minimax_base_url, api_key=settings.minimax_api_key)`, lazy `_ensure_initialized`, `generate()`, `generate_json()`, singleton via `get_minimax_client()`. Include a `MINIMAX_PRICING` dict and `calculate_minimax_cost()` helper. Add `is_minimax_available()` checking the key + `OPENAI_SDK_AVAILABLE`.

This is a **new file** modeled on the Kimi pattern — no edits to `kimi_client.py` itself.

### 2c. Wire into the LLM router

**File:** [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py)

- Add a `minimax_circuit` CircuitBreaker alongside `kimi_circuit` / `gemini_circuit`
- Add a `_call_minimax()` method modeled on `_call_kimi()`
- Register `"minimax"` / model id `"MiniMax-M2"` in the routing table for tasks where it's a useful mid-tier (e.g. `JOB_ANALYSIS`, `RESEARCH`, `PLANNING`)
- Surface availability + circuit state in the `/health/llm` endpoint

### 2d. Pass MiniMax env into containers

**File:** [docker-compose.yml](docker-compose.yml)

Extend the `x-backend-env: &backend-env` anchor so backend, celery-worker, celery-beat, flower all get the keys from `.env`:

```yaml
x-backend-env: &backend-env
  # ... existing vars ...
  ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
  KIMI_API_KEY: ${KIMI_API_KEY:-}
  KIMI_BASE_URL: ${KIMI_BASE_URL:-https://api.moonshot.cn/v1}
  KIMI_MODEL: ${KIMI_MODEL:-kimi-k2.5}
  GEMINI_API_KEY: ${GEMINI_API_KEY:-}
  MINIMAX_API_KEY: ${MINIMAX_API_KEY:-}
  MINIMAX_BASE_URL: ${MINIMAX_BASE_URL:-https://api.minimaxi.com/v1}
  MINIMAX_MODEL: ${MINIMAX_MODEL:-MiniMax-M2}
```

Currently the anchor passes none of these — that's a pre-existing gap.

### 2e. Tests

**New file:** `backend/tests/services/test_minimax_client.py` — 5–6 unit tests mirroring [backend/tests/services/test_kimi_client.py](backend/tests/services/test_kimi_client.py): availability check, lazy init, generate happy path, JSON extraction, auth failure, cost calculation. Mock `AsyncOpenAI`.

---

## Step 3 — Fix `.gitignore` and untrack cache dirs

### 3a. Append to [.gitignore](.gitignore)

```gitignore
# Type/lint caches
.mypy_cache/
.ruff_cache/

# Orphaned JSON dumps at repo root (not config files)
/sprint*.json
/all_sprints.json
/final_sprints.json
/s[0-9]*_start.json
/s[0-9]*_complete.json
/task*.json
/t[0-9]*.json
/dashboard.json
/comparison.json
/quality_trend.json
/wf_analytics.json
/jobs_count.json
/sources.json
/openapi_dump.json
/llm_health.json
/complete.json
```

### 3b. Untrack already-staged caches and JSON dumps

These files are currently staged (`A`) in `git status`. Untrack them with `git rm --cached` (one-time, leaves files on disk, doesn't lose work):

```bash
cd c:/code/fortressOS && git rm -r --cached .mypy_cache/
cd c:/code/fortressOS && git rm --cached sprint1.json sprint11.json all_sprints.json final_sprints.json
```

---

## Step 4 — Delete orphan files and stale docs

### 4a. Orphan JSON dumps at repo root (safe — not read by any code)

Delete from disk:

```
sprint1.json, sprint11.json, all_sprints.json, final_sprints.json,
s7_start.json, s7_complete.json, s8_start.json, s8_complete.json,
s13_start.json, s13_complete.json,
task43.json, task46.json, t47.json, t48.json, t49.json,
complete.json, dashboard.json, comparison.json,
quality_trend.json, wf_analytics.json, jobs_count.json,
sources.json, openapi_dump.json, llm_health.json
```

### 4b. Stale root docs (last touched by commit `8ef136a`, the same broken-conftest commit noted in MEMORY.md)

Verify each is stale by skimming, then delete:

- `TRANSFORMATION_STATUS.md`
- `IMPLEMENTATION_REVIEW.md`
- `STATUS.md`
- `PROJECT_SUMMARY.md`

**Keep:**
- `README.md` (canonical)
- `CLAUDE.md` (active project guide)
- `QUICKSTART.md` and `README_SETUP.md` — review and **merge into README.md** if redundant, otherwise keep

### 4c. Other cleanup

- `Profile.pdf` at repo root → delete or move to `docs/` (unclear purpose)
- `userlist.txt` (48 bytes, appears empty) → delete
- `htmlcov/` directory → delete from disk (already in `.gitignore`, just stale output)
- `.coverage`, `coverage.xml` → delete (regenerated by test runs)

---

## Critical Files Modified

| File | Change |
|------|--------|
| `c:\code\fortressOS\.env` | **Create** (new) |
| `c:\code\fortressOS\backend\.env` | **Delete** (consolidate to root) |
| [.env.example](.env.example) | Update postgres creds + add MiniMax block |
| [.gitignore](.gitignore) | Add `.mypy_cache/`, `.ruff_cache/`, orphan JSON patterns |
| [backend/app/core/config.py](backend/app/core/config.py) | Add MiniMax settings |
| `backend/app/infrastructure/minimax_client.py` | **Create** (modeled on `kimi_client.py`) |
| [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py) | Add `minimax_circuit`, `_call_minimax()`, routing entries |
| [docker-compose.yml](docker-compose.yml) | Extend `x-backend-env` anchor with API keys |
| `backend/tests/services/test_minimax_client.py` | **Create** |

## Files Reused (do NOT duplicate)

- `KimiClient` pattern in [backend/app/infrastructure/kimi_client.py](backend/app/infrastructure/kimi_client.py) — copy structure, do not edit
- `CircuitBreaker` already in [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py)
- `OPENAI_SDK_AVAILABLE` import guard pattern from `kimi_client.py`
- `Settings` BaseSettings pattern in [backend/app/core/config.py](backend/app/core/config.py)
- Test fixtures in [backend/tests/services/test_kimi_client.py](backend/tests/services/test_kimi_client.py)

---

## Verification

After implementation:

1. **Env loads:**
   ```bash
   cd c:/code/fortressOS && docker compose config | grep -E "MINIMAX|KIMI|ANTHROPIC"
   ```
   Should show all three keys being passed (values masked or visible from `.env`).

2. **Stack boots cleanly:**
   ```bash
   cd c:/code/fortressOS && docker compose up -d --build backend celery-worker
   cd c:/code/fortressOS && docker compose logs --tail=50 backend
   ```
   No `MINIMAX_API_KEY not set` crash at startup (lazy init).

3. **MiniMax visible in router health:**
   ```bash
   curl http://localhost:8001/health/llm
   ```
   Response should include `"minimax": {"available": true, ...}` when key is set.

4. **Smoke test the client (with key set):**
   ```bash
   cd c:/code/fortressOS && docker compose exec backend python -c "
   import asyncio
   from app.infrastructure.minimax_client import get_minimax_client
   async def main():
       c = await get_minimax_client()
       r = await c.generate('Say hello in one sentence.')
       print(r['content'])
   asyncio.run(main())
   "
   ```

5. **Unit tests pass:**
   ```bash
   cd c:/code/fortressOS && docker compose exec backend pytest tests/services/test_minimax_client.py -v
   ```

6. **Cleanup verification:**
   ```bash
   cd c:/code/fortressOS && git status --short | wc -l
   ```
   Should drop from ~14,400 to under 100. The 14,103 `.mypy_cache` entries should be gone.

7. **Frontend still loads:** visit `http://localhost:3002` — should be unchanged.
