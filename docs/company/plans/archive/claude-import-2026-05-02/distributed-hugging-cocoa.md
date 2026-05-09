# Central LLM Router Across Zero, Ada, Legion (Ollama ↔ vLLM Toggle)

## Context

You've been flip-flopping between Ollama and vLLM and having to edit code each time. The three projects (Zero, Ada, Legion) all call local LLMs differently today — Zero has vLLM+Ollama support already, Ada is Ollama-only, Legion is Ollama-only. Qwen 3.6 landed in April 2026 and is now the best open model for your 5090.

**Goal:** One consistent `LOCAL_LLM_BACKEND=vllm|ollama` env toggle across all three projects, shared vLLM containers (one chat, one embed) used by all three, cloud providers preserved as-is, unit tests + optional live integration tests.

**Why shared containers:** Ollama dynamically swaps models so one instance serves N projects. vLLM pins a model into VRAM permanently — per-project vLLM would multiply VRAM cost by N. Single shared vLLM = VRAM cost scales with distinct models, not distinct projects.

## Target Model Stack (April 2026)

| Role | Model | VRAM (FP8) | Why |
|---|---|---|---|
| Chat/Code | `Qwen/Qwen3.6-35B-A3B-FP8` | ~22 GB | MoE 35B/3B-active. 73.4% SWE-bench. 208 tok/s on vLLM (beats Ollama on decode, first such case). 262K ctx native. |
| Embedding | `Qwen/Qwen3-Embedding-0.6B` | ~1.5 GB | Same family as chat (consistent tokenizer). Top-tier MTEB. Tiny footprint leaves KV-cache headroom on 5090. |

Fits comfortably on 5090 32GB with KV cache headroom. Cloud models (Gemini, MiniMax, Claude, OpenAI, OpenRouter, Kimi) are **unchanged** — they remain per-project as they are today.

**Migration cost:** All three projects must re-embed existing vector stores (Qdrant/pgvector) from nomic-embed → Qwen3-Embedding-0.6B. Each project gets a one-shot re-embed script.

## Architecture

```
                ┌────────────────────────────────────┐
                │  vllm-chat  :8000  (Qwen3.6-35B)    │
                │  vllm-embed :8001  (Qwen3-Embed)    │
                │  ollama    :11434  (swap on demand) │
                └────────────────────────────────────┘
                      ▲          ▲          ▲
                      │          │          │
                ┌─────┴──┐  ┌────┴───┐  ┌───┴────┐
                │  Zero  │  │  Ada   │  │ Legion │
                │ router │  │ router │  │ router │
                └────────┘  └────────┘  └────────┘
                     │          │           │
                     └──── cloud fallbacks ─┘
```

Each project has its **own** router file (parallel implementations — no shared package). All three expose the same interface and read the same env vars.

## Shared .env Contract (identical across all 3 projects)

```env
# Local backend selector
LOCAL_LLM_BACKEND=vllm           # "vllm" | "ollama"

# vLLM endpoints (shared containers)
VLLM_CHAT_BASE_URL=http://localhost:8000/v1
VLLM_EMBED_BASE_URL=http://localhost:8001/v1
VLLM_CHAT_MODEL=Qwen/Qwen3.6-35B-A3B-FP8
VLLM_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B
VLLM_API_KEY=EMPTY               # vLLM ignores but OpenAI SDK requires non-empty

# Ollama endpoint (existing, unchanged)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen3.6:35b-a3b
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b

# Cloud (existing per-project keys remain — unchanged)
# GEMINI_API_KEY, MINIMAX_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, ...
```

## Docker: Shared vLLM Containers

