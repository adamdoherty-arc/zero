# Legion Deep Review & Improvement Plan

## Context

Legion is an AI Agent Orchestration System with massive ambition — 311 Python files, 133 services, 29 agents, 24 frontend pages, 64 test files. It manages itself and other projects through an autonomous loop of work discovery, sprint creation, task execution, and learning. After months of development, the system runs but doesn't reliably deliver. The core feedback loop is broken at multiple points, resulting in a 62% sprint failure rate and learning systems that accumulate data but produce no useful output.

This plan provides an honest 0-100 grade across 12 dimensions, identifies the root causes preventing Legion from being "world class," and defines a phased improvement roadmap.

---

## Current Grade: 48/100

### Dimension Scores

| # | Dimension | Score | Evidence |
|---|-----------|-------|----------|
| 1 | **Core Architecture** | 65 | Well-structured layers (API/Service/Model), SQLAlchemy 2.x async, FastAPI. BUT: 133 services (many dead/redundant), god files (executor 3,832 LOC, unified_llm 1,827 LOC), no dependency injection |
| 2 | **Agent System** | 55 | 29 agents registered, middleware pipeline (metrics/learning/workspace), keyword+task_type routing. BUT: council verdicts used as raw task titles ("Council: {'action': ...}"), routing can't match these, middleware never invoked |
| 3 | **Sprint Execution** | 30 | Sprint manager with pessimistic locking, error recovery service exists. BUT: 62% failure rate (18 FAILED / 11 COMPLETED), 78 SKIPPED tasks vs 44 COMPLETED, 18 stuck RUNNING tasks never cleaned up, auto-sprints failing in a loop |
| 4 | **LLM Integration** | 60 | Two-tier (Kimi plans, Ollama executes), semaphore queue, circuit breaker, structured output. BUT: 350 LLM calls in 24h all have NULL status — tracking broken |
| 5 | **Learning System** | 25 | 5,816 sprint_learnings accumulated, council service, episodic memory, routing optimizer. BUT: only 1 episode stored, only 16 cross-sprint insights, learning-to-action pipeline produces nothing useful |
| 6 | **Frontend UI** | 68 | 24 pages, React+TypeScript, hooks pattern, WebSocket events, consistent styling. BUT: architecture summary completely wrong ("vector embeddings service"), sprint API returns 9 instead of 33, FAILED sprints hidden |
| 7 | **Testing** | 50 | 64 test files, ~1,400 tests. BUT: top services untested (unified_llm 1,827 LOC, agentic_loop 1,703 LOC, plan_service 1,495 LOC), some tests hang |
| 8 | **DevOps/Infra** | 72 | Docker Compose with 7+ services, health checks, Prometheus+Grafana+Jaeger, 32 supervised background tasks, resource limits. Solid operational foundation |
| 9 | **Documentation** | 35 | CLAUDE.md is 500+ lines but partly outdated, architecture summary on project page is completely wrong, no user-facing docs, no API docs beyond code |
| 10 | **API Quality** | 50 | 63 endpoint files, Pydantic models on core routes. BUT: sprint endpoint filters out FAILED, some return dicts not models, total_sprints count mismatches DB |
| 11 | **Error Handling** | 40 | ErrorRecoveryService centralized in 4 paths, circuit breaker. BUT: no `last_error` column on sprints, stuck tasks not cleaned, silent failures throughout |
| 12 | **Self-Improvement Loop** | 30 | Plans with grading, health gate, council verdicts, work discovery. BUT: grades bounce wildly (22-60), auto-sprints create garbage tasks from council verdicts, improvement cycle doesn't converge |

### Critical Root Causes (Why It's at 48, Not 90)

1. **Council verdicts become garbage task titles**: Work discovery takes raw council output (`"Council: {'action': '...'}"`) and uses it as task titles. Keyword routing can't match these, so `route_task()` returns `"main_agent"` and the middleware pipeline is never invoked. This is the single biggest quality issue.

2. **No sprint error tracking**: The `sprints` table has no `last_error` column. When sprints fail, there's no way to know WHY. The system can't learn from failures it can't record.

3. **Auto-skip is too aggressive**: 78 SKIPPED vs 44 COMPLETED. Tasks are being skipped faster than completed, which means the system is giving up rather than trying.

4. **Stuck RUNNING tasks**: 18 tasks stuck in RUNNING state, never cleaned up. The executor race condition fix (count RUNNING before concluding "no pending") may not be fully working.

