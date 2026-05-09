# Cheap multimodal routing + free-tier rotation for Stage-8 VLM verifier

## Context

The carousel V2 pipeline shipped end-to-end last session. Worker, schema, and persistence are verified. The remaining blocker is **Stage-8 image verification (VLM)** — it currently routes through `vision_service.describe_image_url` which:

1. Tries an Ollama `llava` call first (Ollama was retired ecosystem-wide on 2026-04-27 per `.env.example`)
2. Falls back to raw-httpx Gemini Flash with a hardcoded `os.getenv("GEMINI_API_KEY")` lookup

The Ollama-first path is dead and **hangs for up to 900 s** (the configured `ollama_timeout`) before falling through, which is why the unstubbed live-worker workflow last session got stuck at `score_images`.

The user wants Stage-8 to:
- Use **Kimi K2.6** (paid, already-keyed, native MoonViT vision) as primary
- **Rotate across OpenRouter free-tier vision models** for bulk cheap calls (8 free vision models exist: Llama 3.2 Vision, Qwen2.5-VL 32B/72B, Gemma 3 4B/12B/27B, Gemma 4 31B, Nemotron Nano VL — all with 20 req/min, 50 req/day per free OpenRouter account)
- **Multi-key rotation** so multiple OpenRouter accounts multiply throughput
- Fall back to **Gemini Flash** (already-keyed) when free pools are exhausted

## What's actually wired today (verified by audit)

| Component | Status | Notes |
|---|---|---|
| `ZERO_KIMI_API_KEY` | ✅ SET | Moonshot K2.6 — supports vision via MoonViT, base64 data URLs |
| `ZERO_GEMINI_API_KEY` | ✅ SET | Multimodal native |
| `ZERO_OPENROUTER_API_KEY` | ✅ SET | 1 key; need to support multi-key list |
| `ZERO_MINIMAX_API_KEY` | ❌ EMPTY | MiniMax M2.7 has **no image support** anyway — text-only despite marketing |
| `ZERO_TMDP_API_KEY` + `ZERO_TMDP_READ_ACCESS_TOKEN` | ✅ SET | TMDB image source |
| `ZERO_FANART_API_KEY` | ✅ SET | Fanart.tv |
| `ZERO_COMICVINE_API_KEY` | ❌ EMPTY | Optional |
| `ZERO_REDDIT_CLIENT_ID` / `_SECRET` | ❌ EMPTY | Optional |
| `vllm-chat` container | ✅ UP healthy | Qwen3-32B-AWQ on `:18800` — **text-only** |
| Shared LiteLLM proxy | ✅ UP at `:4444` | Aliases `kimi-k2.5`, `gemini-flash-latest`, `openrouter-auto` exposed |
| Provider modules wire images | ❌ NONE | Kimi/OpenRouter/Gemini providers all text-only despite cloud models supporting vision |

## Design — five focused changes

### 1. Add `image_urls=` parameter to three provider modules
- **`backend/app/infrastructure/llm_providers/kimi_provider.py`** — when `image_urls` is non-empty, format the user message as OpenAI content-array (`{"type": "image_url", "image_url": {"url": ...}}`). Kimi accepts both URLs and base64 data-URLs. Backwards-compatible: empty list → text path unchanged.
- **`backend/app/infrastructure/llm_providers/openrouter_provider.py`** — same OpenAI content-array format.
- **`backend/app/infrastructure/llm_providers/gemini_provider.py`** — convert to google-genai SDK `Part.from_bytes(data=..., mime_type=...)` parts. Download URL → bytes when caller passed a URL.

### 2. New `backend/app/services/carousel_v2/openrouter_free_pool.py`
- On startup + every 6h, `GET https://openrouter.ai/api/v1/models?supported_parameters=image_input` and filter slugs ending in `:free`. Cache in Redis at key `carousel_v2:openrouter:free_vision_models` with 6h TTL.
- Multi-key rotation: parse `ZERO_OPENROUTER_API_KEYS` (plural, comma-separated). Falls back to `ZERO_OPENROUTER_API_KEY` (singular) when plural unset. **Pool size = 1 today** per user; architecture is plural-ready so adding accounts later is env-only with zero code change.
- Per `(key, model)` quota state in Redis: `carousel_v2:or_quota:{key_id}:{model}` → `{rpm_remaining, daily_remaining, cooldown_until}`. Reset windows: 1 min for RPM (20/min), 24 h for daily (50/day).
- `select_next() → (key, model)`: round-robin over (active_keys × active_models), skipping any in cooldown or out-of-quota. Returns `None` when pool exhausted.
- `mark_429(key, model, retry_after)`: cooldown for `Retry-After` seconds (defaults to next-window boundary).
- `mark_success(key, model, tokens_used)`: decrement quota counters.

