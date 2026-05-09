# Legion Platform Audit — 2026-04-07

## Context

Second run of `/legion-platform-auditor` since baseline on 2026-04-04. Backend has been heavily worked between runs (Recovery-01, Sprint-Cleanup-01/02, Observe-03, Learn-14, Fix-50/51/52, plus brand-new Prompt Manager and GPU Manager features). This run grades all 28+ catalog features against 6 functional dimensions, detects newly added features missing from the catalog, and produces a top-impact remediation backlog.

**Plan-mode note:** This file IS the audit report itself. The skill normally writes 8 knowledge files (audit_history.json, dead_features.json, etc.) at Step 6 — those mutations are deferred until the user approves the audit and lifts plan mode.

## Audit Scope

- **Backend warm-up:** `/api/health` returned `healthy`, 36/36 background tasks alive (26 daemons + 10 oneshots), MiniMax active, sprint creation gate `safe`, agentic loops 0 active.
- **Endpoint inventory:** 542 total endpoints in `/openapi.json` (vs ~290 implied by catalog) — catalog is significantly stale.
- **Probed:** 60+ endpoints across all 28 catalogued features + 5 endpoints for the 2 newly-discovered features.
- **Pages read:** 15 frontend pages directly via Explore agent, 17 backend services profiled for code-quality metrics.
- **Git delta:** 80+ files changed in 4 commits since last audit (7da6e882, 2c080272, e747715b, 8436d16b — all "Nightly Sync" auto-commits sweeping the recent recovery work).

## Catalog Drift Detected

Two features exist in code but are **missing from `feature_catalog.json`** — auto-add candidates (importance 1.0):

| # | Feature | Type | Evidence | Status |
|---|---------|------|----------|--------|
| 29 | Prompt Manager | UI page (frontend/src/pages/PromptManager.tsx, 696 LOC) | Route `/prompt-manager` in App.tsx:141, 18 endpoints under `/api/prompt-manager/*`, 16 React hooks in `usePromptManager.ts` | **EXISTS in catalog as id=29 but NOT counted in `total_features`** |
| 30 | GPU Manager | Backend-only daemon | New project_id=14 ("GPU Manager"), router `/api/gpu-manager` registered, daemon `gpu_manager` running, migration 027 | **NOT in catalog** |

Additionally, the catalog references many stale endpoint paths from before the Clean-02 router consolidation. Examples (catalog → real):

- `/api/agents/dashboard/status` → `/api/agent-dashboard/status`
- `/api/episodic-memory/stats` → `/api/memory/episodes/stats`
- `/api/explainability/summary` → `/api/explain/summary`
- `/api/qa/test-gate/status` → `/api/testing/gate/{sprint_id}`
- `/api/test-feedback/metrics` → `/api/testing/metrics/{project_id}`
- `/api/alerts` → `/api/alerts/active`
- `/api/approvals` → `/api/safety/approvals`
- `/api/ollama/models` → `/api/ollama-manager/models`
- `/api/sprints/analytics/overview` → `/api/sprints/analytics/summary`
- `/api/model-performance/rankings` → `/api/grading/models/rankings`
- `/api/git/updates` → `/api/git/check-all` (and only POST)
- `/api/incidents` → `/api/incidents/{project_id}`
- `/api/autonomous/planning/status` → `/api/autonomous/status`
- `/api/autonomous/execute/recent` → `/api/sprints/executions/recent`

**Action:** when this plan is approved, regenerate `feature_catalog.json` from a script that walks `App.tsx` routes and the openapi.json paths, instead of hand-maintaining it.

## Code Quality Trend (Cross-Cutting Win)

Comparing to the 2026-04-04 baseline stored in `audit_history.json`:

| Anti-pattern | 2026-04-04 | 2026-04-07 | Δ | Status |
|---|---|---|---|---|
| `except:` (silent) | 128 | **4** | **-97%** | A+ — only 4 left in 2 files (`daily_sprint_generator_service.py`, `work_discovery_service.py`) |
| `datetime.now()` (no UTC) | 0 | **0** | 0 | A+ — clean |
| `\.status == "..."` (string enum) | 105 | **63** | -40% | B — concentrated in 32 files; biggest offenders are `annotation_queue_service.py` (4), `swarm.py` (3), `approval_service.py` (3), `nightly_git_sync_service.py` (4), `llm_console.py` (4), `ollama_manager_service.py` (5), `project_grader_service.py` (4) |
| `print(` (no logger) | 182 | **1** | **-99%** | A+ — only `async_subprocess.py:1` left (probably intentional) |

This is the single biggest win since the last audit. **Every feature gets a +5 to +15 point lift on D5 (code quality)** purely from this. The only outstanding issue is the 63 string-enum comparisons — and the death-loop history (Sprint-Cleanup-01) shows these are real silent bug factories, not cosmetic.

## Feature Scorecard (Worst → Best)

Weights: Functional 25% / Data 20% / Integration 20% / UX 15% / Code Quality 10% / Tests 10%. Importance multiplier from `feature_catalog.json` applied to platform-grade rollup only.

| Rank | Feature | Route / Endpoint | Score | Grade | D1 | D2 | D3 | D4 | D5 | D6 | Δ vs Apr 4 |
|------|---------|------------------|-------|-------|----|----|----|----|----|----|----|
| 1 | **Settings** | `/settings` | 50 | F | 60 | 50 | 35 | 55 | 80 | 15 | +2.5 |
| 2 | **Dependencies (Project)** | `/projects/:id/dependencies` | 51 | F | 55 | 60 | 45 | 45 | 75 | 15 | +6.5 |
| 3 | **Alerts** | `/alerts` | 53 | F | 65 | 30 | 45 | 55 | 80 | 20 | +4.5 |
| 4 | **Builder Mode** | (backend-only) | 56 | F | 65 | 70 | 35 | 45 | 75 | 15 | +10 |
| 5 | **Product Docs** | `/product-docs` | 56 | F | 70 | 55 | 40 | 70 | 75 | 20 | +1.2 |
| 6 | **Approvals** | `/approvals` | 58 | F | 65 | 30 | 40 | 65 | 75 | 70 | 0 |
| 7 | **Releases** (backend-only) | `/api/releases/*` | 58 | F | 65 | 65 | 35 | 50 | 75 | 55 | +4.5 |
| 8 | **Incidents** (backend-only) | `/api/incidents/{pid}` | 60 | D | 70 | 70 | 35 | 50 | 75 | 55 | +7.5 |
| 9 | **Ask Legion** | `/ask-legion` | 62 | D | 78 | 70 | 45 | 65 | 80 | 20 | +1.5 |
| 10 | **External Knowledge** | (backend-only) | 64 | D | 75 | 80 | 35 | 55 | 75 | 75 | **+16.7** |
| 11 | **Git Updates** | `/git` | 64 | D | 75 | 65 | 50 | 65 | 75 | 50 | +10.7 |
| 12 | **Ideas** | `/projects/:id/ideas` | 64 | D | 78 | 70 | 55 | 65 | 75 | 25 | +4 |
| 13 | **Project Detail** | `/projects/:id` | 67 | D+ | 72 | 75 | 75 | 55 | 80 | 40 | +1.5 |
| 14 | **Pull Requests** | `/pull-requests` | 67 | D+ | 70 | 50 | 55 | 75 | 80 | 80 | +4.7 |
| 15 | **Test Results** | `/test-results` | 67 | D+ | 75 | 65 | 50 | 65 | 80 | 70 | +5 |
| 16 | **Analytics** | `/analytics` | 68 | D+ | 80 | 70 | 45 | 70 | 80 | 45 | +12.5 |
| 17 | **LLM Review** (backend-only) | `/api/llm-review/*` | 68 | D+ | 80 | 80 | 40 | 50 | 80 | 35 | **+17** |
| 18 | **Execution Monitor** | `/execution` | 70 | C- | 78 | 75 | 65 | 70 | 75 | 65 | +5 |
| 19 | **Agent Dashboard** | `/agent-dashboard` | 70 | C- | 80 | 75 | 50 | 70 | 80 | 60 | +9 |
| 20 | **Autonomous Control** | `/autonomous` | 71 | C- | 80 | 75 | 55 | 80 | 75 | 65 | +4.2 |
| 21 | **Ollama Manager** | `/ollama-manager` | 72 | C- | 80 | 80 | 50 | 70 | 75 | 80 | +6.7 |
| 22 | **Service Health** | `/service-health` | 73 | C | 85 | 80 | 60 | 70 | 80 | 55 | +5 |
| 23 | **LLM Console** | `/llm-console` | 75 | C | 85 | 90 | 55 | 65 | 80 | 50 | +9.2 |
| 24 | **Project Plans** | `/projects/:id/plans` | 79 | C+ | 88 | 80 | 65 | 85 | 75 | 90 | +2.5 |
| 25 | **Learning Dashboard** | `/learning` | 80 | B- | 88 | 80 | 65 | 80 | 80 | 80 | **+14.2** |
| 26 | **Sprint Center** | `/projects/:id/sprints` | 80 | B- | 88 | 85 | 75 | 70 | 75 | 65 | **+10** |
| 27 | **Projects List** | `/projects` | 81 | B- | 90 | 85 | 80 | 70 | 80 | 65 | +4.7 |
| 28 | **Dashboard** | `/` | 82 | B- | 90 | 85 | 90 | 60 | 80 | 75 | +4.7 |
| 29 | **Prompt Manager** ⭐ NEW | `/prompt-manager` | 78 | C+ | 90 | 85 | 65 | 75 | 80 | 30 | NEW |
| 30 | **GPU Manager** ⭐ NEW | (backend-only) | 65 | D | 80 | 75 | 35 | 55 | 75 | 30 | NEW |