5. **LLM status tracking broken**: 350 calls but 0 success/0 error. The `status` column on `llm_call_details` isn't being written. This means the entire LLM quality/review pipeline has no signal.

6. **Episodic memory nearly empty**: Only 1 episode stored despite 5,816 learnings. The `store_episode()` quality gate (>=0.7) is filtering everything out, or the call path is broken.

7. **Grade instability**: Project review grade bounced from 22 to 60 over 10 days. The LLM grader produces inconsistent assessments, and adaptive clamping can't compensate.

---

## Improvement Plan: 48 → 90

### Sprint 1: "Foundation-02: Fix the Core Loop" (Estimated: 8 tasks)

**Goal**: Make sprint execution actually work — reduce failure rate from 62% to <20%.

**Files to modify**:
- `backend/app/services/work_discovery_service.py` — Clean council verdict output before creating tasks
- `backend/app/services/autonomous_sprint_executor.py` — Fix stuck RUNNING task cleanup, reduce SKIPPED aggressiveness
- `backend/app/services/sprint_manager.py` — Add `last_error` tracking (or use description field)
- `backend/app/services/unified_llm_service.py` — Fix LLM call status tracking (success/error writes)
- `backend/app/services/episodic_memory_service.py` — Lower quality gate or fix store_episode call path

**Tasks**:
1. **Fix task title quality**: In work_discovery_service.py, when source is "council_verdict", extract the action text and create a clean, actionable task title. Strip JSON formatting, limit to 100 chars.
2. **Fix LLM call status tracking**: In unified_llm_service.py, verify that `status` field is being written to llm_call_details on every call (success AND error paths).
3. **Fix stuck RUNNING tasks**: In autonomous_sprint_executor.py, add a cleanup sweep at sprint start — any tasks RUNNING for >30 min should be reset to PENDING or FAILED.
4. **Reduce auto-skip aggressiveness**: In autonomous_sprint_executor.py, tighten `_should_auto_skip_task()` criteria — only skip if task has failed 3+ times, not on first attempt.
5. **Add sprint error tracking**: Either add `last_error` column via migration, or use the existing `description` field to append error details on failure.
6. **Fix episodic memory ingestion**: Check and fix the store_episode call in autonomous_sprint_executor.py — lower quality threshold from 0.7 to 0.5, ensure it's called on ALL successful task completions.
7. **Fix sprint API filtering**: The `/api/sprints` endpoint is returning only 9 sprints instead of 33 for project_id=3. Fix the query to include all statuses.
8. **Clean up existing stuck data**: One-time DB cleanup of the 18 stuck RUNNING tasks.

### Sprint 2: "Doc-01: Fix Project Documentation" (Estimated: 5 tasks)

**Goal**: Make the Legion project page accurate and useful.

**Files to modify**:
- `backend/app/services/continuous_scanning_service.py` — Fix architecture scanning prompt
- API call to update project description/architecture_summary
- `frontend/src/pages/ProjectDetail.tsx` — Verify overview tab display

**Tasks**:
1. **Fix architecture summary**: Update the project's `architecture_summary` in the DB to accurately describe Legion as "AI Agent Orchestration System" not "vector embeddings service".
2. **Fix project description**: Update from "Auto-discovered: Legion" to proper description.
3. **Update tech_stack**: Currently shows empty frameworks/databases — should list FastAPI, SQLAlchemy, PostgreSQL, React, LangGraph.
4. **Review scanning prompt**: Fix the continuous_scanning_service so future scans produce accurate summaries.
5. **Update CLAUDE.md**: Remove outdated sprint history (move to separate file), update current state.

### Sprint 3: "Quality-09: Stabilize Grading" (Estimated: 5 tasks)

**Goal**: Make grades meaningful and convergent — no more 22-60 bouncing.

**Files to modify**:
- `backend/app/services/project_grader_service.py` — Improve grading prompt consistency
- `backend/app/services/plan_service.py` — Grade context quality

**Tasks**:
1. **Structured grading rubric**: Replace free-form LLM grading with a structured rubric (12 dimensions, 1-10 each, weighted average). The LLM scores each dimension individually.
2. **Grade context anchoring**: Include previous 3 grades + their breakdowns in the grading context, so the LLM can justify changes.
3. **Tighter clamping for mature plans**: Plans with 10+ grades should have max ±10 delta (not ±15).
4. **Grade validation**: If the LLM grade differs from previous by >20, automatically re-grade once before accepting.
5. **Dimension-level tracking**: Store per-dimension scores in `grade_breakdown` JSON, display in UI.

