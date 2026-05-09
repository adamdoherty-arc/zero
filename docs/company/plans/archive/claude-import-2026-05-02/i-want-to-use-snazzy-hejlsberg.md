# LLMRouter — shared LLM infrastructure control plane

## Context

`c:\code\shared-infra` runs vLLM (Qwen3-32B-AWQ chat + Qwen3-Embedding-0.6B) and the central LiteLLM proxy on `:4444` for **Zero**, **Legion**, and **ADA**. Today the management surface is split across:

- `shared-infra/docker-compose.vllm.yml` (vLLM + LiteLLM)
- `shared-infra/litellm/config.yaml` (model registry, fallbacks, $50/24h budget)
- `scripts/nssm/install-services.ps1` (NSSM `SharedInfra-Stack` service)
- `scripts/health-watchdog.py` (vault status writer)
- Legion's `backend/app/agents/llm_ops/*` (model research, daily reports, planner, response curator, vendor feeds — already shipped, see migration `040_llm_ops_project.py`)

Two acute problems:

1. **vLLM is in a tight crash-restart loop.** The shared-infra dir has 580+ `nssm-stderr-*.log` files spanning 4 hours — one crash every ~25 seconds. Root cause is two stacked bugs (see §2).
2. **No clean control plane.** Redeploys mean editing files in `shared-infra/` then bouncing the NSSM service. There is no swap workflow, no deploy history, no smart routing layer, no privacy gate, no per-project budget visibility, no UI.

`c:\code\LLMRouter\` is empty. This plan turns it into the **infrastructure control plane**: it owns the lifecycle of vLLM/Ollama/LiteLLM, exposes a smart router (PII gating + intent-based local-vs-cloud) in front of LiteLLM, and provides an API + UI to deploy, swap, monitor, and surface Legion's model-research reports. Legion's `llm_ops` keeps owning *what to run* (research, A/B eval, swap proposals); LLMRouter owns *how it runs* (deploy, health, traffic shaping, redeploy from this repo).

The 12-week ecosystem plan (`review-the-two-lively-cascade.md`) Stage 4 originally put a Not Diamond router inside Legion. Research below pulls that decision forward into LLMRouter and replaces Not Diamond with **vLLM Semantic Router** (Red Hat, March 2026 GA). See §3 for the rationale.

---

## 1. Architecture

```
                 Zero / Legion / ADA / Reachy / Claude Code
                           │  (canonical model name + partition tag)
                           ▼
        ┌────────────────────────────────────────────────┐
        │  LLMRouter API :4445  (this project)            │
        │  ────────────────────────────────────────────  │
        │  Smart router      → vLLM Semantic Router      │
        │  Privacy gate      → PII / partition enforcer  │
        │  Cost ceiling      → per-project + global $/24h │
        │  Routing decision  → local | cloud | refuse    │
        │                                                  │
        │  Control plane     → /deploy /restart /swap    │
        │                       /catalog /reports         │
        │  Surfaces          → React UI :5174            │
        └────────────────────────────┬────────────────────┘
                                     ▼
                       LiteLLM Proxy :4444 (gateway)
                       fallbacks · budget · provider creds
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
   vllm-chat :18800            vllm-embed :8001            Ollama :11434
   Qwen3.6-35B-A3B-AWQ          Qwen3-Embedding-0.6B        qwen3-coder-next
   (+ Qwen3-Reranker-0.6B)                                  (escalation tier)
                                     │
                                     ▼
                       Cloud passthrough (LiteLLM):
                       Anthropic · Gemini · Kimi · MiniMax · OpenRouter

   Postgres (legion DB)         Langfuse (self-host)         Discord webhook
   swap_history, deploys,       traces, cost, evals          deploy notifications
   approvals
