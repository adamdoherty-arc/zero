# Plan: Full Migration from Kimi K2.5 → MiniMax M2.7

## Context

ADA currently uses **Kimi K2.5** (Moonshot AI) as its sole cloud LLM, integrated in 8 locations spanning the LLM router, AI client, LangGraph providers, and chart vision pipeline. The user wants to **fully replace Kimi with MiniMax M2.7** wherever it is used (planning, financial reasoning, vision/chart analysis), keeping local Ollama as the fallback. This is a clean swap, not an additive change.

**Why MiniMax M2.7:**
- ~55% cheaper than Kimi K2.5 ($0.30/$1.20 vs $0.60/$3.00 per 1M tokens)
- SOTA on agentic tool-calling (τ²-Bench 77.2, BrowseComp 76.3%, SWE-Bench 80.2%)
- Designed for live debugging, financial modeling, and document generation — directly aligned with ADA's planning and advisor workloads
- 205K context window (vs Kimi's 262K — slight reduction, still ample)
- OpenAI-compatible API at `https://api.minimax.io/v1` — drop-in for existing `AsyncOpenAI` client code
- Multimodal/vision support for chart pattern detection
- Released March 18, 2026 (current and stable)

---

## Head-to-Head (for the record)

| Dimension | Kimi K2.5 (current) | MiniMax M2.7 (target) |
|---|---|---|
| Input price | $0.60 / 1M | **$0.30 / 1M** |
| Output price | $3.00 / 1M | **$1.20 / 1M** |
| Context window | 262K | 205K |
| Architecture | Dense + reasoning mode | 230B MoE / 10B active |
| Math (AIME 2025) | 96.1% | ~78% |
| Agentic (τ²-Bench) | n/a | **77.2** |
| Coding (SWE-Bench Verified) | High | **80.2%** (M2.5 baseline; M2.7 ≥) |
| Browsing (BrowseComp) | n/a | **76.3%** |
| Tool-calling stability | Good | **SOTA** |
| API compatibility | OpenAI-compatible | OpenAI-compatible |
| Vision | Yes | **Yes** |
| Endpoint | `api.moonshot.ai/v1` | `api.minimax.io/v1` |

**Trade-off accepted**: Kimi wins on pure-math benchmarks (AIME, GPQA). For ADA's workloads — financial planning, agentic tool-calling, and chart vision — MiniMax M2.7 is the better fit at half the price.

---

## Current Kimi Integration Map (8 files to touch)

| # | File | Current role | Action |
|---|---|---|---|
| 1 | [.env](.env) lines 122-123 | `KIMI_API_KEY`, `KIMI_BASE_URL` | **Replace** with `MINIMAX_API_KEY`, `MINIMAX_BASE_URL` |
| 2 | [backend/config.py](backend/config.py) lines 158-167 | Kimi pydantic settings + `kimi_available` property | **Replace** with MiniMax settings + `minimax_available` |
| 3 | [backend/infrastructure/ai_client.py](backend/infrastructure/ai_client.py) lines 1364-1732 | `KimiClient` class (text + vision), `get_kimi_client()`, `is_kimi_available()`, `analyze_chart_with_kimi()`, pricing tuples | **Replace** with `MinimaxClient`, `get_minimax_client()`, `is_minimax_available()`, `analyze_chart_with_minimax()` |
| 4 | [backend/infrastructure/llm_router.py](backend/infrastructure/llm_router.py) lines 158-199, 497-546, 608-623 | `KIMI_MODELS`, `KIMI_PRICING`, `CLOUD_MODELS`, `_call_kimi()`, routing dispatch | **Replace** with `MINIMAX_MODELS`, `MINIMAX_PRICING`, `_call_minimax()`. Update `ROUTING_TABLE[TaskType.PLANNING] = ["minimax-m2.7", "qwen3.5:35b-a3b"]` |
| 5 | [src/ada/langgraph/providers/kimi.py](src/ada/langgraph/providers/kimi.py) | `get_kimi_llm()`, `get_kimi_vision_llm()`, `is_kimi_available()` | **Rename** file to `minimax.py`. Replace functions with `get_minimax_llm()`, `get_minimax_vision_llm()`. Update all importers. |
| 6 | [backend/services/kimi_chart_scheduler.py](backend/services/kimi_chart_scheduler.py) | 15-min chart vision scan loop | **Rename** to `minimax_chart_scheduler.py`. Replace KimiClient calls with MinimaxClient. Update [backend/services/scheduled_tasks.py](backend/services/scheduled_tasks.py) import. |
| 7 | [backend/routers/kimi_chart_analysis.py](backend/routers/kimi_chart_analysis.py) | REST endpoints `/api/kimi-chart/*` | **Rename** to `minimax_chart_analysis.py`. Change prefix to `/api/minimax-chart/*`. Update [backend/main.py](backend/main.py) router registration. |
| 8 | [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) + topic files | Kimi references in routing notes | Update to reflect MiniMax M2.7 as the cloud provider |

**Frontend impact**: Search for any frontend references to `/api/kimi-chart/*` and update to `/api/minimax-chart/*`. Likely in [frontend/src/hooks/](frontend/src/hooks/) and any chart analysis page.

---

## Implementation Strategy

### Phase A: Foundation (config + client)
1. **Add credentials** to `.env`:
   ```
   MINIMAX_API_KEY=<user-provided>
   MINIMAX_BASE_URL=https://api.minimax.io/v1
   MINIMAX_MODEL=MiniMax-M2.7
   ```
   (Leave the existing `KIMI_*` lines in place during migration; remove only after verification.)

2. **Update [backend/config.py](backend/config.py)** lines 158-167: add MiniMax settings as a parallel block to Kimi. Keep both during migration so nothing breaks mid-edit.

3. **Build `MinimaxClient`** in [backend/infrastructure/ai_client.py](backend/infrastructure/ai_client.py):
   - Copy `KimiClient` (lines 1364-1707) as a starting template — both use `AsyncOpenAI`, so the diff is small.
   - Change defaults: `base_url="https://api.minimax.io/v1"`, `MODELS = {"chat": "MiniMax-M2.7", "vision": "MiniMax-M2.7"}` (M2.7 is multimodal — single model for both).
   - Update pricing tuple in the `TOKEN_PRICING` dict (line 154 area): `"MiniMax-M2.7": (0.0003, 0.0012)`.
   - **Drop Kimi-specific quirks**: the `extra_body: {"thinking": {"type": "disabled"}}` parameter is Kimi-only. MiniMax M2.7 has no thinking-mode toggle in the request body — remove that param.
   - Port `analyze_image()` for vision (lines 1614-1707) — same multimodal message structure (`image_url` + text), same `AsyncOpenAI` SDK, just different model name.
   - Add `get_minimax_client()` singleton + `is_minimax_available()` mirror.

### Phase B: Router rewrite
4. **Update [backend/infrastructure/llm_router.py](backend/infrastructure/llm_router.py)**:
   - Replace `KIMI_MODELS` (line 178) → `MINIMAX_MODELS = {"minimax-m2.7": "MiniMax-M2.7"}`
   - Replace `KIMI_PRICING` (line 184) → `MINIMAX_PRICING = {"minimax-m2.7": (0.0003, 0.0012)}`
   - Replace `CLOUD_MODELS = {"kimi-k2.5", ...}` (line 199) → `CLOUD_MODELS = {"minimax-m2.7"}`
   - Update routing table line 158: `TaskType.PLANNING: ["minimax-m2.7", "qwen3.5:35b-a3b"]` (MiniMax primary, Ollama fallback)
   - Replace `_call_kimi()` method (lines 497-546) with `_call_minimax()` — same shape, points to `get_minimax_client()`.
   - Update `_call_chain()` dispatch (lines 608-623) to call `_call_minimax()` for cloud entries.
   - Re-export `get_minimax_client()` and `analyze_chart_with_minimax()` (replacing the Kimi re-exports at lines 1431-1446).

### Phase C: LangGraph provider
5. **Rename [src/ada/langgraph/providers/kimi.py](src/ada/langgraph/providers/kimi.py) → `minimax.py`**:
   - Replace `get_kimi_llm()` → `get_minimax_llm()`. Same `ChatOpenAI` wrapper, different `base_url` and `api_key` env var.
   - Replace `get_kimi_vision_llm()` → `get_minimax_vision_llm()`.
   - Drop the `chat_template_kwargs: {"thinking": False}` model_kwargs — MiniMax doesn't use it.
   - Find and update all imports: `grep -rn "from src.ada.langgraph.providers.kimi" backend/ src/`

### Phase D: Vision pipeline
6. **Rename [backend/services/kimi_chart_scheduler.py](backend/services/kimi_chart_scheduler.py) → `minimax_chart_scheduler.py`**:
   - Replace `KimiClient` imports with `MinimaxClient`.
   - Replace `get_chart_analyzer(VisionModel.KIMI)` with `get_chart_analyzer(VisionModel.MINIMAX)` — may need to add the `MINIMAX` enum value.
   - Update any `kimi_*` variable names to `minimax_*` for clarity.
   - Update [backend/services/scheduled_tasks.py](backend/services/scheduled_tasks.py) to import from the new module name.

7. **Rename [backend/routers/kimi_chart_analysis.py](backend/routers/kimi_chart_analysis.py) → `minimax_chart_analysis.py`**:
   - Change prefix from `/api/kimi-chart` to `/api/minimax-chart`.
   - Update [backend/main.py](backend/main.py) router registration line.
   - Update frontend hooks/pages calling `/api/kimi-chart/*` to use the new prefix. Use Grep to find all callers.

### Phase E: Cleanup + memory
8. **Remove Kimi remnants**:
   - Delete `KIMI_API_KEY`, `KIMI_BASE_URL`, `KIMI_MODEL` lines from `.env`.
   - Delete the Kimi pydantic settings block from `config.py`.
   - Delete the `KimiClient` class from `ai_client.py` (lines 1364-1732).
   - Search for any remaining `kimi` references: `grep -rin "kimi" backend/ src/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx"` — clean up any stragglers.

9. **Update [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md)**:
   - Replace the Kimi K2.5 references in the `llm_router.py` infrastructure block.
   - Update routing table notes: `PLANNING → MiniMax M2.7 (cloud), everything else → local Ollama`.
   - Remove the `KimiClient. ~~GeminiClient~~ REMOVED` line; replace with `MinimaxClient`.

### Phase F: Database/cost tracking compatibility
10. **Audit cost tracking tables** for any hardcoded `kimi-k2.5` model name strings. If found in queries (e.g. cost dashboards, llm usage history), update to handle both legacy `kimi-k2.5` rows and new `minimax-m2.7` rows. Check `backend/services/llm_usage_*` and any analytics service.

---

## Reusable Patterns (Don't Reinvent)

| Pattern | Location | How to reuse |
|---|---|---|
| `AsyncOpenAI` wrapper class | [ai_client.py:1364](backend/infrastructure/ai_client.py#L1364) | Copy `KimiClient` template; change base_url, model, drop thinking-mode quirks |
| Singleton factory | [ai_client.py:1714](backend/infrastructure/ai_client.py#L1714) | Mirror `get_kimi_client()` exactly |
| Cost calculation | `calculate_kimi_cost()` in llm_router.py | Generalize to `calculate_cloud_cost(model, in_tok, out_tok)` looking up `MINIMAX_PRICING` |
| LangChain ChatOpenAI wrapper | [src/ada/langgraph/providers/kimi.py:42](src/ada/langgraph/providers/kimi.py#L42) | Copy structure, swap env vars and base URL |
| Routing fallback chain | `_select_model()` at [llm_router.py:413](backend/infrastructure/llm_router.py#L413) | **No logic change** — just update the data list per TaskType |
| Vision multimodal message | [ai_client.py:1654-1670](backend/infrastructure/ai_client.py#L1654-L1670) | OpenAI standard `image_url` + text content blocks — works as-is on MiniMax |

---

## Verification Plan

Run **in order** after implementation. Each step must pass before proceeding.

1. **Container restart with new env vars**:
   ```bash
   docker compose up -d backend
   docker logs ada-backend --tail 30
   ```
   Expect: clean startup, no `KIMI_API_KEY` errors, `MinimaxClient` initialized in logs.

2. **Health endpoint**:
   ```bash
   curl http://localhost:8006/api/system/llm-health
   ```
   Expect: `minimax_available: true`, no Kimi references.

3. **Direct LLM call test**:
   ```bash
   curl -X POST http://localhost:8006/api/system/llm-test \
     -H "Content-Type: application/json" \
     -d '{"task_type":"PLANNING","prompt":"Plan a CSP on AAPL"}'
   ```
   Expect: 200, response includes `model: "MiniMax-M2.7"`, `cost_usd` ~half of historical Kimi cost.

4. **LangGraph plan-and-execute** (uses TaskType.PLANNING):
   ```bash
   curl -X POST http://localhost:8006/api/langgraph/plan-and-execute \
     -H "Content-Type: application/json" \
     -d '{"objective":"analyze AAPL for a weekly CSP this week"}'
   docker logs ada-backend --tail 50 | grep -i "model_selected\|minimax"
   ```
   Expect: `model_selected=minimax-m2.7`, coherent multi-step plan returned.

5. **Advisor briefing test** (formerly Kimi):
   ```bash
   curl -X POST http://localhost:8006/api/advisor/briefing \
     -H "Content-Type: application/json" \
     -d '{"symbols":["AAPL","MSFT","NVDA"]}'
   ```
   Expect: full briefing response, MiniMax model in metadata.

6. **Position opportunities** (formerly Kimi):
   ```bash
   curl http://localhost:8006/api/position-opportunities/scan
   ```
   Expect: opportunities list with structured analysis.

7. **Vision/chart test** (formerly Kimi vision):
   ```bash
   curl -X POST http://localhost:8006/api/minimax-chart/analyze/AAPL
   ```
   Expect: chart pattern analysis returned. **This is the highest-risk step** — if vision parity fails, MiniMax may not handle the image format identically.

8. **Chart scheduler dry run**:
   ```bash
   curl -X POST http://localhost:8006/api/minimax-chart/trigger-scan
   docker logs ada-backend --tail 50 | grep -i "chart\|minimax"
   ```
   Expect: scheduler executes one cycle, no errors.

9. **Ollama fallback test**:
   - Temporarily set `MINIMAX_API_KEY=` (empty) in `.env`
   - `docker compose up -d backend`
   - Re-run step 4 (plan-and-execute)
   - Expect: falls back to `qwen3.5:35b-a3b`, plan still returns
   - Restore the API key and `docker compose up -d backend`

10. **Frontend smoke test**:
    ```bash
    python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/ask-ada
    python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/chart-analysis
    ```
    Expect: `"status": "success"` for both.

11. **Grep for stragglers** (final cleanup):
    ```bash
    grep -rin "kimi" backend/ src/ frontend/src/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.md"
    ```
    Expect: no live code references; only historical mentions in `.claude/memory/daily/` logs (which can be left alone).

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Vision parity** — MiniMax handles chart images differently | Medium | Test step 7 thoroughly. If MiniMax misses a pattern Kimi caught, keep `KimiClient` as a vision-only fallback (don't fully delete it). |
| **Frontend route mismatch** — old `/api/kimi-chart/*` calls 404 | Low | Grep frontend before deploying. Could add a router-level redirect if needed. |
| **Cost dashboard breaks** on new model name | Low | Audit step 10 above. Update queries to handle both `kimi-k2.5` (historical) and `minimax-m2.7` (new). |
| **MiniMax API outage** | Low | Ollama fallback (`qwen3.5:35b-a3b`) is in the routing chain — verified by step 9. |
| **Rate limits unknown** on MiniMax | Medium | Existing `RateLimitedChatOpenAI` wrapper handles backoff. Monitor `/api/system/llm-health` after rollout for circuit breaker trips. |
| **Structured output (JSON mode)** behavior differs | Low | OpenAI-compatible API supports `response_format: {type: "json_object"}` — same as Kimi. Test the rule_parser graph specifically (uses structured output). |

---

## Rollback Plan

If anything goes wrong after deployment:
1. Revert the `.env` changes (`KIMI_API_KEY` back, remove `MINIMAX_API_KEY`).
2. `git revert <commit-sha>` for the code changes.
3. `docker compose up -d backend` — back to Kimi within 60 seconds.

The pre-cleanup approach (Phase A keeps Kimi config alongside MiniMax) ensures partial-state safety during the migration itself.

---

## Sources

- [MiniMax M2.7 — Official API docs](https://platform.minimax.io/docs/guides/text-ai-coding-tools)
- [MiniMax M2.7 — OpenRouter pricing & providers](https://openrouter.ai/minimax/minimax-m2.7)
- [MiniMax M2.7 — pricepertoken.com 2026 pricing](https://pricepertoken.com/pricing-page/model/minimax-minimax-m2.7)
- [MiniMax OpenAI-compatible API reference](https://platform.minimax.io/docs/api-reference/text-openai-api)
- [MiniMax M2 — Ingenious in Simplicity (release notes)](https://www.minimax.io/news/minimax-m2)
- [MiniMax M2.5 — Built for Real-World Productivity](https://www.minimax.io/news/minimax-m25)
- [Kimi K2.5 vs MiniMax M2.5 benchmarks (llm-stats)](https://llm-stats.com/models/compare/kimi-k2.5-vs-minimax-m2.5)
- [VentureBeat — MiniMax M2 is the new king of open-source LLMs](https://venturebeat.com/ai/minimax-m2-is-the-new-king-of-open-source-llms-especially-for-agentic-tool)
