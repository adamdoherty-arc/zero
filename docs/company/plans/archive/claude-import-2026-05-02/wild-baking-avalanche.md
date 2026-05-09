# Legion Platform Audit — Run 6

## Context

Last audit (Run 5, 2026-04-08) scored **80.8/100 (B-)**, the first B-grade in Legion history. Trajectory: 62 -> 68 -> 75 -> 80.8 across 5 runs. Since then:

- **New feature**: GitHub Repos page (`/github-repos`) — full stack with 4 new files (~1143 LOC), zero tests
- **Config changes**: Ollama re-enabled, Kimi re-enabled, DSPy evolution enabled, primary model swapped to Ollama
- **Backend modifications**: prompt_manager_service, sprint_quality_grader, annotation_queue_service, gpu_manager_daemon, ollama_client, prompt_evaluator_agent
- **Known Run 5 regressions**: bare_except_count=3, service_count=144 (target 80), files_over_800_loc=28 (target 4)

Goal: Grade all 32 features across 6 dimensions, detect regressions, register GitHub Repos as feature #32, generate improvement recommendations, update knowledge files.

---

## Phase 1: Backend Pre-check (~2 min)

Verify backend is warm and responsive:
```bash
curl -s --max-time 5 http://localhost:8005/health
curl -s --max-time 10 http://localhost:8005/api/dashboard-summary
curl -s -o /dev/null -w "%{http_code}" http://localhost:3005/
```

Collect codebase metrics snapshot (service count, bare excepts, files >800 LOC, test file counts, router count, page count) — compare against Run 5 baseline in `code_quality_baseline.json`.

---

## Phase 2: Feature Discovery (~3 min)

1. Verify route inventory from `frontend/src/App.tsx` (expect 25 routes)
2. Verify sidebar items from `frontend/src/components/Sidebar.tsx` match routes
3. Register **GitHub Repos** as new feature in catalog:
   - Route: `/github-repos`, Section: SYSTEM, 5 endpoints, 503 LOC page, 0 tests
4. Reconcile `backend/app/api/router_registry.py` routers against catalog
5. Check for dead features (pages with no sidebar entry, endpoints returning only errors)

---

## Phase 3: Parallel Feature Audits (~25 min)

Launch **5 parallel agents**, one per batch. Each agent audits its assigned features across all 6 dimensions using curl (API checks) and grep/glob (code checks).

### Batch A: Core Project & Sprint (5 features)
Dashboard, Projects List, Project Detail, Sprint Center, Builder Mode

### Batch B: LLM & Learning System (7 features)
LLM Console, LLM Review, Prompt Manager, Autonomous Control, Learning Dashboard, Reasoning Capture (backend-only), Sprint Quality (backend-only)

### Batch C: Agent & Execution (6 features)
Execution Monitor, Agent Dashboard, Pull Requests, Test Results, Alerts, Approvals

### Batch D: System & Infrastructure (8 features)
Service Health, Ollama Manager, GPU Manager, **GitHub Repos [NEW]**, Product Docs, Analytics, Git Updates, Settings

### Batch E: AI & Backend-Only (6 features)
Ask Legion, External Knowledge, Sprint Creation Gate, Daily Standup, Notification Service, Rate Limiting

### Per-Feature Audit (6 dimensions, current weights)

| Dim | Weight | What to Check |
|-----|--------|---------------|
| D1 Functional (0.27) | curl primary APIs, check 200 + real data, grep for placeholders |
| D2 Data Quality (0.18) | Check for nulls, stale timestamps, empty arrays, dummy data |
| D3 Integration (0.17) | Grep inbound/outbound links, check signal flow, WebSocket usage |
| D4 UX/Perf (0.16) | Grep for loading states, error handling, responsive classes |
| D5 Code Quality (0.12) | Check LOC, bare excepts, datetime safety, string enums, response_model |
| D6 Test Coverage (0.10) | Find test files, count test functions, check pass rate |

Formula: `score = D1*0.27 + D2*0.18 + D3*0.17 + D4*0.16 + D5*0.12 + D6*0.10`

---

## Phase 4: System Coherence Checks (~5 min)

1. **Data Flow Integrity**: Trace Sprint Creation -> Task Decomposition -> Execution -> Learning -> Grading pipeline via DB queries
2. **API Consistency**: Sample 10 endpoints for response_model usage, error format, naming conventions
3. **UX Consistency**: Check ErrorBoundary wrapping, loading state patterns, queryKeys.ts centralization
4. **Duplication Detection**: GitHub Repos vs External Knowledge (both have GitHub repo concepts), LLM Console vs LLM Review, Analytics vs Dashboard
5. **Dead Feature Scan**: Pages with no inbound links, endpoints returning only errors, 30+ days without modification + score <50

---

## Phase 5: Scoring & Report (~10 min)

1. Calculate per-feature weighted scores using dimension weights from `dimension_weights.json`
2. Calculate platform score (weighted average by feature importance)
3. Generate full scorecard ranked worst-first
4. Generate Top 10 highest-impact improvements (ranked by `(100-score) * importance`)
5. Compare against Run 5 baseline — flag regressions
6. Update knowledge files:
   - `audit_history.json` — append Run 6 results (prune to last 20)
   - `feature_catalog.json` — add GitHub Repos
   - `code_quality_baseline.json` — update metrics snapshot
   - `dimension_weights.json` — evolve weights based on movement patterns
   - `improvement_log.md` — append Run 6 summary
   - `improvement_patterns.md` — append new patterns discovered
   - `dead_features.json` — update if any new dead features found
   - `duplication_registry.json` — update with GitHub Repos vs External Knowledge overlap

---

## Critical Files

| File | Role |
|------|------|
| `frontend/src/App.tsx` | Route definitions (source of truth) |
| `frontend/src/components/Sidebar.tsx` | Navigation items |
| `backend/app/api/router_registry.py` | All 63+ router registrations |
| `frontend/src/lib/queryKeys.ts` | Centralized query keys |
| `.claude/skills/legion-platform-auditor/knowledge/*.json` | Knowledge files to update |
| `backend/app/api/endpoints/github_repos.py` | New feature to audit |
| `backend/app/services/github_repos_service.py` | New feature service |
| `frontend/src/pages/GitHubRepos.tsx` | New feature page |

---

## Verification

After audit completes:
1. `audit_history.json` has Run 6 entry with all 32 feature scores
2. Platform score computed and grade assigned
3. Trend arrows show direction vs Run 5 for every feature
4. GitHub Repos appears as new feature with full 6-dimension scoring
5. Code quality baseline updated with current metrics
6. Report printed to conversation with scorecard, improvements, and coherence summary