```

### Boundary with Legion's existing `llm_ops`

- **Legion owns:** model research (HF/NVIDIA feed crawlers), daily report generation, A/B eval matrix, swap *proposals* with measured wins. Already built. Tables `LLMModelCatalogDB`, `LLMDailyReportDB`, `LLMModelDiscoveryDB`, `LLMResponseTraceDB` in the `legion` Postgres database.
- **LLMRouter owns:** smart routing in front of LiteLLM, vLLM/Ollama/LiteLLM container lifecycle, deploy/swap *execution*, health, GPU budget enforcement, crash-loop prevention, deploy history, NSSM-replacement supervisor.
- **Contract:** Legion writes a swap proposal row → LLMRouter polls `/llm-ops/proposals` from Legion, surfaces it in the UI for one-click approve, then executes the swap (compose edit + container restart + LiteLLM hot reload + canary check + rollback on failure).

---

## 2. Phase 0 — stop the crash loop (Day 1, before anything else)

The user picked "both in parallel," so this happens immediately while the rest of LLMRouter scaffolds.

### Root cause (confirmed by research)

Two stacked bugs:

1. **Compose drift.** `docker-compose.vllm.yml` declares `--max-model-len 8192`, `--gpu-memory-utilization 0.85`. Running container shows `max_model_len=16384`, `gpu_memory_utilization=0.72`, plus `num_gpu_blocks_override=512`. That last flag is *never* set by default — there is a phantom override (likely `docker-compose.override.yml`, an env var like `VLLM_MAX_MODEL_LEN`, or NSSM `AppParameters` injecting old args). The user's compose changes never took effect.
2. **vLLM 0.19 CUDA-graph profiler regression.** v0.19 charges the CUDA-graph memory (~0.64 GiB) against the KV budget that v0.18.x didn't. With weights at 18.14 GiB + graphs at 0.64 GiB on a `--gpu-memory-utilization=0.72` budget (≈23 GiB), KV cache lands at **−4.76 GiB** → `ValueError: No available memory for the cache blocks` → exit 1 → restart. (See vLLM issues #35743, #39010, #39025, #40742.)

### Phase 0 actions (read-only diagnosis first, then minimal write)

1. **Find the phantom args** (READ ONLY):
   - `docker compose -f c:\code\shared-infra\docker-compose.vllm.yml config` — see resolved compose
   - `nssm dump SharedInfra-Stack` — see the literal command NSSM runs
   - `ls c:\code\shared-infra\docker-compose.override.yml` — Compose auto-merges this if it exists
   - `docker inspect vllm-chat --format '{{json .Config.Cmd}} {{json .Config.Env}}'` — final source of truth
   - `gci env: | findstr -i vllm` — host env vars leaking in
2. **Apply the compose fix** to `c:\code\shared-infra\docker-compose.vllm.yml`:
   - Pin image: `vllm/vllm-openai:v0.19.1` (no `:latest`)
   - Add env: `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
   - Command flags (canonical):
     ```
     --model Qwen/Qwen3-32B-AWQ
     --served-model-name qwen3-chat
     --host 0.0.0.0 --port 8000
     --max-model-len 8192
     --gpu-memory-utilization 0.80
     --kv-cache-dtype fp8
     --enable-prefix-caching
     --max-num-batched-tokens 2096
     --disable-log-requests
     --disable-frontend-multiprocessing
     ```
   - **Remove** any `--num-gpu-blocks-override` once the source is found.
3. **Delete or rewrite `docker-compose.override.yml`** if it's the source of phantom args.
4. **Pin LiteLLM image** off `:main-stable` to `ghcr.io/berriai/litellm:main-v1.81.14-stable` (1.82.7 / 1.82.8 were credential-stealer compromised — Cycode, Mar 24 2026 supply chain attack).
5. **Fix the NSSM pattern** in `scripts/nssm/install-services.ps1`. Today: `nssm install SharedInfra-Stack docker compose -f docker-compose.vllm.yml up` (foreground, no `-d`) — that fights Docker's `restart: unless-stopped` policy. Replace with a supervisor PowerShell script that runs `docker compose up -d` once after Docker is healthy and monitors `docker inspect`. Add `nssm set ... AppThrottle 60000` and `nssm set ... DependOnService com.docker.service`.
6. **Purge old NSSM logs** — 580 files in `shared-infra/`. Add a `.gitignore` and rotate.
7. **Smoke test:** `curl http://localhost:18800/v1/models`, then a real chat completion via LiteLLM `:4444`, then a Zero/Legion request.

