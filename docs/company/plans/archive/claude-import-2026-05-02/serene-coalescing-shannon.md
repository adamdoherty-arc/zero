# Legion Recovery Plan — Make It Actually Work

## Context

You've been working on Legion for months. 52 fix sprints (Fix-01 → Fix-52) have shipped, each addressing what looked like the cause of failures. Yet today:

- **ADA Trading Platform**: 18 failed sprints, 75 failed tasks, **0% completion**
- **Legion**: 17 failed sprints, 68 failed tasks
- **Ollama Manager**: 2 failed sprints
- **Sprint quality grader** says: Decomposition 85, Prompt Quality 100, **Execution 12**, Learning Capture 0
- Dashboard returns 502, prompt evaluator leaks chain-of-thought, frontend has stale tabs/counters
- Kimi is rate-limiting, Ollama may be silently CPU-thrashing on the RTX 5090

The grader is honest. The system is broken at **task execution**, not at planning or grading. Every fix has been one layer too late.

This plan does three things:
1. **Stops the bleeding** — fix THE root cause of sprint failures (one ignored `errors` array in the supervisor) so tasks actually start completing
2. **Simplifies the LLM layer to MiniMax-only** — MiniMax M2 (API key already added) becomes the *sole* provider for planning AND execution. Ollama is **temporarily disabled** to remove every variable: no semaphore, no circuit breaker races, no GPU/VRAM concerns, no session corruption from local timeouts. **Ollama comes back as a local execution tier in a future phase, ONLY after the system is provably stable end-to-end.** Kimi also off — one provider, one failure mode, easy to debug.
3. **Closes the self-improvement loop** — wire failure-analysis-to-fix as an immediate feedback (not 4h batched), enable the council, surface learning during planning

After this plan: Legion should reach **>50% sprint completion in the first day**, **80%+ within a week** as the learning loop starts compounding. Once stable, Phase 5 brings Ollama back as local fallback to cut cloud spend.

A history of what we tried and learned will be appended to [.claude/skills/legion-sprint-auditor/knowledge/recovery_history.md](.claude/skills/legion-sprint-auditor/knowledge/recovery_history.md) so future sessions don't repeat this archaeology.

---

## STATUS (post-Phase 4 verification, April 2026): Recovery-01 has a Phase 1 leak — DO THIS NEXT

Phases 0, 2, 3, 4 are verified working. Phase 1 ships a partial fix. **The swarm still routes to disabled Ollama.** This blocks success criterion #2 (1h wall-clock end-to-end completion) — wall-clock time will not pass it because every swarm coder call hits `LLM Error: Ollama disabled (Recovery-01 Phase 1)` in <1 second, exhausts the (post-Phase 0) 6-attempt retry loop, corrupts the session, and the orchestrator gives up with `the connection is closed`. All in-flight tasks then get orphan-swept with `Stuck task recovered`.

**Live evidence (Sprints 2873 + 2874, 03:34 UTC)**:
```
[Swarm] Coder: executing with model=qwen3-coder-next, task=...
[Swarm] Coder produced no usable output (cli_output=LLM Error: LLM not available:
        Ollama disabled (Recovery-01 Phase 1) — see serene) —
        routing to diagnostician (attempt 1/6)
... (5 more retries) ...
[Lifecycle] Execute sprint 2874 error: the connection is closed
[Orchestrator] Task execution error: the connection is closed
Sprint 2873: all 5 tasks marked FAILED with last_error="Stuck task recovered"
Sprint 2874: PLANNED → ACTIVE → task 9350 stuck RUNNING
```