**New file:** `c:\code\shared-infra\docker-compose.vllm.yml` (or co-locate in one of the projects — user's call, default to a new top-level `shared-infra/` folder).

```yaml
services:
  vllm-chat:
    image: vllm/vllm-openai:latest
    command: >
      --model Qwen/Qwen3.6-35B-A3B-FP8
      --port 8000
      --max-model-len 65536
      --gpu-memory-utilization 0.72
    ports: ["8000:8000"]
    deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }] } } }
    volumes: [ "hf-cache:/root/.cache/huggingface" ]
    restart: unless-stopped

  vllm-embed:
    image: vllm/vllm-openai:latest
    command: >
      --model Qwen/Qwen3-Embedding-0.6B
      --port 8001
      --task embed
      --gpu-memory-utilization 0.08
    ports: ["8001:8001"]
    deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }] } } }
    volumes: [ "hf-cache:/root/.cache/huggingface" ]
    restart: unless-stopped

volumes:
  hf-cache:
```

Both containers share one GPU. Memory utilization tuned so chat gets ~22GB and embed gets ~2GB, leaving ~8GB for KV cache growth.

## Per-Project Refactor

Each project keeps **one** router module that exposes this API:

```python
async def chat(messages, *, task: str | None = None, **kw) -> ChatResponse
async def embed(texts: list[str]) -> list[list[float]]
async def stream(messages, **kw) -> AsyncIterator[str]
```

Internally the router:
1. Reads `LOCAL_LLM_BACKEND` → picks vLLM or Ollama for local calls.
2. Both vLLM and Ollama expose OpenAI-compatible endpoints → use `AsyncOpenAI` client with different `base_url` + `model`. **Single code path.**
3. Cloud fallback logic (per-project, preserved from today's code).
4. Preserves each project's existing concurrency/circuit-breaker features.

### Zero (`c:\code\zero`)

Primary file: `backend/app/infrastructure/llm_router.py`

- Already has multi-provider plugins including `vllm_provider.py` and `ollama_provider.py`.
- **Refactor:** collapse "vllm vs ollama" decision behind `LOCAL_LLM_BACKEND`. Remove any per-call provider=`vllm|ollama` parameters that duplicate the toggle. Point `VLLM_CHAT_BASE_URL` at the shared container (update existing `zero-vllm-chat` service or delete it in favor of shared).
- `router_config.json` persisted config: add `local_backend` key that mirrors the env var (env wins on startup).
- Update `workspace/llm/router_config.json` default.
- **Keep:** gemini, minimax, openrouter, huggingface, kimi providers.

### Ada (`c:\code\ada`)

Primary file: `backend/infrastructure/llm_router.py` (`OllamaLLMRouter`, 1,559 lines)

- Currently hard-codes Ollama. Rename class to `LocalLLMRouter`; keep `get_router()` factory stable.
- Add vLLM code path: same `AsyncOpenAI` client, different base URL + model, toggled by `LOCAL_LLM_BACKEND`.
- Keep: global semaphore (`get_ollama_semaphore` → rename to `get_local_llm_semaphore`), circuit breaker, MiniMax fallback, Kimi shim.
- Update `backend/config.py` Settings to add `LOCAL_LLM_BACKEND`, `VLLM_*` vars.

### Legion (`c:\code\legion`)

Primary file: `backend/app/services/unified_llm_service.py`

- Already multi-provider. Add `vllm_client.py` under `backend/app/services/llm_clients/` mirroring `ollama_client.py`.
- Add `LOCAL_LLM_BACKEND` resolution in `unified_llm_service.py` — when task routing picks "local tier", dispatch to either `ollama_client` or `vllm_client` based on the env var.
- Update `backend/app/core/legion_config.py::MODEL_REGISTRY` to add vLLM entries and mark them as the local tier when backend=vllm.
- Update `backend/app/core/config.py` Settings.
- Keep: priority queue, per-provider circuit breakers, Claude/OpenAI/Gemini clients.

## Tests

Each project gets matching test coverage under its existing test dir:

- `test_llm_router_backend_toggle.py` — parametrized over `LOCAL_LLM_BACKEND=vllm|ollama`, asserts the right base URL + model are used. Mocks `AsyncOpenAI` via `unittest.mock` / `respx`.
- `test_llm_router_cloud_fallback.py` — simulate local-down, assert cloud provider picked per that project's existing rules.
- `test_llm_router_embed.py` — toggle embedding backend, assert correct endpoint + dimension shape.
- `test_llm_router_live.py` — **optional** integration test, skipped via `pytest.importorskip`/env check if `VLLM_CHAT_BASE_URL` is unreachable. Actually hits the live containers.

Existing tests to preserve/update:
- Zero: none currently — add fresh.
- Ada: `backend/tests/test_llm_router.py`, `test_ada_llm_service.py` — update for new class name + env var.
- Legion: `backend/tests/services/test_unified_llm.py`, `test_llm_task_routing.py` — extend with backend-toggle cases.

## Re-Embedding Scripts

Each project gets `scripts/reembed_vectors.py`:
- Iterates the vector store, re-embeds with current `LOCAL_LLM_BACKEND`, writes to a new collection/table, atomic swap at the end.
- One-time operation. Safe to run on each project independently.

## Files to Modify (paths)

**Shared (new):**
- `c:\code\shared-infra\docker-compose.vllm.yml`
- `c:\code\shared-infra\README.md` (brief: how to start/stop shared vLLM)

**Zero:**
- `backend/app/infrastructure/llm_router.py`
- `backend/app/infrastructure/config.py`
- `backend/app/infrastructure/llm_providers/vllm_provider.py` (tune)
- `backend/app/infrastructure/llm_providers/ollama_provider.py` (tune)
- `backend/tests/infrastructure/test_llm_router_backend_toggle.py` (new)
- `backend/tests/infrastructure/test_llm_router_cloud_fallback.py` (new)
- `backend/tests/infrastructure/test_llm_router_embed.py` (new)
- `backend/tests/infrastructure/test_llm_router_live.py` (new, skippable)
- `scripts/reembed_vectors.py` (new)
- `.env.example`

**Ada:**
- `backend/infrastructure/llm_router.py` (rename class, add vLLM path)
- `backend/config.py`
- `backend/tests/test_llm_router.py` (extend)
- `backend/tests/test_llm_router_backend_toggle.py` (new)
- `backend/tests/test_llm_router_live.py` (new, skippable)
- `scripts/reembed_vectors.py` (new)
- `.env.example`

**Legion:**
- `backend/app/services/unified_llm_service.py`
- `backend/app/services/llm_clients/vllm_client.py` (new)
- `backend/app/services/llm_clients/ollama_client.py` (tune)
- `backend/app/core/legion_config.py`
- `backend/app/core/config.py`
- `backend/tests/services/test_unified_llm.py` (extend)
- `backend/tests/services/test_llm_router_backend_toggle.py` (new)
- `backend/tests/services/test_llm_router_live.py` (new, skippable)
- `scripts/reembed_vectors.py` (new)
- `.env.example`

## Verification

1. **Start shared infra:** `docker compose -f c:\code\shared-infra\docker-compose.vllm.yml up -d`. Verify `curl http://localhost:8000/v1/models` and `http://localhost:8001/v1/models`.
2. **Set `LOCAL_LLM_BACKEND=vllm` in each project's `.env`**, start each project, hit a chat endpoint, confirm response + no Ollama calls in logs.
3. **Flip to `ollama`**, restart, confirm Ollama is hit instead. Single variable toggle works.
4. **Run unit tests:** `pytest backend/tests/infrastructure/test_llm_router*` (Zero), `pytest backend/tests/test_llm_router*` (Ada), `pytest backend/tests/services/test_llm_router*` (Legion). All green under both backend values.
5. **Run live integration tests** with vLLM up: `pytest -m live` — should hit real endpoints. With vLLM down: same command auto-skips.
6. **Run re-embed scripts** on each project once, verify RAG still returns relevant results.
7. **Cloud fallback check:** stop both local backends, trigger a cloud-eligible task per project, confirm it still succeeds via cloud.

## Out of Scope

- Changing cloud provider selection logic (each project keeps its current rules).
- Consolidating cloud provider code across projects.
- Any frontend/UI work.
- Upgrading `qwen3.6:35b-a3b` tag availability in Ollama — if Ollama hasn't published that tag yet, use whatever Qwen tag is latest in Ollama at runtime. vLLM side uses HF model IDs directly.
