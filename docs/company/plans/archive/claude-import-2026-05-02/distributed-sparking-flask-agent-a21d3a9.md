# Comprehensive Audit: 6 PROJECTS Features in Legion Platform

**Date**: 2026-04-04
**Auditor**: Claude Opus 4.6
**Methodology**: Code-level review of frontend pages, backend endpoints, backend services, test files, cross-links, and integration patterns.

---

## Feature 1: Projects List

**Route**: `/projects` | **Frontend**: `Projects.tsx` (785 lines) | **Backend**: `projects.py` (656 LOC), `project_service.py` (382 LOC)

### D1: Functional Completeness — 90/100
- Full grid view with project cards (no list view toggle, but grid is responsive 1/2/3 cols)
- Complete CRUD: create dialog, edit/settings dialog, delete confirmation dialog
- Pagination with page controls (20 items/page)
- Tech stack display (array or object format handled)
- Health score display via `dependency_health` badge on cards
- AI-powered auto-detection of project path (analyzePathMutation)
- Browse folder dialog for path selection
- Autonomous mode toggle per project
- Sprint count stats on each card
- No "Coming Soon", "TODO", or placeholder text found
- Missing: list view option (grid only), search/filter by name, sort options

### D2: Data Quality — 85/100
- Queries real DB via `GET /projects` endpoint (project_service.py queries ProjectDB)
- Sprint counts (total/active/completed) are computed from real SprintDB table
- `transformProject` safely handles null/missing fields with `??` defaults
- Tech stack handles both array and object (`frameworks`/`dependencies`) formats
- No hardcoded or dummy data patterns found
- `dependency_health` and `health_score` come from real project_knowledge data
- Minor: client-side pagination means ALL projects loaded at once (no server-side offset/limit)

### D3: Integration — 80/100
- Inbound: Dashboard (11 `/projects` references), Sidebar (2 refs), App.tsx routes, CommandPalette
- Outbound: Card click navigates to `/projects/{id}` (ProjectDetail via ProjectScope)
- ProjectScope handles sub-navigation to Plans, Sprints, Ideas, Dependencies
- No WebSocket integration (polling-based via React Query refetch)
- AI-suggest integrates with `/projects/ai-suggest` endpoint
- Analyze button triggers `/projects/{id}/analyze` for sprint creation

### D4: UX/Performance — 82/100
- Loading: Full skeleton grid (6 card placeholders with `animate-pulse`)
- Empty state: Card with icon + "No projects yet" + "Add Project" CTA
- Error handling: toast.error on mutation failures
- Responsive: `grid-cols-1 md:grid-cols-2 lg:grid-cols-3`
- Mutation feedback: "Creating...", "Deleting...", "Saving..." button states
- Loading spinner on analyze button
- No ErrorBoundary wrapping (handled at route level by App.tsx)
- staleTime=0, aggressive refetch (refetchOnMount='always', refetchOnWindowFocus=true)

### D5: Code Quality — 72/100
- Frontend: 785 lines is large but organized with clear state management
- Backend project_service.py is clean at 382 LOC, no bare excepts, no datetime.now() without UTC
- Backend projects.py endpoint: 656 LOC with proper Pydantic response models
- No string enum comparisons found in project_service
- useMemo for pagination is correct but using useMemo for side effects (setCurrentPage) is an anti-pattern (line 100-104)
- `select` transform in useQuery is well-done for cache consistency

### D6: Test Coverage — 65/100
- Backend: `test_projects.py` (10 tests API), `test_project_service.py` (10 tests service), `test_project_grader.py` (23 tests)
- Frontend: `Projects.test.tsx` exists (~11 test cases)
- Total: 43 backend tests + 11 frontend tests = 54 tests
- No ideas test, no dependency review test

**Weighted Score**: 90*0.25 + 85*0.20 + 80*0.20 + 82*0.15 + 72*0.10 + 65*0.10 = 22.5 + 17.0 + 16.0 + 12.3 + 7.2 + 6.5 = **81.5/100**

**Key Issues**:
1. Client-side pagination loads all projects at once (no server-side limit/offset)
2. No search/filter capability on the projects list
3. useMemo used for side effect (setCurrentPage reset)
4. No WebSocket for real-time project status updates