The "connection is closed" error is **NOT a session-refresh bug** (the user's earlier framing of Recovery-02). It is a downstream symptom of the 6-attempt loop holding the session open while pounding a disabled provider.

### Root cause chain

| # | File | Line | What it does | What's wrong |
|---|---|---|---|---|
| 1 | [legion_config.py](backend/app/core/legion_config.py#L649-L652) | 649-652 | `_PRIMARY_MODEL_TAG = MODEL_REGISTRY[ModelType.OLLAMA_QWEN_CODER_NEXT].ollama_tag` then `OLLAMA_ESCALATION = [_PRIMARY_MODEL_TAG]` | Comment claims "never used while Ollama disabled" — **wrong**, swarm uses it. |
| 2 | [agent_swarm_service.py](backend/app/services/agent_swarm_service.py#L120) | 120 | `from app.core.legion_config import OLLAMA_ESCALATION as MODEL_LADDER` | Imports the Ollama-only ladder unconditionally. |
| 3 | [agent_swarm_service.py](backend/app/services/agent_swarm_service.py#L321) | 171, 264, 297, 321, 461, 544, 600, 1158 | All hardcoded to `MODEL_LADDER[0]` = `"qwen3-coder-next"` | Coder, critique, review, diagnosis, and initial state all pin to disabled Ollama. |
| 4 | [sprint_tools.py](backend/app/services/sprint_tools.py#L86-L96) | 86-96 | `await llm.execute(prompt=..., force_model=attempt_model, ...)` | `force_model="qwen3-coder-next"` **bypasses task_type routing entirely** ([unified_llm_service.py:491-498](backend/app/services/unified_llm_service.py#L491-L498)). Phase 1's collapsed `TASK_MODEL_ROUTING` is never consulted. |
| 5 | [unified_llm_service.py](backend/app/services/unified_llm_service.py#L205) | 205 | `OLLAMA_DISABLED` check raises `ServiceUnavailableError("Ollama disabled (Recovery-01 Phase 1) — see serene")` | Correct gate — but it fires on EVERY swarm call because of the chain above. |
| 6 | [sprint_tools.py](backend/app/services/sprint_tools.py#L106-L109) | 106-109 | Catches `ServiceUnavailableError` → returns string `"LLM Error: ..."` | Phase 0's supervisor fix correctly catches this (good) but every retry hits the same wall. |

### The fix (~6 lines, single file)

The minimum surgical fix is to gate the `MODEL_LADDER` import in `agent_swarm_service.py` so it picks MiniMax M2 when Ollama is disabled. `_resolve_force_model()` at [unified_llm_service.py:363](backend/app/services/unified_llm_service.py#L363) already accepts `ModelType("minimax-m2")` directly, so passing `"minimax-m2"` as `force_model` routes to MiniMax with no other code changes needed. The `OLLAMA_FALLBACK` chain in `sprint_tools.py:65-72` exits immediately for non-Ollama keys, so the loop runs once and the rest of the tool stays untouched.

**File: [backend/app/services/agent_swarm_service.py](backend/app/services/agent_swarm_service.py#L120)** — replace line 120:

```python
# OLD (line 120):
from app.core.legion_config import OLLAMA_ESCALATION as MODEL_LADDER

# NEW:
import os as _os
from app.core.legion_config import OLLAMA_ESCALATION, ModelType
if _os.getenv("OLLAMA_DISABLED", "true").lower() in ("true", "1", "yes"):
    # Recovery-01 Phase 1: route swarm through MiniMax M2 while Ollama is disabled
    MODEL_LADDER = [ModelType.MINIMAX_M2.value]
else:
    MODEL_LADDER = OLLAMA_ESCALATION
```

That's the entire fix. No other file needs to change. Specifically:

- **Do NOT modify `OLLAMA_ESCALATION`** in `legion_config.py` — it's also consumed by `OLLAMA_DEFAULT_TAG` at line 781, and changing it would corrupt downstream Ollama-aware code paths needed for Phase 5 reactivation.
- **Do NOT modify `sprint_tools.py`** — `force_model="minimax-m2"` flows through `_resolve_force_model()` cleanly. The "Ensure Ollama is running" wording in the error message at line 107 is now misleading but is not blocking.
- **Do NOT touch the 5 hardcoded `MODEL_LADDER[0]` references** in `agent_swarm_service.py` — they all read from the module-level `MODEL_LADDER` which now points at MiniMax via the gated import above.

### Optional secondary cleanup (defer to follow-up sprint)

These are quality-of-life improvements that are NOT required to pass criterion #2:

1. **`sprint_tools.py:107`** — update the error message from "Ensure Ollama is running: ollama serve" to a generic "LLM provider unavailable" (cosmetic, log-noise only).
2. **`agent_swarm_service.py` log lines** — `[Swarm] Coder: executing with model=...` will now print `minimax-m2` instead of `qwen3-coder-next`. Verify the dashboards/Grafana panels that key off this string still render.
3. **Phase 5 prep** — when Ollama comes back, the env-gated import above flips automatically.

### Verification

```bash
# 1. Rebuild + restart backend (NOT just restart — code is baked into image)
docker-compose build legion-backend && docker-compose up -d legion-backend

# 2. Confirm the swarm now picks MiniMax
docker exec legion-backend python -c "from app.services.agent_swarm_service import MODEL_LADDER; print(MODEL_LADDER)"
# Expected: ['minimax-m2']

# 3. Force a single sprint through the swarm path
docker exec legion-backend python -c "
import asyncio
from app.services.autonomous_sprint_executor import AutonomousSprintExecutor
asyncio.run(AutonomousSprintExecutor().run_sprint(<sprint_id>))
"

# 4. Watch the swarm log line
docker logs legion-backend --tail 200 2>&1 | grep -E "Swarm.*Coder.*executing"
# Expected: [Swarm] Coder: executing with model=minimax-m2, task=...
# NOT:      [Swarm] Coder: executing with model=qwen3-coder-next, task=...

# 5. Confirm at least 1 task COMPLETED with qa_status='approved'
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, status, qa_status, last_error FROM sprint_tasks WHERE sprint_id=<id>;"

# 6. Tail logs for "Ollama disabled" — should be ZERO new occurrences after restart
docker logs legion-backend --since 5m 2>&1 | grep -c "Ollama disabled"
# Expected: 0

# 7. THEN run the 1h wall-clock test for criterion #2
# Leave AGENTIC_MODE=true for ~60 minutes, then check:
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, name, status, total_tasks, completed_tasks FROM sprints
   WHERE created_at > now() - interval '1 hour' AND status='COMPLETED';"
# Expected: at least 1 row
```

### Updated criterion #2 status

Criterion #2 (1h wall-clock end-to-end completion) is **BLOCKED on this 6-line fix**, NOT on wall-clock time. The agentic loop is firing correctly (verified by Phase 2 — Sprint 2874 was created in 6s by failure-triggered RCA), but every sprint it creates dies in the swarm coder before any task can complete. After this fix lands, criterion #2 should pass within one cycle (≤5 minutes), not 1 hour.

### Recovery-02 reframing

The user's prior framing of `Recovery-02 = Fix-51-style session-refresh in sprint_lifecycle_graph.execute_active_sprints` was based on the assumption that "the connection is closed" was the root cause. It is not — it is a symptom of the swarm beating on disabled Ollama for 6 attempts in a single session. After this Phase 1 leak fix lands:

- **If "the connection is closed" still appears** in `sprint_lifecycle_graph.py:342` or `task_orchestration_agent.py:423` logs → Recovery-02 = the session-refresh fix as originally framed.
- **If the error disappears entirely** → Recovery-02 should be retitled and target the next observed bottleneck (likely cost budgeting or rate limiting on MiniMax once swarm volume picks up).

Decide on Recovery-02 scope AFTER verifying the Phase 1 leak fix in production.

---

## The ONE Bug That Hides All Others

**Location**: [backend/app/services/agent_swarm_service.py:227-230](backend/app/services/agent_swarm_service.py#L227-L230) — `supervisor_node()`

```python
# CURRENT (broken):
if phase == "executing":
    return {"next_agent": "critique", "phase": "critiquing"}
```

**What happens**: `coder_node` calls `execute_llm_task()`. When the LLM call fails (timeout, rate limit, error), `sprint_tools.execute_llm_task()` returns the string `"LLM Error: ..."` and `coder_node` populates `state["errors"] = ["LLM Error: ..."]`.

The supervisor **never reads `errors`**. It blindly routes to critique. Critique sees `cli_output.startswith("LLM Error")` and skips with `review_output=None`. Supervisor then routes to **testing on empty output**, which fails. After 6 retry loops with the same broken LLM call, the task is marked FAILED. All 7 tasks in a sprint hit the same wall. Sprint marked FAILED. Repeat forever.

**This bug exists regardless of which LLM provider you use.** Switching to MiniMax doesn't fix it — MiniMax can also rate-limit, time out, or fail. We MUST fix the supervisor first.

**Why every prior fix missed this**: Fix-41 → Fix-52 fixed enum case, session isolation, QA auto-approve, episode storage, complete_sprint() calls, structured output in graders — all DOWNSTREAM of execution. None of them looked at the supervisor routing table because the swarm path was assumed to be working. It never has been.

**The 5-line fix**:
```python
if phase == "executing":
    errors = state.get("errors", [])
    if errors:
        attempt = state.get("attempt_count", 0)
        max_attempts = state.get("max_attempts", 6)
        if attempt >= max_attempts:
            return {"next_agent": "mark_failed", "phase": "failed"}
        return {"next_agent": "diagnostician", "phase": "diagnosing"}
    return {"next_agent": "critique", "phase": "critiquing"}
```

Plus a generic LLM-availability pre-check in `coder_node` so we don't waste retry cycles when the active provider is rate-limiting or unreachable.

---

## Phase 0 — Stop The Bleeding (1-2 hours)

Goal: get the swarm path actually completing tasks.

### Files to modify
| File | Change |
|---|---|
| [backend/app/services/agent_swarm_service.py](backend/app/services/agent_swarm_service.py) | Add `errors` check in `supervisor_node` (lines ~227-230). Add `cli_output.startswith("LLM Error")` short-circuit in `coder_node` (line ~315) so a failed call goes straight to `diagnostician`, not `critique`. |
| [backend/app/services/sprint_tools.py](backend/app/services/sprint_tools.py) | `execute_llm_task()` should raise an explicit `LLMExecutionError` instead of returning the literal string `"LLM Error: ..."`. The swarm coder catches it and populates `state["errors"]` cleanly. (Optional but cleaner; the supervisor fix above works either way.) |

### Verification
```bash
# 1. Run a single sprint manually
docker exec legion-backend python -c "
from app.services.autonomous_sprint_executor import AutonomousSprintExecutor
import asyncio
asyncio.run(AutonomousSprintExecutor().run_sprint(<sprint_id>))
"

# 2. Check that completed_tasks > 0
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, name, total_tasks, completed_tasks, failed_tasks, status FROM sprints WHERE id=<sprint_id>;"

# 3. Confirm no 'LLM Error' strings made it to qa_status='approved'
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, status, qa_status, last_error FROM sprint_tasks WHERE sprint_id=<sprint_id>;"
```

**Expected**: at least 1 task COMPLETED with `qa_status='approved'`. Sprint quality `Execution` dimension jumps from 12 → 70+.

---

## Phase 1 — LLM Layer: MiniMax-Only (3-4 hours)

Goal: collapse the LLM layer to a **single provider (MiniMax M2)** for *every* call site — planning, execution, council, RCA, prompt evaluation, sprint generation, brain. Kimi is disabled. Ollama is disabled. One provider, one failure mode, one rate limiter to reason about. The user has already added `MINIMAX_API_KEY`.

> Why one provider: 52 prior fixes proved that every additional provider doubles the surface area of session-corruption / circuit-breaker / queue-saturation bugs. Stabilize the core on one provider, then re-introduce Ollama in Phase 5 as a measured optimization, not a survival mechanism.

### Decision: MiniMax M2 as the sole model

Based on April 2026 pricing/limits research:

| Model | Input $/M | Output $/M | Rate Limit | Notes |
|---|---|---|---|---|
| **MiniMax M2** ← **sole provider** | **$0.255** | **$1.00** | **500 RPM (paid) / 1500 calls per 5h** | Targets agent workflows; user has key |
| Kimi K2.5 (DISABLED) | $0.60 | $2.50 | 200 RPM | Was rate-limiting Legion; off |
| Ollama qwen3-coder-next (DISABLED) | local | local | semaphore=2 | Off until Phase 5 — too many concurrent local-execution failure modes |

MiniMax M2 is **2.4× cheaper input, 2.5× cheaper output, 2.5× higher RPM** than Kimi, and MiniMax explicitly targets agent-based coding workflows. 1500 calls per 5h is enough headroom for one Legion instance at expected sprint volume (~5-10 sprints/h × ~10 calls/sprint = 50-100/h, well under the limit).

Sources: [MiniMax pricing](https://platform.minimax.io/docs/pricing/overview), [Kimi K2.5 pricing 2026](https://www.nxcode.io/resources/news/kimi-k2-5-pricing-plans-api-costs-2026), [Coding comparison](https://docs.bswen.com/blog/2026-03-24-kimi-vs-minimax-coding-comparison/), [Chinese AI coding plans comparison](https://docs.bswen.com/blog/2026-03-31-ai-coding-plans-pricing-comparison/), [Rate limits](https://platform.minimax.io/docs/guides/rate-limits)

### Files to create / modify
| File | Change |
|---|---|
| [backend/app/llm/minimax_client.py](backend/app/llm/minimax_client.py) | **NEW** — mirror [backend/app/llm/kimi_client.py](backend/app/llm/kimi_client.py) line-for-line (it already has the correct pattern: `format=` kwarg + `json_schema` constraint, retry-on-rate-limit, 180s default timeout, `max_tokens=4000`, `_source=` tracking). Use OpenAI-compatible endpoint `https://api.minimax.io/v1/chat/completions`. Model id: `MiniMax-M2`. Honor `temperature` from caller (default 0.2). |
| [backend/app/core/legion_config.py](backend/app/core/legion_config.py) | (a) Add `ModelType.MINIMAX_M2 = "minimax-m2"` enum value. (b) Add `MODEL_REGISTRY[ModelType.MINIMAX_M2]` entry: provider="minimax", timeout=180, max_tokens=4000, cost_per_1k_input=0.000255, cost_per_1k_output=0.001. (c) **Rewrite `TASK_MODEL_ROUTING`** so EVERY task type maps to `[ModelType.MINIMAX_M2]` only — single-element list for PLANNING, ARCHITECTURE, GENERAL, CODE_GENERATION, DEBUGGING, TESTING, REVIEW, ANALYSIS. (d) Set `FULL_MODEL_ESCALATION = [ModelType.MINIMAX_M2]` (no escalation chain — same model). (e) Update tier aliases: `"primary"`, `"sonnet"`, `"opus"` ALL → `ModelType.MINIMAX_M2`. |
| [backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py) | (a) Add `_get_minimax_client()` lazy initializer mirroring `_get_kimi_client()`. (b) Add `minimax` branch in the provider switch in `execute()` and `execute_structured()` and `execute_with_tools()`. (c) **Disable Ollama branch**: when `OLLAMA_DISABLED=true` (new env var, default `true` for now), the Ollama provider raises `ServiceUnavailableError("Ollama disabled — see Phase 5 of recovery plan")` immediately, BEFORE acquiring the semaphore. (d) **Disable Kimi branch**: same pattern, gated by `KIMI_DISABLED=true`. (e) Add a sliding-window rate limiter for MiniMax: `_minimax_rate_limiter` enforcing `MINIMAX_RPM=400` (80% of paid 500 RPM ceiling) via an `asyncio.Semaphore`-style window. On 429 from MiniMax, exponential backoff up to 3 retries. (f) `get_llm_health()` reports MiniMax queue depth + recent 429 count. |
| [backend/app/llm/kimi_client.py](backend/app/llm/kimi_client.py) | **No code changes** — kept as-is for backwards compat with existing DB records and Phase 5 reactivation. Just unreachable behind the `KIMI_DISABLED` gate. |
| [backend/app/services/prompt_evaluator_agent.py](backend/app/services/prompt_evaluator_agent.py) | **THE leak fix** — replace `service.execute(prompt=...)` (lines ~266-272 in `_evaluate_request`) with `service.execute_structured(prompt=..., response_model=PromptEvalResponse)`. Define two Pydantic schemas at top of file: `PromptRequestEval` and `PromptResponseEval`, each with `clarity: int`, `specificity: int`, `context_completeness: int`, `overall: int`, `issues: list[str]`, `suggested_improvement: str`. Mirror exactly how [llm_review_service.py:153](backend/app/services/llm_review_service.py#L153) uses `execute_structured()` with `LLMReviewResponse`. This stops Kimi/MiniMax chain-of-thought from being persisted as the "evaluation". |
| [backend/.env](backend/.env) | Add `MINIMAX_API_KEY=<user-supplied>`. Add `OLLAMA_DISABLED=true`. Add `KIMI_DISABLED=true`. Add `MINIMAX_RPM=400`. **Do NOT** add `OLLAMA_NUM_GPU` — Ollama is off this phase. |
| [docker-compose.yml](docker-compose.yml) | Pass `MINIMAX_API_KEY`, `OLLAMA_DISABLED=true`, `KIMI_DISABLED=true`, `MINIMAX_RPM=400` env vars through to `legion-backend`. |

### Audit step (no code changes — verification only)
After the routing rewrite, grep for any remaining Ollama / Kimi reference paths so we know nothing slips through:

```bash
# Should return zero hits for "executable" calls (only client files + Phase 5 docs)
grep -rn "ollama\|qwen3\|kimi" backend/app/services/ --include="*.py" \
  | grep -v "kimi_client.py\|ollama_manager\|gpu_manager\|external_knowledge"
```

Any hit needs to either route through `UnifiedLLMService.execute()` (which is now MiniMax-only) or be removed.

### Verification
```bash
# 1. MiniMax connectivity through the unified service
curl -s -X POST http://localhost:8005/llm/execute \
  -H "Content-Type: application/json" \
  -d '{"prompt":"return JSON {\"ok\":true}","task_type":"PLANNING","_source":"verify"}'
# Expected: 200 with content from MiniMax-M2, model field reads "minimax-m2"

# 2. Confirm Ollama is disabled (should refuse, not queue)
curl -s -X POST http://localhost:8005/llm/execute \
  -H "Content-Type: application/json" \
  -d '{"prompt":"hi","task_type":"GENERAL","force_model":"qwen3-coder-next","_source":"verify"}'
# Expected: 503 ServiceUnavailable with "Ollama disabled" message

# 3. Confirm health endpoint shows minimax as the only provider in use
curl -s http://localhost:8005/llm/health | python -m json.tool
# Expected: minimax provider listed, ollama=disabled, kimi=disabled

# 4. Prompt evaluator emits clean structured JSON
curl -s http://localhost:8005/api/prompt-manager/evaluate/<call_id>
# Expected: clean {"clarity":85,"specificity":...} — no "Let me analyze..." prose

# 5. Run a single sprint and confirm every llm_call_details row has provider='minimax'
docker exec legion-db psql -U legion -d legion -c \
  "SELECT provider, count(*) FROM llm_call_details WHERE created_at > now() - interval '10 minutes' GROUP BY provider;"
# Expected: only minimax rows
```

---

## Phase 2 — Close the Self-Improvement Loop (4-6 hours)

Goal: when a sprint fails, Legion immediately diagnoses, proposes a targeted fix, and runs it — without waiting 4 hours for the daemon. This is what makes it "24/7 autonomous" instead of "24/7 broken loop."

### The 5 disconnects to fix

| # | Where | Current behavior | Fix |
|---|---|---|---|
| 1 | [agentic_loop_service.py:408-428](backend/app/services/agentic_loop_service.py#L408) | Auto-rollback on 3 failures, no diagnosis | Call `RootCauseAnalysisService.cluster_recent_failures(sprint_id)` immediately on sprint FAIL. If 2+ tasks have similar errors, create a targeted Fix-NN sprint with that root cause as the description. |
| 2 | [self_improvement_daemon.py:76 + root_cause_analysis.py:170-180](backend/app/services/root_cause_analysis.py#L170) | RCA circuit breaker blocks new Fix sprints when recent ones fail >50% | Raise threshold to 70%, require 5+ recent sprints (not 3). Allow exactly **1** in-flight Fix sprint to bypass the breaker — that's the recovery sprint, blocking it creates the death spiral. |
| 3 | [self_improvement_daemon.py:381-411](backend/app/services/self_improvement_daemon.py#L381) | `ENABLE_COUNCIL=false` default, council output not consumed | Set `ENABLE_COUNCIL=true` in [docker-compose.yml](docker-compose.yml). Verify [work_discovery_service.py](backend/app/services/work_discovery_service.py) `_discover_from_council_verdicts()` actually returns items. Apply council verdict title cleaning (regex extraction documented in MEMORY.md). |
| 4 | Learning aggregator | `episodic_retrievals=0` — episodes stored but never retrieved | In [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) `_execute_task()`: before LLM call, retrieve top-3 similar episodes via `EpisodicMemoryService.retrieve_similar(task.title, k=3)` and inject as system prompt context. CLAUDE.md notes this was wired for the graph path but not Auto-Sprints. |
| 5 | Sprint quality grading | Computed on-demand only | Call `SprintQualityGrader.grade(sprint_id)` immediately after `complete_sprint()` / `fail_sprint()`. If grade <50: enqueue an `Improve-NN` sprint targeting the lowest-scoring dimension. |

### Files to modify
- [backend/app/services/agentic_loop_service.py](backend/app/services/agentic_loop_service.py) — failure-triggered RCA call, sprint quality grade hook
- [backend/app/services/root_cause_analysis.py](backend/app/services/root_cause_analysis.py) — circuit breaker tuning + 1-bypass rule
- [backend/app/services/self_improvement_daemon.py](backend/app/services/self_improvement_daemon.py) — council always-on path
- [backend/app/services/autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) — episodic memory retrieve at task start
- [docker-compose.yml](docker-compose.yml) — `ENABLE_COUNCIL=true`, `ENABLE_KNOWLEDGE_SEEDING=true`
- [backend/app/services/work_discovery_service.py](backend/app/services/work_discovery_service.py) — verify council verdict source returns items, clean dict-repr titles

### Verification
```bash
# 1. Force a sprint failure, verify fix sprint auto-created within 60s
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, name, status, created_at FROM sprints WHERE name LIKE 'Fix-%' OR name LIKE 'Improve-%' ORDER BY id DESC LIMIT 5;"

# 2. Confirm episodic retrievals > 0 in Prometheus
curl -s http://localhost:9090/api/v1/query?query=legion_episodic_retrievals_total

# 3. Confirm council sessions producing verdicts
docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, council_type, created_at FROM council_sessions ORDER BY id DESC LIMIT 5;"
```

---

## Phase 3 — Frontend Cleanups (1-2 hours)

Goal: stop confusing the operator with stale tabs, broken scroll, and 502s on the dashboard.

| Issue | File | Fix |
|---|---|---|
| **Managed Projects tab on every project** (should be Legion only) | [frontend/src/pages/SprintCenter.tsx:871, 1329-1387](frontend/src/pages/SprintCenter.tsx#L871) | Wrap `TabsTrigger` and `TabsContent` in `{routeProjectId === 3 && (...)}` |
| **Agent Swarm tab on every project** (should be Legion only) | [frontend/src/pages/SprintCenter.tsx:872-875, 1390-1394](frontend/src/pages/SprintCenter.tsx#L872) | Same conditional pattern |
| **Sprint detail dialog has no scroll** | [frontend/src/components/sprint/SprintDetailDialog.tsx:65,81](frontend/src/components/sprint/SprintDetailDialog.tsx#L65) | Restructure DialogContent to use proper flex: header (fixed), `<ScrollArea className="flex-1">` wrapping a padded inner div, footer (fixed). Drop the `-mr-3 pr-3` negative-margin trick. |
| **Dependencies "Latest" always "-"** | [backend/app/services/dependency_review_service.py](backend/app/services/dependency_review_service.py), [frontend/src/components/project/DependenciesTab.tsx:53-57](frontend/src/components/project/DependenciesTab.tsx#L53) | npm/pip aren't in the backend container. Either (a) add `npm` + `pip` to [backend/Dockerfile](backend/Dockerfile), or (b) fetch latest versions via the registry HTTP APIs (`https://registry.npmjs.org/{pkg}/latest`, `https://pypi.org/pypi/{pkg}/json`) — preferred, no docker bloat. Render "Not scanned" italic when null. |
| **"1 active sprint" stale on every project** | DB cleanup | Phantom sprint from Fix-51's atomic-creation patch. One-time SQL: `DELETE FROM sprints WHERE status='ACTIVE' AND total_tasks > 0 AND completed_tasks=0 AND failed_tasks=0 AND created_at < now() - interval '24 hours';` |
| **Dashboard 502 on /dashboard-summary** | [backend/app/api/endpoints/dashboard.py:86+](backend/app/api/endpoints/dashboard.py#L86) | Wrap query block in `async with asyncio.timeout(15):`, convert TimeoutError → HTTPException(503). Identify slow query via Jaeger trace and add an index or batching. |

### Verification
```bash
# 1. Frontend type-check
cd frontend && npm run build

# 2. Dashboard responds < 5s
time curl -s http://localhost:8005/api/dashboard-summary | head -c 200

# 3. Open the GPU Manager project — confirm Managed Projects + Agent Swarm tabs absent
# 4. Open a failed sprint — confirm scrolling reaches the bottom Tasks list
```

---

## Phase 4 — Record History So We Stop Repeating This (30 min)

Append to [.claude/skills/legion-sprint-auditor/knowledge/recovery_history.md](.claude/skills/legion-sprint-auditor/knowledge/recovery_history.md):

- The supervisor `errors` array bug — full root cause, evidence, fix diff, lesson: **always trace the actual swarm routing table when sprints have 0% completion regardless of LLM health**
- The MiniMax M2 vs Kimi K2.5 decision matrix and prices snapshot for April 2026
- The "one-provider rule" — why we collapsed to MiniMax-only and what triggers Phase 5 (Ollama re-introduction)
- The 5 self-improvement loop disconnects (council disabled, RCA death spiral, no immediate failure analysis, learning unused, no auto-grade)
- Verification queries for each phase so any future session can re-confirm in <5 minutes

Also append a one-liner to [C:\Users\hadam\.claude\projects\c--code-Legion\memory\MEMORY.md](C:\Users\hadam\.claude\projects\c--code-Legion\memory\MEMORY.md) under a new "Fix-53 / Recovery" section pointing to the recovery_history.md file. Keep MEMORY.md under 200 lines.

---

## Phase 5 — FUTURE: Bring Ollama Back as a Local Execution Tier (DEFERRED)

**Do not run this phase until Phases 0-4 are verified working.** This phase exists in the plan only so we don't lose the design when we get there.

### Trigger conditions (all must hold)
- 7 consecutive days of >70% sprint completion on at least 3 projects with MiniMax-only
- Average MiniMax cost per sprint <$0.50 (proves Phase 0-2 are stable enough to measure)
- Episodic memory + RCA + council loop demonstrably reducing sprint failures week-over-week
- No new "execution silently zero" incidents in the last 7 days

### Scope (when triggered)
- Re-enable Ollama via `OLLAMA_DISABLED=false` and add `OLLAMA_NUM_GPU=999` to `.env` to *explicitly* request GPU offload (current default is silent VRAM thrash → CPU fallback on the RTX 5090)
- Add a per-task-type **routing policy** in `legion_config.py`: cheap deterministic tasks (CODE_GENERATION small files, TESTING, simple DEBUGGING) → Ollama qwen3-coder-next; complex reasoning (PLANNING, ARCHITECTURE, RCA, council) → MiniMax M2
- Reuse the GPU Manager project's recommendation engine (`backend/app/services/gpu_manager_service.py`) — it already has the rules to switch Ollama between GPU/CPU based on VRAM headroom
- Keep MiniMax as the **automatic fallback** when Ollama circuit is open OR queue depth >5 — never block on local
- Add a "shadow mode" first: route 10% of eligible tasks to Ollama for one week, compare grade outcomes against MiniMax baseline before flipping the routing percentage up

### Files this future phase will touch
- [backend/.env](backend/.env), [docker-compose.yml](docker-compose.yml) — flip `OLLAMA_DISABLED=false`, add `OLLAMA_NUM_GPU=999`, add `OLLAMA_TRAFFIC_PERCENT=10`
- [backend/app/core/legion_config.py](backend/app/core/legion_config.py) — restore per-task-type lists; first element MiniMax, second Ollama
- [backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py) — re-enable Ollama branch + traffic-percent gate
- [backend/app/services/gpu_manager_service.py](backend/app/services/gpu_manager_service.py) — wire its recommendations to actually flip `OLLAMA_NUM_GPU`

This is the phase that brings the cost savings and the "use my RTX 5090" goal — but only after we have a system stable enough to measure A/B outcomes against.

---

## Critical Files Reference

**Backend services that change**
- [backend/app/services/agent_swarm_service.py](backend/app/services/agent_swarm_service.py) — supervisor `errors` check, coder LLM-Error short-circuit
- [backend/app/services/sprint_tools.py](backend/app/services/sprint_tools.py) — raise `LLMExecutionError` instead of returning string sentinel (optional)
- [backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py) — MiniMax client wiring, Ollama/Kimi disable gates, MiniMax sliding-window rate limiter
- [backend/app/core/legion_config.py](backend/app/core/legion_config.py) — `ModelType.MINIMAX_M2`, MODEL_REGISTRY entry, all `TASK_MODEL_ROUTING` lists collapsed to MiniMax-only
- [backend/app/services/agentic_loop_service.py](backend/app/services/agentic_loop_service.py) — failure-triggered RCA + auto-grade
- [backend/app/services/root_cause_analysis.py](backend/app/services/root_cause_analysis.py) — circuit breaker tuning + 1-bypass rule
- [backend/app/services/self_improvement_daemon.py](backend/app/services/self_improvement_daemon.py) — council always-on path
- [backend/app/services/autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) — episodic retrieval injection
- [backend/app/services/prompt_evaluator_agent.py](backend/app/services/prompt_evaluator_agent.py) — structured output (THE leak fix)
- [backend/app/services/work_discovery_service.py](backend/app/services/work_discovery_service.py) — council verdict cleaning

**New files**
- [backend/app/llm/minimax_client.py](backend/app/llm/minimax_client.py) — mirror [kimi_client.py](backend/app/llm/kimi_client.py) line-for-line
- [.claude/skills/legion-sprint-auditor/knowledge/recovery_history.md](.claude/skills/legion-sprint-auditor/knowledge/recovery_history.md)

**Frontend**
- [frontend/src/pages/SprintCenter.tsx](frontend/src/pages/SprintCenter.tsx) — tab visibility (Managed Projects, Agent Swarm)
- [frontend/src/components/sprint/SprintDetailDialog.tsx](frontend/src/components/sprint/SprintDetailDialog.tsx) — scroll fix
- [frontend/src/components/project/DependenciesTab.tsx](frontend/src/components/project/DependenciesTab.tsx) — "Not scanned" label
- [backend/app/api/endpoints/dashboard.py](backend/app/api/endpoints/dashboard.py) — `asyncio.timeout()` wrapper

**Config**
- [backend/.env](backend/.env), [docker-compose.yml](docker-compose.yml) — `MINIMAX_API_KEY`, `OLLAMA_DISABLED=true`, `KIMI_DISABLED=true`, `MINIMAX_RPM=400`, `ENABLE_COUNCIL=true`, `ENABLE_KNOWLEDGE_SEEDING=true`

**Untouched (kept for Phase 5 reactivation)**
- [backend/app/llm/kimi_client.py](backend/app/llm/kimi_client.py) — code unchanged, gated off behind `KIMI_DISABLED`
- All Ollama client / semaphore / circuit-breaker code in `unified_llm_service.py` — gated off behind `OLLAMA_DISABLED`

**Patterns to reuse (do not reinvent)**
- [backend/app/llm/kimi_client.py](backend/app/llm/kimi_client.py) — exact pattern for new MiniMax client (`format=` kwarg, `json_schema` constraint, retry-on-429, `_source=` tracking)
- [backend/app/services/llm_review_service.py:153](backend/app/services/llm_review_service.py#L153) — exact pattern for `execute_structured()` with Pydantic response model
- Existing `RootCauseAnalysisService.cluster_recent_failures()` — already exists, just call it from agentic loop
- Existing `EpisodicMemoryService.retrieve_similar()` — already exists, just inject into Auto-Sprint path

---

## Sprint to track this

Create one sprint in Legion's DB (`project_id=3`) named **`Recovery-01: Make Legion actually work`** with one task per executable phase (Phases 0-4 only — Phase 5 is deferred and tracked as a separate future sprint):

```sql
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES ('Recovery-01: Make Legion actually work',
        'Fix THE root cause of sprint failures (swarm supervisor errors check), collapse to MiniMax-only, close self-improvement loop, frontend cleanups. Ollama/Kimi disabled; reactivation plan in Phase 5 (deferred). See plan: serene-coalescing-shannon.md',
        3, 'PLANNED', 1, 5, NOW(), NOW());
```

Then 5 tasks (Phase 0-4). Story points 3/5/8/3/2 = **21 total**.

A separate `Recovery-02: Bring Ollama back as local execution tier` sprint will be created later, once the Phase 5 trigger conditions are met.

---

## End-to-end success definition

After all phases ship, in this order, verify:

1. **Run a single sprint manually** → at least 5/7 tasks COMPLETED with `qa_status='approved'`
2. **Wait 1 hour** with `AGENTIC_MODE=true` → at least 1 new sprint created and completed end-to-end without manual intervention
3. **Force one task failure** → within 60s a `Fix-NN` sprint appears in DB targeting that error pattern
4. **Frontend** → GPU Manager project shows no Managed Projects tab, no Agent Swarm tab, sprint detail scrolls fully, dashboard loads in <5s
5. **Prompt evaluator** → `/api/prompt-manager/evaluate/{id}` returns clean JSON, no chain-of-thought prose
6. **Sprint quality grader** → at least one new sprint scores `Execution >= 80`, `Learning Capture > 0`

When all 6 pass: Legion is actually working. Then we let it run 24/7 and let the council + RCA + episodic loop start compounding.
