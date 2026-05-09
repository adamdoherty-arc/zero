# Legion System Coherence Check Report

## Data Flow Integrity: PARTIAL

### Stage 1: Sprint Creation (sprint_manager.py) -- PASS
- `SprintManager.create_sprint()` creates a `SprintDB` with status `PLANNED`.
- `complete_sprint()` publishes `EventType.SPRINT_COMPLETED` via event bus and calls `LearningAggregatorService.generate_sprint_insights()`.
- `fail_sprint()` publishes `EventType.SPRINT_FAILED` via event bus, sweeps orphaned tasks.
- **Verified**: Output (SprintDB) is consumed by the executor and task decomposition stages.

### Stage 2: Task Decomposition (daily_sprint_generator_service.py) -- PASS
- `DailySprintGeneratorService.generate_sprint()` takes a `PlanGradeDB` and creates `SprintTaskDB` records.
- Uses LLM to decompose improvement areas into concrete tasks with `_decompose_with_llm()`.
- Creates tasks with actionable prompts, filters out vague prompts via `_is_prompt_actionable()`.
- **Verified**: Output (SprintTaskDB records attached to SprintDB) feeds into the autonomous executor.

### Stage 3: Agent Routing (autonomous_sprint_executor.py ~line 1820-1856) -- PASS
- `route_task_learned()` is called first (ML-based), with `route_task()` as static fallback.
- Routes by keyword matching (14 keyword groups) and task_type mapping (10 types).
- Falls through to `main_agent` if no specialist matches.
- **Verified**: Returns agent_name string consumed by `execute_via_agent()`.

### Stage 4: Execution (agent_execution_service.py) -- PASS
- `execute_via_agent()` instantiates the agent, runs it through the middleware pipeline (`MetricsMiddleware`, `WorkspaceIsolationMiddleware`, `LearningMiddleware`).
- Returns string output or None. Handles approval recording for high-risk actions.
- If agent output is insufficient (<50 chars or intent-only), falls through to CLI planner and direct LLM paths.
- **Verified**: Output feeds back into the autonomous executor for task completion or fallback.

### Stage 5: Learning (learning_aggregator.py) -- PASS with caveat
- `record_task_outcome()` writes to three stores: SprintLearningDB, EnhancedCrossSprintLearning, ModelPerformanceTracker.
- Called from autonomous_sprint_executor line 1876-1887 on agent success.
- **Caveat**: Learning is only recorded on the agent pipeline success path. If the task falls through to CLI planner or direct LLM and succeeds there, learning recording is NOT visible in the code excerpt read. This is a **potential gap** -- the fallback paths may or may not record outcomes separately.

### Stage 6: Grading (project_grader_service.py) -- PASS
- `ProjectGraderService.grade_project()` collects sprint data (SprintDB, SprintTaskDB statuses), task errors, LLM quality stats, and learnings.
- Produces a `GradeResult` with dimensional breakdown (6 dimensions for project_review, 4 for docker_logs_review).
- Grades are persisted as `PlanGradeDB`, which feeds back into `DailySprintGeneratorService` (Stage 2), completing the loop.
- **Verified**: Consumes sprint results and produces grades that trigger new sprints.

### Broken Links Found
1. **Learning gap on fallback paths**: When a task succeeds via CLI planner or direct LLM (not the agent pipeline), `record_task_outcome()` may not be called. The code at lines 1866-1887 only records on agent success. The fallback paths (lines 1915-1926) need verification for learning recording.
2. **No event publication on task completion**: `SprintManager.mark_task_completed()` does not publish events. Only sprint-level completion/failure publishes events. Individual task outcomes are not broadcast to the event bus.

---

## API Consistency: PARTIAL

### Response Envelope Format
| Endpoint File | Pattern | Pydantic response_model? | Envelope |
|---|---|---|---|
| projects.py | `response_model=Project`, `response_model=BrowsePathResponse` | YES (most) | Direct model return |
| sprints.py | `response_model=SprintResponse`, `response_model=List[SprintResponse]` | YES (core CRUD) | Direct model return |
| plans.py | `response_model=List[PlanResponse]`, `response_model=List[LatestGradeResponse]` | YES (all) | Direct model return |
| llm_console.py | NO response_model on any endpoint | NO | Raw dicts |
| agents.py | `response_model=List[AgentResponse]` | YES (listing) | Direct model return |
| alerts.py | NO response_model on any endpoint | NO | Raw dicts, `{"success": True}` |
| releases.py | `response_model=List[ReleaseResponse]`, `response_model=ReleaseResponse` | YES (all) | Direct model return |
| incidents.py | `response_model=List[IncidentResponse]`, `response_model=IncidentResponse` | YES (all) | Direct model return |
| grading.py | NO response_model on any endpoint | NO | Raw dicts |
| ollama_manager.py | `response_model=List[OllamaModelResponse]`, etc. | YES (most) | Direct model return |