If the GPU still feels tight after this (Reachy spikes), the architectural fallback is **swap chat to Qwen3-14B-AWQ** (~9 GiB resident, ~18 GiB headroom) — but try the args fix first.

---

## 3. Phase 1 — LLMRouter scaffolding (Week 1)

### Stack

- **Backend:** Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy async + Alembic. Reuses `legion` Postgres database (new schema `llmrouter`). Pin packages with uv.
- **Frontend:** React + Vite + TanStack Query, mounted at `:5174`. Visual style matches Legion `:3001`.
- **Auth:** shared bearer key with Legion (`LLMROUTER_MASTER_KEY` env), per-project subkeys for project attribution.
- **Process model:** uvicorn behind NSSM service `LLMRouter-API`, replaces `SharedInfra-Stack` in role.

### Repo layout

```
c:\code\LLMRouter\
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry, mounts routers
│   │   ├── core/
│   │   │   ├── config.py            # pydantic-settings, env loaders
│   │   │   ├── database.py          # async engine + session factory
│   │   │   └── security.py          # bearer-key auth + project attribution
│   │   ├── routing/                 # see §4 — the smart router
│   │   │   ├── semantic_router.py   # vLLM Semantic Router client wrapper
│   │   │   ├── privacy_gate.py      # partition → backend enforcement
│   │   │   ├── cost_gate.py         # per-project $/24h
│   │   │   └── decision.py          # final routing function
│   │   ├── lifecycle/               # see §5 — the control plane
│   │   │   ├── vllm_supervisor.py   # docker / compose actions
│   │   │   ├── litellm_reload.py    # hot-reload LiteLLM config
│   │   │   ├── compose_writer.py    # safe edits to docker-compose.vllm.yml
│   │   │   ├── litellm_writer.py    # safe edits to litellm/config.yaml
│   │   │   ├── canary.py            # post-deploy health probes
│   │   │   └── rollback.py          # revert on canary failure
│   │   ├── catalog/                 # what runs where right now
│   │   │   ├── runtime_state.py     # poll vllm + ollama for live state
│   │   │   └── reports.py           # surface Legion llm_ops reports
│   │   ├── api/
│   │   │   ├── route.py             # POST /v1/chat/completions, /embeddings — OpenAI-compatible
│   │   │   ├── deploy.py            # POST /admin/deploy, /admin/restart
│   │   │   ├── swap.py              # POST /admin/swap (model swap workflow)
│   │   │   ├── catalog.py           # GET /catalog, /catalog/runtime
│   │   │   ├── reports.py           # GET /reports/latest (proxies Legion)
│   │   │   ├── health.py            # /healthz, /readyz, /diag
│   │   │   └── budget.py            # GET /budget/today, /budget/by-project
│   │   ├── models/
│   │   │   ├── deploy.py            # DeployHistory, ContainerEvent
│   │   │   ├── swap.py              # SwapProposal, SwapExecution
│   │   │   ├── route_trace.py       # routing decisions for eval
│   │   │   └── budget.py            # cost rollups
│   │   └── observability/
│   │       └── langfuse.py          # OTel trace context, cost callback
│   ├── alembic/
│   │   └── versions/001_init.py
│   ├── pyproject.toml               # uv-managed
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx        # health + VRAM + req/s + $/day
│   │   │   ├── Catalog.tsx          # current + candidate models
│   │   │   ├── Deploy.tsx           # one-click swap with diff preview
│   │   │   ├── Crashes.tsx          # crash log triage (parsed nssm logs)
│   │   │   ├── Routing.tsx          # routing trace explorer
│   │   │   └── Reports.tsx          # Legion's llm_ops daily reports
│   │   └── api/client.ts
│   └── package.json
├── infra/
│   ├── docker-compose.vllm.yml      # MOVED from shared-infra (LLMRouter is source of truth)
│   ├── litellm/
│   │   └── config.yaml              # MOVED from shared-infra
│   ├── docker-compose.router.yml    # vLLM Semantic Router container
│   └── nssm/
│       └── install.ps1              # registers LLMRouter-API + supervisor
├── scripts/
│   ├── deploy.ps1                   # CLI: llmrouter deploy [--canary]
│   ├── swap.ps1                     # CLI: llmrouter swap qwen3-chat qwen3.6-35b-a3b
│   ├── diag.ps1                     # one-shot diagnostic dump for crash triage
│   └── migrate-from-shared-infra.ps1 # one-time: move ownership from c:\code\shared-infra
├── README.md
├── ARCHITECTURE.md
└── MANDATE.md
```

