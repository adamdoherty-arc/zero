# Converge ADA + Legion + Zero onto vLLM

## Context

User wants all three projects (ADA, Legion, Zero) to converge on **vLLM with the latest Qwen 3.6 model**, fixing ADA's "unhealthy" banner in the process and cleaning up each project's LLM call patterns.

**Current reality (verified by `docker ps` and `ollama list`):**
- vLLM is **not actually running**. `legion-vllm` container doesn't exist. Legion's `docker-compose.vllm.yml` is defined but never started, and it points at the wrong model family (`Qwen2.5-Coder-32B-Instruct-AWQ` — stale).
- Legion's LiteLLM proxy IS running (`legion-litellm:4000`) and currently proxies to Ollama on the host.
- Ollama on host has 6 models including the user's new `qwen3.6:35b-a3b-q8_0` (38GB — too big to coexist with vLLM on 32GB VRAM).
- ADA health check pings Ollama and fails → "Backend currently unavailable" banner.

**Target model (latest, verified on HuggingFace):**
- vLLM: **`QuantTrio/Qwen3.6-35B-A3B-AWQ`** — 4-bit AWQ of Qwen 3.6 35B-A3B MoE. Weights ~18-22GB, KV cache ~6GB at 32K context. Fits RTX 5090 with headroom. A3B architecture = only 3B active params per token = very fast inference.
- Embeddings: keep Ollama `nomic-embed-text-v2-moe` (957MB, already loaded).
- Cloud fallbacks: MiniMax M2, Kimi K2.5 (already configured in LiteLLM).
- vLLM version: >=0.19.0 required for Qwen3.6 reasoning parser.

This means:
1. Start vLLM for the first time with the right model.
2. Unload big Ollama chat models to free VRAM (`qwen3.6:35b-a3b-q8_0`, `qwen3-coder-next`).
3. Keep Ollama running only for embeddings.

## Target Architecture

```
   ADA backend ──┐
   Zero backend ─┼──► LiteLLM proxy (legion-litellm:4000) ──► vLLM (legion-vllm:8000)  [Qwen3.6-35B-A3B-AWQ]
   Legion ───────┘                                        └──► MiniMax / Kimi (cloud fallback)
                                                          └──► Ollama (embeddings only, nomic-embed-text-v2-moe)
```

**Why one LiteLLM proxy for all three**
- Single budget ceiling, single retry policy, single observability surface.
- Swap models in one place (`docker/litellm/config.yaml`) — no per-project redeploys.
- Each project uses its own `LITELLM_API_KEY` scoped via LiteLLM's virtual keys → per-project rate limits and cost attribution.

**Why keep Ollama for embeddings**
- vLLM can serve one model per instance. Running a second vLLM for `nomic-embed-text` wastes VRAM.
- Ollama is excellent at small embedding models (fast, low memory, auto-unloads).
- Split: **vLLM = chat/completion (heavy), Ollama = embeddings (light)**.

## VRAM Reality Check — required before anything else

Single RTX 5090 = 32GB. Target steady state:
- vLLM Qwen3.6-35B-A3B-AWQ @ 32K ctx: **~24-26 GB** (18GB weights + ~6GB KV cache + overhead)
- Ollama nomic-embed-text-v2-moe: ~1 GB
- Headroom for Windows + browser + Docker: ~4-5 GB

Works. But **if Ollama also keeps `qwen3.6:35b-a3b-q8_0` (38GB) or `qwen3-coder-next` (51GB) loaded**, you OOM instantly. Step 1 is to purge chat models from Ollama — it becomes an embedding-only service.

Recommended Ollama cleanup (after vLLM proves out):
```
ollama rm qwen3.6:35b-a3b-q8_0 qwen3.6:35b-a3b-q4_K_M qwen3.6:35b-a3b qwen3.6-8k qwen3-coder-next
# Keep: nomic-embed-text-v2-moe
```
Or keep them on disk but ensure `OLLAMA_MAX_LOADED_MODELS=1` and nothing requests them.

## Plan

### Phase 0 — Start vLLM for the first time with the right model