### Error Response Format
- **Consistent pattern**: Most endpoints raise `HTTPException(status_code=4xx, detail=str(e))`. This is FastAPI standard.
- **ErrorResponse schema exists** (`backend/app/schemas/api_responses.py`) but is NOT used by most endpoints. Only `DeleteResponse` and `SuccessResponse` are imported by some endpoints.
- **Inconsistency**: Error handlers were wired (per sprint API-03) but individual endpoints still use raw `HTTPException` rather than the unified `ErrorResponse` schema.

### Success Response Format
- **Inconsistent**: Some endpoints return `{"success": True}` (alerts.py), some return `{"status": "ok"}`, some return raw dicts with ad-hoc keys.
- **No standard envelope**: There is no consistent `{data: ..., meta: ...}` wrapper. Responses are either Pydantic models (good) or raw dicts (inconsistent).

### Naming Conventions
- **Mostly snake_case**: Endpoint paths use kebab-case (`/run-all`, `/clean-slate`, `/force-retry`), which is REST-conventional.
- **Prefix inconsistency**: `releases.py` and `incidents.py` use `prefix="/api/releases"` and `prefix="/api/incidents"` (double-prefixed since main.py likely already adds `/api`). Other routers like `plans.py` use `prefix="/plans"`. This means releases/incidents are at `/api/api/releases` unless main.py handles it differently.

### Summary of Issues
1. **3 of 10 endpoint files lack response_model** (llm_console, alerts, grading) -- return raw dicts
2. **ErrorResponse schema is defined but unused** by individual endpoints
3. **Success response format inconsistent** (`{"success": True}` vs `{"status": "ok"}` vs raw data)
4. **Releases and incidents have double `/api` prefix** (likely a bug)

---

## UX Consistency: PARTIAL

### Loading Patterns
| Page | Pattern |
|---|---|
| Dashboard.tsx | Custom loading check (`summaryLoading`), `QueryErrorFallback` on error |
| SprintCenter.tsx | `SprintCardSkeleton` import, `QueryErrorFallback` |
| ProjectPlans.tsx | `TableSkeleton`, `ListSkeleton` from skeleton components |
| LearningDashboard.tsx | `DashboardSkeleton`, `ListSkeleton` |
| Analytics.tsx | No skeleton, just `loading` boolean flag |
| ServiceHealth.tsx | No skeleton, no explicit loading state |
| LLMConsole.tsx | No skeleton, no explicit loading state |
| Alerts.tsx | No skeleton, no explicit loading state |

**Finding**: Only 4 of 8 pages use Skeleton components. Analytics, ServiceHealth, LLMConsole, and Alerts show no loading skeleton -- they just render empty until data arrives.

### Empty State Patterns
| Page | Uses EmptyState? |
|---|---|
| Dashboard.tsx | YES |
| ProjectPlans.tsx | YES |
| LearningDashboard.tsx | YES |
| Analytics.tsx | YES |
| SprintCenter.tsx | NO (no EmptyState import) |
| ServiceHealth.tsx | NO |
| LLMConsole.tsx | NO |
| Alerts.tsx | NO |

**Finding**: 4 of 8 pages use `EmptyState`. The other 4 have no standardized empty state handling.

### Error Display
| Page | Pattern |
|---|---|
| Dashboard.tsx | `QueryErrorFallback` component |
| SprintCenter.tsx | `QueryErrorFallback` component |
| ExecutionMonitor.tsx | `QueryErrorFallback` component |
| Others | No explicit error display (rely on global ErrorBoundary from App.tsx `<S>` wrapper) |

**Finding**: Only 3 pages have inline error handling. The rest depend on the `<S>` wrapper's ErrorBoundary in App.tsx, which shows a generic error page rather than inline recovery.

### Tab Patterns
Pages using Tabs: 10 total (Ideas, ProjectScope, SprintCenter, ProjectPlans, LearningDashboard, Analytics, Approvals, ProductDocs, Alerts, PullRequests).

All use `@/components/ui/tabs` (Tabs, TabsList, TabsTrigger, TabsContent) -- this is consistent.

**Exception**: Analytics.tsx uses a custom `activeTab` state with manual tab buttons instead of the shared Tabs component.

---

## Duplication Report

