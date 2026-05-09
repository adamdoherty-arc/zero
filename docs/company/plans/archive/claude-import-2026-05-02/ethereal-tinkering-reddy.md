# Plan: Upgrade Legion Platform Auditor + Improve Ada Platform Auditor

## Context

Legion's `/legion-deep-review` skill grades 10 broad system dimensions but lacks the per-feature granularity, adaptive learning, dead feature detection, and duplication analysis that Ada's `/platform-auditor` has. Meanwhile, Ada's skill could benefit from code quality checks, test coverage mapping, and auto-discovery that Legion already does well.

**Goal**: Create a new `/legion-platform-auditor` skill matching Ada's per-feature approach (adapted for Legion's domain), and add 5 improvements to Ada's existing skill.

---

## Part 1: New Legion `/legion-platform-auditor` Skill

### Files to Create

#### 1. `c:\code\Legion\.claude\skills\legion-platform-auditor\SKILL.md` (NEW)

Full skill definition with:

**28 Auditable Features** organized by sidebar section:
- **AI Assistant (1)**: Ask Legion
- **Operations (10)**: Dashboard, LLM Console, Autonomous Control, Execution Monitor, Agent Dashboard, Learning Dashboard, Pull Requests, Test Results, Alerts, Approvals
- **System (6)**: Service Health, Ollama Manager, Product Docs, Analytics, Git Updates, Settings
- **Projects (6 nested)**: Projects List, Project Detail, Project Plans, Sprint Center, Ideas, Dependencies
- **Backend-Only (5)**: Builder Mode, Releases, Incidents, External Knowledge, LLM Review

**6 Dimensions** (adapted — Competitive Edge replaced with Test Coverage):
1. Functional Completeness (25%) — pages load, APIs return data, no placeholders
2. Data Quality (20%) — real data, fresh timestamps, no orphaned records
3. Integration (20%) — cross-links, data flow, WebSocket updates
4. UX/Performance (15%) — loading states, error handling, responsive
5. Code Quality (10%) — no bare excepts, no datetime bugs, no string enums
6. Test Coverage (10%) — tests exist per feature, pass rate

**Feature Importance Weights**:
- 1.5x: Dashboard, Sprint Center, Autonomous Control (core loop)
- 1.2x: Projects, Agent Dashboard, Learning Dashboard, LLM Console, Service Health
- 1.0x: All other Operations
- 0.7x: System pages + backend-only

**7 Modes**:
- `/legion-platform-auditor` — Full audit all 28 features (~20 min)
- `/legion-platform-auditor --quick` — Only changed features since last run
- `/legion-platform-auditor --section {AI|OPERATIONS|SYSTEM|PROJECTS|BACKEND}` — One section
- `/legion-platform-auditor --feature {name}` — Single feature deep dive
- `/legion-platform-auditor --coherence` — System coherence checks only
- `/legion-platform-auditor --test` — Focus on test coverage per feature
- `/legion-platform-auditor --grade` — Just display current grades

**9 Execution Steps**:
0. Load previous knowledge files
1. Detect changes since last audit (git log mapping)
2. Audit each feature (28 features x 6 dimensions)
3. Calculate per-feature grades (weighted sum)
4. System coherence checks (5 cross-cutting analyses)
5. Generate full report (scorecard, improvements, dead features, duplication)
6. Update knowledge files (8 files)
7. Self-improvement analysis (trend detection, weight evolution)

**System Coherence Checks** (Legion-specific):
1. Data Flow: Sprint Creation → Decomposition → Agent Routing → Execution → Learning → Grade
2. API Consistency: response envelope, error format, pagination
3. UX Consistency: loading/error/empty patterns
4. Duplication: 126 services vs 80 target, overlapping routers
5. Dead Features: no inbound links, all errors, stale 30+ days

**Safety Rules** (same as Ada): read-only, timeout curls, carry forward on error, cap history at 20 runs

#### 2. Knowledge files (8 new, seeded empty/initial):

