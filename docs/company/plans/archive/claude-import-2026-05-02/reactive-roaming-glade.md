# Central LLM Router Consolidation (Zero + Legion + ADA)

## Context

We just spent ~50 file edits to swap the local Ollama model from `qwen3-coder-next` / `gemma4:*` to `qwen3.6:35b-a3b-q8_0` across Zero, Legion, and ADA. This was painful because every project already has a central LLM router, but most services bypass it and hardcode model strings. Next model swap should be a single `router_config.json` edit plus a `POST /api/llm/default-model`, with zero file edits and zero Docker rebuilds.

**Goal**: every production codepath routes through its project's central router by task type. Model names live in exactly three places per project (router defaults, persisted config, DB overrides). All other references are deleted or replaced with `router.resolve(task_type)` calls.

**Scope confirmed**:
- All 3 projects, one big sweep.
- Council of Agents: add 4 new task types per role to preserve intentional provider diversity.
- Agent Company: keep DB columns as optional overrides with router fallback when NULL.

---

## Phase 1: Zero (c:\code\zero)

### 1.1 Extend router with new task types

Edit [backend/app/models/llm.py](backend/app/models/llm.py) `LlmRouterConfig.task_assignments` defaults and mirror into [workspace/llm/router_config.json](workspace/llm/router_config.json). Add these task types:

| Task type | Primary | Fallbacks | Temperature | Rationale |
|---|---|---|---|---|
| `character_research` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Free local for high-volume character pipeline |
| `complexity_simple` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Cheap tier for planner |
| `complexity_moderate` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Cheap tier for planner |
| `complexity_complex` | `kimi/kimi-k2.5` | `gemini/gemini-3.1-pro-preview`, `ollama/qwen3.6:35b-a3b-q8_0` | 0.3 | Premium tier for hard work |
| `prompt_grading` | `kimi/moonshot-v1-32k` | `ollama/qwen3.6:35b-a3b-q8_0` | 0.2 | Cheap judge |
| `prompt_grading_heavy` | `kimi/kimi-k2.5` | `kimi/moonshot-v1-32k` | 1.0 | Heavy judge |
| `council_ceo` | `kimi/kimi-k2.5` | `gemini/gemini-3.1-pro-preview` | 0.3 | Diversity: premium reasoning |
| `council_researcher` | `kimi/kimi-k2.5` | `kimi/moonshot-v1-32k` | 0.7 | Diversity: premium researcher |
| `council_analyst` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Diversity: local analyst |
| `council_validator` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Diversity: local validator |
| `agent_ceo` | `kimi/kimi-k2.5` | `gemini/gemini-3.1-pro-preview` | 0.7 | AI Company CEO plans |
| `agent_researcher_plan` | `kimi/kimi-k2.5` | `kimi/moonshot-v1-32k` | 0.7 | Plan structured research |
| `agent_researcher_execute` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.7 | Execute research |
| `agent_analyst` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Data analysis |
| `agent_engineer` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.2 | Code generation |
| `agent_validator` | `ollama/qwen3.6:35b-a3b-q8_0` | `kimi/moonshot-v1-32k` | 0.3 | Validation |

### 1.2 Refactor services to use router

1. [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)
   - Delete `RESEARCH_LLM_MODEL = "qwen3.6:35b-a3b-q8_0"` (line 125).
   - Replace all 11 call sites (lines ~895, 1125, 1142, 1474, 1491, 1607, 1924, 1941, 2657, 4622) that pass `model=RESEARCH_LLM_MODEL` with `task_type="character_research"` (unified client already accepts this).

2. [backend/app/services/planner_service.py](backend/app/services/planner_service.py)
   - Delete `COMPLEXITY_MODELS` dict (lines 24-28), `PLAN_MODEL`, `SYNTHESIS_MODEL` constants (lines 30-31).
   - Line 141: replace `model = COMPLEXITY_MODELS.get(complexity, ...)` with `task_type = f"complexity_{complexity}"`.
   - Lines 63, 71, 206: replace `model=PLAN_MODEL` / `model=SYNTHESIS_MODEL` with `task_type="planning"` / `task_type="summarization"`.

3. [backend/app/services/council_service.py](backend/app/services/council_service.py)
   - Replace `COUNCIL_ROLES` provider/model pairs (lines 23-44) with `task_type` per role: `council_ceo`, `council_researcher`, `council_analyst`, `council_validator`.
   - Lines 95, 127 already pass `config["model"]` to structured_chat. Refactor to pass `config["task_type"]` through to the unified client which resolves via router.