| Feature A | Feature B | Overlap | Recommendation |
|---|---|---|---|
| **Execution Monitor** (`/execution`) | **Sprint Center** (`/projects/:id/sprints`) | Both show execution status and task progress. Sprint Center shows per-project sprints with tasks; Execution Monitor shows cross-project recent executions. | **Complementary but overlapping**. Sprint Center is project-scoped, Execution Monitor is global. Consider merging Execution Monitor as a tab within a global operations page. |
| **Analytics** (`/analytics`) | **Dashboard** (`/`) | Both show sprint counts, success rates, and trends. Dashboard is a summary with links; Analytics has deeper cross-project comparison and model rankings. | **Complementary**. Dashboard is overview, Analytics is deep-dive. Acceptable overlap but the `overview` tab in Analytics duplicates Dashboard's sprint stats. |
| **Agent Dashboard** (`/agent-dashboard`) | **Learning Dashboard** (`/learning`) | Agent Dashboard shows agent registry, categories, health, topology. Learning Dashboard shows sprint learnings, council sessions, knowledge, decisions, features. | **Complementary**. Agent Dashboard = agent inventory/health. Learning Dashboard = ML system. No meaningful overlap. |
| **Alerts** (`/alerts`) | **Approvals** (`/approvals`) | Alerts shows Prometheus-based metric alerts (firing/resolved). Approvals shows agent approval requests and autonomy level. | **No overlap**. Different domains entirely. Alerts = system metrics. Approvals = agent governance. |
| **LLM Console** (`/llm-console`) | **LLM Review** (backend only, no page) | LLM Console shows real-time and historical LLM calls with filtering. LLM Review is a backend-only quality review system with 6 API endpoints but NO frontend page. | **Potential overlap**. LLM Review data (flagged calls, patterns, review scores) should surface in the LLM Console page. Currently the review data is invisible to users. |
| **Service Health** (`/service-health`) | **Dashboard** (`/`) | Service Health shows infrastructure status (DB, Redis, Ollama, background tasks, diagnostics). Dashboard shows high-level system status. | **Complementary**. Dashboard = operational overview. Service Health = infrastructure drill-down. No duplication. |

---

## Dead Features

| Feature | Route | Issue | Recommendation |
|---|---|---|---|
| **AskLegion** | `/ask-legion` | Zero inbound navigation -- NOT linked from Sidebar (removed from nav items) or any other page. Only reachable via direct URL or the prefetch map in Sidebar. | Add to sidebar or remove the page. Currently a hidden feature. |
| **Settings** | `/settings` | Zero inbound navigation from other pages. Only in sidebar `systemItems`. No links from any page point to `/settings`. | Low priority -- sidebar link exists. Acceptable. |
| **Product Docs** | `/product-docs` | Only linked from App.tsx redirect (`/documentation` -> `/product-docs`). Sidebar link exists. No page links to it. | Acceptable -- sidebar provides access. |
| **Ollama Manager** | `/ollama-manager` | Zero inbound links from other pages. Only sidebar link. | Acceptable -- sidebar provides access. |
| **Pull Requests** | `/pull-requests` | Zero inbound links from other pages. Only sidebar link. | Acceptable -- sidebar provides access. |
| **Git Updates** | `/git` | Only linked from Dashboard.tsx. No sidebar `to="/git"` match found but it IS in sidebar `systemItems`. | Acceptable. |
| **Test Results** | `/test-results` | Only linked from Dashboard.tsx. Sidebar link exists. | Acceptable. |
| **LLM Review** | No frontend route | Backend has 6 API endpoints (`/llm-review/*`) but NO frontend page exists to display the data. | **Dead backend feature** -- build a frontend page or integrate into LLM Console. |
| **ProjectDependencies** | `/projects/:id/dependencies` | 24 lines -- thin wrapper around `DependenciesTab` component. | Not dead, just thin. Acceptable architecture (smart component pattern). |
| **Releases** | No frontend route found | Backend has 7 API endpoints (`/api/releases/*`) but no frontend page. | **Dead backend feature** -- no UI to manage releases. |
| **Incidents** | No frontend route found | Backend has 2 API endpoints (`/api/incidents/*`) but no frontend page. | **Dead backend feature** -- no UI to view/resolve incidents. |

---

## Summary Scores

| Area | Rating | Key Issues |
|---|---|---|
| **Data Flow Integrity** | PARTIAL | Learning not recorded on CLI/direct LLM fallback paths; no task-level event bus publication |
| **API Consistency** | PARTIAL | 3/10 endpoints lack response_model; ErrorResponse schema defined but unused; success format inconsistent; releases/incidents double `/api` prefix |
| **UX Consistency** | PARTIAL | 4/8 pages lack Skeleton loading; 4/8 pages lack EmptyState; only 3 pages have inline error handling; Analytics uses custom tabs instead of shared component |
| **Duplication** | LOW | Most page pairs are complementary not redundant; LLM Console / LLM Review overlap is the biggest gap |
| **Dead Features** | MODERATE | 3 backend feature sets have no frontend (LLM Review, Releases, Incidents); AskLegion page has zero navigation paths |

## Priority Recommendations

1. **HIGH**: Wire `record_task_outcome()` into CLI planner and direct LLM fallback paths in `autonomous_sprint_executor.py` to close the learning gap.
2. **HIGH**: Build frontend pages for Releases and Incidents, or remove the backend endpoints -- currently invisible to users.
3. **MEDIUM**: Add `response_model` to llm_console.py, alerts.py, and grading.py endpoints for API consistency.
4. **MEDIUM**: Fix the double `/api` prefix on releases.py and incidents.py routers.
5. **MEDIUM**: Add Skeleton loading and EmptyState to ServiceHealth, LLMConsole, Alerts, and Analytics pages.
6. **MEDIUM**: Surface LLM Review data (flagged calls, quality patterns) in the LLM Console page.
7. **LOW**: Add AskLegion back to the sidebar navigation or document it as accessible only via Command Palette.
8. **LOW**: Standardize success response format -- pick either `SuccessResponse` from api_responses.py or raw `{"success": true}`, not both.
