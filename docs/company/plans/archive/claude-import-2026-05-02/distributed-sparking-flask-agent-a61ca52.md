# Comprehensive Operations Feature Audit — Legion Platform

**Date**: 2026-04-04
**Auditor**: Claude Opus 4.6
**Weights**: D1=0.25, D2=0.20, D3=0.20, D4=0.15, D5=0.10, D6=0.10

---

## Feature 1: Ask Legion (/ask-legion)

**Frontend**: `frontend/src/pages/AskLegion.tsx` (415 LOC)
**Backend**: `backend/app/api/endpoints/chat.py` (149 LOC), `chat_service.py`

```
D1: 90/100 — Fully functional chat UI with message bubbles, streaming SSE, session management,
              project scoping, source citations, typing indicator, quick prompts. No placeholders.
D2: 85/100 — Backend ChatService queries real DB (projects, sessions). SSE streaming via
              event_generator. Sessions stored in-memory (not DB-persisted). Sources from
              real Qdrant retrieval. Non-hardcoded.
D3: 50/100 — Linked from Sidebar and App.tsx route. No outbound links to other features.
              No WebSocket integration (uses SSE instead). Not linked from Dashboard.
D4: 55/100 — No isLoading/isPending/Skeleton states found. Has isStreaming for send button
              disable. Auto-scroll, auto-resize textarea. Responsive grid-cols-2 for prompts.
              No ErrorBoundary wrapper. No error display for failed messages.
D5: 80/100 — Clean code, proper TypeScript types. 415 LOC is acceptable. Backend uses
              try/except with HTTPException. No bare excepts. No datetime issues.
              One `catch { /* ignore */ }` in project fetch is a minor concern.
D6: 10/100 — No backend test for chat_service or chat.py. No frontend test for AskLegion.tsx.
              Zero test coverage.
Weighted: 65.3
Key Issues:
- No loading/error states for initial render
- No test coverage at all
- Sessions are in-memory only (lost on restart)
- No cross-links from Dashboard or other pages
```

---

## Feature 2: Dashboard (/)

**Frontend**: `frontend/src/pages/Dashboard.tsx` (683 LOC)
**Backend**: `backend/app/api/endpoints/dashboard.py` (396 LOC)

```
D1: 95/100 — Comprehensive dashboard: stat cards (sprints, tasks, projects, agents),
              project grades, LLM queue, plan executor, ideas pipeline, executor status,
              current sprint, test health, autonomous planning, brain activity, swarm panel,
              recent activity, managed projects. All sections render real content.
D2: 95/100 — Single dashboard-summary endpoint replaces 11 API calls. Real DB queries
              (projects, sprints, tasks, ideas, grades, learnings, LLM queue). Brain
              decisions from in-memory service. All real timestamps. Week-over-week trends
              from SQL.
D3: 90/100 — Extensive outbound links: /projects, /git, /execution, /learning, /autonomous,
              /agent-dashboard, /test-results. Inbound: default route (/). Uses
              useDashboardSummary, useManagedProjects, useAutonomousStatus, useRecentExecutions,
              useTestMetrics. GradeOverviewCards shared component.
D4: 85/100 — Has isLoading state, EmptyState component, QueryErrorFallback for error.
              Responsive grid (grid-cols-1 md:grid-cols-2 lg:grid-cols-4). Status helpers
              from lib. animate-pulse on swarm panel.
D5: 80/100 — 683 LOC is on the higher side but manageable. Backend uses datetime.now(UTC)
              correctly with .replace(tzinfo=None). Proper try/except blocks with logger.debug
              fallbacks. No bare excepts.
D6: 70/100 — Backend: test_dashboard.py in both api/ and services/ (20 test functions in
              services). Frontend: Dashboard.test.tsx exists. Good coverage.
Weighted: 88.8
Key Issues:
- 683 LOC is close to flagging threshold; could split into sub-components
- Brain decisions rely on in-memory log (lost on restart)
```

