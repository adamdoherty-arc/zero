# Switch ADA Portfolio Advisor to Kimi K2.6 + Fix UX

## Context

The **ADA Portfolio Advisor** panel on the Trade Planner is broken right now: it's failing with `Failed to generate briefing: Request failed with status code 429` and the badge still reads `MiniMax M2.7`. Two underlying problems:

1. **Wrong provider.** When Kimi was "removed" in Apr 2026 (per `MEMORY.md`), the trade advisor service was rewired to MiniMax M2.7, with a `$5/day` cost cap on the advisor specifically (`AI_DAILY_COST_CAP` in [trade_advisor_service.py:1638](c:/code/ADA/backend/services/trade_advisor_service.py#L1638)). The user wants to switch this single feature back to **Kimi K2.6** (Moonshot AI). The live `.env` already has `KIMI_API_KEY`, `KIMI_BASE_URL=https://api.moonshot.ai/v1`, `KIMI_MODEL=kimi-k2.6` configured.
2. **Bad failure UX.** When the cost cap (or any provider error) trips, the user just sees the raw 429 string with no retry button. The CC Roll Strategies section header renders but the body is empty. Priority actions are split into orphan fragments like `"--"` and `"Both CCs deeply ITM"` instead of being grouped under their parent action.

Goal: Restore a real `KimiClient`, route the advisor through Kimi → MiniMax → Ollama in that order, fix the badge/cost display, and clean up the failure + empty-state UX so the panel actually delivers actionable recommendations again.

---

## Routing chosen

**Kimi K2.6 (primary cloud) → MiniMax M2.7 (fallback cloud) → Ollama (local, free).**

This is scoped to the Trade Advisor service only. The shared `llm_router.py` `TaskType.PLANNING` table will be updated to put `kimi-k2.6` first so other planning callers (`weekly_strategic_plan`, `unified_ai_advisor`, `position_opportunities`, `alpha_hypothesis`) automatically benefit too.

---

## Files to modify

### Backend — restore real Kimi client + routing

| File | Change |
|---|---|
| [backend/infrastructure/ai_client.py](c:/code/ADA/backend/infrastructure/ai_client.py) | **Add a real `KimiClient` class** (model the body on the existing `MinimaxClient` at line 1362). OpenAI-compatible POST to `{KIMI_BASE_URL}/chat/completions`, `Authorization: Bearer {KIMI_API_KEY}`, model = `KIMI_MODEL` (default `kimi-k2.6`). Support `thinking_mode`, `temperature`, `max_tokens`, `timeout`, return `{content, reasoning, model, input_tokens, output_tokens, latency_ms, cost_usd}`. Add `get_kimi_client()` singleton + `is_kimi_available()` reading `KIMI_API_KEY`. |
| [backend/infrastructure/llm_router.py](c:/code/ADA/backend/infrastructure/llm_router.py) | **Stop aliasing Kimi shims to MiniMax.** Restore `is_kimi_available()` (line 217) to check `KIMI_API_KEY`. Restore `get_kimi_client()` (line 1453) to return the new `KimiClient`. Add `KIMI_MODELS = {"kimi-k2.6": "kimi-k2.6"}` and `KIMI_PRICING = {"kimi-k2.6": (0.00060, 0.00250)}` (Moonshot K2.6 tier — confirm pricing during impl; pricing is a constant, easy to fix later). Add `kimi-k2.6` to `CLOUD_MODELS`. Update `ROUTING_TABLE[TaskType.PLANNING]` (line 161) from `["minimax-m2.7", "qwen3.5:35b-a3b"]` → `["kimi-k2.6", "minimax-m2.7", "qwen3.5:35b-a3b"]`. Keep `calculate_kimi_cost` working against Kimi pricing now, not MiniMax. |
| [backend/services/trade_advisor_service.py](c:/code/ADA/backend/services/trade_advisor_service.py) | Rewrite [`_call_ai`](c:/code/ADA/backend/services/trade_advisor_service.py#L1624) to try **3 providers in sequence**, not 2: (1) Kimi via `get_kimi_client()`, (2) MiniMax via `get_minimax_client()`, (3) Ollama router with `TaskType.FINANCIAL_ANALYSIS`. Each cloud attempt logs which provider+model succeeded; cost cap check still gates cloud attempts; Ollama fallback is always free. Distinguish two failure modes in the raised exception: `CostCapExceeded` (subclass of RuntimeError, → 429) and `ProviderUnavailable` (→ 503). Update the docstring comment that still says "Kimi K2.5". |
| [backend/routers/trade_advisor.py](c:/code/ADA/backend/routers/trade_advisor.py) | Update [generate handler at line 195](c:/code/ADA/backend/routers/trade_advisor.py#L195) to map `CostCapExceeded` → 429 with `detail={"reason": "cost_cap", "message": ..., "daily_cost": X, "cap": 5.00}`, and `ProviderUnavailable` → 503 with `detail={"reason": "provider_down", ...}`. Frontend can then render distinct messages. The existing `/kimi-status` endpoint at line 1316 should now actually probe Kimi (not MiniMax). |
| [.env.example](c:/code/ADA/.env.example) | Uncomment & document the `KIMI_API_KEY` / `KIMI_BASE_URL` / `KIMI_MODEL` block (lines 117-118). Mark MiniMax as "fallback only". |

### Frontend — model badge, error UX, CC roll strategies

| File | Change |
|---|---|
| [frontend/src/components/planner/AdvisorBriefingPanel.tsx](c:/code/ADA/frontend/src/components/planner/AdvisorBriefingPanel.tsx) | **Model badge:** add `'kimi-k2.6': 'Kimi K2.6'` to the `friendlyModelName` map at line 578. **Error UX:** at line 762, replace the raw error string with a typed renderer — read `error.response.data.detail.reason`; `cost_cap` shows "Daily AI budget reached ($X / $5). Resets midnight UTC." with a disabled retry button; `provider_down` shows "Kimi & MiniMax both unavailable, fell back to local model." + active "Try cloud again" button; default shows the raw message + retry. **Priority actions:** in the render loop at line 812, group orphan fragments. The current parser produces top-level items with `*N.` prefix and bare sub-items; render sub-items indented under the most recent `*N.` parent and drop items that are just `--` or whitespace. **CC Roll Strategies:** in [CCRollStrategiesSection at line 192](c:/code/ADA/frontend/src/components/planner/AdvisorBriefingPanel.tsx#L192), the section header renders even when the hook is `isError` — change the early return at line 199 to also bail when the hook errors, and surface a one-line error inside if positions=[] but `isError=true`. |
| [frontend/src/hooks/useCCRollStrategies.ts](c:/code/ADA/frontend/src/hooks/useCCRollStrategies.ts) (verify) | Confirm the hook actually returns `positions` for the user's 3 active CCs. Add `staleTime` and proper error surface. If the endpoint is returning empty for 3 known CCs (IREN, AXTI, NEBX × 3, IREX × 2 per the briefing), that's a bug in the backend route — investigate during impl, not now. |

### Backend — priority actions parser cleanup (optional but in scope)

| File | Change |
|---|---|
| [backend/services/trade_advisor_service.py](c:/code/ADA/backend/services/trade_advisor_service.py) | The structured-output extractor at [line 2102-2132](c:/code/ADA/backend/services/trade_advisor_service.py#L2102) is the good path. The fallback `_parse_briefing` at [line 1775](c:/code/ADA/backend/services/trade_advisor_service.py#L1775) is what produces the `"--"` orphans. Tighten its line filter: drop items shorter than 8 chars or matching `^[\-—•*\s]+$`, and prepend the most recent parent header to sub-bullets so each action is self-contained. |

---

## Reuse — what NOT to rebuild

- `MinimaxClient` already has the OpenAI-compatible call shape, error handling, cost calculation, and singleton pattern. **Copy its body**, don't redesign.
- `is_kimi_available()` and `get_kimi_client()` shims **already exist** as call sites — every legacy caller (`trade_advisor`, `thematic_discovery`, `signal_enrichment`, `weekly_strategic_plan`) already uses them. We just point them back at a real Kimi client instead of redirecting to MiniMax.
- `LLMQueueManager`, `RateLimitedChatOpenAI`, and the global `get_ollama_semaphore()` need no changes — the new client plugs in at the same level as `MinimaxClient`.
- `friendlyModelName` map and the cost/model badge already exist. One-line addition.
- `BriefingResponse` schema already returns `model` and `cost_usd` to the frontend. No API contract change.

---

## Verification

After implementation:

1. **Backend boot:**
   ```bash
   docker restart ada-backend
   docker logs ada-backend --tail 30
   ```
   Expect no startup errors; expect log line confirming `KimiClient` initialized.

2. **Provider probe:**
   ```bash
   curl http://localhost:8006/api/trade-advisor/kimi-status
   ```
   Should return `{"available": true, "model": "kimi-k2.6", "base_url": "https://api.moonshot.ai/v1"}`.

3. **End-to-end briefing generation:**
   ```bash
   curl -X POST http://localhost:8006/api/trade-advisor/generate \
     -H "Content-Type: application/json" \
     -d '{"briefing_type": "post-market"}'
   ```
   Expect 200 with `model: "kimi-k2.6"` and non-zero `cost_usd`. If 429, response body should be `{"detail": {"reason": "cost_cap", ...}}` not a bare string.

4. **Frontend smoke:**
   ```bash
   python .claude/skills/playwright-testing/runner.py smoke http://localhost:5420/trade-planner
   ```
   Then open the page and confirm:
   - Footer badge reads `Kimi K2.6` (not `MiniMax M2.7`)
   - "Refresh" button generates a fresh briefing without 429
   - Priority Actions list has no `"--"` orphans; sub-items appear indented under their parent action
   - CC Roll Strategies section either populates with 3 positions or hides cleanly

5. **Failure-mode UX:**
   - Temporarily set `KIMI_API_KEY=invalid` in `.env`, restart, click Refresh.
   - Should fall through to MiniMax (badge shows MiniMax) without user-facing error. Restore key.
   - To test cost cap: manually set `redis-cli set ai_usage:advisor_daily_cost:$(date +%Y-%m-%d) 5.01`, click Refresh.
   - Should see "Daily AI budget reached" inline error with disabled retry, not a raw 429.

6. **Other planning callers unaffected:** `weekly_strategic_plan`, `unified_ai_advisor`, `position_opportunities` all share the `TaskType.PLANNING` route. After change they should also use Kimi K2.6 — verify by tailing logs while triggering one of those routes (e.g. `POST /api/advisor/generate`).

---

## Out of scope

- Migrating `kimi_chart_analysis` (chart vision) — that's a separate router and was only renamed for backward compat. Keep on MiniMax for now since K2.6 vision support is unverified.
- Removing the legacy `LLMProvider.KIMI` enum value or the `kimi_chart_analysis` DB table.
- Tuning the `$5/day` cost cap (raise/lower) — leave it; the new error UX makes hitting it manageable.
- Changing `TaskType.FINANCIAL_ANALYSIS` (Ollama) routing.
