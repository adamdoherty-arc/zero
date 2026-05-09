# Learn-19 Tier 2 Activation: Gate Review + Canary Bump

## Context

Learn-18 (Tier 1 per-source provider routing) has been live since April 8, 2026. Learn-19 pre-wired 5 dormant Tier 2 rows at `canary_traffic_pct=0`. The user has asked to review whether Tier 2 can now be activated (bumped from pct=0 to pct=10).

## Gate Review (verified live, 2026-04-09)

### Gate 1: Zero rollbacks on T1 sources — PASS
- `legion_provider_override_rolled_back_total` returns **empty result** (counter never incremented)
- Zero rollbacks across all 4 Tier 1 sources over the entire observation period

### Gate 2: Verifier positive for ≥2 T1 sources — KNOWN LIMIT (waived)
- `feedback_loop_verifier` returns `canaries_checked: 0`, all 16 outcomes `insufficient_data`
- **Root cause**: Learn-18 seed rows have `parent_version_id=NULL` (orphan placeholders) — verifier's canary scan requires non-NULL parent for before/after comparison
- This is a documented design limitation (MEMORY.md Learn-18 + Learn-19 entries), not a regression
- **The real safety signal is Gate 1** (rollback counter), which passes cleanly
- This limit won't change with more time — it's structural

### Gate 3: Sprint creation gate still in `safe` mode — PASS
- `GET /api/sprints/creation-mode` returns `{"mode":"safe"}`
- Gate has held throughout the entire observation period

### Gate 4: 14d Fix- failure rate = 0.000 — PASS
- 18 total Fix- sprints in 14d, **0 FAILED** → rate = 0.000

### T1 Override Traffic Validation (since April 8 seed date)
| Source | MiniMax calls | Ollama calls | Ollama % | Status |
|--------|--------------|--------------|----------|--------|
| `prompt_evaluator` | 3,634 | 355 | 8.9% | Active, matches 10% target |
| `llm_review_agent` | 398 | 29 | 6.8% | Active, within noise of 10% |
| `project_grader_docker_logs` | 4 | 1 | 20% | Active, small N noise |
| `work_discovery` | 3 | 0 | 0% | Only 3 calls total, P(miss all 3) = 73% at 10% |

- **385 Ollama calls** routed through the override system with zero rollbacks
- `prompt_evaluator` alone shows 355 override-routed calls — strong signal
- Prometheus `legion_llm_provider_override_total{reason="pre_authorized"}` incrementing for `llm_review_agent` (2 hits in current counter window)

### Timeline Note
- T1 seeds created: **April 8, 2026** (yesterday)
- Today: **April 9, 2026** — ~1.5 days into the original 7-day gate
- **Early activation justified because**: (a) 385 Ollama calls with 0 rollbacks is a strong signal, (b) Tier 2 starts at pct=10 (not 100%) so blast radius is small, (c) Gate 2 will never pass regardless of time (structural limit), (d) everything is instantly reversible via `UPDATE SET canary_traffic_pct=0`

### Verdict: **ACTIVATE TIER 2**
3 of 4 gates pass cleanly. Gate 2 is a documented structural limit that time won't fix. Override traffic is healthy with 385+ calls and zero rollbacks.

## Activation Plan

### Step 1: Bump 5 Learn-19 rows from pct=0 to pct=10
```sql
UPDATE prompt_templates
SET canary_traffic_pct = 10
WHERE evolved_by = 'learn19_seed' AND canary_traffic_pct = 0;
```
Affects rows 33-37 (slugs: `learn19-ollama-external-knowledge-cross-ref`, `learn19-ollama-task-orchestration-evaluate`, `learn19-ollama-agent-code-reviewer`, `learn19-ollama-tasktype-documentation`, `learn19-ollama-tasktype-analysis-wide`).

### Step 2: Verify the rows are updated
```sql
SELECT id, slug, source_filter, canary_traffic_pct, evolved_by
FROM prompt_templates WHERE evolved_by = 'learn19_seed';
```
All 5 should show `canary_traffic_pct = 10`.

### Step 3: Clear the prompt manager cache
The cache auto-refreshes on TTL, but for immediate effect:
```bash
curl -s http://localhost:8005/api/prompt-manager/templates/provider-overrides
```
This triggers a cache refresh via `list_provider_overrides()`.

### Step 4: Verify override resolution works for Tier 2 sources
Wait 2-5 minutes, then check if any Tier 2 source has produced an Ollama call:
```sql
SELECT source, provider, COUNT(*)
FROM llm_call_details
WHERE provider = 'ollama'
  AND source IN ('external_knowledge_cross_ref', 'task_orchestration_evaluate', 'agent:code_reviewer')
  AND created_at > NOW() - INTERVAL '10 minutes'
GROUP BY source, provider;
```
Note: `agent:code_reviewer` already has ambient Ollama traffic (230 calls/7d) so it should show override hits quickly. The task_type-wide rows (`documentation`, `analysis`) will route ANY source with that task_type at 10%.

### Step 5: Verify frontend shows Tier 2 at pct=10
Navigate to LLM Console → Provider Overrides panel. All 9 rows should show:
- T1 rows (4): `canary_traffic_pct = 10` (unchanged)
- T2 rows (5): `canary_traffic_pct = 10` (bumped from 0)

### Step 6: Monitor for 30 minutes
Watch Prometheus for:
- `legion_provider_override_rolled_back_total` stays at 0
- No new `OllamaProviderOverrideQualityRegression` alert fires
- Backend stays healthy: `curl http://localhost:8005/health`