4. [backend/app/services/prompt_grader_service.py](backend/app/services/prompt_grader_service.py)
   - Delete `DEFAULT_GRADER_MODEL` / `HEAVY_GRADER_MODEL` constants (lines 94, 99).
   - `_pick_model()` returns a task type string (`prompt_grading` or `prompt_grading_heavy`) instead of a model string.
   - Callers (lines 103, 104, 113, 118, 124) pass the task type through.

5. [backend/app/services/agent_company_service.py](backend/app/services/agent_company_service.py)
   - Lines 192, 209, 217-218: precedence is (a) DB row's `llm_provider`/`llm_model` if non-NULL, else (b) `router.resolve_provider_model(f"agent_{role.id}")` where `role.id` in `{"ceo","researcher","analyst","engineer","validator"}`.
   - Researcher two-tier logic: plan phase uses `agent_researcher_plan`, execute phase uses `agent_researcher_execute`.
   - No migration change required; DB columns stay as optional overrides.

6. [backend/app/models/gpu.py](backend/app/models/gpu.py) line 82:
   - Remove hardcoded `preferred_model` default. Compute lazily from `get_settings().ollama_model` if needed for startup probes only.

### 1.3 Keep as-is (bootstrap/safety)

- [backend/app/models/llm.py](backend/app/models/llm.py): `LlmRouterConfig` defaults (this IS the source of truth).
- [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py) `ollama_model` field: bootstrap-only, used by meeting audit logging and startup probes.
- [backend/app/infrastructure/unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py) line 141: emergency fallback when budget exceeded.
- Meeting services logging `model_used=get_settings().ollama_model`: audit trail, not routing.

### 1.4 Persist and rebuild

- Hand-edit [workspace/llm/router_config.json](workspace/llm/router_config.json) to add the new task assignments.
- Rebuild zero-api: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
- No Alembic migration required.

---

## Phase 2: Legion (C:\code\Legion)

### 2.1 Derive `MODEL_CONTEXT_WINDOWS` from `MODEL_REGISTRY`

[backend/app/services/context_manager.py](C:/code/Legion/backend/app/services/context_manager.py) lines 38-54: replace the hardcoded `MODEL_CONTEXT_WINDOWS` dict with a build step at import:

```python
from app.core.legion_config import MODEL_REGISTRY

def _build_context_windows():
    return {
        cfg.ollama_tag: cfg.context_window
        for mt, cfg in MODEL_REGISTRY.items()
        if cfg.ollama_tag
    }

MODEL_CONTEXT_WINDOWS = _build_context_windows()
```

Single source of truth; next time a model is added to `MODEL_REGISTRY`, context windows stay in sync automatically.

### 2.2 Validate `force_model` against `ModelType` enum + tier aliases

[backend/app/api/endpoints/llm.py](C:/code/Legion/backend/app/api/endpoints/llm.py) `GenerateRequest.force_model` (lines 42-45): add a Pydantic `field_validator` that rejects strings not in `{mt.value for mt in ModelType} | TIER_ALIASES.keys()`. Fail fast with a clear error instead of leaking into downstream Ollama calls.

### 2.3 Docstring updates (cosmetic)

Replace hardcoded Ollama tag examples with tier aliases in:
- [backend/app/services/chains/code_generation_chain.py](C:/code/Legion/backend/app/services/chains/code_generation_chain.py) line 9
- [backend/app/services/chains/fix_chain.py](C:/code/Legion/backend/app/services/chains/fix_chain.py) line 10
- [backend/app/services/sprint_tools.py](C:/code/Legion/backend/app/services/sprint_tools.py) lines 44-45

### 2.4 Leave as-is (legitimate)

- [backend/app/services/brain/planning_cortex.py](C:/code/Legion/backend/app/services/brain/planning_cortex.py): enum IDs in LLM prompt templates, not model routing.
- [backend/app/services/autonomous_sprint_executor.py](C:/code/Legion/backend/app/services/autonomous_sprint_executor.py) line 509: `force_model="primary"` correctly resolves via `TIER_ALIASES`.
- [backend/app/models/enums.py](C:/code/Legion/backend/app/models/enums.py): `ModelType` enum values are DB/API contracts and must remain stable.

Legion has no Docker; restart its API process after edits.

---

## Phase 3: ADA (C:\code\ADA)

### 3.1 Delete orphaned duplicate routers