---

## Feature 2: Project Detail

**Route**: `/projects/:id` | **Frontend**: `ProjectDetail.tsx` (85 lines) | **Backend**: `projects.py` (GET summary), `ProjectScope.tsx` (131 lines)

### D1: Functional Completeness — 78/100
- Quick stats cards (Sprints, Active, Completed, Plans, Ideas) with click navigation
- OverviewTab shows: description, architecture summary, knowledge grid (file_structure, api_surface, documentation, environment_config, generics)
- Knowledge scan trigger button
- Tech stack display in ProjectScope header
- Status and dependency_health badges
- Missing: no grade display on this page (grades live in Plans), no auto-sprint toggle (only on Projects list), no project settings from this view

### D2: Data Quality — 82/100
- Fetches real data via `useProjectSummary(projectId)` hook
- Sprint counts computed from real `useSprints` query
- Plan count from `usePlans`, idea stats from `useIdeaStats`
- Knowledge items from real `project_knowledge` table
- Architecture summary from real project knowledge service scan
- All data is real DB data, no stubs

### D3: Integration — 88/100
- Parent: ProjectScope wraps all sub-pages with shared context (project + projectId via Outlet)
- 5-tab navigation (Overview, Plans, Sprints, Ideas, Dependencies) all wired
- StatCards click-navigate to respective sub-pages
- Back to Projects link in error state
- Shares ProjectContext with all child pages
- No WebSocket but parent (ProjectScope) handles loading/error states

### D4: UX/Performance — 70/100
- Loading: ProjectScope shows PageSkeleton for the entire scope
- Error: ApiError 404 handling + generic error display
- Responsive: `grid-cols-2 md:grid-cols-3 lg:grid-cols-5` for stat cards
- Knowledge freshness indicator with auto-refresh suggestion when stale (>24h)
- Missing: no dedicated loading state in ProjectDetail itself (relies on ProjectScope)
- Missing: no error handling for individual data queries (plans/sprints/ideas)
- Scanning button has isPending feedback

### D5: Code Quality — 88/100
- Very clean: 85 lines is appropriately sized
- Clean separation: ProjectScope handles context, ProjectDetail handles content
- OverviewTab extracted as reusable component
- No code smells, proper TypeScript typing
- Backend project_service has no quality issues

### D6: Test Coverage — 30/100
- No dedicated test for ProjectDetail or ProjectScope
- Backend coverage comes from project_service tests (10 tests) but no dedicated overview/summary endpoint tests
- OverviewTab component has no tests

**Weighted Score**: 78*0.25 + 82*0.20 + 88*0.20 + 70*0.15 + 88*0.10 + 30*0.10 = 19.5 + 16.4 + 17.6 + 10.5 + 8.8 + 3.0 = **75.8/100**

**Key Issues**:
1. No frontend test coverage for this page or its OverviewTab
2. No error handling for individual data query failures (plans/sprints/ideas)
3. No project settings or auto-sprint toggle accessible from detail view
4. Relies entirely on parent for loading/error states

---

## Feature 3: Project Plans

**Route**: `/projects/:id/plans` | **Frontend**: `ProjectPlans.tsx` (1006 lines) | **Backend**: `plans.py` (398 LOC), `plan_service.py` (1495 LOC)

### D1: Functional Completeness — 92/100
- Active Plans tab with full table (name, type, status, grade, schedule, runs, actions)
- Grade History tab with expandable rows + trend charts + radar charts
- Plan Detail slide-over with 3 sub-tabs (Overview, Grades, Schedule)
- Create/Edit plan dialog with schedule picker + cron presets
- Delete (archive) confirmation dialog
- Bulk operations: select all, bulk run, bulk pause, bulk resume
- Seed Plans button to create defaults
- Run All button
- Grade trend AreaChart + DimensionRadar chart
- Plan execution progress bar with live log streaming
- Error banner with force retry
- CSV export for grades
- Plan metrics card (avg grade, success rate, avg duration, total tokens)
- Latest grade comparison (vs previous run, dimension diffs)
- Executor status display (running/idle, queue depth, plans today)
- Status filter tabs (all/active/paused/archived)
- Missing: no sorting on grade columns, no pagination for plans list itself

