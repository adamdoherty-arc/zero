# Plan: Legion Watchdog Health Score 65 → 100

## Context
Watchdog run #21 scored **65/100**. The user wants a comprehensive plan to reach 100/100 across all 12 health dimensions. Root cause analysis (via 3 Explore agents + 1 Plan agent) identified 7 targeted sprints with 29 tasks total.

## Current Scores & Targets

| # | Dimension | Current | Target | Sprint |
|---|-----------|---------|--------|--------|
| D1 | Learning Pipeline | 95 | 100 | Fix-43 |
| D2 | Model Tracking | 90 | 100 | Fix-43 |
| D3 | LLM Review | 55 | 100 | Fix-44 |
| D4 | Agentic Loop | 80 | 100 | Quality-09 |
| D5 | Sprint Execution | 20 | 100 | Fix-43 + Quality-09 |
| D6 | Infrastructure | 85 | 100 | Infra-03 |
| D7 | Dependency Security | 85 | 100 | Infra-03 |
| D8 | ML Learning System | 53 | 100 | Learn-12 + Quality-09 |
| D9 | Data Quality | 15 | 100 | Fix-44 + Quality-09 |
| D10 | Frontend Health | 90 | 100 | FE-06 |
| D11 | Agentic Architecture | 49 | 100 | Arch-11 |
| D12 | Plan Execution | 63 | 100 | Quality-09 |

## Sprint Dependency Graph

```
Fix-43 ──┐
Fix-44 ──┤
         ├── Learn-12 ──┐
         │              ├── Quality-09 (final)
Arch-11 ─┤              │
Infra-03 ┤              │
FE-06 ───┘──────────────┘
```

---

## Sprint 1: Fix-43 — Sprint Execution Pipeline Hardening (5 tasks)
**Dims**: D1 95→100, D2 90→100, D5 20→70 | **Priority**: CRITICAL

1. **Fix fallback prompt quality** — `backend/app/services/daily_sprint_generator_service.py`
   - `_fallback_decompose()` generates vague prompts ("Use find and grep...") that fail `_is_prompt_actionable()` — death spiral
   - Rewrite to produce domain-specific prompts using plan.name + plan.description with concrete file paths/functions

2. **Add stuck-task timeout** — `backend/app/services/autonomous_sprint_executor.py`
   - RUNNING tasks >15 min never cleaned up → sprint stays ACTIVE forever
   - In `_execute_all_tasks()`: if task RUNNING >15 min (compare updated_at), mark FAILED with timeout error

3. **Tighten Auto-Sprint circuit breaker** — `backend/app/services/sprint_manager.py`
   - `check_category_failure_rate()` uses 80% threshold — never trips for Auto-Sprint (54% failure)
   - Lower to 60% for Auto-Sprint category, keep 80% for manual

4. **Centralize task status counter updates** — `backend/app/services/sprint_manager.py`
   - Counter mismatches (30/run) from inline `task.status = X` without calling `_recalculate_sprint_counters()`
   - Add `update_task_status()` method; update all callers (executor, swarm, graph, claude_executor)

5. **Wire record_task_outcome into ALL paths** — executor + graph
   - Learning pipeline loses data — `record_task_outcome()` only called in 2 of 4 completion paths

## Sprint 2: Fix-44 — LLM Review Calibration + Data Quality (4 tasks)
**Dims**: D3 55→100, D9 15→70

1. **Calibrate FLAG_THRESHOLD** — `backend/app/services/llm_review_service.py`
   - `FLAG_THRESHOLD = 40` too strict (avg_score=40 → 67% flagged). Lower to 25, add severity tiers (CRITICAL <20, WARNING 20-35, OK >35)

2. **Suppress false positive flags** — same file
   - "incomplete" (4344) + "wrong_format" (2848) are mostly false positives from short legitimate responses
   - Don't flag responses <200 chars as "incomplete" if prompt was also short

3. **Add counter reconciliation to lifecycle transitions** — `backend/app/services/sprint_lifecycle_graph.py`
   - Call `_recalculate_sprint_counters()` BEFORE sprint status transitions (ACTIVE→COMPLETED/FAILED)

4. **Add orphan sweep on agentic loop start** — `backend/app/services/agentic_loop_service.py`
   - Orphaned tasks (PENDING/RUNNING in terminated sprints) accumulate 129/run
   - Sweep at cycle start: mark CANCELLED with explanation

## Sprint 3: Learn-12 — ML Learning System Full Wiring (5 tasks)
**Dims**: D8 53→90

