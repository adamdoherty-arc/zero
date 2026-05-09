# Legion: Phase 2 — Make Auto-Sprints Actually Complete Work

## Context

Legion has two review skills already built:
- **`/legion-watchdog`** — 24 runs, production-ready. API health monitoring, 12 dimensions, auto-fixes, persistent knowledge (34 issues tracked, 47 fix recipes). Run with `--check`, `--fix`, `--audit`, `--improve`, `--ml`.
- **`/legion-deep-review`** — 0 runs, source code quality auditor, 8-phase pipeline, 10-dimension grading. Run with `--quick`, `--test`, `--api`, `--grade`, `--improve`.

Phase 1 (previous session) completed 6 sprints:
- Clean-07: 3,420 lines dead code removed
- Fix-46: All tasks now route through middleware pipeline (was bypassing for main_agent)
- Doc-01: CLAUDE.md updated with honest 38/100 grade
- Clean-08: 14 more dead files deleted (4,152 lines)
- Test-13: 108 unified_llm_service tests + 23 agentic loop tests (1840 total passing)
- Learn-12: Learned routing wired into autonomous executor

**But Auto-Sprints still won't complete tasks through agents.** The agent pipeline is wired but 4 interconnected bugs form a chain that prevents any agent output from being accepted. This plan fixes that chain.

---

## The Chain of Failure (Root Cause)

```
Task created (task_type=NULL)     ← Bug 1: never populated at creation time
        ↓
Executor defaults to "code_generation"  ← Bug 2: wrong classification
        ↓
Routes to main_agent (keyword mismatch)  ← Bug 3: routing blind without task_type
        ↓
MainAgent returns "I'll create the code..."  ← By design (intent analysis only)
        ↓
Output extraction finds no .content/.output  ← Bug 4: wrong field names checked
        ↓
Falls through to str(result)
        ↓
Substance check rejects "I'll " prefix  ← Bug 5: too strict
        ↓
Task marked as agent-failed → falls to direct LLM
```

**Evidence** (verified via code reads):
- `daily_sprint_generator_service.py:154` — SprintTaskDB created without `task_type=`
- `autonomous_sprint_executor.py:2049` — `getattr(task, "task_type", None) or "code_generation"`
- `agent_execution_service.py:214-225` — checks `.content`/`.output`/`.result` but agents use `immediate_response`, `bug_description`, etc.
- `main_agent.py:413-428` — `_generate_response()` returns hardcoded "I'll create the code..." strings
- `autonomous_sprint_executor.py:2086-2090` — rejects output starting with "I'll "
- `classify_task_type_from_text()` exists in `model_selection_service.py:40` — already used at runtime but never at creation

---

## Updated Grade: 48/100 (up from 38)

| Dimension | Score | Change | Notes |
|-----------|-------|--------|-------|
| Core Loop | 20/100 | +15 | Pipeline wired (Fix-46) but agent output discarded |
| Service Architecture | 50/100 | +15 | 115 services (was 130), 53 routers |
| Learning System | 30/100 | +10 | Learned routing wired, episodic threshold lowered |
| Data Quality | 30/100 | +3 | Fewer orphaned tasks, still counter issues |
| Test Coverage | 55/100 | +10 | 1840 passing (was 1604) |
| Documentation | 55/100 | +15 | CLAUDE.md accurate, honest grade |
| Frontend UI | 65/100 | = | No frontend changes |
| Grading System | 50/100 | = | Working, needs integration |
| Agent System | 35/100 | +5 | All route through middleware now |
| Middleware Pipeline | 15/100 | +5 | Wired but still 0 successful invocations |

---

## Sprint Sequence (4 sprints)

### Sprint 1: Fix-47 — Task Type Classification at Creation Time

**Why**: Without correct `task_type`, routing is blind and all learning data is poisoned with wrong labels. `classify_task_type_from_text()` already exists but is only called at runtime, never at creation.

**Tasks**:
1. In `daily_sprint_generator_service.py:154`, add `task_type=` to SprintTaskDB constructor using `classify_task_type_from_text(f"{title} {description}")`
2. In the LLM prompt inside `_decompose_with_llm()`, add `"task_type"` to the required JSON fields (valid values: code_generation, debugging, testing, refactoring, documentation, architecture, planning, research)
3. In `agentic_loop_service.py` `_plan_sprint()` (~line 1127), classify task_type on both brain-planned and fallback paths
4. In `sprint_manager.py` `add_task()` (~line 616), if `task_data.task_type` is None, classify from title+description as fallback

