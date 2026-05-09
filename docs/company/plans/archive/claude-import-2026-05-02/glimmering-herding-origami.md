# Plan: Gemma 4 Full Cleanup — Bypasses, Dashboard, Tests, Docs

## Context

The LLM router was updated with Gemma 4 models (replacing deepseek-r1, qwen3.5:27b, qwen3.5:9b). The router itself is correct, but 6 services bypass it with hardcoded models, tests reference deleted models, the `LLMProvidersSection` UI exists but is dead (backend returns dummy data), and docs are stale.

## Phase 1: Fix 6 Router Bypasses

Route all LLM calls through the centralized router.

### 1a. `src/xtrades/analyzer.py` (~line 164)
- **Problem**: Direct `ChatOpenAI(base_url=ollama)` bypassing router
- **Fix**: Import `get_chat_openai(TaskType.FINANCIAL_ANALYSIS)` and use it instead of manual ChatOpenAI construction
- Keep the Anthropic/OpenAI cloud paths as-is (intentional external API)

### 1b. `src/ada/agents/trading/options_flow_agent.py` (~line 355)
- **Problem**: `model="qwen2.5:14b"` hardcoded. File header says "DEPRECATED"
- **Fix**: Replace hardcoded model call with `get_router().generate_text(prompt, task_type=TaskType.FINANCIAL_ANALYSIS)`