D1=Functional, D2=Data, D3=Integration, D4=UX, D5=Code Quality, D6=Test Coverage

### Platform Grade: **68/100 (D+)**

Up from 62/100 on 2026-04-04 (+6 points). The lift comes almost entirely from:
1. Universal D5 jump from the code-quality cleanup (+15-20 pts D5 across all features)
2. Major D1/D2 lifts on **External Knowledge** (now actually running — 57 repos, 109 KB entries), **LLM Review** (5753 calls reviewed, 3878 flagged), **Learning Dashboard** (30062 learnings, 1438 routing decisions, episodic memory live), and **Sprint Center** (sprint creation gate + first clean executions)
3. Two new well-built features (Prompt Manager + GPU Manager)

## Top 10 Highest-Impact Improvements

Ranked by `(100 − score) × importance`:

| # | Feature | Score | Action | Estimated Lift | Effort |
|---|---|---|---|---|---|
| 1 | **Sprint Center** (1.5x) | 80 | Replace the 63 remaining string-enum comparisons concentrated in `swarm.py`, `agent_swarm_service.py`, `sprint_orchestrator.py` etc. — these are silent bug factories per Sprint-Cleanup-01 history. | +6 → 86 | M |
| 2 | **Dashboard** (1.5x) | 82 | Fix `/api/grading/overview` 404 (catalog says it exists, real path is `/api/grading/projects/{id}/grade` or `/api/grading/latest`). Add UX skeletons for the brain-decisions panel (D4 = 60). | +5 → 87 | S |
| 3 | **Autonomous Control** (1.5x) | 71 | Surface the `sprint_creation_mode` gate state in the UI (currently visible only in `/api/health`). Add a one-click toggle. | +7 → 78 | S |
| 4 | **Alerts** (1.0x) | 53 | The endpoint returns `[]`. Either seed default alert rules from `docker/prometheus/alert_rules.yml` or rename the page to "Alert Rules" with config UI. | +12 → 65 | M |
| 5 | **Settings** (0.7x) | 50 | Page is a placeholder (390 LOC, mostly health display). Add 3 real preferences: theme, notifications opt-in, default project. Or rename to "System Info" and accept 70/100 as the ceiling. | +15 → 65 | S |
| 6 | **Builder Mode** (0.7x) | 56 | `/api/projects/specs` returns 7KB of real data but **there is no UI**. Wire a `/builder` page that lists pending specs and lets the user confirm/edit. | +12 → 68 | L |
| 7 | **Dependencies (Project)** (0.7x) | 51 | 24-LOC wrapper. Real data exists at `/api/dependency-reviews/{id}/latest`. Inline the full table with diff vs latest scan, severity bands. | +12 → 63 | M |
| 8 | **LLM Console** (1.2x) | 75 | D6 = 50 — write `test_llm_console_service.py`. Add D4 polish: persistent column widths, virtualization already there. | +5 → 80 | M |
| 9 | **Learning Dashboard** (1.2x) | 80 | New Reasoning tab is wired but timeline polling could be tightened. Add filter UI for the 7 kinds (currently filter-only via URL). | +5 → 85 | S |
| 10 | **Approvals** (1.0x) | 58 | Endpoint returns `[]`. The autonomy slider is the only real interaction. Either auto-create demo approval rows for empty projects, or add a "What is this page for?" explainer + link to safety config. | +10 → 68 | S |