- Delete [src/services/intelligent_llm_router.py](C:/code/ADA/src/services/intelligent_llm_router.py) (duplicate, not synchronized with backend).
- Delete [backend/utils/ada_local_llm.py](C:/code/ADA/backend/utils/ada_local_llm.py) (all tier constants hardcode the same model; replaced by router).
- `grep -Rn` for remaining imports of both files and redirect to `backend/infrastructure/llm_router.py`.

### 3.2 Expose router via API, delete MODEL_MAPPING

[backend/routers/chat.py](C:/code/ADA/backend/routers/chat.py) lines 216-219: delete `MODEL_MAPPING` dict. Chat endpoint accepts a `task_type` param instead of a `model` string. Add a new endpoint `GET /api/llm/models` that returns the router's resolved models per task type for the frontend dropdown to consume.

### 3.3 Refactor services (priority P0 and P1 only this phase)

**P0 (high-traffic runtime paths)**:
- [backend/services/ada_llm_service.py](C:/code/ADA/backend/services/ada_llm_service.py) lines 354, 497, 733: replace `os.getenv("ADA_CHAT_MODEL", ...)` with `router.route(TaskType.GENERAL)`.
- [backend/services/llm_client.py](C:/code/ADA/backend/services/llm_client.py) line 50: delegate to `get_router()`.
- [backend/services/ai_csp_recommender.py](C:/code/ADA/backend/services/ai_csp_recommender.py) lines 747, 778, 808: drop `model=` params, add `task_type=TaskType.FINANCIAL_ANALYSIS`.
- [backend/services/ai_technical_analyzer.py](C:/code/ADA/backend/services/ai_technical_analyzer.py) line 435: drop hardcoded Claude model, route via `TaskType.TECHNICAL_ANALYSIS`.
- [backend/services/signal_enrichment_pipeline.py](C:/code/ADA/backend/services/signal_enrichment_pipeline.py) lines 369, 388: same.
- [backend/services/llm_judge_service.py](C:/code/ADA/backend/services/llm_judge_service.py) line 133: route via `TaskType.REASONING`.

**P1 (response fields and agent defaults)**:
- [backend/infrastructure/base_agent.py](C:/code/ADA/backend/infrastructure/base_agent.py) lines 523, 602: remove `model=` default; accept `task_type` kwarg.
- [backend/routers/discord.py](C:/code/ADA/backend/routers/discord.py) lines 1301, 1456, 1527: resolve from router instead of hardcoded string in response.
- [backend/routers/multi_strategy_scanner.py](C:/code/ADA/backend/routers/multi_strategy_scanner.py) lines 591, 601: router resolve for `model_used` field.
- [backend/routers/reasoning.py](C:/code/ADA/backend/routers/reasoning.py) line 389: router resolve for recommendation.

**Pydantic response defaults**: [backend/models/strategy_models.py](C:/code/ADA/backend/models/strategy_models.py) line 523, [backend/routers/reasoning.py](C:/code/ADA/backend/routers/reasoning.py) lines 83, 112, 123: remove hardcoded `model_used: str = "..."`; compute at response construction via `router.route(task_type)`.

### 3.4 Add new task types if needed

Extend `TaskType` enum in [backend/infrastructure/llm_router.py](C:/code/ADA/backend/infrastructure/llm_router.py) if the semantics don't map cleanly:
- `TaskType.STRUCTURED_ANALYSIS` (position opportunities)
- `TaskType.CHART_ANALYSIS` (vision tasks)

### 3.5 Keep as-is (bootstrap/tests)