### Migration from shared-infra

`scripts/migrate-from-shared-infra.ps1` (one-time, idempotent):

1. Copy `c:\code\shared-infra\docker-compose.vllm.yml` → `c:\code\LLMRouter\infra\docker-compose.vllm.yml` (with the Phase 0 fixes applied).
2. Copy `c:\code\shared-infra\litellm\config.yaml` → `c:\code\LLMRouter\infra\litellm\config.yaml`.
3. Stop NSSM `SharedInfra-Stack`, register `LLMRouter-Stack` pointing at `LLMRouter\infra\docker-compose.vllm.yml`.
4. Leave `c:\code\shared-infra\` in place with a `DEPRECATED.md` and a symlinked `docker-compose.vllm.yml → ..\LLMRouter\infra\docker-compose.vllm.yml` so any stale tooling still finds it.

---

## 4. Phase 2 — smart router (Week 2)

The user picked "Full smart router (LangChain/Not Diamond/RouteLLM)." Research substantially changed the answer:

- **Not Diamond's LiteLLM module is deprecated.** They're a 24-person seed-stage shop and their core value prop is now matched by LiteLLM's own Adaptive Router (beta) + Semantic Router LoRA. Not Diamond is **out**.
- **RouteLLM (LMSYS) is effectively unmaintained** (last meaningful update Aug 2024) and is fundamentally a 2-model picker. Wrong shape. **Out.**
- **LangGraph for routing is wrong layer** — reported 2× latency overhead, belongs above the gateway. **Out.**
- **vLLM Semantic Router (Athena v0.2, Mar 2026)** is the right answer. Red Hat-backed, ships ModernBERT+LoRA classifiers including a **PII classifier** out of the box, designed for exactly this seat (semantic in front of LiteLLM/vLLM). **In.**
- **LiteLLM Auto Router + Adaptive Router** (v1.74.9+) cover semantic embedding routing and online learning of per-task winners as first-party features. Use these to *replace* the parts that would have needed Not Diamond.

### Architecture

```
incoming request
    ▼
LLMRouter /v1/chat/completions  (OpenAI-compatible)
    │
    ├─→ partition tag check (hard rule)
    │     vault-write | trading | personal-pii | health → local_only=true
    │
    ├─→ vLLM Semantic Router classify
    │     intent: code | reason | summarize | classify | chat
    │     pii_score, jailbreak_score
    │
    ├─→ cost gate: per-project budget today + global $50/24h ceiling
    │
    ├─→ decision matrix:
    │     local_only=true       → qwen3-chat or qwen3-coder
    │     intent=code, lang=py  → qwen3-coder-30b-a3b
    │     intent=classify       → qwen3.5-2b
    │     intent=reason, hard   → claude-sonnet-4-6 (if budget)
    │     intent=chat, simple   → claude-haiku-4-5
    │     fallback              → LiteLLM Adaptive Router decides
    │
    └─→ forward to LiteLLM with chosen canonical name + trace headers