### D2: Data Quality — 90/100
- 19 API endpoints backing this feature (all listed in plans.py docstring)
- All queries hit real DB tables (PlanDB, PlanGradeDB, PlanScheduleDB, PlanExecutionLogDB)
- Grades are real LLM-generated scores with breakdowns
- Schedule history from real cron-based execution
- Metrics computed from actual grade/execution data
- Grade comparison computes real dimension diffs
- No hardcoded data

### D3: Integration — 78/100
- Inbound: ProjectScope tab navigation, GradeOverviewCards (dashboard) link to specific plan
- Outbound: Grade cards link to sprint view (`/projects/{id}/sprints`)
- WebSocket: NOT used (status polling via usePlanStatus with refetchInterval)
- ProjectContext flows correctly from ProjectScope
- Executor status endpoint for daemon health
- Plan execution triggers background sprint creation

### D4: UX/Performance — 88/100
- Loading: TableSkeleton (5 rows, 7 cols) and ListSkeleton (4 rows)
- Empty state: EmptyState component with "No plans configured" + Create/Seed CTAs
- Error: gradesError fallback with AlertTriangle
- Responsive: hidden columns on md:/lg: breakpoints, overflow-x-auto on table
- Plan Detail slide-over with animate-in animation
- Execution progress: real-time step progress bar with log streaming
- Keyboard: Escape to close detail panel, Enter/Space on rows
- Bulk selection bar with clear/run/pause/resume
- Spinner on execute buttons, "Executing" label feedback

### D5: Code Quality — 60/100
- Frontend: 1006 lines is quite large (should be ~600 with extraction)
- Many sub-components are inlined rather than extracted to separate files
- Backend plan_service.py at 1495 LOC is flagged (>500 LOC threshold)
- Backend has 21 `except Exception` catches and 6 `except:` patterns
- Lots of code duplication in grade display components
- However: proper Pydantic models, proper async patterns, proper DB queries

### D6: Test Coverage — 75/100
- Backend: `test_plans.py` (44 tests), `test_plan_service.py` (91 tests), `test_plans_integration.py` (15 tests)
- Total: 150 backend tests -- strong coverage
- No frontend test file for ProjectPlans specifically
- Integration tests may hang (noted in CLAUDE.md)

**Weighted Score**: 92*0.25 + 90*0.20 + 78*0.20 + 88*0.15 + 60*0.10 + 75*0.10 = 23.0 + 18.0 + 15.6 + 13.2 + 6.0 + 7.5 = **83.3/100**

**Key Issues**:
1. 1006-line page file should be decomposed (many inline sub-components)
2. plan_service.py at 1495 LOC exceeds healthy threshold
3. No frontend test coverage
4. No WebSocket for real-time plan execution updates (polling-based)
5. 21+ broad exception catches in plan_service

---

## Feature 4: Sprint Center

**Route**: `/projects/:id/sprints` | **Frontend**: `SprintCenter.tsx` (1499 lines) | **Backend**: `sprints.py` (2893 LOC), `sprint_manager.py` (1352 LOC)

### D1: Functional Completeness — 90/100
- 5 tabs: Sprints, Kanban Board, Ideas, Managed Projects, Agent Swarm
- Sprint list grouped by status (Active, Paused, Planned, In Review, Failed, Completed, Cancelled) with collapsible sections
- Create Sprint dialog with AI-suggest, task management, model selection
- Plan from Ideas dialog with capacity slider
- Autonomous execution dialog with branch-based dev config
- Sprint detail dialog (lazy-loaded)
- Error analysis panel (lazy-loaded)
- Ask AI dialog (lazy-loaded)
- Swarm panel (lazy-loaded)
- AgenticStatusPanel (compact, lazy-loaded)
- Kanban board for current sprint tasks
- Metrics cards (Completion, Tasks, Story Points, Blocked, Test Gate)
- Delete sprint with confirmation
- Retry failed tasks, execute via CLI, reset for retry
- Autonomous status polling