### 3. New `backend/app/services/carousel_v2/cheap_vlm_router.py`
Tiered VLM dispatch — **Kimi first** (paid but reliable + lower latency), then free pool, then paid Gemini fallback. Each tier failure-soft.

```
Tier 0: Kimi K2.6 multimodal       (~$0.30 / 1M tokens, 1 key — confirmed set)
Tier 1: OpenRouter free pool       ($0,  1 key today × 8 models × 50/day)
Tier 2: Gemini 2.0 Flash           (~$0.10 / 1M tokens, paid fallback)
```

Rationale: user picked Kimi-first for predictable latency. Free pool is the bulk-discount overflow tier when Kimi is rate-limited or returns transient errors. Gemini is the floor.

Public surface:
```python
async def verify_image(
    image_url_or_bytes: str | bytes,
    *,
    character: str,
    franchise: str | None = None,
    timeout: float = 30.0,
) -> dict  # {character, actor, franchise, likeness, is_promotional_still, watermark, text_overlay, vertical_safe_crop_box, _model, _tier, _cost_estimate}
```

Internals:
- Build a typed JSON-schema prompt (same shape Stage 8 already expects)
- Walk tiers in order; for each tier, call `select_next()` (only Tier 1 rotates), make the call with `instructor.from_openai` for typed output
- On `429` → `mark_429` + try next slot in same tier
- On `5xx` → exponential backoff with jitter (max 3 attempts per slot)
- On auth `401/403` → black-list the key for that tier for the day
- All other errors → escalate to next tier
- Returns `{"error": "all_tiers_exhausted", "available": False}` after Tier 2 exhausts (Stage 8 will then pass-through with `vlm_likeness=None`)

### 4. Wire Stage-8 to the new router
- **`backend/app/services/image_scorer_service.py`** — replace the `from app.services.vision_service import describe_image_url` import in `_stage_vlm_verify` with `from app.services.carousel_v2.cheap_vlm_router import verify_image`. Adapt the call so the `vlm_*` fields map cleanly into `ScoredCandidate`. **Failure-soft semantics preserved** — Stage 9 composite still ranks usefully without VLM signal.

### 5. Clean up dead Ollama path in vision_service
- **`backend/app/services/vision_service.py`** — delete the Ollama branch entirely (Ollama retired 2026-04-27; the 900 s timeout was the source of the previous hang). Reachy camera use case keeps `describe_image(bytes, prompt)` but that body now routes through `cheap_vlm_router.verify_image` so both Reachy and carousel share one code path.

### 6. Settings + env wiring
- **`backend/app/infrastructure/config.py`** — add `openrouter_api_keys: list[str] = []` derived from `ZERO_OPENROUTER_API_KEYS` (comma-split) with fallback to `[openrouter_api_key]` when set. Same pattern available for Kimi/Gemini if user later adds multi-key support.
- **`.env.example`** — document `ZERO_OPENROUTER_API_KEYS=key1,key2,key3` (plural) alongside the existing singular form.

### 7. Cost + rotation telemetry
- Each VLM call writes to `image_scores.vlm_model` (already a column) the actual model used, e.g. `openrouter/qwen/qwen2.5-vl-72b-instruct:free`.
- Each call's estimated cost recorded in a new `image_scores.vlm_cost_usd` column (Alembic migration 040 — single column add; ORM model already trivially accepts it).
- Hooks into existing Langfuse `_call_provider` tracer so trace dashboard shows per-tier hit rates.

## Critical files