---

## Feature 3: LLM Console (/llm-console)

**Frontend**: `frontend/src/pages/LLMConsole.tsx` (514 LOC)
**Backend**: `backend/app/api/endpoints/llm_console.py` (256 LOC)

```
D1: 95/100 — Complete LLM observability: active calls, recent calls, stats (active/today/
              latency/failed), cost summary, source/status filters, virtualized call list,
              full detail dialog with prompt/response/metadata/copy. Trends and cost
              attribution endpoints exist.
D2: 90/100 — Combines in-memory tracker (active calls) with DB queries (LLMCallDetailDB).
              Stats endpoint aggregates both. Real timestamps, tokens, latency_ms. Cost
              estimation based on model type. DB-backed historical queries with filters.
D3: 65/100 — No inbound links from Dashboard (not directly linked, though LLM queue widget
              exists). No outbound links to other features. No WebSocket (uses polling via
              useLLMConsole hook). Linked from Sidebar.
D4: 85/100 — Virtual scrolling (@tanstack/react-virtual) for performance. Source/status
              filters. Responsive grid (md:grid-cols-4). Refresh button. Loading states in
              detail dialog. Copy-to-clipboard with toast. No skeleton loaders.
D5: 85/100 — 514 LOC is over 400 threshold but well-structured with extracted components.
              Backend: proper datetime handling, no bare excepts, clean query building.
              estimateCost is client-side approximation (acceptable for display).
D6: 35/100 — Frontend: LLMConsole.test.tsx exists. Backend: No test file for llm_console.py
              or llm_call_tracker. Partial coverage only.
Weighted: 78.5
Key Issues:
- No backend tests for llm_console endpoints
- Not linked from Dashboard (despite LLM queue widget existing there)
- Trends endpoint uses in-memory data only (max 200 calls)
```

---

## Feature 4: Autonomous Control (/autonomous)

**Frontend**: `frontend/src/pages/AutonomousControl.tsx` (393 LOC)
**Backend**: `backend/app/api/endpoints/agentic.py` (consolidated endpoint)

```
D1: 90/100 — Full autonomous control panel: project selector, status overview (status, ideas
              ready, new ideas, active sprints), mode control (passive/standard/aggressive),
              quick actions (discover, analyze, plan sprint, plan 3 sprints), sprint capacity
              selector, planning history with decision types. Info banner.
D2: 85/100 — Queries real autonomous status, planning history, available modes from backend
              services. Mutations for start/stop/plan/analyze all hit real service endpoints.
              Planning history shows real decision types with timestamps.
D3: 70/100 — Dashboard links to /autonomous ("Control Panel", "Plan Sprint"). Sidebar link.
              No outbound links from this page. Uses useAutonomousStatus, usePlanningHistory,
              useAutonomousModes hooks. No WebSocket.
D4: 75/100 — isPending states on all 6 mutation buttons (start, stop, plan, plan multiple,
              analyze, discover). Toast notifications. No skeleton loaders. Responsive
              grid (md:grid-cols-4, lg:grid-cols-2). Empty state when no project selected.
D5: 80/100 — 393 LOC (just under threshold). Clean hook usage. Backend endpoint file
              (agentic.py) is well-structured with consolidated routes. Proper error handling
              with toast.error on catch.
D6: 45/100 — Frontend: AutonomousControl.test.tsx exists. Backend: test_agentic_loop.py
              has 23 tests but covers the loop service, not the endpoint directly.
              No test for autonomous planning endpoints specifically.
Weighted: 76.5
Key Issues:
- No skeleton loaders while data loads
- Backend endpoint tests missing (only service-level tests exist)
- No outbound cross-links to execution monitor or sprint details
```

---

## Feature 5: Execution Monitor (/execution)

**Frontend**: `frontend/src/pages/ExecutionMonitor.tsx` (325 LOC)
**Backend**: Uses autonomous execute endpoints + swarm endpoints