### D2: Data Quality — 85/100
- Queries real data via useSprints, useCurrentSprint, useSprintTasks, useSprintMetrics
- Sprint model capabilities from useModelCapabilities
- Test gate data from useTestGate
- Ideas data from useIdeas
- Autonomous status polling returns real execution state
- Sprint detail via useSprintDetail
- All data from real DB tables (SprintDB, SprintTaskDB, ExecutionDB)
- Some `any` types used (askAISprint, sprintToDelete) reduce type safety

### D3: Integration — 85/100
- Inbound: ProjectScope tab, ProjectDetail stat cards, Dashboard sprint links
- Outbound: Link to Ideas page, link to Autonomous page
- Lazy-loaded components: AgenticStatusPanel, ErrorAnalysisPanel, AskAIDialog, SwarmPanel, SprintDetailDialog
- ProjectContext flows from ProjectScope via useOutletContext
- Ideas tab shows queued ideas with link to full Ideas page
- Managed Projects tab shows all projects with tech stacks
- No direct WebSocket but autonomous status uses polling

### D4: UX/Performance — 85/100
- Loading: SprintCardSkeleton (3 instances)
- Error: QueryErrorFallback for sprint query errors
- Empty: Multiple empty states (no sprints, no active sprint for kanban, no queued ideas)
- Responsive: `grid-cols-1 md:grid-cols-5` for metrics, `grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5` for kanban
- Lazy loading via React.lazy for 5 heavy sub-components (reduces bundle)
- Collapsible sprint sections (completed/cancelled collapsed by default)
- Toast feedback on all mutations
- Suspense fallbacks for lazy components
- Performance: single-pass grouping of sprints/tasks by status (memo'd)

### D5: Code Quality — 45/100
- Frontend: 1499 lines is severely oversized (target ~600)
- Many handlers defined inline rather than extracted
- Backend sprints.py at 2893 LOC is massive (should be split)
- Backend sprint_manager.py at 1352 LOC exceeds threshold
- 24 `except Exception` catches in sprint_manager and 9 broad catches
- `any` types used in several places (sprint objects)
- Good: memoization used, callbacks wrapped in useCallback, single-pass status grouping

### D6: Test Coverage — 72/100
- Backend: test_sprints.py (20 tests), test_sprint_manager.py (17 tests), test_sprint_transitions.py (3 tests), test_sprint_generator.py (78 tests), test_sprint_execution_graph.py (53 tests), test_autonomous_sprint_executor.py (9 tests)
- Total: ~180 backend tests across 6 files
- Frontend: SprintCenter.test.tsx exists (~13 test cases)
- Known issue: 41 pre-existing test failures in sprint manager status tests

**Weighted Score**: 90*0.25 + 85*0.20 + 85*0.20 + 85*0.15 + 45*0.10 + 72*0.10 = 22.5 + 17.0 + 17.0 + 12.75 + 4.5 + 7.2 = **80.95/100**

**Key Issues**:
1. 1499-line page file is the largest in the codebase -- needs aggressive decomposition
2. sprints.py at 2893 LOC is the largest endpoint file
3. Sprint manager has many broad exception catches
4. `any` types used for sprint objects reduce type safety
5. 41 pre-existing test failures reduce actual test reliability
6. No WebSocket for real-time sprint/task status

---

## Feature 5: Ideas

**Route**: `/projects/:id/ideas` | **Frontend**: `Ideas.tsx` (575 lines) | **Backend**: `ideas.py` (495 LOC), `ideas_service.py` (748 LOC)

### D1: Functional Completeness — 85/100
- Ideas list with card layout
- Source tabs (All, My Ideas, Auto-Discovered)
- Status filter (new, analyzed, queued, scheduled, completed, rejected)
- Category filter (feature, bug, enhancement, technical_debt)
- Create idea dialog with AI-suggest integration
- Idea detail dialog with: description, analysis summary, suggested tasks, risks, related files
- Actions: Analyze (new -> analyzed), Queue (analyzed -> queued), Reject
- Discover from Code button
- Stats cards (Total, New, Queued, Avg Complexity, Est Hours)
- Category icons
- Refresh button
- Tags display
- Missing: no sorting, no pagination (client-side only), no bulk operations, no edit idea dialog

### D2: Data Quality — 82/100
- Queries real IdeaDB table via ideas_service
- Analysis results from real LLM analysis (complexity_score, estimated_hours, suggested_tasks)
- Stats computed from real DB aggregation
- Discover from Code triggers real codebase scanning
- IdeaResponse model_validate ensures proper serialization
- Pagination parameters exist in API (page, page_size) but not exposed in UI
- No hardcoded data

### D3: Integration — 72/100
- Inbound: ProjectScope tab, SprintCenter Ideas tab (link to full page), SprintCenter "Plan from Ideas" dialog
- Outbound: Limited -- ideas are consumed by sprint planning but no direct links out
- ProjectContext flows from ProjectScope
- AI suggest integrates with ai_suggest_service
- Discover from Code integrates with ideas_service discovery
- No WebSocket integration

### D4: UX/Performance — 78/100
- Loading: 4 skeleton card placeholders with animate-pulse
- Empty: "Select a project" state, "No ideas yet" with Add/Discover CTAs
- Responsive: `grid-cols-2 md:grid-cols-5` for stats
- Source tabs with count labels
- Status/category filters
- Toast feedback on all mutations
- ScrollArea in detail dialog for long content
- Missing: no error state handling for query failures

### D5: Code Quality — 70/100
- Frontend: 575 lines is a bit large but acceptable
- 3 `except:` bare catches in ideas_service.py
- Backend ideas_service at 748 LOC exceeds 500 LOC threshold
- No datetime.now() without UTC issues found
- No string enum comparisons found
- Category icons properly typed
- Clean state management

### D6: Test Coverage — 15/100
- No backend test file for ideas (test_idea* glob returns empty)
- No frontend test file for Ideas
- Zero dedicated test coverage for this feature
- Only covered indirectly through integration tests

**Weighted Score**: 85*0.25 + 82*0.20 + 72*0.20 + 78*0.15 + 70*0.10 + 15*0.10 = 21.25 + 16.4 + 14.4 + 11.7 + 7.0 + 1.5 = **72.25/100**

**Key Issues**:
1. ZERO test coverage -- the biggest gap across all 6 features
2. No pagination in UI despite API support
3. No edit idea functionality
4. No bulk operations (bulk queue, bulk reject)
5. No error state handling for data queries
6. ideas_service.py exceeds 500 LOC threshold

---

## Feature 6: Dependencies

**Route**: `/projects/:id/dependencies` | **Frontend**: `ProjectDependencies.tsx` (24 lines), `DependenciesTab.tsx` (189 lines) | **Backend**: `dependency_review.py` (170 LOC), `dependency_review_service.py` (763 LOC)

### D1: Functional Completeness — 75/100
- Summary stats cards (Total, Outdated, Critical, Health badge)
- Dependency freshness progress bar
- Full dependency DataTable with columns: Package, Current, Latest, Manager, Status, Type
- DataTable supports: sorting, search by name, pagination (25/page), virtualization (>50 rows)
- Severity badges (major/minor/patch/none)
- Finding type badges (security/outdated/deprecated/modernization)
- Deprecated package indicator (strikethrough + warning icon)
- Scan Dependencies button with loading feedback
- Empty state with scan CTA
- Missing: no security audit details view, no auto-update trigger, no per-dependency action buttons, no history/trend

### D2: Data Quality — 78/100
- Data from real DependencyReviewDB and ProjectDependencyDB tables
- dependency_review_service scans real project files (package.json, requirements.txt, etc.)
- Findings computed from actual version comparison
- Cross-project summary endpoint aggregates real data
- Falls back to summary from ProjectKnowledge if detailed scan not available
- Missing: dependency data can be stale (no freshness indicator on deps table)

### D3: Integration — 65/100
- Inbound: ProjectScope tab navigation only
- Outbound: none
- ProjectContext flows from ProjectScope
- useProjectDependencies hook + useScanProject hook
- Falls back between project summary dep report and dedicated dep review endpoint
- No WebSocket
- No links to/from other features (isolated feature)
- dependency_health badge appears on Projects list cards (indirect integration)

### D4: UX/Performance — 72/100
- Loading: via parent isPending (DependenciesTab doesn't have its own loading)
- Empty state: scan CTA with Package icon
- Responsive: `grid-cols-2 md:grid-cols-4` for stats
- DataTable handles large datasets with virtualization
- Scan button has loading spinner
- Missing: no error state, no Skeleton loader, relies on parent for loading

### D5: Code Quality — 80/100
- Frontend: Very clean -- 24 line page + 189 line component
- Proper component extraction (DependenciesTab is reusable)
- DataTable with typed columns
- Backend dependency_review.py is clean at 170 LOC
- dependency_review_service at 763 LOC exceeds threshold slightly
- 2 `except:` patterns in dependency_review_service
- Proper Pydantic response models

### D6: Test Coverage — 10/100
- No backend test file for dependency review (test_depend* glob returns empty)
- No frontend test file for Dependencies
- Zero dedicated test coverage

**Weighted Score**: 75*0.25 + 78*0.20 + 65*0.20 + 72*0.15 + 80*0.10 + 10*0.10 = 18.75 + 15.6 + 13.0 + 10.8 + 8.0 + 1.0 = **67.15/100**

**Key Issues**:
1. ZERO test coverage -- critical gap
2. Most isolated feature (minimal cross-links)
3. No error handling UI
4. No dependency update trigger or auto-fix
5. No history/trend view for dependency health over time
6. No detailed security audit view per vulnerability

---

## Summary Table

| Feature | D1 (Func) | D2 (Data) | D3 (Integ) | D4 (UX) | D5 (Code) | D6 (Test) | **Weighted** |
|---------|-----------|-----------|------------|---------|-----------|-----------|--------------|
| Projects List | 90 | 85 | 80 | 82 | 72 | 65 | **81.5** |
| Project Detail | 78 | 82 | 88 | 70 | 88 | 30 | **75.8** |
| Project Plans | 92 | 90 | 78 | 88 | 60 | 75 | **83.3** |
| Sprint Center | 90 | 85 | 85 | 85 | 45 | 72 | **81.0** |
| Ideas | 85 | 82 | 72 | 78 | 70 | 15 | **72.3** |
| Dependencies | 75 | 78 | 65 | 72 | 80 | 10 | **67.2** |
| **Average** | **85.0** | **83.7** | **78.0** | **79.2** | **69.2** | **44.5** | **76.8** |

## Top 10 Issues by Impact

1. **Ideas: Zero test coverage** -- 748 LOC service with no tests at all
2. **Dependencies: Zero test coverage** -- 763 LOC service with no tests
3. **Sprint Center: 1499-line page file** -- needs aggressive decomposition into sub-components
4. **sprints.py: 2893-line endpoint file** -- largest in the codebase, should be split by domain
5. **plan_service.py: 1495 LOC** -- exceeds healthy service threshold by 3x
6. **sprint_manager.py: 24 broad exception catches** -- swallows errors, obscures failures
7. **No WebSocket on any of the 6 features** -- all use polling, which is less responsive
8. **Ideas: No pagination in UI** despite API support for `page` and `page_size`
9. **Project Detail: No dedicated frontend tests** -- relies only on indirect coverage
10. **Dependencies: Most isolated feature** -- minimal cross-linking, no history/trends

## Recommendations Priority (High/Medium/Low)

### HIGH
- Write test suites for Ideas (service + endpoint) -- target 30+ tests
- Write test suites for Dependencies (service + endpoint) -- target 20+ tests
- Extract SprintCenter.tsx into 5+ sub-component files
- Split sprints.py endpoint into sub-modules (task endpoints, execution endpoints, etc.)

### MEDIUM
- Add WebSocket integration for sprint/plan execution status
- Add Ideas pagination control in the UI
- Add server-side pagination for Projects list
- Add ProjectDetail/ProjectScope frontend tests
- Decompose plan_service.py into grading + execution + scheduling sub-services

### LOW
- Add search/filter on Projects list
- Add dependency history/trend view
- Add bulk operations to Ideas page
- Add edit idea dialog
- Replace broad `except Exception` with specific exception types in sprint_manager