File: `C:\code\Legion\docker-compose.vllm.yml`
- Line 37: change `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` → **`QuantTrio/Qwen3.6-35B-A3B-AWQ`**
- Line 39: served-name stays `qwen3.6` (canonical name all three projects will use)
- Line 43: `--max-model-len 32768` (reduce from 16384 default to leave headroom; A3B has 262K native but we don't need it)
- Add: `--reasoning-parser qwen3` (required by Qwen3.6 official recipe)
- Image: `vllm/vllm-openai:v0.19.0` or newer (pinned — `:latest` drifts)

File: `C:\code\Legion\.env`
- `VLLM_MODEL=QuantTrio/Qwen3.6-35B-A3B-AWQ`
- `VLLM_MAX_MODEL_LEN=32768`
- `VLLM_GPU_UTIL=0.85` (leave 15% for embeddings + OS)

Boot:
```
cd C:\code\Legion
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d legion-vllm
docker logs -f legion-vllm   # first boot: 15-20 min to download weights
curl http://localhost:8000/v1/models   # when healthy, returns qwen3.6
```

### Phase 1 — Make Legion's LiteLLM proxy multi-tenant

Files:
- `C:\code\Legion\docker\litellm\config.yaml` — add virtual API keys for `ada` and `zero`, add vLLM as the primary for chat tasks (currently dormant).
- `C:\code\Legion\docker-compose.yml` — expose LiteLLM port to host (already on 4000) and ensure `legion-network` is reachable from host Docker bridges.
- `C:\code\Legion\.env` — reconcile `OLLAMA_DISABLED` mismatch between root `.env` (`false`) and `backend/.env` (`true`). Final value: `true`.

Changes to `config.yaml`:
- Replace both `qwen3.6` and `qwen3.6:35b-a3b-q8_0` Ollama-backed entries → single `qwen3.6` route pointing at vLLM (`openai/qwen3.6` @ `VLLM_BASE_URL`).
- Keep `qwen3.6-ollama` as a dormant failback (only triggers if vLLM + MiniMax both fail).
- New fallback chain: `qwen3.6 → minimax-m2 → kimi-k2.5-preview → qwen3.6-ollama`.
- Add virtual keys for per-project cost attribution and budgets:
  - `sk-zero-...` budget $20/24h
  - `sk-ada-...` budget $15/24h
  - `sk-legion-...` budget $15/24h (internal)
- Keep `nomic-embed-text-v2-moe` as its own LiteLLM entry pointing at host Ollama (embedding calls still go through the proxy for unified logging).

### Phase 2 — ADA migration (fixes unhealthy banner)

Files:
- `C:\code\ADA\backend\infrastructure\llm_router.py:155-173` — replace direct Ollama client with OpenAI-compatible client pointed at LiteLLM. Model names stay (`qwen3.6:35b-a3b-q8_0` → `qwen3.6` in LiteLLM config).
- `C:\code\ADA\backend\routers\ai_health.py:48-93` — the `_check_ollama()` function becomes `_check_llm_gateway()`, pings `http://host.docker.internal:4000/v1/models` with LiteLLM key.
- `C:\code\ADA\.env` — add `LITELLM_URL=http://host.docker.internal:4000`, `LITELLM_API_KEY=sk-ada-...`, keep `OLLAMA_HOST` only for embeddings.
- `C:\code\ADA\frontend\src\components\GlobalHealthBar.tsx` — no code change; status will go green automatically once backend reports healthy.

Optimization while there:
- ADA's `llm_router.py` has stub references to HuggingFace/Gemini/OpenRouter that aren't used. Remove them — dead code, confuses the routing table.
- Legacy `get_kimi_client()` / `analyze_chart_with_kimi()` shims (`llm_router.py:1535-1558`) — replace callers with direct `router.complete(task_type=...)` calls, then delete shims.

### Phase 3 — Zero migration (opportunistic, safer)

Zero already has a solid multi-provider router. Don't rip it apart — just add vLLM as a provider and reroute the heaviest task types.

Files:
- `C:\code\zero\backend\app\infrastructure\vllm_provider.py` — NEW. Copy `ollama_provider.py`, point at `http://host.docker.internal:4000/v1`, use LiteLLM key, cost estimate `$0`.
- `C:\code\zero\backend\app\infrastructure\llm_router.py` — register `VLLMProvider` alongside existing providers.
- `C:\code\zero\workspace\llm\router_config.json` — reroute heavy local tasks (`character_carousel_generation`, `character_research`, `coding`, `agent_execution`) to `vllm` primary, MiniMax fallback. Keep Kimi as primary for planning. Keep Ollama as embedding-only.
- `C:\code\zero\backend\app\services\character_content_service.py:209` — drop hardcoded `ollama_semaphore`; use shared `_LLM_SEMAPHORE` so vLLM/cloud aren't artificially throttled to Ollama's concurrency.
- `C:\code\zero\backend\app\infrastructure\ollama_client.py` — narrow its use to embeddings (`embed`, `embed_batch`), mark `complete()` methods as deprecated.

Optimization while there:
- `/health/ready` currently checks Ollama non-blocking (good pattern — keep as-is, just add LiteLLM check beside it).
- `gpu_refresh` scheduler job (every 5 min) — currently only reads Ollama VRAM. Extend to query vLLM `/metrics` endpoint.
- Budget enforcement in `unified_llm_client.py:141` still forces Ollama fallback when budget exceeded — change to force vLLM fallback (also $0 cost).

### Phase 4 — Legion cleanup (was P1 before; still needed)

Files:
- `C:\code\Legion\backend\app\services\ollama_manager_service.py` — gate daemon on `OLLAMA_DISABLED`. If disabled, daemon is a no-op. Consider renaming to `LocalModelManagerService` and making it vLLM-aware.
- `C:\code\Legion\backend\app\api\endpoints\service_health.py:69-122` — add `_check_vllm()`, have `_check_ollama()` return "disabled" status cleanly instead of "unhealthy".
- Delete dead code: `backend/app/agents/ollama_experiment_agent.py`, `.claude/skills/legion-ollama-experimenter/`, `backend/docs/ollama_experiment_loop.md`.
- Tests: rename `tests/services/test_ollama_manager.py` → `test_local_model_manager.py`, skip when `OLLAMA_DISABLED=true`.
- `C:\code\Legion\backend\app\services\unified_llm_service.py` — primary routing: `qwen3.6` → vLLM via LiteLLM. Ollama references in `TASK_MODEL_ROUTING` can stay (LiteLLM handles translation) but document that they route to vLLM now.

### Phase 5 — Cross-project optimizations

Patterns worth enforcing everywhere once migration is done:
- **Prompt caching headers**: LiteLLM supports Anthropic-style `cache_control` passthrough. For Zero's repeated-system-prompt services (character content, agent company), enabling cache on system prompts alone saves 40-60% on tokens. Already scaffolded in LiteLLM config (`cache_read` surfacing).
- **Streaming by default**: Zero's character_content_service does non-streaming generations. Switch to streaming where possible — cuts perceived latency ~3x, doesn't change costs.
- **Task-type tagging**: LiteLLM logs every request; with `task_type` metadata on every call, you get per-task cost dashboards in Langfuse/Grafana for free.
- **Shared concurrency**: today each project has its own semaphores on Ollama. With a single vLLM backend, set one global RPM limit at the LiteLLM layer instead — simpler, honest.

## Pros / Cons of This Direction

**Pros**
- **Throughput**: vLLM paged attention + continuous batching → 3-10× Ollama under concurrent load. All three apps can hit it simultaneously without head-of-line blocking.
- **Single control plane**: model swaps, budget caps, rate limits, observability in one place (LiteLLM).
- **Per-project cost attribution**: virtual keys give you real dollar visibility per app.
- **VRAM efficiency**: one 24GB model serves everyone vs. Ollama hot-swapping between per-app model demands (which thrashes VRAM).
- **ADA unhealthy banner resolves** as a byproduct.

**Cons**
- **Model variety loss**: Ollama's superpower is "run any model in 30s." vLLM locks you to one chat model at a time. Experimenting with a new model = `docker compose restart legion-vllm` with different env vars.
- **Single point of failure**: Legion's vLLM dying takes chat down for all three apps. Mitigated by MiniMax/Kimi cloud fallbacks in LiteLLM config.
- **Cold start**: vLLM 5-10 min first boot for model download, ~90s to load from cache. Ollama loads in 10-20s.
- **Coder model compromise**: Qwen2.5-Coder-32B is optimized for code. Fine for Legion and Zero coding paths; adequate for ADA chat; not ideal if ADA's workload is heavy reasoning/research.
- **Coupling**: ADA and Zero now depend on Legion's container being up. Operational entanglement.

## What's Necessary to Keep Healthy

1. **Health checks per project**:
   - ADA: `/api/ai-health/status` pings LiteLLM `/v1/models` (not Ollama).
   - Zero: `/health/ready` pings LiteLLM + Ollama (embedding-only, can be "degraded not failed").
   - Legion: already has good dual-mode checks; clean up after migration.
2. **LiteLLM observability**: enable `json_logs: true` (already on) + wire to Loki or file tail. Without logs a single proxy failure blindsides all three apps.
3. **Fallback test**: pull the vLLM container down and verify each app degrades gracefully to MiniMax. Document RTO.
4. **Boot ordering on Windows**: Docker Desktop auto-starts, then `legion-postgres` → `legion-litellm` → `legion-vllm` → app backends. vLLM's 600s `start_period` in healthcheck handles slow model load.
5. **Budget ceiling**: LiteLLM `max_budget: 50.0 / 24h` is already set. Add per-virtual-key ceilings (e.g. Zero $20, ADA $15, Legion $15).
6. **Model registry consistency**: Zero (`qwen3:35b`), ADA (`qwen3.6:35b-a3b-q8_0`), Legion (`qwen3.6`) — collapse to one canonical name in LiteLLM (`qwen3.6`), aliases map in config.

## Critical Files

| Project | File | Purpose |
|---|---|---|
| Legion | `docker/litellm/config.yaml` | Promote vLLM to primary, add virtual keys |
| Legion | `docker-compose.yml` + `docker-compose.vllm.yml` | Ensure both start together |
| Legion | `.env` + `backend/.env` | Reconcile `OLLAMA_DISABLED=true` |
| Legion | `backend/app/services/ollama_manager_service.py` | Gate on flag |
| Legion | `backend/app/api/endpoints/service_health.py` | Add `_check_vllm` |
| ADA | `backend/infrastructure/llm_router.py` | Point at LiteLLM |
| ADA | `backend/routers/ai_health.py` | Check LiteLLM instead of Ollama |
| ADA | `.env` | Add LITELLM_URL/KEY |
| Zero | `backend/app/infrastructure/vllm_provider.py` (NEW) | vLLM provider class |
| Zero | `backend/app/infrastructure/llm_router.py` | Register vLLM |
| Zero | `workspace/llm/router_config.json` | Reroute heavy tasks |
| Zero | `backend/app/services/character_content_service.py` | Drop Ollama semaphore |
| Zero | `backend/app/infrastructure/ollama_client.py` | Narrow to embeddings |

## Verification

**After Phase 1** (Legion LiteLLM ready for multi-tenant):
```
curl http://localhost:4000/v1/models -H "Authorization: Bearer $LITELLM_MASTER_KEY"
# Expect qwen3.6, minimax-m2, kimi-k2.5-preview
curl -sf http://localhost:8000/health   # vLLM up
```

**After Phase 2** (ADA migrated):
```
curl http://localhost:8003/api/ai-health/status?quick=true
# overall_status == "healthy"; banner gone
docker logs ada-backend 2>&1 | grep -iE "ollama|litellm"  # no Ollama chat errors
```

**After Phase 3** (Zero migrated):
```
curl http://localhost:18792/health/ready   # healthy
docker logs zero-api | grep vllm_provider  # provider active
# Trigger character content generation → LiteLLM logs show request with task_type=character_carousel_generation
```

**After Phase 4** (Legion clean):
```
docker logs legion-backend | grep -i ollama  # silent except one-line DISABLED notice
pytest backend/tests -k "not ollama" -q      # green without Ollama dependency
```

**Fallback drill**:
```
docker stop legion-vllm
# Trigger chat in each app — should succeed via MiniMax fallback in LiteLLM, with added latency logged
docker start legion-vllm
# Traffic auto-resumes on vLLM
```

## Confirmed Decisions

1. **Model**: `QuantTrio/Qwen3.6-35B-A3B-AWQ` (latest Qwen 3.6, fits 32GB VRAM, A3B MoE for speed).
2. **Quant**: AWQ 4-bit (user confirmed "AWQ or whatever").
3. **Embeddings**: Ollama keeps `nomic-embed-text-v2-moe` — no change.
4. **Budgets**: Zero $20 / ADA $15 / Legion $15 per 24h via LiteLLM virtual keys.
5. **Scope**: execute all 5 phases end-to-end.
6. **Canonical name everywhere**: `qwen3.6`. LiteLLM handles the actual HF path.

## Execution Order (what runs first)

1. Phase 0 — start vLLM with new model (15-20 min first boot). Verify `/v1/models`.
2. Phase 1 — update LiteLLM config + add virtual keys, `docker compose restart legion-litellm`. Verify proxy sees vLLM.
3. Phase 4 — Legion backend cleanup + `.env` reconciliation, restart `legion-backend`. Smoke test.
4. Phase 2 — ADA migration. Verify unhealthy banner clears.
5. Phase 3 — Zero vLLM provider addition. Verify character content routes through vLLM.
6. Phase 5 — prompt caching + streaming + observability polish.

Rollback at any step: `docker stop legion-vllm` → LiteLLM auto-falls-back to MiniMax → each app keeps working with slightly higher latency/cost.