```
D1: 88/100 — Full execution monitoring: executor status, running/completed/failed counters,
              status filter, execution list with cancel, log dialog with role-colored output.
              WebSocket live indicator. Real-time updates.
D2: 85/100 — Queries real execution data (useRecentExecutions with limit 50). Executor
              status from autonomous status endpoint. Execution logs from dedicated endpoint.
              Real timestamps, durations, conversation previews.
D3: 80/100 — Dashboard links to /execution ("Monitor", "Logs", recent activity clicks).
              WebSocket integration (useExecutionActivity from useWebSocket). Inbound from
              Dashboard click handlers. No outbound links.
D4: 85/100 — Skeleton loading (animate-pulse h-16 placeholders). QueryErrorFallback for
              errors. WebSocket connected/polling indicator. isPending on cancel mutation.
              Responsive grid (md:grid-cols-4). Filter dropdown. Empty state.
D5: 80/100 — 325 LOC, well-structured. Uses status helpers from lib. Proper error handling
              in handleCancel. Clean component separation (log dialog extracted).
D6: 50/100 — Frontend: ExecutionMonitor.test.tsx exists. Backend: test_autonomous_sprint_
              executor.py (9 tests) covers the service. No endpoint-specific test.
Weighted: 79.8
Key Issues:
- Log dialog could show more structured data
- No outbound cross-links (e.g., to sprint details, agent dashboard)
- Backend endpoint-level tests missing
```

---

## Feature 6: Agent Dashboard (/agent-dashboard)

**Frontend**: `frontend/src/pages/AgentDashboard.tsx` (387 LOC)
**Backend**: `backend/app/api/endpoints/agent_dashboard.py` (312 LOC)

```
D1: 85/100 — Agent cards with status/metrics/last active, summary bar (total/active/idle/
              error/active loops), category and status filters, cards vs. topology graph view
              toggle, agent detail panel with metrics. Orchestration summary endpoint exists.
D2: 70/100 — AGENT_TYPES is a hardcoded list of 10 agents (not the full 26+ registered).
              Metrics come from LLM call tracker (in-memory, approximate). Status from task
              health registry. Orchestration summary queries real DB for learnings/grades.
              Agent metrics endpoint matches on source string (fragile).
D3: 60/100 — Dashboard links to /agent-dashboard ("View All Brain Activity"). Sidebar link.
              No outbound links. AgentTopologyGraph is a custom component but no links to
              individual agent pages. No WebSocket.
D4: 70/100 — Loading skeletons (animate-pulse cards). Error display for failed load.
              View mode persisted to localStorage. Category/status filter buttons. Responsive
              grid (md:grid-cols-2 xl:grid-cols-3). RefreshCw with spin animation.
D5: 65/100 — Backend hardcodes 10 agent types instead of reading from AgentRegistry (which
              has 26+). String matching for metrics (`agent_id in source`) is fragile. Multiple
              bare `except Exception: pass` blocks (6 occurrences). 312 LOC backend acceptable.
D6: 25/100 — No test file for agent_dashboard.py endpoint. Frontend: no AgentDashboard test.
              Related tests exist (test_agent_execution_service, test_specialist_agents) but
              don't cover this endpoint.
Weighted: 63.5
Key Issues:
- Hardcoded 10 agents vs 26+ registered (data quality issue)
- 6 bare `except Exception: pass` blocks in backend
- No tests at all for this feature
- Fragile string-matching for agent metrics
```

---

## Feature 7: Learning Dashboard (/learning)

**Frontend**: `frontend/src/pages/LearningDashboard.tsx` (857 LOC)
**Backend**: Multiple endpoints (learnings, council, episodic, explainability)