**Files**:
- [daily_sprint_generator_service.py:154](backend/app/services/daily_sprint_generator_service.py#L154)
- [agentic_loop_service.py:1127](backend/app/services/agentic_loop_service.py#L1127)
- [sprint_manager.py:616](backend/app/services/sprint_manager.py#L616)
- [model_selection_service.py:40](backend/app/services/model_selection_service.py#L40) (reuse existing)

**Exit criteria**: New SprintTaskDB rows have non-null task_type. Tests verify classification.

---

### Sprint 2: Fix-48 — Agent Output Extraction & Substance Check

**Why**: Agents return typed Pydantic objects (BugAnalysisOutput, CodeReviewerOutput, etc.) but `execute_via_agent` checks for `.content`/`.output`/`.result` — none of which exist on these types. Output falls to `str(result)` which is the Pydantic repr, then rejected by the substance check.

**Tasks**:
1. Add `get_content_summary()` method to `AgentOutput` base class ([base_agent.py:103](backend/app/agents/base_agent.py#L103)) — default: join all non-empty string fields excluding metadata (`agent_name`, `status`, `timestamp`). Each subclass can override.
2. Fix output extraction in [agent_execution_service.py:214-225](backend/app/services/agent_execution_service.py#L214) — try `result.get_content_summary()` first, then fall back to `str(result)`
3. Fix substance check in [autonomous_sprint_executor.py:2086-2090](backend/app/services/autonomous_sprint_executor.py#L2086) — lower threshold from 200→50 chars, replace `startswith("I'll ")` with `_is_intent_only()` helper that checks for action-plan-only responses
4. Fix MainAgentOperator ([main_agent.py:413](backend/app/agents/main_agent.py#L413)) — when `context.task_id` is set (autonomous execution), call `self.llm_service.execute()` with the query and return actual LLM output, not just an intent string

**Files**:
- [base_agent.py:103](backend/app/agents/base_agent.py#L103) — AgentOutput class
- [agent_execution_service.py:214](backend/app/services/agent_execution_service.py#L214) — output extraction
- [autonomous_sprint_executor.py:2086](backend/app/services/autonomous_sprint_executor.py#L2086) — substance check
- [main_agent.py:413](backend/app/agents/main_agent.py#L413) — MainAgentOperator

**Exit criteria**: Agent output is accepted (not discarded). Prometheus `legion_agent_execution_total{result="success"}` > 0.

---

### Sprint 3: Fix-49 — Council Verdict & Work Discovery Hygiene

**Why**: Council verdicts used as raw task titles (`"Council: {'action': '...'"`) can't match routing keywords, always fall to main_agent. Work items lack task_type from discovery.

**Tasks**:
1. In [work_discovery_service.py](backend/app/services/work_discovery_service.py) council verdict handler (~line 1131), ensure `clean_title` never contains raw dict repr — if title starts with `"Council:"` or contains `{`, re-extract action text from dict values
2. In `agentic_loop_service.py` `_plan_sprint()`, enrich prompts for council-sourced items with the action text, score, and priority context (not raw verdict string)
3. Add `task_type` field to work item dicts in each `_discover_from_*` method using `classify_task_type_from_text()` — feeds into Sprint 1's propagation

**Files**:
- [work_discovery_service.py:1131](backend/app/services/work_discovery_service.py#L1131)
- [agentic_loop_service.py:1112](backend/app/services/agentic_loop_service.py#L1112)

**Exit criteria**: No task titles contain `{'action':` patterns. Council tasks route to specialist agents.

---

### Sprint 4: Test-14 — Pipeline Integration Tests

**Why**: Each fix needs regression tests to prevent re-breaking. The agent output extraction path has zero tests.

**Tasks**:
1. **New `test_agent_output.py`** — test `get_content_summary()` for each AgentOutput subclass, test `execute_via_agent` output extraction, test substance check accepts valid agent output
2. **New `test_task_type_classification.py`** — test SprintManager.add_task populates task_type, test daily_sprint_generator creates tasks with task_type, test classify_task_type_from_text with sample inputs
3. **Add to `test_work_discovery.py`** — test council verdict title cleaning, test work items include task_type
4. **Add to `test_sprint_generator.py`** — test task_type is in LLM prompt schema

**Files**:
- `backend/tests/services/test_agent_output.py` (new, ~20 tests)
- `backend/tests/services/test_task_type_classification.py` (new, ~15 tests)
- `backend/tests/services/test_work_discovery.py` (existing, add ~10 tests)
- `backend/tests/services/test_sprint_generator.py` (existing, add ~5 tests)

**Exit criteria**: 50+ new tests passing. Total 1890+. No regressions.

---

## Execution Order

```
Fix-47 (task_type) ──────────┐
                              ├──→ Test-14 (integration tests)
Fix-48 (output extraction) ──┤
                              │
Fix-49 (council hygiene) ─────┘
```

Fix-47 and Fix-48 are independent (can be done in any order). Fix-49 builds on Fix-47. Test-14 comes last.

---

## After These Sprints

Run both skills to measure progress:
1. `/legion-watchdog --audit` — operational health check
2. `/legion-deep-review --grade` — feature completeness score
3. **Target**: Grade 60+ (from 48), Auto-Sprint task completion > 30%
4. Track all results in Legion UI (project_id=3)

---

## Verification Per Sprint

1. Run tests: `cd backend && python -m pytest tests/ -v -k "not Semaphore"`
2. Docker rebuild: `docker-compose build legion-backend && docker-compose up -d`
3. Health check: `curl http://localhost:8005/health`
4. Check Prometheus metrics for agent execution success
5. Commit with sprint name in message