```
NEW    backend/app/services/carousel_v2/openrouter_free_pool.py
NEW    backend/app/services/carousel_v2/cheap_vlm_router.py
NEW    backend/app/migrations/versions/040_image_scores_vlm_cost.py
NEW    backend/tests/carousel_v2/test_cheap_vlm_router.py
NEW    backend/tests/carousel_v2/test_openrouter_free_pool.py
EDIT   backend/app/infrastructure/llm_providers/kimi_provider.py
EDIT   backend/app/infrastructure/llm_providers/openrouter_provider.py
EDIT   backend/app/infrastructure/llm_providers/gemini_provider.py
EDIT   backend/app/services/image_scorer_service.py
EDIT   backend/app/services/vision_service.py             (remove dead Ollama path)
EDIT   backend/app/db/models.py                           (vlm_cost_usd col)
EDIT   backend/app/infrastructure/config.py               (multi-key list)
EDIT   .env.example
```

## Reused infrastructure (no rewrite)
- `app/services/carousel_v2/idempotency.py` — Redis client pattern works for quota state
- `app/infrastructure/langfuse_client.py` — VLM calls go through `_call_provider` so traces appear automatically
- `app/services/image_scorer_service.py` — Stage 9 composite z-score keeps current weights; only the VLM signal source changes
- `instructor` (already in requirements) — typed JSON outputs across all tiers
- `tenacity` (already in requirements) — exponential backoff for 5xx
- `redis>=5.2.0` (already in requirements + container running) — quota state

## Verification

**Unit tests** — `tests/carousel_v2/test_cheap_vlm_router.py`, `test_openrouter_free_pool.py`:
- 429 from Tier 1 model → router rotates to next (key, model) pair without escalating tier
- All Tier-1 slots in cooldown → escalates to Tier 2 (Gemini)
- 5xx with Retry-After → backs off, retries, then escalates
- Auth 401 → blacklists key for the day
- Multi-key: 2 keys × 4 models = 8 slots; verify all are reachable in a round-robin sweep
- Daily-quota math: 50/day × 8 models × N keys = effective free-tier capacity

**Integration smoke** — extend `backend/smoke_test_carousel_v2.py`:
- Remove the `_ScorerStub` so the real `image_scorer_service.score()` runs through the new router
- Curate a known character ("Homelander") via real TMDB + Fanart (keys are set)
- Assert: `image_scores` rows have `vlm_model` populated with at least one of the free OpenRouter slugs **OR** Kimi, `vlm_likeness ∈ [0, 1]`, `vlm_cost_usd ≥ 0`
- Assert: workflow completes within 60 s for 5 candidates (vs the previous 900 s+ hang on dead Ollama)

**Cost regression** — replay 30 candidate images through the router with all keys active:
- Per-image cost ≤ $0.002 (cheap free + Kimi mix)
- Per-carousel Stage-8 spend ≤ $0.05 (well under the $0.15-$0.25 per-carousel target in the original blueprint)

**Live worker re-run** — restart the long-running `python -m app.workflows.worker` inside zero-api, then trigger `live-worker-smoke-2` (a fresh GenerateCarouselWorkflow). Confirm:
- Score_images activity completes in < 60 s (not the prior 900 s timeout)
- `image_scores` rows persist with real `vlm_*` columns
- Workflow reaches `awaiting_review` or `published` (composite ≥ 7.5 with real LLM judges)
- Temporal UI shows green completion

## Risks + mitigations

- **OpenRouter free models churn** — they add/remove free models. Mitigated by dynamic model-list discovery every 6 h.
- **Free-tier quota burst** — 50/day × N keys × 8 models = capacity. If the worker burns through faster than recovery, Tier 0 (Kimi) and Tier 2 (Gemini) catch the overflow. Cost telemetry alerts when Tier 2 hit-rate > 30 % (signal to add more OpenRouter keys).
- **MiniMax was assumed multimodal** — audit confirms text-only. Plan does not add MiniMax to Stage-8 path. The user's mention of MiniMax for designer/skeptic/judges is fine — those are text-only stages.
- **Kimi vision rate limits** — Moonshot doesn't publish exact RPM, but K2.6 is paid so 429 should be rare. Single-key Tier-0 is sufficient at current carousel volume (200-400/day → < 1/min).
- **Gemini paid-tier price** — `gemini-2.0-flash` is ~$0.10 / 1M tokens. Even if Tier 0 + Tier 1 fail completely (worst case), 30 images × 800 tokens ≈ 24 K tokens → $0.0024 per carousel. Budget-safe.