```
D1: 95/100 — 6 tabs (Overview, Sprint Learnings, Council, Knowledge, Decisions, Features).
              Overview: stat cards, LLM activity, velocity, model performance, episodic memory.
              Sprint Learnings: type filter, learning cards, pattern cards. Council: run button,
              session list with verdicts. Knowledge: domain coverage grid. Decisions: trace
              list. Features: importance bars with detail breakdown. All fully rendered.
D2: 90/100 — 10+ hooks hitting real endpoints (useLearningSummary, useDecisionTraces,
              useFeatureImportance, useCouncilExplanations, useEpisodeStats, useKnowledgeCoverage,
              useLearningVelocity, usePromptStats, useLearnings, usePatterns). All query real
              DB tables (sprint_learnings, council_sessions, episodes, knowledge_sources).
D3: 55/100 — Dashboard links to /learning ("Learnings" button). Sidebar link. No outbound
              links to other features. No WebSocket integration. Council "Run" button is
              self-contained.
D4: 75/100 — DashboardSkeleton and ListSkeleton for loading states. EmptyState components
              throughout. isLoading checks on each tab. Error states for learnings/patterns
              with retry buttons. Responsive grid (grid-cols-2 lg:grid-cols-4). ScrollArea
              for long lists.
D5: 70/100 — 857 LOC is very high (over 2x the 400 LOC flag). Should be split into separate
              files per tab. Many `any` type assertions on session.verdicts, f.detail, etc.
              Backend services have proper error handling.
D6: 65/100 — Backend: test_learning_aggregator (48), test_learning_engine (22),
              test_learning_council (23), test_learning_agents (83). Strong service-level
              coverage. No frontend test file. No endpoint-level test.
Weighted: 77.3
Key Issues:
- 857 LOC -- needs decomposition into sub-components/files
- Heavy use of `any` types on backend response data
- No frontend test
- Limited cross-linking to other features
```

---

## Feature 8: Pull Requests (/pull-requests)

**Frontend**: `frontend/src/pages/PullRequests.tsx` (373 LOC)
**Backend**: `backend/app/api/endpoints/pull_requests.py` (237 LOC)

```
D1: 90/100 — Summary cards (total/open/merged/closed), filter tabs, PR list with status
              badges and GitHub links, detail dialog with sprint info/branch/tasks/GitHub
              live status/AI review/merge/feedback actions. Monitoring sweep button.
D2: 85/100 — Queries real SprintDB records filtered by pr_number IS NOT NULL. Summary
              aggregates from DB. Detail fetches live GitHub status via GitHubService.
              Review triggers PRManagementService (real LLM-powered review). Merge hits
              real GitHub API.
D3: 55/100 — Sidebar link. No inbound links from Dashboard or other pages. No outbound
              links to sprint details. No WebSocket.
D4: 70/100 — Loader2 spinner while loading. isPending on review/merge/monitor mutations.
              isSuccess/isError states with feedback messages. No skeleton loaders. Empty
              state for no PRs. Responsive grid-cols-4 for summary.
D5: 80/100 — 373 LOC (under threshold). Clean code. Backend uses proper try/except with
              ImportError fallback for optional PRManagementService. No bare excepts.
              Proper HTTPException usage.
D6: 55/100 — Backend: test_pr_management.py (30 tests) covers the service well. No frontend
              test file. No endpoint-level test.
Weighted: 74.0
Key Issues:
- Not linked from Dashboard (should be in a "Git/PR" section)
- No skeleton loaders
- No frontend test
- GitHub integration requires token configuration
```

---

## Feature 9: Test Results (/test-results)

**Frontend**: `frontend/src/pages/TestResults.tsx` (657 LOC)
**Backend**: `backend/app/api/endpoints/qa.py` (300 LOC), `test_feedback.py`