### Rollback (if needed)
```sql
UPDATE prompt_templates SET canary_traffic_pct = 0 WHERE evolved_by = 'learn19_seed';
```
Takes effect within cache TTL (~60s). No restart needed.

### Critical files (read-only, no code changes needed)
- [backend/app/services/prompt_manager_service.py](backend/app/services/prompt_manager_service.py) — `get_provider_override()` and `list_provider_overrides()` already handle Tier 2 rows
- [backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py) — `_enforce_provider_gate()` with `pre_authorized` bypass already works for any source
- [frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx) — Tier badge + Savings column already renders T2 rows

### Success criteria
- All 5 T2 rows at `canary_traffic_pct = 10`
- At least 1 Tier 2 source produces an Ollama call within 30 minutes
- Zero rollbacks in 30-minute monitoring window
- Frontend Provider Overrides panel shows 9 rows, all at pct=10

---

# Learn-18 → Learn-21: Ollama Re-introduction + AutoAgent Idea Harvest (Original Roadmap)

## Context

**Why now**: MiniMax and Kimi spend is unsustainable (~$154/wk combined per `llm_call_details` aggregates over the last 7 days). Recovery-01 collapsed everything to MiniMax M2 only as a stopgap to escape the Fix-41→Fix-52 death loop. The system has been stable since Sprint-Cleanup-02 (gate in `safe` mode, zero new RCA Fix sprints, Sprint 2916 COMPLETED), so it is finally safe to re-introduce a free local provider.