1. **Wire knowledge_ingestion into execution graph** — `backend/app/services/sprint_execution_graph.py`
   - `format_domain_context()` implemented (33 entries) but never called. Add after episodic memory in `plan_task()`

2. **Wire episodic memory retrieval feedback** — same file
   - `record_retrieval_helped()` never called after task completion. Call in `verify_task()` with task success/fail

3. **Add decision trace persistence** — `backend/app/services/explainability_service.py`
   - Routing decisions in-memory only, lost on restart. New migration: `decision_traces` table. Wire `record_decision()` to DB

4. **Expand agent routing rules** — `backend/app/services/agent_execution_service.py`
   - Only 1/29 agents active (code_reviewer). Expand `_KEYWORD_AGENT_ROUTING` from 9→18 rules for security, testing, devops, docs, arch

5. **Route through middleware pipeline** — `backend/app/services/agent_swarm_service.py`, `claude_executor.py`
   - Middleware shows 0 invocations. Route matching tasks through `execute_via_agent()` instead of raw LLM

## Sprint 4: Arch-11 — Agentic Architecture Maturity (5 tasks)
**Dims**: D11 49→85

1. **Enable ReAct tool-use** — `backend/app/agents/base_agent.py` + specialists
   - `call_llm_with_tools()` implemented but unused. Override in top 5 agents to use tools. Feature flag `AGENT_TOOL_USE=true`

2. **Add agent reflection** — `backend/app/agents/base_agent.py`
   - Add `_reflect()` method: after execute(), ask LLM for self-assessment when quality <0.7

3. **Wire inter-agent delegation** — same file
   - `delegate_to()` exists but never called. Wire: code_reviewer→security for security issues, architecture→testing for test gaps

4. **Add agent critique capability** — same file
   - Add `critique()` method for cross-agent review. Wire into QA gate

5. **Add approval workflow for high-risk actions** — `backend/app/services/agent_execution_service.py`
   - Approval system exists but 0 requests. For CODE_GENERATION/ARCHITECTURE with confidence <0.5, require approval

## Sprint 5: Infra-03 — Infrastructure + Dependency Completeness (3 tasks)
**Dims**: D6 85→100, D7 85→100

1. **Route execution through middleware** — `claude_executor.py`, `agent_swarm_service.py`
   - Check for matching agent via `get_agent_for_task()`, route through `execute_via_agent()` when found

2. **Skip dep scan for virtual projects** — dependency scanner
   - Virtual projects (path `/virtual/`) fail scans. Skip with "not applicable" result

3. **Add middleware health endpoint** — `backend/app/api/endpoints/service_health.py`
   - `/api/health/middleware`: pipeline_loaded, count, total_invocations, per-middleware stats

## Sprint 6: FE-06 — Frontend Health Measurement (2 tasks)
**Dims**: D10 90→100

1. **Add frontend smoke test endpoint** — `backend/app/api/endpoints/service_health.py`
   - `/api/health/frontend`: container healthy + curl returns 200 + expected HTML markers

2. **Add frontend test count to health metrics** — same file
   - Expose test_count/pass_count/fail_count in daily-standup data

## Sprint 7: Quality-09 — Plan Execution + Final Sweep (5 tasks)
**Dims**: D4 80→100, D5 70→100, D8 90→100, D9 70→100, D12 63→100
**Depends on**: All previous sprints

1. **Fix docker_logs grade parse** — `backend/app/services/project_grader_service.py`
   - 40% parse failure. Add 5th strategy: regex for `"score": \d+`. Add retry with simpler prompt

2. **Wire grades into sprint generation** — `backend/app/services/plan_service.py`
   - Low grades (<50) don't trigger sprints. After grading, call `generate_sprint()` if grade <50 and no active sprint

3. **Add plan freshness tracking** — same file
   - Ensure all active plans graded every 48h. Add `last_graded_at` convenience query

4. **Reduce agentic loop idle gaps** — `backend/app/services/agentic_loop_service.py`
   - Max sleep 120s→60s when active sprints exist. Add maintenance cycle for stuck tasks + counter reconciliation

5. **Update watchdog scoring** — `.claude/skills/legion-watchdog/`
   - Review all 12 scoring functions for accuracy. Fix measurement bugs where watchdog itself blocks reaching 100

## Verification
After each sprint:
1. Docker rebuild + restart: `docker-compose build legion-backend && docker-compose up -d`
2. Health check: `curl http://localhost:8005/health`
3. Run watchdog: `/legion-watchdog` to verify score improvement
4. Backend tests: `cd backend && python -m pytest tests/ -v`

Final target: Watchdog run #22+ scores 100/100 across all 12 dimensions.