```
D1: 92/100 — Project/sprint selectors, 6-metric overview (runs/rate/passed/failed/duration/
              coverage), coverage detail card with trend bars and per-file breakdown, daily
              reports, sprint test gate with unblock, recent test runs (expandable), recent
              failures (expandable), learned failure patterns. Run Tests button.
D2: 85/100 — 10+ hooks querying real data: useProjectTestHistory, useTestGate,
              useRecentFailures, useTestMetrics, useTestPatterns, useSuiteRunStatus,
              useCoverageReport, useDailyReports. QA backend queries real DB tables.
              Test gate data is real.
D3: 65/100 — Dashboard links to /test-results ("View Details", "View Test Results").
              Sidebar link. No outbound links. No WebSocket (polls suite status). Uses
              useSprints for sprint selector.
D4: 70/100 — isPending on run/unblock mutations. Expandable sections for failures/results.
              Coverage color coding. No skeleton loaders. Trend bars. Empty states for
              no data. Responsive grid (md:grid-cols-6, lg:grid-cols-2).
D5: 70/100 — 657 LOC is high (over 400 threshold). Single file with all sections. Should
              decompose into components. Backend QA endpoint is clean. Some `catch {}` blocks
              without error content.
D6: 55/100 — Backend: test_qa_gate_service.py (32 tests). No frontend test. No endpoint
              test for qa.py. test_feedback.py exists as endpoint but no tests for it.
Weighted: 75.5
Key Issues:
- 657 LOC -- needs decomposition
- No skeleton loaders
- Backend endpoint-level tests missing
- QA endpoint file focuses on sign-off workflow, not test result display
  (frontend queries different hooks)
```

---

## Feature 10: Alerts (/alerts)

**Frontend**: `frontend/src/pages/Alerts.tsx` (275 LOC)
**Backend**: `backend/app/api/endpoints/alerts.py` (85 LOC)

```
D1: 85/100 — Three tabs (Active, History, Rules). Active: alert cards with severity badges,
              state icons, acknowledge button, firing count. History: compact list with
              resolve times. Rules: full config display with enable/disable, delete.
              Evaluate Now button.
D2: 75/100 — Backend alert_service is an in-memory service (not DB-persisted). Rules are
              predefined + custom in-memory. Alert history maintained in memory only.
              Real metric evaluation via evaluate_all(). Lost on restart.
D3: 45/100 — Sidebar link only. No inbound links from Dashboard. No outbound links.
              No WebSocket. Polling at 15s (active) and 30s (history) intervals with
              visibility gating.
D4: 55/100 — No skeleton loaders. No isLoading states shown. isPending on evaluate
              (RefreshCw spin). No ErrorBoundary or error states. No responsive breakpoints
              found. Visibility-gated polling is good.
D5: 75/100 — 275 LOC (well under threshold). Backend is very concise (85 LOC). Lazy imports
              for alert_service. No bare excepts in backend. Frontend has some inline
              mutation logic.
D6: 5/100  — No backend test file for alert_service or alerts.py. No frontend test.
              Zero test coverage for this feature.
Weighted: 57.8
Key Issues:
- In-memory only (all data lost on restart)
- No test coverage at all
- No loading/error states
- Not cross-linked from Dashboard
- No responsive breakpoints
```

---

## Feature 11: Approvals (/approvals)

**Frontend**: `frontend/src/pages/Approvals.tsx` (342 LOC)
**Backend**: `backend/app/api/endpoints/safety.py` (647 LOC)