## System Coherence

| Check | Status | Notes |
|---|---|---|
| **Data Flow Integrity** | **PASS** | Verified pipeline live: Sprint creation gate → orchestrator → swarm/executor (132 tasks completed in 24h) → learning aggregator (30062 learnings) → grading (rich rankings) → reasoning capture (Observe-03 wired all 7 kinds). First time the full loop is observably closed since baseline. |
| **API Consistency** | **PARTIAL** | Multiple envelope formats: some return raw arrays (`/api/alerts/active` = `[]`), some return wrapped objects (`/api/pull-requests/` = `{total:0, pull_requests:[]}`). Error envelope is consistent (`{error,message,status_code,request_id,timestamp}`). 4 collection endpoints (`/api/sprints`, `/api/learnings`, `/api/pull-requests`, `/api/releases`) require trailing slash and 307 redirect. |
| **UX Consistency** | **PARTIAL** | Loading states inconsistent: SprintCenter/LLMConsole/PromptManager use Skeleton (rich), Alerts/Approvals/AskLegion/GitUpdates use 0-1 spinner. ErrorBoundary universal (good), but inline error display uses 3 different patterns (`QueryErrorFallback`, `error &&`, `EmptyState`). Recommendation: standardize on `QueryErrorFallback` + `EmptyState`. |
| **Duplication Level** | **LOW-MED** | See section below. |
| **Dead Features** | **3** | Settings, Dependencies (thin wrapper), and the **Builder Mode** (no UI consumer despite working backend). External Knowledge previously flagged dead is now alive (57 repos discovered). |

### Cross-Service Duplication Audit

| Pair | Overlap | Recommendation |
|------|---------|----------------|
| Execution Monitor vs Sprint Center > Tasks tab | ~70% — both render task execution lists | Promote SprintCenter as canonical, redirect `/execution` to filter view |
| Analytics vs Dashboard | ~30% — both show sprint trends | Keep both: Dashboard = today, Analytics = historical |
| Agent Dashboard vs Learning Dashboard > Decisions | ~20% — both show agent activity | Distinct: Agent = topology/health, Learning = decisions/explainability |
| LLM Console vs LLM Review (backend) | ~40% — both query `llm_call_details` | Build a `/llm-review` UI page that consumes `/api/llm-review/*` instead of duplicating filters in LLM Console |
| Service Health vs Dashboard daemon-status | ~50% — both list daemons | Keep, but link Service Health as authoritative |
| Alerts vs Approvals | ~10% — different domains | Keep distinct, but unify into a single "Inbox" sidebar group |
| `release_service.py` (204 LOC) vs `incident_service.py` (168 LOC) | ~25% — both lifecycle CRUD with severity | Acceptable — different domains |