- `knowledge/audit_history.json` — `{"runs": [], "schema_version": 1, "max_runs": 20}`
- `knowledge/feature_catalog.json` — Full 28-feature catalog seeded from exploration data (routes, hooks, APIs, importance, sub-tabs, test files)
- `knowledge/dimension_weights.json` — Default 6 weights (0.25, 0.20, 0.20, 0.15, 0.10, 0.10)
- `knowledge/dead_features.json` — `[]`
- `knowledge/duplication_registry.json` — `[]`
- `knowledge/improvement_patterns.md` — Empty template
- `knowledge/improvement_log.md` — Empty template
- `knowledge/code_quality_baseline.json` — Seed from watchdog's existing baseline data

### Key Differences from Ada's Version

| Aspect | Ada | Legion |
|--------|-----|--------|
| D6 dimension | Competitive Edge | Test Coverage |
| Feature count | 37 UI features | 28 (23 UI + 5 backend-only) |
| Port | localhost:8006 | localhost:8005 |
| API prefix | /api/ | /api/ |
| Auto-discovery | Hardcoded catalog | Catalog + auto-discovery from App.tsx + router_registry.py |
| Code quality | Not checked | D5 checks bare excepts, datetime bugs, string enums, large files |

---

## Part 2: Improvements to Ada's `/platform-auditor`

### File to Edit: `c:\code\ada\.claude\skills\platform-auditor\SKILL.md`

**5 Changes**:

1. **Step 0.5: Backend Pre-check** (NEW step after Step 0)
   - Before auditing, verify backend is warm: `curl -s --max-time 5 http://localhost:8006/api/health`
   - If cold, hit 3 heavy endpoints to warm caches (dashboard, portfolio, market)
   - Wait 5s, then proceed — prevents false D2 failures from cold start timeouts
   - This addresses the Run 3 lesson: "D2 scores systematically wrong due to backend timeouts"

2. **D5 Optimization → D5 Code Quality + Optimization** (EXPAND dimension)
   - Keep existing D5 checks (duplication, dead code, complexity, bundle impact)
   - ADD: per-feature backend code quality checks:
     - `grep -c "except:" backend/routers/{router}.py` (bare excepts)
     - `grep -c "TODO\|FIXME\|HACK" backend/routers/{router}.py`
     - `grep -c "print(" backend/services/{service}.py` (should use logger)
     - Function > 100 LOC count
   - Scoring: -3 per bare except, -2 per TODO, -5 per print, -5 per 100+ LOC function

3. **Test Coverage Mapping** (ADD to Step 2 per-feature audit)
   - For each feature, check if test file exists: `backend/tests/test_{feature_service}.py`
   - Count test functions: `grep -c "def test_\|async def test_" backend/tests/test_{service}.py`
   - Add to per-feature data: `"test_files": N, "test_functions": N`
   - Factor into D1 scoring: -10 if zero test coverage for a critical feature

4. **History Pruning** (EDIT Step 7)
   - Change "Never truncate audit_history.json" → "Cap at last 20 runs, prune oldest on append"
   - Add pruning logic description: keep only `runs[-20:]` after each append
   - Update Safety Rule 7 from "always append" to "append then prune to 20"

5. **Feature Catalog Auto-Discovery** (ADD Step 1.5)
   - After loading catalog, scan `frontend/src/App.tsx` for route definitions
   - Compare discovered routes to `feature_catalog.json`
   - Flag any routes NOT in catalog as "NEW — needs cataloging"
   - Auto-add with default importance 1.0 and empty sub-tabs
   - Log discovery in improvement_log.md

---

## Implementation Order

1. Create Legion `SKILL.md` (largest deliverable)
2. Create Legion 8 knowledge files (seeded)
3. Edit Ada `SKILL.md` (5 targeted edits)

## Verification

After implementation:
- Run `/legion-platform-auditor --grade` to verify the skill loads and runs
- Check all 8 knowledge files are valid JSON/MD
- Verify Ada's SKILL.md has all 5 improvements integrated cleanly
- Confirm old `/legion-deep-review` still exists untouched