```

### Components

- `routing/semantic_router.py` — async client to vLLM Semantic Router sidecar (`docker-compose.router.yml` adds the container). Returns `(intent, pii_score, jailbreak_score)`.
- `routing/privacy_gate.py` — reads `X-Partition` header; enforces `vault-write | trading | personal-pii | health → local_only`. Combines with semantic router PII score (defense in depth).
- `routing/cost_gate.py` — Postgres-backed rolling 24h cost lookup; returns `cloud_allowed: bool`. Integrates with LiteLLM's `/spend/logs`.
- `routing/decision.py` — pure function `(prompt, partition, classifier_output, cost_state) → canonical_model_name`. Logged every call to `route_trace` table for offline eval.
- All routes emit OTel spans to **Langfuse self-host** (already a target architecture). Adds Phoenix Arize later for offline drift analysis.

### What gets persisted

`route_trace` table (one row per request): `request_id, project, partition, intent, pii_score, decided_model, latency_ms, cost_usd, success, fallback_used`. This is the eval set Legion's `llm_ops.weekly_eval` consumes to retrain the semantic router LoRA.

---

## 5. Phase 3 — control plane (Week 2–3, in parallel with Phase 2)

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /catalog` | LiteLLM model registry + which backend each routes to |
| `GET /catalog/runtime` | Live state: GPU mem, loaded models, RPS, p50/p99 |
| `POST /admin/deploy` | Apply a compose change, restart container, run canary |
| `POST /admin/restart {service}` | Bounce vllm-chat / vllm-embed / litellm without full redeploy |
| `POST /admin/swap` | Swap a model (e.g., `qwen3-chat: Qwen3-32B-AWQ → Qwen3.6-35B-A3B-AWQ`) — edits compose + LiteLLM config + canary + rollback |
| `GET /reports/latest` | Proxies Legion `/llm-ops/reports/latest` so the LLMRouter UI shows research output without leaving the page |
| `GET /budget/today` | Today's spend by provider + project |
| `GET /diag` | One-shot: container args (vs compose declared), env, GPU memory, last 50 crash log lines, NSSM service state |
| `POST /admin/canary {target_model}` | Send N test prompts, return latency/quality delta |
| `POST /admin/rollback` | Revert last deploy from `deploy_history` |

### Safe-edit pattern for compose & LiteLLM config

`compose_writer.py` and `litellm_writer.py` both:

1. Read current file with mtime.
2. Apply structured edit via ruamel.yaml (preserves comments + ordering).
3. Compare mtime; abort if changed under us (manual edit detected → require force flag).
4. Write to a temp file, atomic rename.
5. Record full before/after diff in `deploy_history` table with deploy_id.
6. Trigger restart + canary; on failure, restore from `deploy_history`.

LiteLLM hot reload: send `POST /reload/config` if the LiteLLM image supports it; otherwise `docker compose restart shared-litellm`.

### Crash log triage

`Crashes.tsx` parses `nssm-stderr-*.log` files (or rolled service logs once NSSM is fixed) into structured events: timestamp, error class, stack hash. Groups by stack hash so 580 identical crashes show as one row with count=580. Each row links to `/diag` snapshot.

### Approval flow for swaps

1. Legion `llm_ops.planner` writes proposal to its `LLMSwapProposal` table.
2. LLMRouter polls and surfaces in UI.
3. User clicks Approve → LLMRouter applies compose change, restarts, canaries (10 prompts vs old model, compares latency + simple quality probe).
4. On canary pass: write `swap_execution` row, post Discord summary.
5. On canary fail: rollback, write incident row, alert.

---

## 6. Phase 4 — model upgrades surfaced through swap workflow (Week 3+)

Driven through the new swap workflow above. From local-LLM research:

| Role | From | To | Why |
|---|---|---|---|
| Chat | Qwen3-32B-AWQ | **Qwen3.6-35B-A3B-AWQ** (`QuantTrio/Qwen3.6-35B-A3B-AWQ`) | MoE 3B-active, ~2× throughput at same/better quality, same VRAM bucket (~20 GB) |
| Code | (same as chat) | **Qwen3-Coder-30B-A3B-AWQ-4bit** (`cpatonn/...`) | 51.6 SWE-Verified with OpenHands, native 256K, built for coding-agent function calls |
| Coder escalation | — | **qwen3-coder-next 80B-A3B** GGUF on Ollama with RAM offload | Sonnet-class for hard problems, on demand only |
| Reranker | (none) | **Qwen3-Reranker-0.6B** | Adds reranking tier, ~1.5 GB, same family as embed |
| Classifier | (none) | **Qwen3.5-2B-Instruct** | Dedicated 2B for the smart router's intent classification |
| Embed | Qwen3-Embedding-0.6B | (stay) | Still best-in-class for size |
| Vision | — | **skip locally** | Qwen3-VL-8B is good but 10 GB on a tight GPU isn't worth it; cloud Gemini is fine |