Catalog says target backend services <80, current 126. No new dead services found this run; the recent commits already removed 14 dead files (commit `e830e52b`).

## Dead Feature Report

| Feature | Route | Status | Issue | Recommendation |
|---|---|---|---|---|
| **Settings** | `/settings` | DEAD-LITE | 390 LOC display-only, zero user prefs | Rename to "System Info" or add 3 preferences (effort: S) |
| **Dependencies (Project)** | `/projects/:id/dependencies` | DEAD-LITE | 24-LOC wrapper, real data exists upstream | Inline the full report (effort: M) |
| **Builder Mode** | (no UI) | NO-UI | Backend works (`/api/projects/specs` = 7KB real data), no consumer | Create `/builder` page (effort: L) |
| ~~External Knowledge~~ | ~~backend-only~~ | **REVIVED** | Was dormant on 4/4. Now live: 57 repos, 109 KB entries, 6 feeds, 52 articles, 37 cross-refs | Remove from dead list |
| **GPU Manager** | (no UI) | NO-UI | Backend daemon running (project_id=14), 6 endpoints, no frontend consumer | Add a card to Service Health page or build standalone `/gpu` (effort: M) |

## Live Data Snapshots (selected highlights)

```
GET /api/health/daily-standup
  sprints: 36 completed / 18 failed / 1 active in 24h
  tasks: 132 completed / 8 failed / 0 stuck / 0 running
  project_health: GPU Manager 48, ADA 66, Legion 69, Zero 83.5
  llm: minimax provider, 7 calls/60s, queue depth 0, breaker closed

GET /api/llm-console/stats
  active_count: 1
  today_total: 4697 (3882 completed / 815 failed)
  today_avg_latency_ms: 12103
  today_flagged_count: 21
  today_avg_review_score: 13.4
  today_with_improvement: 109

GET /api/learnings/stats
  total_learnings: 30062
  high_impact_count: 17363
  type_distribution:
    sprint_summary 498 / process 42 / success 7549 / code_change 4 /
    grade_delta 575 / model_performance 16759 / estimation 3 /
    pattern 740 / failure 3155 / grade_dimension 720 / routing 17

GET /api/llm-review/stats
  total_reviewed: 5753   (avg_score: 40)
  total_flagged: 3878    (incomplete 4376, wrong_format 2864, low_effort 979,
                          hallucination 642, off_topic 123, security_risk 51)
  total_pending: 1275

GET /api/external-knowledge/stats
  repos_discovered: 57   repos_scanned: 57
  knowledge_entries_total: 109
  feeds_configured: 6   articles_ingested: 52
  cross_references_created: 37
  last_cycle_at: 2026-04-07T15:47:53

GET /api/explain/summary (routing telemetry)
  total_decisions: 1438   avg_confidence: 0.812
  learned_ratio: 1.0      db_outcomes: 1438
  best models: minimax-m2 (94.1%), primary (91.7%), plan-generated (95%)
  worst: auto (62%)

GET /api/agent-dashboard/agents
  All 36 agents return rich JSON: capabilities, color, status=idle,
  metrics{executions_24h, success_rate, avg_duration_ms}, last_active
```

## Critical Path Files (verified read-only)