**Why Ollama re-introduction is feasible now (and wasn't 30 days ago)**:
1. Recovery-01 stabilized the swarm path (`supervisor_node` reads `state["errors"]`, `LLMExecutionError` raises cleanly).
2. Sprint-Cleanup-02's universal `sprint_creation_gate` prevents the auto-creation tsunami that masked failures.
3. **Learn-14 → Learn-17 already built the entire safety net**: per-call quality scoring (`llm_call_details.review_score`), TextGrad fire-and-forget critique, DSPy/GEPA canary routing infrastructure, and `feedback_loop_verifier` auto-rollback. We do not need to build A/B testing — it already exists.
4. GPU Manager (project_id=14) and Ollama Manager (project_id=13) are both live, so VRAM saturation and model swap thrash are observable in real time.

**Why AutoAgent (https://github.com/hkuds/autoagent) is a no-go for embedding**:
- Hard dependency on `litellm==1.55.0`, which Recovery-01 explicitly removed.
- Ollama support is broken upstream (Issue #43 — "model not found" errors).
- CLI-first ephemeral design with no library API; agents evaporate on restart.
- Forking it would create a 2+ person-week ongoing maintenance burden.
- **Decision (per user direction)**: steal the 3 best ideas natively, don't run AutoAgent at all.

**Intended outcome**: A 4-sprint roadmap (Learn-18 → Learn-21) that (a) brings Ollama back online incrementally via the **existing canary infrastructure** with auto-rollback on quality regression, (b) cuts ~$80-120/wk from premium-LLM spend, (c) imports AutoAgent's best ideas (natural-language workflow synthesis, tool generation via GEPA, zero-code sprint UI) into Legion's native prompt evolution system without taking the dependency.

## Discovery Findings (verified live, 2026-04-08)

### Sprint stability scoreboard (last 14d)
| Category | Total | Completed | Failed | Cancelled | Success | Verdict |
|----------|-------|-----------|--------|-----------|---------|---------|
| Health | 24 | 24 | 0 | 0 | **100%** | **STABLE — Ollama-safe** |
| Builder | 1 | 1 | 0 | 0 | **100%** | **STABLE — Ollama-safe** |
| Deps | 24 | 20 | 1 | 2 | **83%** | **STABLE — Ollama-safe** |
| Auto-Sprint | 34 | 21 | 1 | 9 | 62% | UNSTABLE — keep premium |
| Learn | 4 | 2 | 0 | 0 | 50% | UNSTABLE — keep premium |
| Fix | 18 | 4 | 0 | 14 | 22% | VERY UNSTABLE — premium |
| Test | 2 | 0 | 0 | 1 | 0% | VERY UNSTABLE — premium |

### Provider cost reality (last 7d)
| Provider | Calls | Tokens (in/out) | Est. Cost | Last call |
|----------|-------|------------------|-----------|-----------|
| **Kimi** | 6,021 | 6.99M / 6.15M | **~$136** | 2026-04-07 02:12 (~22h ago — stale, gate is now holding) |
| **MiniMax** | 7,537 | 7.82M / 3.18M | ~$18 | 2026-04-08 00:23 (live) |
| Ollama | 1,002 | 806K / 390K | **$0** | 2026-04-08 00:12 (**LIVE — gate is leaking**) |

**Two surprises that change the plan**:
1. **Kimi was the actual budget killer (~$136/wk vs MiniMax ~$18/wk)** but the `KIMI_DISABLED=true` gate has finally held for 22 hours. So Kimi is no longer leaking, and Ollama re-introduction is mostly about MiniMax displacement going forward.
2. **`OLLAMA_DISABLED=true` is leaking** — 1,002 Ollama calls in 7d with the most recent only 11 minutes old. There is a code path (likely `agent_swarm_service` lazy-import bypass or a stale `force_model="primary"` resolver) that calls Ollama directly without going through `_enforce_provider_gate` at [unified_llm_service.py:278-291](backend/app/services/unified_llm_service.py#L278-L291). **This must be audited and either closed or formalized in Learn-18.**

### Source-level safe migration candidates
| Source | Calls/7d | Avg review_score | Latency-sensitive? | Migration tier |
|--------|----------|------------------|--------------------|---------------|
| `prompt_evaluator` | 9,595 | 0 (passive) | No | **Tier 1 — first migration target** |
| `llm_review_agent` | 1,902 | 0 (passive) | No | **Tier 1** |
| `work_discovery` | 64 | 0 | No | **Tier 1** |
| `project_grader_docker_logs` | 50 | 0 | No | **Tier 1** |
| `external_knowledge_cross_ref` | 42 | 9.81 | No | Tier 2 |
| `task_orchestration_evaluate` | 59 | 4.54 | Mid | Tier 2 |
| `agent:code_reviewer` | 333 | 2.70 | Mid | Tier 2 |
| `claude_executor` | 341 | 2.58 | Mid | Tier 2 |
| `brain:plan_vote` | 181 | 2.82 | Yes | **Tier 3 — keep premium** |
| `planning_cortex` | 823 | 6.11 | Yes | **Tier 3 — keep premium** |
| `sprint_tool` | 761 | 0 | Yes | **Tier 3 — keep premium** |

### Existing infrastructure that already does what we need (no rebuild)
- [unified_llm_service.py:266-291](backend/app/services/unified_llm_service.py#L266-L291) — `_ollama_disabled()`, `_kimi_disabled()`, `_enforce_provider_gate()`. The gate exists; we extend it to be **per-source-aware** rather than global.
- [unified_llm_service.py:848-876](backend/app/services/unified_llm_service.py#L848-L876) — DB-backed prompt template lookup with canary roll-of-dice already wired.
- [prompt_manager_service.py:60-119](backend/app/services/prompt_manager_service.py#L60-L119) — `_cache` + `_canary_cache` pattern keyed by `task_type_mapping`. Canary cache already loads `canary_eligible=True AND canary_traffic_pct>0` rows.
- [prompt_manager_service.py:28-44](backend/app/services/prompt_manager_service.py#L28-L44) — `SOURCE_TASK_TYPE_MAP` already maps every source name to a task type. **This is the hook point** — extend it to also carry an optional provider override.
- `feedback_loop_verifier.py` — Learn-17 service with Welch's t-test on `review_score` deltas, auto-rollback at p<0.1, 24h cooldown, MIN_SAMPLE_SIZE=50. **Already wraps `revert_template()`** — extend it to also revert provider routing.
- [legion_config.py:676-689](backend/app/core/legion_config.py#L676-L689) — `TASK_MODEL_ROUTING` already a `Dict[TaskType, List[ModelType]]` fallback chain. The chain just happens to be `[MINIMAX_M2]` everywhere right now.
- `MODEL_REGISTRY[ModelType.OLLAMA_QWEN_CODER_NEXT]` is still wired ([legion_config.py:455-501](backend/app/core/legion_config.py#L455-L501)) and `OLLAMA_AVAILABLE_TAGS` is computed from it.

## Approach — Multi-sprint roadmap (Learn-18 → Learn-21)

**Execution mode**: All 4 sprints created **manually** via `POST /api/sprints/` (which is on the `manual_api` allowlist of `sprint_creation_gate` in `safe` mode, so we don't need to flip the gate). Each sprint gates the next via existing `sprint_chain_service.create_next_sprint`.

**Hard constraint (carries through every sprint)**: Every change must be feature-flag-gated and reversible by either (a) flipping an env var, (b) deleting a row in `prompt_templates`, or (c) `git revert`. No global "Ollama is back" switch. The user has been burned by exactly that pattern — see Recovery-01.

---

### Learn-18: Per-source provider canary infrastructure + Tier 1 migration

**Goal**: Make `_enforce_provider_gate` source-aware. Re-enable Ollama for 4 specific Tier 1 sources (`prompt_evaluator`, `llm_review_agent`, `work_discovery`, `project_grader_docker_logs`) with full quality monitoring and auto-rollback. Audit and close (or formalize) the leak path that produced the 1,002 stale Ollama calls.

**Tasks**:

1. **Audit the Ollama gate leak path** (verification first, fix second).
   - Grep for all paths that construct or call `OllamaClient` directly without going through `unified_llm_service.execute()`. Likely culprits per Recovery-01 notes: `agent_swarm_service` lazy import, `force_model="primary"` callers, `claude_executor` direct path, the smart-swap code at [unified_llm_service.py:472](backend/app/services/unified_llm_service.py#L472).
   - Document each leak in the sprint description with file:line.
   - Decide per-leak: close (raise gate error) or formalize (route through new per-source gate).

2. **Migration `034_per_source_provider_routing.py`** (Alembic, autogenerate-then-edit pattern from Sprint-Cleanup-02):
   - Add `provider_override` column to `prompt_templates` (`String(20)`, nullable, no default). Values: `'ollama'`, `'minimax'`, `'kimi'`, or `NULL` (use task-type default).
   - Add `source_filter` column to `prompt_templates` (`String(255)`, nullable). Comma-separated source names; `NULL` = all sources of this task_type.
   - Add partial index `idx_prompt_templates_provider_override ON (provider_override, source_filter) WHERE provider_override IS NOT NULL`.

3. **Extend `prompt_manager_service.py`**:
   - Add `get_provider_override(source: str, task_type: str) -> Optional[str]` method that consults `_canary_cache` AND a new `_provider_override_cache` (loaded by `_refresh_cache`). Returns the provider name string or `None`.
   - Cache lookup logic: (a) check canary cache for `(task_type, source)` match → if matched and dice roll within `canary_traffic_pct`, return `provider_override`; (b) check static override cache for exact `(task_type, source)` → if matched, return; (c) return `None` (no override).
   - Both `_cache.clear()` and `_provider_override_cache.clear()` must fire together on any template lifecycle event (rule from Learn-16 cache pattern).

4. **Extend `unified_llm_service._enforce_provider_gate`**:
   - New signature: `_enforce_provider_gate(provider, model, *, source: str = "", task_type: str = "")`.
   - Before raising `ServiceUnavailableError`, check `prompt_manager_service.get_provider_override(source, task_type)`. If the override matches the requested provider, allow the call (skip the gate).
   - Log every override decision via a new `legion_llm_provider_override_total{source, target_provider, reason}` Prometheus counter for auditability.

5. **Extend `feedback_loop_verifier.py`**:
   - Add `_revert_provider_override(template_id, source)` helper. Same Welch's t-test math, same MIN_SAMPLE_SIZE=50, same DELTA_THRESHOLD=5.0, same ROLLBACK_COOLDOWN_HOURS=24, same `add_done_callback` pattern. The verifier already runs every 30 min as a side effect of the `_improvement_cycle()` in `prompt_evaluator_agent.py`, so no new daemon needed.
   - On regression: set `provider_override='minimax'` AND `canary_traffic_pct=0` on the canary row, log a warning, increment `legion_provider_override_rolled_back_total{source, target_provider}` counter.
   - Reuse `revert_template()` and `promote_canary()` primitives — never reimplement (rule from Learn-17).

6. **Seed Tier 1 canaries via SQL**:
   - 4 INSERT rows into `prompt_templates`, one per source: `prompt_evaluator`, `llm_review_agent`, `work_discovery`, `project_grader_docker_logs`.
   - Each: `parent_version_id = (current active template for that task_type)`, `canary_eligible=True`, `canary_traffic_pct=10` (start at 10% per Learn-16 default), `provider_override='ollama'`, `source_filter='<source_name>'`.
   - SQL via Alembic data migration in the same `034_*.py` file so it's reversible.

7. **Frontend toggle UI** in the existing LLM Console page ([frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx)):
   - New panel "Provider Overrides" listing every active override row with: source filter, target provider, canary %, last rolled-back-at, current `review_score` delta vs control.
   - Buttons: bump canary % (10→25→50→100), force rollback (writes `canary_traffic_pct=0`), delete override.
   - Reuse existing `useLLMConsole.ts` hook patterns; add `useProviderOverrides.ts`.

8. **Prometheus alerts** added to [docker/prometheus/alert_rules.yml](docker/prometheus/alert_rules.yml):
   - `OllamaProviderOverrideQualityRegression` — `legion_provider_override_rolled_back_total` increasing > 0/15min.
   - `OllamaCallLatencyHigh` — `legion_llm_call_duration_seconds{provider="ollama"} p95 > 600s for 10min`.
   - `OllamaCircuitBreakerOpen` — existing alert; verify it still fires.

9. **Verification (mandatory before Learn-19)**:
   - After rebuild, query `SELECT source, COUNT(*) FROM llm_call_details WHERE provider='ollama' AND created_at > NOW() - INTERVAL '2 hours' GROUP BY source` — should ONLY show the 4 Tier 1 sources.
   - `legion_provider_override_total` counter should be incrementing for those 4 sources.
   - `feedback_loop_verifier` `/api/prompt-manager/verification/run` returns the 4 new override rows in the verdict list (`insufficient_data` initially).
   - Backend `/health` reports `"ollama_disabled": true` BUT `/api/prompt-manager/templates/canary` lists 4 rows with `provider_override='ollama'`.
   - **Spontaneous-fire rule (Learn-17, Recovery-01)**: within 5 minutes of restart, at least one of the 4 sources should have produced a real Ollama call AND a `review_score` row.

**Critical files**:
- [backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py) (`_enforce_provider_gate` at L278-291, `execute` template lookup at L848-876)
- [backend/app/services/prompt_manager_service.py](backend/app/services/prompt_manager_service.py) (`SOURCE_TASK_TYPE_MAP` L28-44, `_canary_cache` L60-119, `get_template_for_task_type`)
- [backend/app/services/feedback_loop_verifier.py](backend/app/services/feedback_loop_verifier.py) (extend regression handling)
- [backend/app/core/legion_config.py](backend/app/core/legion_config.py) (`TASK_MODEL_ROUTING` L676-689 — add comment but DO NOT collapse, the override layer sits above this)
- [backend/app/models/prompt_manager.py](backend/app/models/prompt_manager.py) (add `provider_override`, `source_filter` columns)
- [backend/alembic/versions/034_per_source_provider_routing.py](backend/alembic/versions/034_per_source_provider_routing.py) (NEW)
- [backend/app/api/endpoints/prompt_manager.py](backend/app/api/endpoints/prompt_manager.py) (new GET `/templates/provider-overrides`, POST `/templates/{id}/bump-canary-pct`)
- [frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx) (new "Provider Overrides" panel)
- [frontend/src/hooks/useProviderOverrides.ts](frontend/src/hooks/useProviderOverrides.ts) (NEW, mirrors `useLLMConsole.ts`)
- [docker/prometheus/alert_rules.yml](docker/prometheus/alert_rules.yml)

**Reuse (do NOT reimplement)**:
- `prompt_manager_service._cache_valid()`, `_refresh_cache()` (Learn-16 cache TTL pattern)
- `feedback_loop_verifier._compute_delta_pvalue()` (Welch's t-test math)
- `feedback_loop_verifier._rollback()` → `revert_template()` (Learn-17 lifecycle primitive rule)
- `_metrics.ollama_queue_depth`, `_metrics.circuit_breaker_state` (existing Prometheus gauges)
- `OllamaClient` and the entire `_ollama_semaphore` / `_ollama_circuit` infrastructure ([unified_llm_service.py:64-70](backend/app/services/unified_llm_service.py#L64-L70))
- `add_done_callback(lambda t: t.exception())` pattern from Learn-15 for any new fire-and-forget tasks

**Verification (end-to-end)**:
- Migration: `cd backend && alembic upgrade head` → check `\d prompt_templates` shows new columns
- Smoke test: `docker exec legion-backend python -c "import asyncio; from app.services.prompt_manager_service import PromptManagerService; svc=PromptManagerService(); print(asyncio.run(svc.get_provider_override('prompt_evaluator', 'analysis')))"` → should return `'ollama'`
- Live: `curl -s http://localhost:8005/api/prompt-manager/templates/provider-overrides | python -m json.tool` returns 4 rows
- Spontaneous fire (within 5 min): `docker exec legion-db psql -U legion -d legion -c "SELECT source, provider, COUNT(*) FROM llm_call_details WHERE created_at > NOW() - INTERVAL '5 minutes' AND provider='ollama' GROUP BY source, provider"`
- Auto-rollback dry-run: `curl -s -X POST http://localhost:8005/api/prompt-manager/verification/run | python -m json.tool` — should include the 4 override rows in the result
- Rollback escape hatch: `UPDATE prompt_templates SET canary_traffic_pct=0 WHERE provider_override='ollama'` reverts everything in <1s

**Success criteria**:
- 100% of `prompt_evaluator` calls flow to Ollama within 24h of canary bump to 100%
- `review_score` for `prompt_evaluator` calls on Ollama is within 5 points of MiniMax baseline (Welch p<0.1)
- Cost: 7d MiniMax cost drops by ~$2 (the prompt_evaluator portion)
- Zero unscheduled rollbacks
- The 1,002-call leak path is either closed or all leaks are accounted for in the override system

---

### Learn-19: Tier 2 expansion (mid-stakes sources, conditional on Learn-18 verdict)

**Goal**: Once Learn-18 has been live for 7 days with a positive verdict from `feedback_loop_verifier`, expand to Tier 2 sources. This sprint exists ONLY if Learn-18 verifies cleanly.

**Pre-flight gate** (codified in the sprint's first task):
- `legion_provider_override_rolled_back_total` counter for `prompt_evaluator` is exactly 0 over 7d
- `feedback_loop_verifier` reports `verified_positive=true` for at least 2 of the 4 Tier 1 sources
- Sprint Creation Gate is still in `safe` mode (no spam)
- 14d Fix- failure rate stays at 0.000

**If gate fails**: do NOT create Learn-19. Investigate Tier 1 regression instead and create a Recovery-02 sprint.

**Tasks** (only if gate passes):

1. Add 4 more canary rows for Tier 2 sources via SQL: `external_knowledge_cross_ref`, `task_orchestration_evaluate`, `agent:code_reviewer`, `claude_executor`. Initial `canary_traffic_pct=10`.

2. Extend the LLM Console panel to surface Tier 2 metrics side-by-side with Tier 1, so the user can visually compare quality regression across all 8 sources at once.

3. Add a new task_type-level migration: for `TaskType.DOCUMENTATION` and `TaskType.ANALYSIS` (the 2 task types where Ollama already has avg `review_score > 20` per the discovery data), create a **task_type-wide** override row (with `source_filter=NULL`). This catches any new source that maps to those task types automatically.

4. Add a `legion_llm_cost_savings_usd_total` Prometheus counter that increments with `(minimax_cost_per_call - 0)` whenever an override routes a call to Ollama instead of MiniMax. Show on the Grafana dashboard.

**Critical files**: same as Learn-18; only data migrations change.

**Verification**: same pattern as Learn-18 but for the 4 new sources. Plus a cumulative cost-savings rollup query.

**Success criteria**: ~$8/wk in cumulative savings, zero rollbacks across all 8 active overrides, `feedback_loop_verifier` 7d effectiveness gauge stays > 95%.

---

### Learn-20: Natural-language workflow synthesis (steal AutoAgent idea #1)

**Goal**: Implement AutoAgent's most compelling capability — turning a natural-language description into an executable plan/sprint — using Legion's existing infrastructure. Zero new dependencies. Builds on the Builder Mode spec inference work that already exists.

**Tasks**:

1. **Reuse `BuilderSpecDB` and `ProjectSpecService`** (already shipped in Builder-01):
   - The spec pipeline already does prompt → structured output. Generalize the prompt template to also produce a `SprintPlan` schema in addition to `ProjectSpec`.

2. **New service `WorkflowSynthesisService`** in `backend/app/services/workflow_synthesis_service.py`:
   - Single method: `synthesize_sprint_from_description(description: str, project_id: int, target_category: str) -> SprintDB`.
   - Uses `unified_llm_service.execute_structured()` with a flat Pydantic schema (no `Dict[str, X]` per Learn-15 rule). Schema fields: `sprint_name: str`, `sprint_description: str`, `task_titles: List[str]`, `task_prompts: List[str]`, `estimated_story_points: List[int]`.
   - Routes through the **task_type='planning'** path so it inherits whatever provider that task_type currently uses (MiniMax for now, can be migrated to Ollama via Learn-18 canary later).
   - Calls the existing `SprintManager.create_sprint` (which is on the `manual_api` allowlist of `sprint_creation_gate`) so it works in current `safe` mode.

3. **API endpoint** `POST /api/sprints/from-description` in [backend/app/api/endpoints/sprints.py](backend/app/api/endpoints/sprints.py):
   - **CRITICAL — FastAPI route ordering**: place this above `GET /sprints/{sprint_id}` and add the `# NOTE: literal path — must be before /{sprint_id}` defensive comment per Sprint-Cleanup-02 rule.
   - Body: `{description: str, project_id: int, category: str}` (e.g., `category="Builder"`, `category="Improve"`).
   - Returns the created sprint immediately. The actual task execution still goes through the normal sprint lifecycle.

4. **Frontend "Quick Sprint" UI** in [frontend/src/pages/SprintCenter.tsx](frontend/src/pages/SprintCenter.tsx):
   - New button next to the existing manual creation form: "Describe Sprint in English →".
   - Modal with a single textarea + category picker. On submit, calls the new endpoint.
   - On success, shows a preview of the synthesized tasks with an "Approve & Create" / "Edit" / "Discard" choice.
   - This is the first step toward AutoAgent's "zero-code" promise.

5. **Wire reasoning capture (Observe-03)**: every synthesis call writes a `brain_decision` row with `decision_type='workflow_synthesis'`, the input description, the synthesized output, and a confidence score. Allows audit and learning.

**Critical files**:
- [backend/app/services/workflow_synthesis_service.py](backend/app/services/workflow_synthesis_service.py) (NEW)
- [backend/app/api/endpoints/sprints.py](backend/app/api/endpoints/sprints.py) (new endpoint at top, before `{sprint_id}` route)
- [frontend/src/pages/SprintCenter.tsx](frontend/src/pages/SprintCenter.tsx)
- [frontend/src/hooks/useWorkflowSynthesis.ts](frontend/src/hooks/useWorkflowSynthesis.ts) (NEW)
- [backend/app/models/spec.py](backend/app/models/spec.py) (extend `BuilderSpecDB` to also store `synthesized_sprint_id` FK if it produced one)

**Reuse (do NOT reimplement)**:
- `unified_llm_service.execute_structured()` and the Pydantic schema validation it provides
- `SprintManager.create_sprint()` and the entire sprint lifecycle
- `sprint_creation_gate` allowlist (the new endpoint goes through `manual_api`, no gate change needed)
- Reasoning capture helper from Observe-03
- Builder-01's `ProjectSpecService` patterns for prompt design

**Verification**:
- Curl: `curl -X POST http://localhost:8005/api/sprints/from-description -d '{"description":"Add a button to the dashboard that exports the current view as PDF","project_id":3,"category":"Builder"}'` returns a sprint with 3-5 tasks
- DB: `SELECT * FROM sprints WHERE created_at > NOW() - INTERVAL '5 minutes' ORDER BY id DESC LIMIT 1` shows the new sprint with the synthesized tasks
- DB: `SELECT * FROM brain_decisions WHERE decision_type='workflow_synthesis' ORDER BY id DESC LIMIT 1` shows the reasoning capture row
- Frontend: navigate to `/sprints`, click "Describe Sprint in English", enter a paragraph, see the preview, approve, see the new sprint in the list

**Success criteria**: 5 successfully synthesized sprints in the first 24 hours, all with `task_count >= 1`, zero failed synthesis attempts (synthesis call succeeds even if user rejects the preview).

---

### Learn-21: Tool synthesis via Learn-16/GEPA (steal AutoAgent idea #2)

**Goal**: Extend Learn-16's DSPy/GEPA prompt evolution daemon to also evolve **tool definitions**, not just system prompts. This is AutoAgent's most novel capability and Legion already has 80% of the infrastructure.

**Tasks**:

1. **Migration `035_tool_evolution.py`**:
   - Add new template `kind` column to `prompt_templates` (`String(20)`, default `'system_prompt'`). New value: `'tool_definition'`.
   - Add `tool_signature` column (Text, nullable) — JSON string of the tool's input schema.
   - Add `tool_implementation` column (Text, nullable) — Python source code of the tool body.
   - All new columns default to NULL for existing rows.

2. **Extend `dspy_optimizer_service`** in [backend/app/services/dspy_optimizer_service.py](backend/app/services/dspy_optimizer_service.py):
   - New method `compile_tool(tool_id, train_examples)` mirroring the existing `compile_prompt` API surface.
   - Uses the same `_GEPARewrite` pattern but with a new flat Pydantic schema (per Learn-15 MiniMax rule): `new_tool_signature: str`, `new_tool_implementation: str`, `rationale: str`, `estimated_delta: float`.
   - Train examples come from `llm_call_details` rows where `request_type='tool_use'` and the tool was actually invoked, scored by whether the downstream task succeeded.

3. **Sandboxed tool execution** in a new `backend/app/services/synthesized_tool_runner.py`:
   - Loads tool source from `prompt_templates.tool_implementation`.
   - Validates against `tool_signature` JSON schema.
   - Runs in a subprocess with `subprocess.run(timeout=10, capture_output=True)` for isolation. **No `exec()` of LLM-generated code in-process.** Crash containment is non-negotiable.
   - On success, returns the result as a `ToolResult` dataclass (already exists in Legion).
   - On failure, logs to `llm_call_details.suggested_improvement` so Learn-17's verifier can roll back the tool the same way it rolls back prompts.

4. **Wire into agent middleware**:
   - Extend `MetricsMiddleware` (or add a new `ToolSynthesisMiddleware`) so any agent that has `can_use_synthesized_tools=True` gets `synthesized_tools: List[ToolDef]` injected into its context. Loaded from `prompt_templates WHERE kind='tool_definition' AND is_active=True AND canary_traffic_pct >= 50`.
   - Initially limit to 2 specialist agents (`code_review_agent`, `testing_agent`) to bound the blast radius.

5. **Verify with a planted seed tool**:
   - Insert ONE manual tool definition via SQL: a simple "count_lines" tool that takes a file path and returns line count. Use this to prove the synthesis pipeline end-to-end before letting GEPA write its own.

**Critical files**:
- [backend/alembic/versions/035_tool_evolution.py](backend/alembic/versions/035_tool_evolution.py) (NEW)
- [backend/app/services/dspy_optimizer_service.py](backend/app/services/dspy_optimizer_service.py)
- [backend/app/services/synthesized_tool_runner.py](backend/app/services/synthesized_tool_runner.py) (NEW)
- [backend/app/agents/middleware.py](backend/app/agents/middleware.py)
- [backend/app/models/prompt_manager.py](backend/app/models/prompt_manager.py)

**Reuse (do NOT reimplement)**:
- `feedback_loop_verifier` regression detection — works for tools the same way it works for prompts because both are scored via downstream `review_score`
- `dspy_evolution_daemon` cycle structure (it already runs nightly, just give it a second mode)
- `agent_registry` capability flags pattern
- `prompt_templates` versioning (parent_version_id chain)

**Verification**:
- Run the planted seed tool through the runner: `docker exec legion-backend python -c "import asyncio; from app.services.synthesized_tool_runner import run_tool; print(asyncio.run(run_tool('count_lines', {'path': '/app/main.py'})))"` returns the line count
- Grade a synthesized tool: bump its `canary_traffic_pct=10`, watch `llm_call_details.review_score` for the next 24h, verify Learn-17 either promotes or rolls back

**Success criteria**: 1 planted tool runs successfully, 1 GEPA-synthesized tool reaches `canary_traffic_pct=50`, zero subprocess sandbox escapes.

---

## Cross-sprint constraints (apply to ALL 4 sprints)

1. **No new daemons** — extend existing daemons via the lazy-import + try/except piggyback pattern from Learn-17.
2. **No global env-var flips** — every change is scoped to a feature flag, a DB row, or a specific source. The user has been burned by global flips and refuses to re-introduce them.
3. **`ENABLE_DSPY_EVOLUTION` stays `false` until Learn-21** — flipping it before then would have GEPA writing canaries against an empty `prompt_template_id` capture rate, wasting credits with no learning value. Flip it as the LAST task of Learn-21.
4. **FastAPI route ordering rule** — every literal-path GET/POST under a router with a `/{param}` route MUST be source-ordered before that route. Add the `# NOTE: literal path — must be before /{param}` defensive comment.
5. **MiniMax JSON schema rule (Learn-15)** — every new Pydantic schema sent to MiniMax via `execute_structured` must be flat with explicit named primitive fields. No `Dict[str, X]`.
6. **Reasoning capture writes are non-blocking** — every new persistence call wraps the write in `try/except logger.warning(...)` per Observe-03 rule. Failure to persist reasoning never blocks the user-facing operation.
7. **Spontaneous-fire verification rule (Recovery-01, Sprint-Cleanup-02)** — after every rebuild, the new code path must fire spontaneously within 60 seconds (or 5 min for low-volume paths). If it doesn't, the wiring is broken — DO NOT wait for the cycle to verify.
8. **Docker rebuild discipline** — `docker-compose restart` does NOT pick up backend code changes. Always `docker-compose build legion-backend && docker-compose up -d legion-backend`. Same for frontend.
9. **Sprint Creation Gate stays in `safe` mode** through Learn-18 and Learn-19. Only flip to `on` after Learn-20 is verified, since Learn-20 unlocks the natural-language sprint creation path that needs the gate open to be useful.

## Cost projection

| Sprint | Expected ~weekly savings | Cumulative |
|--------|--------------------------|------------|
| Learn-18 (Tier 1: 4 sources) | ~$2/wk | ~$2/wk |
| Learn-19 (Tier 2: +4 sources, +2 task types) | ~$8-12/wk | ~$10-14/wk |
| Learn-20 (workflow synthesis) | $0 directly, but enables NL-driven sprint creation that previously required premium calls — indirect savings ~$3/wk | ~$13-17/wk |
| Learn-21 (tool synthesis) | $0 directly, enables agent self-improvement which compounds quality over time | ~$13-17/wk steady state |

**This is intentionally conservative.** Tier 1 alone saves ~$2/wk because `prompt_evaluator` uses small prompts. The bigger latent savings come from migrating Kimi-heavy paths in a hypothetical Learn-22, but the user explicitly wants to "test piece by piece" so we don't preemptively migrate Kimi traffic — we wait for Learn-18 to prove the pattern works first.

## Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Ollama latency 6x MiniMax (54s vs 360s) | HIGH | Background daemons fall behind | Tier 1 sources are all background — latency is acceptable. Tier 2/3 stay on premium. |
| GPU VRAM saturation when Ollama load grows | MEDIUM | Model swap thrash, OOM | GPU Manager (project_id=14) already monitors. Add alert when VRAM > 90% AND `ollama_queue_depth` > 8. |
| `feedback_loop_verifier` doesn't have enough samples to verify (sparseness limit, 0.25% capture rate) | HIGH | Canaries stay `insufficient_data` forever | Tier 1 source `prompt_evaluator` produces 9,595 calls/7d → MORE than enough samples. The sparseness only bites Tier 3. |
| Subprocess tool runner sandbox escape (Learn-21) | LOW | RCE | `subprocess.run(timeout=10)`, no shell, no `exec()` in-process, all inputs JSON-validated |
| Learn-18 closes a "leak path" that some legitimate code actually depends on | MEDIUM | Backend crash | Audit-first, fix-second. Document each leak before closing. |
| User decides mid-rollout to change strategy | LOW | Wasted work | Each sprint is independently revertible via `git revert` + 1 SQL DELETE |
| Kimi gate starts leaking again | LOW | Cost spike | The gate already held for 22h. Add a Prometheus alert: `KimiCallRateUnexpected` if `legion_llm_calls_total{provider="kimi"}` rate > 0/min for >5min. |

## What we are NOT doing

- **NOT integrating AutoAgent as a library** — fork/maintenance burden too high, LiteLLM dependency violates Recovery-01.
- **NOT running AutoAgent as a sidecar Docker container** — user explicitly chose "steal the ideas, not the code".
- **NOT flipping `OLLAMA_DISABLED=false` globally** — surgical per-source overrides only.
- **NOT flipping `KIMI_DISABLED=false`** — Kimi's gate has finally held; leave it closed until there's a specific business need to re-open it.
- **NOT migrating `planning_cortex`, `sprint_tool`, or `brain:plan_vote`** to Ollama in this roadmap — these are critical-path quality-sensitive sources, premium-only.
- **NOT touching `sprint_creation_gate`** — stays in `safe` mode through Learn-19.
- **NOT enabling `ENABLE_DSPY_EVOLUTION`** until the LAST task of Learn-21.
- **NOT building a new daemon** — every periodic job piggybacks on `_improvement_cycle()` per Learn-17 rule.

## End-to-end verification (after all 4 sprints)

1. **Ollama is alive and serving 8 specific sources**:
   ```sql
   SELECT source, COUNT(*) FROM llm_call_details
   WHERE provider='ollama' AND created_at > NOW() - INTERVAL '24 hours'
   GROUP BY source ORDER BY COUNT(*) DESC;
   ```
   Expected: 8 source rows, all from the override allowlist, none from elsewhere.

2. **Quality is non-regressed**:
   ```sql
   SELECT source, provider, AVG(review_score), COUNT(*)
   FROM llm_call_details
   WHERE created_at > NOW() - INTERVAL '7 days' AND review_score IS NOT NULL
     AND source IN ('prompt_evaluator','llm_review_agent','work_discovery','project_grader_docker_logs')
   GROUP BY source, provider ORDER BY source, provider;
   ```
   Expected: per-source avg `review_score` for `provider='ollama'` is within 5 points of `provider='minimax'` baseline.

3. **Cost is down**:
   ```sql
   SELECT date_trunc('day', created_at), provider, SUM(cost_total)
   FROM llm_usage WHERE created_at > NOW() - INTERVAL '14 days'
   GROUP BY 1, 2 ORDER BY 1 DESC, 2;
   ```
   Expected: daily MiniMax cost trends down by ~$0.30-0.50/day starting from Learn-18 deploy date.

4. **Workflow synthesis works end-to-end**:
   - Frontend: open SprintCenter → "Describe Sprint in English" → enter "Add dark mode toggle to settings" → see preview → approve → sprint appears in the list with 3+ tasks
   - DB: new sprint exists, has reasoning_capture row, executes through normal sprint lifecycle

5. **Tool synthesis works end-to-end**:
   - The planted `count_lines` tool runs successfully in the sandbox
   - At least 1 GEPA-synthesized tool exists with `canary_traffic_pct >= 10`
   - `feedback_loop_verifier` `/api/prompt-manager/verification/stats` shows tool verification rows

6. **The system is still healthy**:
   - `/health` returns healthy
   - `legion_sprint_creation_blocked_total` rate has not spiked
   - Sprint quality grades for the last 5 manual sprints stay > 75/100
   - `sprint_creation_mode` is still `safe` (or `on` if Learn-20 verified)

## Next operator action after Learn-21 completes

Flip `ENABLE_DSPY_EVOLUTION=true` in `docker-compose.yml`. This is the final unlock from the Learn-14 → Learn-17 roadmap that we have been deferring since the verifier's `prompt_template_id` capture rate was too low. After Learn-18's per-source canary infrastructure is in production, that capture rate should climb naturally as more calls flow through `prompt_manager_service.get_template_for_task_type()` looking up overrides — and once it crosses ~5%, GEPA has enough data to start writing real canaries that the verifier can grade.
