# Legion Platform Audit — 2026-04-04 (First Run)

## Platform Grade: 62/100 (D+)

This is the first comprehensive platform audit across all 28 features. Scores establish a baseline.

**Backend Note**: Backend was under agentic loop load during audit — API calls timed out. Scoring based on code analysis + DB schema checks. D2 scores may improve when verified with live API data.

**Critical Bug Found**: `routing_optimizer.py:215` references `TaskOutcomeDB.duration_seconds` which doesn't exist — learned routing is 100% broken, falling back to keyword routing on every task.

---

## Feature Scorecard (worst-first)

| Rank | Feature | Route | Score | Grade | D1 | D2 | D3 | D4 | D5 | D6 | Importance |
|------|---------|-------|-------|-------|----|----|----|----|----|----|------------|
| 1 | Dependencies | /projects/:id/deps | 44.5 | F | 50 | 50 | 45 | 40 | 55 | 15 | 0.7x |
| 2 | Builder Mode | backend-only | 46.0 | F | 60 | 60 | 30 | 40 | 55 | 15 | 0.7x |
| 3 | External Knowledge | backend-only | 47.3 | F | 55 | 45 | 30 | 40 | 50 | 75 | 0.7x |
| 4 | Settings | /settings | 47.5 | F | 60 | 50 | 35 | 50 | 65 | 15 | 0.7x |
| 5 | Alerts | /alerts | 48.5 | F | 65 | 50 | 40 | 45 | 55 | 20 | 1.0x |
| 6 | LLM Review | backend-only | 51.0 | F | 65 | 60 | 35 | 45 | 55 | 35 | 0.7x |
| 7 | Incidents | backend-only | 52.5 | F | 65 | 60 | 35 | 45 | 50 | 55 | 0.7x |
| 8 | Git Updates | /git | 53.3 | F | 65 | 55 | 40 | 60 | 45 | 45 | 1.0x |
| 9 | Releases | backend-only | 53.5 | F | 65 | 65 | 35 | 45 | 50 | 55 | 0.7x |
| 10 | Product Docs | /product-docs | 54.8 | F | 70 | 60 | 40 | 65 | 55 | 20 | 1.0x |
| 11 | Analytics | /analytics | 55.5 | F | 70 | 55 | 40 | 60 | 55 | 45 | 1.0x |
| 12 | Approvals | /approvals | 58.0 | F | 70 | 55 | 40 | 60 | 55 | 70 | 1.0x |
| 13 | Ideas | /projects/:id/ideas | 60.0 | D | 75 | 65 | 55 | 65 | 55 | 20 | 1.0x |
| 14 | Ask Legion | /ask-legion | 60.3 | D | 78 | 70 | 45 | 65 | 60 | 20 | 1.0x |
| 15 | Agent Dashboard | /agent-dashboard | 61.0 | D | 70 | 60 | 45 | 70 | 60 | 60 | 1.2x |
| 16 | Test Results | /test-results | 62.0 | D | 75 | 60 | 45 | 65 | 55 | 70 | 1.0x |
| 17 | Pull Requests | /pull-requests | 62.3 | D | 70 | 55 | 45 | 75 | 55 | 80 | 1.0x |
| 18 | Execution Monitor | /execution | 65.0 | D | 70 | 65 | 60 | 70 | 55 | 65 | 1.0x |
| 19 | Ollama Manager | /ollama-manager | 65.3 | D | 75 | 70 | 45 | 70 | 50 | 80 | 1.2x |
| 20 | LLM Console | /llm-console | 65.8 | D | 80 | 80 | 50 | 55 | 65 | 50 | 1.2x |
| 21 | Learning Dashboard | /learning | 65.8 | D | 75 | 55 | 50 | 80 | 60 | 80 | 1.2x |
| 22 | Project Detail | /projects/:id | 65.8 | D | 70 | 70 | 75 | 55 | 70 | 40 | 1.0x |
| 23 | Autonomous Control | /autonomous | 66.8 | D | 75 | 70 | 50 | 80 | 55 | 65 | 1.5x |
| 24 | Service Health | /service-health | 68.0 | D+ | 80 | 75 | 55 | 70 | 60 | 55 | 1.2x |
| 25 | Sprint Center | /projects/:id/sprints | 70.0 | C- | 80 | 70 | 70 | 70 | 50 | 65 | 1.5x |
| 26 | Projects List | /projects | 76.3 | C+ | 85 | 80 | 80 | 70 | 60 | 65 | 1.2x |
| 27 | Project Plans | /projects/:id/plans | 76.5 | C+ | 85 | 75 | 65 | 85 | 55 | 90 | 1.0x |
| 28 | Dashboard | / | 77.3 | C+ | 85 | 75 | 90 | 60 | 65 | 75 | 1.5x |