### Sprint 4: "Clean-06: Service Consolidation" (Estimated: 6 tasks)

**Goal**: Reduce from 133 services to ~80 by removing dead/redundant code.

**Tasks**:
1. Audit all 133 services — identify which are imported/used vs dead code
2. Remove clearly unused services (expect 20-30 to be dead)
3. Merge redundant services (e.g., multiple QA services, multiple sprint-related services)
4. Extract autonomous_sprint_executor.py (3,832 LOC) into 3-4 focused modules
5. Update imports across codebase
6. Run full test suite to verify no regressions

### Sprint 5: "Test-13: Critical Path Coverage" (Estimated: 6 tasks)

**Goal**: Get test coverage on the most critical untested services.

**Tasks**:
1. Write tests for unified_llm_service.py (1,827 LOC) — mock Ollama/Kimi, test semaphore, circuit breaker
2. Write tests for agentic_loop_service.py (1,703 LOC) — test cycle logic, conflict detection
3. Write tests for plan_service.py (1,495 LOC) — test grading, scheduling, execution
4. Write tests for work_discovery_service.py (1,268 LOC) — test all 9 sources
5. Fix hanging tests (test_runner_service, test_plans_integration)
6. Target: 70% coverage on critical paths

### Sprint 6: "Learn-12: Make Learning Produce Value" (Estimated: 5 tasks)

**Goal**: Close the learning feedback loop — insights should improve future sprints.

**Tasks**:
1. Fix cross-sprint insight generation — 16 insights from 5,816 learnings is broken
2. Fix episodic memory — 1 episode is broken
3. Wire learnings into sprint planning prompt — include top 5 relevant learnings as context
4. Add learning quality metrics to daily standup
5. Measure: after fix, each sprint should produce 2-3 episodes and 1 insight

---

## Execution Order

```
Sprint 1 (Foundation-02) ← DO FIRST — nothing else matters if core loop is broken
Sprint 2 (Doc-01)        ← Quick win, makes the UI accurate
Sprint 3 (Quality-09)    ← Stabilizes the feedback signal
Sprint 4 (Clean-06)      ← Reduces complexity for all future work
Sprint 5 (Test-13)       ← Safety net before further changes
Sprint 6 (Learn-12)      ← Closes the learning loop
```

## Expected Grade After Each Sprint

| After Sprint | Expected Grade | Key Improvement |
|---|---|---|
| 1 (Foundation-02) | 58 | Sprint failure <20%, LLM tracking works, tasks are actionable |
| 2 (Doc-01) | 62 | Accurate project description, proper architecture summary |
| 3 (Quality-09) | 68 | Stable grades, meaningful rubric, convergent scoring |
| 4 (Clean-06) | 74 | Cleaner codebase, manageable file sizes, no dead code |
| 5 (Test-13) | 80 | Critical paths tested, regressions caught automatically |
| 6 (Learn-12) | 85 | Learning loop produces actionable insights |

## Getting to 90+

After these 6 sprints, the remaining gap to 90+ requires:
- **E2E integration testing** with real LLM calls (not mocked)
- **PR pipeline working end-to-end** (branch → PR → review → merge)
- **Multi-project learning** working (learnings from FortressOS improving Legion)
- **UI polish** — real-time grade progression chart, sprint failure analysis view
- **Operational maturity** — 7-day uptime with <10% failure rate

## Verification

After each sprint, verify:
```bash
# 1. Backend healthy
curl -s http://localhost:8005/health | python -m json.tool

# 2. Sprint failure rate
docker exec legion-db psql -U legion -d legion -c "SELECT status, count(*) FROM sprints WHERE project_id=3 AND created_at > NOW() - INTERVAL '7 days' GROUP BY status;"

# 3. LLM tracking
docker exec legion-db psql -U legion -d legion -c "SELECT status, count(*) FROM llm_call_details WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY status;"

# 4. Learning output
docker exec legion-db psql -U legion -d legion -c "SELECT count(*) FROM episodes WHERE project_id=3;"
docker exec legion-db psql -U legion -d legion -c "SELECT count(*) FROM cross_sprint_insights WHERE project_id=3;"

# 5. Tests pass
cd backend && python -m pytest tests/ -x -q

# 6. Frontend builds
cd frontend && npm run build
```