Each swap goes through the workflow in §5. Legion's `llm_ops` already has the research feed wired; LLMRouter surfaces those reports in `Reports.tsx` and offers one-click "create swap proposal."

### Ollama role

Optional secondary backend, controlled by LLMRouter:

- LLMRouter manages `start-ollama.ps1` env vars and lifecycle.
- LiteLLM keeps `ollama-qwen3-chat` as a vLLM fallback alias.
- New: `qwen3-coder-next-ollama` route for the coder escalation tier.
- UI toggle: "Enable Ollama tier" — disables ollama models in LiteLLM if off, frees 1 GPU slot.

---

## 7. Phase 5 — replace SharedInfra-Stack NSSM (Week 3)

Update `scripts/nssm/install-services.ps1` to register **`LLMRouter-API`** (uvicorn for the FastAPI) and **`LLMRouter-Stack`** (the supervisor for the docker compose, with the AppThrottle + dependency fixes from Phase 0). Remove `SharedInfra-Stack`.

Keep `Legion-Stack`, `Zero-Stack`, `Reachy-Daemon`, `Health-Watchdog` as-is; only the LLM-infra service changes.

`Health-Watchdog` (`scripts/health-watchdog.py`) gets two new probes added: `LLMRouter-API :4445/healthz` and `vLLM Semantic Router :8090/healthz`.

---

## 8. Critical files to create / modify

**Create (LLMRouter):**
- `c:\code\LLMRouter\backend\app\main.py`
- `c:\code\LLMRouter\backend\app\routing\{semantic_router,privacy_gate,cost_gate,decision}.py`
- `c:\code\LLMRouter\backend\app\lifecycle\{vllm_supervisor,litellm_reload,compose_writer,litellm_writer,canary,rollback}.py`
- `c:\code\LLMRouter\backend\app\api\{route,deploy,swap,catalog,reports,health,budget}.py`
- `c:\code\LLMRouter\backend\app\models\{deploy,swap,route_trace,budget}.py`
- `c:\code\LLMRouter\backend\alembic\versions\001_init.py` (new tables in `llmrouter` schema, `legion` database)
- `c:\code\LLMRouter\frontend\src\pages\{Dashboard,Catalog,Deploy,Crashes,Routing,Reports}.tsx`
- `c:\code\LLMRouter\infra\docker-compose.vllm.yml` (with Phase 0 fixes)
- `c:\code\LLMRouter\infra\litellm\config.yaml` (pinned image)
- `c:\code\LLMRouter\infra\docker-compose.router.yml` (vLLM Semantic Router sidecar)
- `c:\code\LLMRouter\scripts\{deploy,swap,diag,migrate-from-shared-infra}.ps1`
- `c:\code\LLMRouter\{README,ARCHITECTURE,MANDATE}.md`

**Modify (existing):**
- `c:\code\shared-infra\docker-compose.vllm.yml` — Phase 0 hot-fix, then deprecate
- `c:\code\shared-infra\litellm\config.yaml` — Phase 0 image pin, then move
- `c:\code\scripts\nssm\install-services.ps1` — fix `SharedInfra-Stack` pattern, then replace with LLMRouter services
- `c:\code\scripts\health-watchdog.py` — add LLMRouter + Semantic Router probes
- `c:\code\ARCHITECTURE.md` — update topology diagram and routing-table sections
- `c:\code\MANDATE.md` — Legion mandate adjusted: research/eval owner; LLMRouter is execution owner
- `c:\code\Legion\backend\app\agents\llm_ops\planner.py` — change "executes swap" to "writes proposal for LLMRouter to execute"
- `c:\code\Legion\MANDATE.md` — boundary update vs LLMRouter