**Legend**: D1=Functional, D2=Data Quality, D3=Integration, D4=UX/Perf, D5=Code Quality, D6=Tests

### Grade Distribution
- **A (90+)**: 0 features
- **B (80-89)**: 0 features
- **C (70-79)**: 3 features (Dashboard, Projects List, Project Plans)
- **D (60-69)**: 13 features
- **F (0-59)**: 12 features

---

## Top 10 Highest-Impact Improvements

Ranked by `(100 - score) * importance_weight`:

| # | Feature | Current | Action | Impact | Effort |
|---|---------|---------|--------|--------|--------|
| 1 | **Autonomous Control** | 66.8 | Fix routing_optimizer `duration_seconds` missing column + add error handling | +10pts | S |
| 2 | **Sprint Center** | 70.0 | Reduce sprint_manager print statements (24), add error boundaries to page | +8pts | S |
| 3 | **Dashboard** | 77.3 | Add loading skeletons (only 1 detected), error boundaries | +5pts | S |
| 4 | **Agent Dashboard** | 61.0 | Add WebSocket for real-time agent status, error handling in page | +10pts | M |
| 5 | **Learning Dashboard** | 65.8 | Fix episodic memory retrieval (0 retrievals), wire council data into UI | +10pts | M |
| 6 | **LLM Console** | 65.8 | Add error handling, improve loading states (only 2) | +8pts | S |
| 7 | **Service Health** | 68.0 | Add more test coverage (only 13 tests), improve error handling | +7pts | M |
| 8 | **Alerts** | 48.5 | Add loading states, error handling, responsive layout, test coverage | +15pts | M |
| 9 | **Ollama Manager** | 65.3 | Clean 7 bare excepts + 7 string enums in service | +8pts | S |
| 10 | **Projects List** | 76.3 | Add error handling to page (0 detected), improve integration links | +5pts | S |

---

## Critical Bugs Found