### 1c. `src/ai_options_agent/llm_manager.py` (~lines 114, 314)
- **Problem**: Direct ChatGroq + ChatAnthropic instantiation
- **Fix**: Route the Ollama path through `get_chat_openai()`. Keep Groq/Anthropic paths as intentional cloud provider options (they're configured via user API keys)

### 1d. `src/ada/omnipresent_ada.py` (~line 392)
- **Problem**: Direct `ChatGroq(model="llama-3.1-70b-versatile")`
- **Fix**: Replace with `get_chat_openai(TaskType.GENERAL)` for the Ollama/default path. Keep Groq as optional cloud fallback behind API key check

### 1e. `src/multimodal/vision_analyzer.py` (~lines 370, 409)
- **Problem**: Direct OpenAI + Anthropic clients for vision
- **Fix**: Keep as-is — vision requires specific multimodal APIs (OpenAI GPT-4V, Anthropic Claude). Kimi vision path already uses `get_kimi_client()` correctly. Add comment documenting intentional bypass.

### 1f. `backend/services/llm_client.py` (~line 185)
- **Problem**: Legacy `LLMClient` with direct completions API
- **Fix**: Verify constructor sources client from router. If not, refactor to delegate to `get_router()`

### 1g. `backend/infrastructure/base_agent.py:523` + `backend/routers/reasoning.py:84,123,408`
- **Problem**: Default `model="qwen-coder"` (stale name)
- **Fix**: Update defaults to `"qwen3-coder-next"`. These are cosmetic since actual routing goes through `get_router()`, but misleading.

## Phase 2: Wire LLM Dashboard (Backend)

Replace ALL dummy data in `backend/routers/provider_config.py` with real data from the router. The frontend component `frontend/src/components/settings/LLMProvidersSection.tsx` already has the complete UI — it just needs real endpoints.

### 2a. `GET /api/providers/health` — Replace dummy with real provider health
- Query `get_router().check_health()` for Ollama status + loaded models
- Query `is_kimi_available()` for cloud status
- Return concurrency stats from `get_router().get_concurrency_stats()`
- Match frontend `LLMProvider` interface: `{ provider_name, display_name, is_available, avg_latency_ms, cost_per_m_input }`

### 2b. `GET /api/providers/services/by-category` — NEW endpoint (frontend expects this)
- Build service-to-model mapping from actual `TaskType` usage across the codebase
- Group into 4 categories matching frontend: `analysis`, `trading`, `chat`, `system`
- Return `LLMService` objects: `{ service_name, display_name, description, provider_chain, requires_vision, use_cache, timeout_seconds, enabled }`
- Source the mapping from a static registry dict in `provider_config.py` that maps service names to their TaskType + metadata

### 2c. `GET /api/providers/models` — NEW endpoint
- Call `get_router()._get_loaded_models()` for currently loaded
- Merge with `MODELS` dict for full registry (name, context_window, supports_tools, supports_vision)
- Include VRAM estimate, load status, and whether model is in any routing chain

### 2d. `GET /api/providers/presets` — Replace dummy with real presets
- "Local Only" (no cloud), "Balanced" (current default), "Cloud Backup" (kimi for all tasks)
- Mark current active preset based on routing table config

### 2e. Enable frontend queries
- In `LLMProvidersSection.tsx`, remove `enabled: false` from the 3 disabled queries
- The health query is already enabled with 60s refetch — keep that

### Service Registry (static dict in provider_config.py)
Based on the 85-service audit, group into categories:

**Analysis** (25 services): CSP Recommender, Earnings Analyzer, Strategy Recommender, Signal Enrichment, Alert Enrichment, etc. → `FINANCIAL_ANALYSIS` / `TECHNICAL_ANALYSIS`

**Trading** (8 services): Unified Advisor, Position Opportunities, Weekly Plans, Alpha Hypothesis → `PLANNING`

**Chat** (9 services): ADA Brain, RAG, Chat Router, Reasoning → `GENERAL` / `REASONING`

**System** (7 services): QA Agent, Code Fix, Enhancement Swarm, Feature Grader → `CODE_GEN` / `CODE_REVIEW`

## Phase 3: Fix Broken Tests

### 3a. `backend/tests/test_llm_router.py`
- Line 54-56: `qwen3.5:9b` → `qwen3.5:35b-a3b` (GENERAL primary)
- Line 90-98: `qwen3.5:27b` → `qwen3.5:35b-a3b` (FINANCIAL_ANALYSIS primary)
- Update docstrings to match new model names

### 3b. `backend/tests/test_dashboard.py`
- ~10 occurrences of `LLM_MODEL="qwen3.5:9b"` → `"qwen3.5:35b-a3b"` in test patches

### 3c. `backend/tests/test_ada_brain_integration.py`
- Lines 396, 437: `model="qwen3.5:9b"` → `"qwen3.5:35b-a3b"` in mock responses

### 3d. `backend/tests/test_ada_llm_service.py`
- ~12 occurrences of `qwen3:8b` → `"qwen3.5:35b-a3b"` in mock responses

## Phase 4: Update Documentation

### 4a. MEMORY.md routing table
- `C:\Users\hadam\.claude\projects\c--code-ADA\memory\MEMORY.md`
- Update: `PLANNING=kimi-k2.5, CODE=qwen3-coder-next, FINANCIAL/TECHNICAL=qwen3.5:35b-a3b, REASONING=gemma4:31b, GENERAL/DOCS=qwen3.5:35b-a3b`

### 4b. Topic files
- `.claude/memory/topics/ada-brain.md:160,162` — update model names table
- `.claude/memory/topics/dashboard.md:287` — update model example

### 4c. Stale tags/docstrings
- `backend/routers/reasoning.py:26` — tag `"deepseek-r1"` → `"reasoning"`
- `backend/services/position_opportunities_service.py:840,888` — update docstring model names

## Files Modified

| File | Change |
|------|--------|
| `backend/routers/provider_config.py` | Replace ALL dummy data with real router data |
| `backend/infrastructure/llm_router.py` | No changes (already correct) |
| `frontend/src/components/settings/LLMProvidersSection.tsx` | Enable queries (remove `enabled: false`) |
| `src/xtrades/analyzer.py` | Route Ollama path through router |
| `src/ada/agents/trading/options_flow_agent.py` | Route through router |
| `src/ai_options_agent/llm_manager.py` | Route Ollama path through router |
| `src/ada/omnipresent_ada.py` | Route default path through router |
| `src/multimodal/vision_analyzer.py` | Add comment (intentional bypass) |
| `backend/services/llm_client.py` | Delegate to router |
| `backend/infrastructure/base_agent.py` | Fix default model name |
| `backend/routers/reasoning.py` | Fix defaults + tags |
| `backend/services/position_opportunities_service.py` | Fix docstrings |
| `backend/tests/test_llm_router.py` | Fix model assertions |
| `backend/tests/test_dashboard.py` | Fix model mocks |
| `backend/tests/test_ada_brain_integration.py` | Fix model mocks |
| `backend/tests/test_ada_llm_service.py` | Fix model mocks |
| `.claude/memory/MEMORY.md` | Update routing table |
| `.claude/memory/topics/ada-brain.md` | Update model names |
| `.claude/memory/topics/dashboard.md` | Update model example |

## Verification

1. `docker restart ada-backend` → clean startup in `docker logs ada-backend --tail 30`
2. `curl http://localhost:8006/api/providers/health` → real Ollama model list, not dummy
3. `curl http://localhost:8006/api/providers/services/by-category` → 4 categories with real service mappings
4. `curl http://localhost:8006/api/providers/models` → all 6 models with load status
5. Open `http://localhost:5420/settings` → LLM Providers tab shows real data
6. `pytest backend/tests/test_llm_router.py -v` → all pass
7. `pytest backend/tests/test_dashboard.py -v -x` → no model name failures
8. Grep for old model names: `rg "qwen3.5:9b|qwen3.5:27b|deepseek-r1:32b" backend/ src/ --type py` → zero hits in active code