```
D1: 88/100 — Three tabs (Pending, History, Steering). Pending: approval cards with
              approve/reject, risk scores, operation details. History: same cards read-only.
              Steering: mid-task message injection. Autonomy level selector dropdown (4 levels).
              Stats bar (pending/approved/rejected/expired today). Project filter.
D2: 85/100 — Backend queries real ApprovalRequestDB table. Autonomy levels stored in
              SafetyConfig (DB). Steering messages stored module-level (in-memory). Cost
              tracking from real LLMUsageDB. Approval history from DB with proper ordering.
D3: 55/100 — Sidebar link. No inbound links from Dashboard. No outbound links to sprints
              or executions. No WebSocket. Uses useProjects for project selector.
D4: 60/100 — pendingLoading/historyLoading states (show "Loading..." text). isPending on
              approve/reject/send mutations. No skeleton loaders. No ErrorBoundary or error
              handling. Stats bar. Responsive grid-cols-4.
D5: 75/100 — Frontend 342 LOC (under threshold). Backend 647 LOC is high but covers safety
              config, approvals, autonomy, steering, blast radius, costs, dry-run, rate
              limiting, checkpoints -- comprehensive. Two checkpoint endpoints return 501
              "Not yet implemented". No bare excepts.
D6: 50/100 — Backend: test_approval_gate.py (28 tests) covers the service. No frontend test.
              No endpoint test for safety.py. Checkpoint endpoints explicitly unimplemented.
Weighted: 71.0
Key Issues:
- Two checkpoint endpoints return 501 (not implemented)
- Steering messages in-memory only
- No skeleton loaders
- No cross-links from Dashboard
- No frontend test
```

---

## Summary Table

| # | Feature | D1 | D2 | D3 | D4 | D5 | D6 | Weighted |
|---|---------|----|----|----|----|----|----|----------|
| 1 | Ask Legion | 90 | 85 | 50 | 55 | 80 | 10 | **65.3** |
| 2 | Dashboard | 95 | 95 | 90 | 85 | 80 | 70 | **88.8** |
| 3 | LLM Console | 95 | 90 | 65 | 85 | 85 | 35 | **78.5** |
| 4 | Autonomous Control | 90 | 85 | 70 | 75 | 80 | 45 | **76.5** |
| 5 | Execution Monitor | 88 | 85 | 80 | 85 | 80 | 50 | **79.8** |
| 6 | Agent Dashboard | 85 | 70 | 60 | 70 | 65 | 25 | **63.5** |
| 7 | Learning Dashboard | 95 | 90 | 55 | 75 | 70 | 65 | **77.3** |
| 8 | Pull Requests | 90 | 85 | 55 | 70 | 80 | 55 | **74.0** |
| 9 | Test Results | 92 | 85 | 65 | 70 | 70 | 55 | **75.5** |
| 10 | Alerts | 85 | 75 | 45 | 55 | 75 | 5 | **57.8** |
| 11 | Approvals | 88 | 85 | 55 | 60 | 75 | 50 | **71.0** |

**Overall Average**: 73.5/100

---

## Cross-Cutting Findings

### Strengths
1. **Functional completeness is high** -- all 11 features render real UI with real data, no placeholder pages
2. **Dashboard is exceptional** -- single API call pattern, extensive cross-links, proper error states
3. **Data quality is generally good** -- most features query real DB tables with proper SQL
4. **Backend code quality is clean** -- no bare excepts found in any endpoint file, proper datetime handling

### Systemic Weaknesses
1. **Test coverage is the weakest dimension** -- 5 features have zero backend/frontend tests, average D6 is only 42/100
2. **Cross-linking is weak** -- most pages are islands; only Dashboard has extensive outbound links
3. **Loading/error states inconsistent** -- some features (Dashboard, Execution Monitor) have proper skeletons; others (Ask Legion, Alerts, Approvals) have none
4. **In-memory data persistence** -- Alerts, Chat sessions, and Steering messages are all lost on restart
5. **Large file sizes** -- Learning Dashboard (857 LOC), Test Results (657 LOC), Dashboard (683 LOC) need decomposition

### Priority Fixes (by impact)
1. **Add tests for Alerts and Ask Legion** (both at 5-10 D6) -- zero test coverage on active features
2. **Add skeleton loaders** to Ask Legion, Alerts, Approvals, Pull Requests
3. **Fix Agent Dashboard hardcoded agents** -- reads 10 agents vs 26+ registered
4. **Persist alert data to DB** -- currently all in-memory
5. **Decompose large page files** -- LearningDashboard, TestResults into sub-components
6. **Add Dashboard cross-links** to Alerts, Pull Requests, Approvals pages