### 1. Learned Routing 100% Broken (HIGH SEVERITY)
- **File**: [routing_optimizer.py:215](backend/app/services/routing_optimizer.py#L215)
- **Issue**: `func.avg(TaskOutcomeDB.duration_seconds)` — column doesn't exist on TaskOutcomeDB
- **Impact**: Every learned routing attempt fails, ALL tasks fall back to keyword/static routing. The ML routing system is completely non-functional.
- **Fix**: Either add `duration_seconds` column to TaskOutcomeDB via migration, or change to use an existing column (e.g., calculate from timestamps)

### 2. String Enum Comparisons Still Present (MEDIUM SEVERITY)
- **Count**: 105 occurrences across 20 service files
- **Worst offenders**: `daily_prompt_service.py` (20), `nightly_git_sync_service.py` (14), `plan_service.py` (12), `approval_service.py` (8)
- **Impact**: Silent query failures when enum case doesn't match DB

### 3. Print Statements Instead of Logger (LOW SEVERITY)
- **Count**: 182 occurrences across 48 service files
- **Worst offenders**: `autonomous_executor.py` (25), `sprint_manager.py` (24), `agentic_loop_service.py` (14)
- **Impact**: Lost observability, no log levels, breaks structured logging

---

## System Coherence Summary

| Check | Status | Details |
|-------|--------|---------|
| **Data Flow Integrity** | PARTIAL | Sprint→Task→Agent→Execute works. Learning pipeline wired but dormant (episodic: 0 retrievals). Routing broken (missing column). |
| **API Consistency** | PARTIAL | Mixed response formats (Pydantic on newer endpoints, raw dicts on older). Error responses use FastAPI default `{detail}`. Naming is consistent snake_case. |
| **UX Consistency** | PARTIAL | Loading: 20/24 pages have loading states (good). Error handling: only 10/24 pages (bad). EmptyState: only 4 pages use it. Tab patterns vary. |
| **Duplication Level** | LOW-MED | 2 notable pairs: Analytics/Dashboard (trend overlap), LLM Console/LLM Review (both inspect LLM calls, different angles — complementary not redundant) |
| **Dead Features** | 3 detected | Settings (status page, not settings), Dependencies (24-line wrapper), External Knowledge (env-gated, dormant) |

### Data Flow Pipeline Trace
```
Sprint Creation ──────────► Task Decomposition ──────► Agent Routing
  (sprint_manager.py)        (sprint_generator)         (route_task in executor)
        ✅                         ✅                    ⚠️ Learned routing BROKEN
                                                            Keyword routing: ✅
                                                            Fallback: ✅

Agent Routing ────────────► Execution ────────────────► Learning
  (agent_execution_svc)      (autonomous_executor)       (learning_aggregator)
        ✅                         ✅                    ⚠️ record_task_outcome wired
                                                            store_episode wired
                                                            0 episodic retrievals

Learning ─────────────────► Grading
  (project_grader)
  ✅ Grades produced, adaptive clamping works
```

### UX Pattern Consistency

| Pattern | Pages Using | Pages Missing | Coverage |
|---------|-------------|---------------|----------|
| Loading states (Skeleton/isPending) | 22/24 | AskLegion(?), ProjectDetail | 92% |
| Error handling (isError/ErrorBoundary) | 10/24 | 14 pages | 42% |
| EmptyState component | 4/24 | 20 pages | 17% |
| Responsive layout (md:/lg:) | 22/24 | Alerts, ProjectDependencies | 92% |
| WebSocket integration | 1/24 | 23 pages | 4% |

### Duplication Analysis

| Feature A | Feature B | Overlap | Verdict |
|-----------|-----------|---------|---------|
| Analytics | Dashboard | Both show trends/stats | Complementary — Dashboard=summary, Analytics=deep-dive |
| LLM Console | LLM Review | Both inspect LLM calls | Complementary — Console=real-time, Review=quality audit |
| Execution Monitor | Sprint Center | Both show task execution | Moderate overlap — consider merging Execution into Sprint Center |
| Service Health | Dashboard | Both show system status | Complementary — Dashboard=overview, Health=detailed |
| Alerts | Approvals | Both notification-like | Low overlap — different domains (alerts vs safety gates) |

### Dead / Near-Dead Features

| Feature | Route | Issue | Recommendation |
|---------|-------|-------|---------------|
| Settings | /settings | Displays backend health + model info. Zero actual user settings. No test coverage. | Rename to "System Info" or add real preferences (theme, notification prefs) |
| Dependencies | /projects/:id/deps | 24-line wrapper component. Minimal functionality. No tests. | Flesh out with vulnerability scanning, outdated alerts, or merge into Project Detail |
| External Knowledge | backend-only | Gated by `ENABLE_EXTERNAL_KNOWLEDGE` env var. Default disabled. Limited activity. | Enable by default or remove the feature gate. Has excellent test coverage (58 tests) |

---

## Code Quality Summary

| Metric | Count | Trend | Target |
|--------|-------|-------|--------|
| Bare except handlers | 128 across 38 files | Baseline | 0 |
| Unsafe datetime.now() | **0** | Baseline (CLEAN!) | 0 |
| String enum comparisons | 105 across 20 files | Baseline | 0 |
| Print statements (services) | 182 across 48 files | Baseline | 0 |
| Services >800 LOC | 8 files | Baseline | <5 |
| Pages >400 LOC | 14/24 pages | Baseline | <8 |
| Frontend test coverage | 7/24 pages | Baseline | 18/24 |
| Backend test functions | 2,235 across 68 files | Baseline | — |
| Pages without tests | 17/24 | Baseline | <6 |

### Files Over 800 LOC (decomposition candidates)
1. `autonomous_sprint_executor.py` — 3,221 LOC
2. `sprint_execution_graph.py` — 2,010 LOC
3. `unified_llm_service.py` — 1,827 LOC
4. `agentic_loop_service.py` — 1,732 LOC
5. `plan_service.py` — 1,373 LOC
6. `work_discovery_service.py` — 1,072 LOC
7. `claude_executor.py` — 1,039 LOC
8. `sprint_manager.py` — 1,013 LOC

---

## Test Coverage Map

| Feature | Backend Test File(s) | # Tests | Frontend Test | Status |
|---------|---------------------|---------|---------------|--------|
| Dashboard | test_dashboard.py | 24 | Dashboard.test.tsx | GOOD |
| Projects | test_project_service.py, test_projects.py | 20 | Projects.test.tsx | GOOD |
| Sprint Center | test_sprint_manager.py, test_sprints.py | 37 | SprintCenter.test.tsx | GOOD |
| Plans | test_plan_service.py, test_plans.py | 150 | — | BEST backend |
| Autonomous | test_agentic_loop.py, test_autonomous_sprint_executor.py | 32 | AutonomousControl.test.tsx | GOOD |
| Execution Monitor | test_autonomous_pipeline.py | 23 | ExecutionMonitor.test.tsx | GOOD |
| Service Health | test_health.py, test_health_diagnostics.py | 13 | ServiceHealth.test.tsx | FAIR |
| LLM Console | test_llm_call_tracker.py | 23 | LLMConsole.test.tsx | FAIR |
| Agent Dashboard | test_agent_execution_service.py | 26 | — | FAIR |
| Learning | test_learning_*.py (4 files) | 120 | — | GOOD backend |
| PR | test_github_service.py, test_pr_management.py | 103 | — | BEST backend |
| Ollama | test_ollama_manager.py | 46 | — | GOOD |
| Approvals | test_approval_gate.py | 28 | — | FAIR |
| External Knowledge | test_external_knowledge.py | 58 | — | GOOD |
| QA/Tests | test_qa_gate_service.py | 32 | — | FAIR |
| Alerts | — | 0 | — | NONE |
| Ask Legion | — | 0 | — | NONE |
| Ideas | — | 0 | — | NONE |
| Analytics | test_model_selection.py (partial) | 40 | — | PARTIAL |
| Product Docs | — | 0 | — | NONE |
| Git Updates | test_nightly_git_sync.py | 18 | — | FAIR |
| Settings | — | 0 | — | NONE |
| Dependencies | — | 0 | — | NONE |
| Builder | — | 0 | — | NONE |
| LLM Review | test_llm_review.py | 10 | — | LIGHT |

**Frontend test coverage**: 7/24 pages tested (29%)
**Features with ZERO tests**: 8 features (Alerts, Ask Legion, Ideas, Product Docs, Settings, Dependencies, Builder, Analytics partially)

---

## Recommended Sprint: Fix-50: Platform Quality Baseline

Based on audit findings, the highest-impact improvements that would raise the platform score from 62 to ~70:

### Task 1: Fix routing_optimizer missing column (S)
- Add `duration_seconds` to TaskOutcomeDB model + migration, OR change query to use existing timestamp columns
- File: `backend/app/services/routing_optimizer.py:215`, `backend/app/models/sprint_execution.py`

### Task 2: Add error boundaries to 14 pages missing them (M)
- Wrap main content in error boundary with fallback UI
- Pages: LLMConsole, AutonomousControl, AgentDashboard, TestResults, Alerts, Approvals, OllamaManager, ProductDocs, Analytics, AskLegion, Projects, Ideas, ProjectDependencies, GitUpdates

### Task 3: Add EmptyState to 20 pages missing it (M)
- Use existing EmptyState component for no-data scenarios
- Highest priority: Alerts, Approvals, Execution Monitor, Test Results

### Task 4: Clean string enum comparisons in top 5 files (S)
- `daily_prompt_service.py` (20), `nightly_git_sync_service.py` (14), `plan_service.py` (12), `approval_service.py` (8), `ollama_manager_service.py` (7)
- Replace `== "completed"` with `== TaskStatus.COMPLETED` etc.

### Task 5: Convert print→logger in top 3 files (S)
- `autonomous_executor.py` (25), `sprint_manager.py` (24), `agentic_loop_service.py` (14)
- Use `logger.info/debug` instead of `print()`

### Task 6: Add frontend tests for 5 critical untested pages (L)
- Alerts, Ideas, Analytics, ProductDocs, AskLegion

---

## Verification Plan
After implementing Fix-50:
1. Run `python -m pytest backend/tests/ -v` — all tests pass
2. Run `cd frontend && npm run build` — TypeScript clean
3. Run `cd frontend && npx vitest run` — frontend tests pass
4. Check routing: `docker logs legion-backend --tail 50 2>&1 | grep "routing"` — no more "duration_seconds" errors
5. Re-run `/legion-platform-auditor --quick` to verify score improvement

---

## Knowledge File Updates (to execute after approval)

1. **audit_history.json**: Append this run's 28 feature scores + coherence results
2. **dead_features.json**: Add Settings, Dependencies, External Knowledge
3. **duplication_registry.json**: Add Analytics/Dashboard, LLM Console/LLM Review pairs
4. **code_quality_baseline.json**: Update per-feature anti-pattern counts
5. **improvement_log.md**: Record first run findings and recommended Fix-50
6. **improvement_patterns.md**: Seed with routing_optimizer bug as high-impact pattern