- [frontend/src/App.tsx:101-144](frontend/src/App.tsx#L101-L144) — 24 active routes (12 redirects)
- [backend/app/api/router_registry.py:1-120](backend/app/api/router_registry.py) — all 60 routers
- [backend/app/services/sprint_creation_gate.py](backend/app/services/sprint_creation_gate.py) — Sprint-Cleanup-02 universal gate
- [backend/app/services/learning_aggregator_service.py](backend/app/services/learning_aggregator_service.py) — 1476 LOC, 6 Prometheus metrics, 48 tests
- [backend/app/services/autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) — 3488 LOC, 35 datetime calls, 13 fresh-session opens, only 8 tests (highest test debt)
- [backend/app/services/llm_review_service.py](backend/app/services/llm_review_service.py) — 891 LOC, 4 Prometheus metrics, fixed `response_text` NameError
- [.claude/skills/legion-platform-auditor/knowledge/feature_catalog.json](.claude/skills/legion-platform-auditor/knowledge/feature_catalog.json) — STALE: 13 endpoint paths broken, 2 features missing

## Recommendations Summary

### Immediate (this week, all S effort)
1. **Auto-regenerate `feature_catalog.json`** from `App.tsx` + `openapi.json` so the catalog never goes stale again. Add `gpu_manager` and bump `total_features` to 30.
2. **Wire the sprint creation gate UI** in Autonomous Control — single button to flip `paused / safe / on`, reading `GET /api/sprints/creation-mode` (added in Sprint-Cleanup-02).
3. **Fix the 4 remaining `except:` blocks** in `daily_sprint_generator_service.py` and `work_discovery_service.py` to log warnings instead of swallowing.
4. **Standardize loading states** across Alerts, Approvals, AskLegion, GitUpdates to use Skeleton + EmptyState + QueryErrorFallback.

### Short-term (next sprint)
5. **Sweep the 63 string-enum comparisons** — same bug class as Sprint-Cleanup-01's "agent_swarm string enum bug". Files in priority order: `ollama_manager_service.py` (5), `annotation_queue_service.py` (4), `nightly_git_sync_service.py` (4), `llm_console.py` (4), `project_grader_service.py` (4).
6. **Build the `/llm-review` UI page** that consumes the existing 6-endpoint `/api/llm-review/*` API — backend has 5753 reviewed calls and 3878 flagged that no human can see.
7. **Builder Mode `/builder` UI** — list pending specs from `/api/projects/specs`, allow confirm/edit/delete.
8. **Dependencies tab full inline view** — replace the 24-line wrapper with a real diff view.

### Long-term (next milestone)
9. **Decompose `autonomous_sprint_executor.py`** (3488 LOC) — research already done per memory notes (6 extractable services), risk has been the unknown of session corruption, but Recovery-01 and Fix-51 stabilized that path.
10. **Settings page** — pick a direction: real preferences (theme, notifications, defaults) or rename to "System Info" and accept that ceiling.
11. **Catalog test coverage** for high-debt services: `autonomous_sprint_executor` (~8 tests on 3488 LOC), `unified_llm_service` (1655 LOC), `agentic_loop_service` (1647 LOC), `plan_service` (1375 LOC).

## Verification

To re-run this audit (read-only) after any of the above are applied:

```bash
# Backend warm-up
curl -sf --max-time 5 http://localhost:8005/api/health

# Spot-check the lifted features
curl -s http://localhost:8005/api/external-knowledge/stats | python -m json.tool
curl -s http://localhost:8005/api/llm-review/stats | python -m json.tool
curl -s http://localhost:8005/api/sprints/creation-mode | python -m json.tool

# Re-run code-quality grep
grep -rcn "except:" backend/app | grep -v ":0$" | wc -l       # target: 0
grep -rcn "datetime\.now()" backend/app | grep -v ":0$"        # target: 0
grep -rcn "\.status == ['\"]" backend/app | grep -v ":0$" | wc -l   # target: <20

# Confirm all 36 daemons alive
curl -s http://localhost:8005/api/health | python -c "import sys,json; d=json.load(sys.stdin); print('alive:', d['background_tasks']['alive'], '/', d['background_tasks']['total'])"
```

When the audit looks healthy and the user lifts plan mode, the skill should perform Step 6 (Update Knowledge Files):
1. Append today's run to `audit_history.json` (prune to last 20 runs)
2. Add `prompt_manager` and `gpu_manager` to `feature_catalog.json`
3. Update `dead_features.json` (remove External Knowledge, add GPU Manager NO-UI)
4. Update `code_quality_baseline.json` to today's counts
5. Append run notes to `improvement_log.md`
6. Bump `dimension_weights.json` slightly toward D1/D5 (the dimensions that moved this run)