**Reuse (do not duplicate):**
- Legion's `model_researcher.py`, `vendor_feeds/*`, `report_generator.py` — call via Legion API
- Legion's `LLMModelCatalogDB`, `LLMDailyReportDB`, `LLMResponseTraceDB` tables — read from same `legion` DB
- `c:\code\scripts\health-watchdog.py` — add probes, don't replace
- LiteLLM proxy itself — keep as the gateway, never replace

---

## 9. Verification plan

**Phase 0 (Day 1) acceptance:**
- `docker logs vllm-chat` shows model loaded + `Available KV cache memory > 0 GiB`
- `curl http://localhost:18800/v1/models` returns 200 with `qwen3-chat`
- Zero/Legion/ADA each successfully complete one chat call via `:4444`
- 30 minutes of uptime with no restarts (`docker inspect vllm-chat | grep RestartCount`)

**Phase 1 (Week 1) acceptance:**
- `LLMRouter-API :4445` runs as NSSM service
- `GET /healthz`, `/diag`, `/catalog` all 200
- One-click `POST /admin/restart vllm-chat` works end-to-end with canary
- Migration script moves ownership to LLMRouter without dropping a request

**Phase 2 (Week 2) acceptance:**
- vLLM Semantic Router classifies 100 sample prompts; manual review shows ≥90% intent match
- Privacy gate blocks 10 synthetic vault-write requests from reaching cloud
- Cost gate triggers at $5 test budget, returns 429 cleanly
- Routing decisions logged to `route_trace` for offline review

**Phase 3 (Week 3) acceptance:**
- One real swap executes via UI: `qwen3-chat: Qwen3-32B-AWQ → Qwen3.6-35B-A3B-AWQ`
- Canary catches a forced-fail (mock the new model returning gibberish) and rolls back
- Discord notification fires on deploy + on swap

**End-to-end demo:** Legion's daily `llm_ops.research` writes a proposal at 03:00 → next morning, LLMRouter UI shows "1 swap pending" → user clicks Approve → 90 seconds later: container restarted on new model, canary green, Discord notified, `swap_execution` row written.

---

## 10. Out of scope / explicitly deferred

- **Replacing LiteLLM proxy.** Bifrost is 50× faster but LiteLLM is fine until proven a bottleneck. Same architecture lets us swap later.
- **Letta/Mem0/LangMem memory layer.** Owned by Legion's Stage 3 plan; LLMRouter does not touch.
- **MCP server for LLMRouter.** Defer to after the Stage 3 LangGraph supervisor lands in Legion.
- **Multi-GPU / cloud bursting.** Out of scope for a single 5090.
- **Phi-5 / GLM-5.1 / DeepSeek R3.** Don't fit 32 GB single-GPU; not on the roadmap.

---

## Appendix A — research files (full versions written by sub-agents)

- `C:\Users\hadam\.claude\plans\i-want-to-use-snazzy-hejlsberg-agent-a18b7d4c6ead83804.md` — full router landscape comparison (Not Diamond, RouteLLM, LiteLLM Auto/Adaptive Router, vLLM Semantic Router, LangGraph, OpenRouter, Bifrost, Helicone, Langfuse, Phoenix)
- `C:\Users\hadam\.claude\plans\i-want-to-use-snazzy-hejlsberg-agent-a8dd27b2b39f4e1ea.md` — full vLLM crash diagnosis with vLLM GitHub issue references
- `C:\Users\hadam\.claude\plans\i-want-to-use-snazzy-hejlsberg-agent-a8fb5e07d51e59794.md` — full local-LLM survey for 32 GB / Q2 2026

## Appendix B — known security pin

LiteLLM **must** pin to `main-v1.81.14-stable` or later (avoid `1.82.7`, `1.82.8`). Per `MANDATE.md` operational invariant #7 and Cycode's March 24 2026 supply-chain advisory.