- [backend/config.py](C:/code/ADA/backend/config.py) line 156 `LLM_MODEL`: bootstrap default consumed by router.
- [backend/infrastructure/ai_client.py](C:/code/ADA/backend/infrastructure/ai_client.py) line 103: bootstrap layer.
- [backend/routers/ai_health.py](C:/code/ADA/backend/routers/ai_health.py) line 386 `warmup_ollama_model`: infrastructure concern.
- Test fixtures that hardcode models: legitimate for testing (mark with a comment so future devs don't "helpfully" refactor them).

### 3.6 ADA P2 / P3 (deferred follow-up)

Out of scope for this sweep but documented for future cleanup:
- 30+ test fixtures that hardcode `ADA_CHAT_MODEL`.
- Infrastructure logging in `minimax_chart_scheduler.py` and similar (no routing impact).

Restart ADA backend after edits.

---

## Critical files to read before editing

- [backend/app/models/llm.py](backend/app/models/llm.py) (Zero router defaults; source of truth)
- [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py) (Zero router contract)
- [backend/app/infrastructure/unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py) (how `task_type` propagates)
- [backend/app/services/agent_company_service.py](backend/app/services/agent_company_service.py) (DB fallback pattern)
- `C:/code/Legion/backend/app/core/legion_config.py` (`MODEL_REGISTRY`)
- `C:/code/Legion/backend/app/services/unified_llm_service.py` (`_resolve_force_model` logic)
- `C:/code/ADA/backend/infrastructure/llm_router.py` (`OllamaLLMRouter`, `TaskType` enum)

---

## Verification

1. **Zero grep sweep** (every hardcoded model string below must be intentional):
   ```bash
   grep -RIn --include='*.py' -e '"ollama/' -e '"kimi/' -e '"gemini/' -e '"minimax/' \
     -e '"openrouter/' -e '"qwen3.6' c:/code/zero/backend/app
   # Allowed: models/llm.py (defaults), infrastructure/config.py (bootstrap),
   # unified_llm_client.py line ~141 (emergency fallback), migration 015 (DB seed).
   # Everything else must go through the router.
   ```

2. **Router config contains new task types**:
   ```bash
   curl -s -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" \
     http://localhost:18792/api/llm/config | \
     jq '.task_assignments | keys[]' | \
     grep -E 'character_research|complexity_|prompt_grading|council_|agent_'
   # Expect 16 new task types listed.
   ```

3. **Smoke test each refactored service**:
   - POST `/api/character-content/research` triggers `character_research` task.
   - POST `/api/company/tasks` triggers `agent_*` task types depending on role.
   - POST `/api/council/debate` triggers `council_*` task types for each role.
   - POST `/api/planner/execute` with simple/moderate/complex complexity fires `complexity_*`.
   - Check logs: `docker logs zero-api 2>&1 | grep llm_router_resolve` — every call should show a task_type, no raw model strings.

4. **Router-driven model swap smoke test** (the whole point):
   ```bash
   curl -s -X POST -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" \
     -H "Content-Type: application/json" \
     http://localhost:18792/api/llm/default-model \
     -d '{"model":"ollama/qwen3.5:35b-a3b","update_all_tasks":true}'

   # Trigger any service; verify it uses the new model WITHOUT a rebuild:
   docker logs zero-api --tail 50 | grep 'model=ollama/qwen3.5:35b-a3b'

   # Revert
   curl -s -X POST ... -d '{"model":"ollama/qwen3.6:35b-a3b-q8_0","update_all_tasks":true}'
   ```

5. **Legion**:
   ```bash
   cd C:/code/Legion
   python -c "from backend.app.services.context_manager import MODEL_CONTEXT_WINDOWS; \
     from backend.app.core.legion_config import MODEL_REGISTRY; \
     assert set(MODEL_CONTEXT_WINDOWS) == {c.ollama_tag for c in MODEL_REGISTRY.values() if c.ollama_tag}"
   # Confirms derivation worked.
   ```

6. **ADA**:
   ```bash
   grep -RIn --include='*.py' -e 'intelligent_llm_router' C:/code/ADA
   # Zero hits expected (file deleted).
   grep -RIn --include='*.py' -e 'ada_local_llm' C:/code/ADA
   # Zero hits expected.
   curl -s http://localhost:8006/api/llm/models | jq '.'
   # Returns router-resolved models per TaskType.
   ```

7. **Legion sprint tracking** (per Zero CLAUDE.md rule): create a task under project_id=8 "Consolidate LLM routing through central routers (Phase 1/2/3)" and close when all grep sweeps are clean.

---

## Non-goals

- Not changing ADA's 30+ test fixture hardcodes (P2/P3, follow-up).
- Not renaming Legion `ModelType` enum IDs (DB/API contracts; only `ollama_tag` field value changes).
- Not removing `config.ollama_model` / `config.LLM_MODEL` bootstrap fields; they remain as the very last safety net.
- Not touching frontend model dropdowns (they already render from `/api/llm/available-models`).

---

## Outcome

Swapping a model in the future becomes:
1. `POST /api/llm/default-model` with the new tag (Zero, runtime, no restart).
2. Edit `legion_config.py::MODEL_REGISTRY.ollama_tag` and restart Legion API.
3. Edit `ADA/backend/config.py::LLM_MODEL` and restart ADA backend.

No service files edited. No migrations. No Docker rebuilds (for Zero). The rest of this plan only happens once.
