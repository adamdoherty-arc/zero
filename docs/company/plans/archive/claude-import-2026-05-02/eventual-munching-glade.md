# Legion Platform Audit — Run #8

## Context

This is a scheduled run of the `/legion-platform-auditor` skill. The skill grades **functional quality** of every Legion feature/page/backend capability across 6 dimensions and is designed to complement watchdog (operational health) and deep-review (system code quality).

**Why now**: Last full audit was 2026-04-24 (run #7, platform_grade=C-, 32 features). Since then, 152 files changed across 5 commits — including Fix-47 (13 fixes, OllamaManager page removed), Plans Cleanup, Audit-Remediation-01 (sprint quality grader scoping fix, LearningEngine swarm wire, LLM review sanitizer), Learn-18/19 activation (per-source provider routing), and a new Legion-managed `llm-ops` project. Significant catalog drift expected.

**Goal**: Produce a fresh per-feature scorecard, identify the highest-impact S/M-effort fixes that can land this session, and create sprints (project_id=1) for L-effort items.

## Catalog Drift Discovered (Step 1.5 preview)

Comparing `feature_catalog.json` to current `frontend/src/App.tsx` routes:

**Removed** (1):
- `OllamaManager` (#13) — page deleted in Fix-47/F12, route now `<Navigate to="/llm-console" />`. Drop from catalog.

**Promoted** backend-only → UI page (3):
- `BuilderMode` (#24) — now at `/builder` (Builder.tsx). Re-grade as a UI feature.
- `Releases` (#25) — now at `/releases` (Releases.tsx). Re-grade as a UI feature.
- `LLMReview` (#28) — now at `/llm-review` (LLMReview.tsx). Re-grade as a UI feature.

**Newly discovered** (2 — never catalogued):
- `GitHubRepos` at `/github-repos` (GitHubRepos.tsx) — needs cataloging, importance 1.0.
- `PromptManager` at `/prompt-manager` (PromptManager.tsx) — needs cataloging, importance 1.2x (Learn-18/19 control panel).

Net catalog: 32 → 32 (28 UI + 4 backend) after `-1 OllamaManager + 2 new`.

## Plan

### Phase A — Audit (read-only)

1. **Pre-warm backend** (Step 0.5): hit `/api/health`, `/api/health/daily-standup`, `/api/projects`, `/api/llm/health` to prevent cold-start D2 failures. Already verified backend is `healthy`.
2. **Update `feature_catalog.json`** with the drift above (this is the only catalog write before grading; per Step 1.5 of the skill it's allowed during auto-discovery).
3. **Audit every feature on 6 dimensions** (per Step 2 of the skill; default weights: D1=25, D2=20, D3=20, D4=15, D5=10, D6=10):
   - **D1 Functional Completeness**: page loads, sub-tabs render, primary GET endpoints return 200 with data, no `Coming Soon|TODO|placeholder|Lorem|Not implemented` strings.
   - **D2 Data Quality**: real (not stubbed/empty) responses, no `demo|example|test_|sample` hardcoded values, recent timestamps.
   - **D3 Integration**: inbound/outbound link counts, WebSocket subscriptions, deep-link wiring.
   - **D4 UX/Performance**: loading states, error handling, responsive classes, <3s API.
   - **D5 Code Quality**: anti-pattern grep on owning service + page (`except:`, `datetime.now()`, `.status == "..."`, file size, bare prints).
   - **D6 Test Coverage**: backend test file exists/passes + count, frontend test file exists.
   - Process **OPERATIONS first**, then PROJECTS, AI ASSISTANT, SYSTEM, BACKEND-ONLY.
   - **Skip rule**: per `--quick` mode, but since 152 files changed touching most features, ALL features get re-audited this run.
4. **Coherence checks** (Step 4):
   - 4a Data flow: Sprint Creation → Decomposition → Routing → Execution → Learning → Grading.
   - 4b API consistency: sample 10 endpoints for envelope/error/casing/pagination.
   - 4c UX consistency: 5+ pages — loading/empty/error patterns.
   - 4d **Duplication detection**: re-check ExecutionMonitor vs SprintCenter, Analytics vs Dashboard, AgentDashboard vs LearningDashboard, LLMConsole vs LLMReview, Alerts vs Approvals, ServiceHealth vs Dashboard. Plus check if `llm-ops` project (new) overlaps with LLMConsole/LLMReview.
   - 4e **Dead-feature scan**: any feature with zero inbound nav + erroring APIs + score <50.

### Phase B — Report

5. Render the standard 5-section report inline (full scorecard ranked worst-first, top-10 highest-impact improvements, duplication report, dead-feature report, coherence summary).
6. Compare to run #7 (2026-04-24) — improving/regressing/stale per feature.

### Phase C — Remediation (Step 8 of the skill — IS IN SCOPE, not deferred)

Per the skill's safety rule #1: "Never skip fixes to save time — the whole point of this skill is fixing, not just reporting."

7. **Triage** every recommendation by S/M/L effort.
8. **Apply S/M fixes immediately**:
   - D5 anti-pattern fixes (bare excepts → typed except + logger; `datetime.now()` → `datetime.now(UTC)`; `.status == "completed"` → `TaskStatus.COMPLETED`) on the worst offenders.
   - D6 missing tests: write `backend/tests/services/test_*.py` for services with D6<30 covering the worst-graded features. Run `python -m pytest <file> -v` to confirm pass before committing.
   - D3 integration gaps: wire deep-link `<Link>` between feature pairs that should connect (e.g. SprintCenter sprint card → ExecutionMonitor for that sprint's most recent execution).
   - **False-positive gate** (skill rule #10): grep matches verified against actual source lines before any edit.
9. **Rebuild Docker after backend/frontend edits** (`docker-compose build legion-backend legion-frontend && docker-compose up -d`) per CLAUDE.md "Always Test Your Work".
10. **L-effort** items → create sprints in Legion DB at **project_id=1** (per CLAUDE.md, post-wipe 2026-04-22) with the correct category prefix (`Quality-NN`, `Test-NN`, `FE-NN`, `API-NN`).

### Phase D — Knowledge persistence

11. Append run #8 to `audit_history.json` (prune to last 20 runs).
12. Update `code_quality_baseline.json` post-remediation counts.
13. Update `dead_features.json`, `duplication_registry.json`.
14. Append run summary to `improvement_log.md` and act-on-recommendations to `improvement_patterns.md`.
15. **Evolve `dimension_weights.json`**: +0.5% to dimensions where I acted on findings, -0.25% to ignored, normalize.

## Critical Files

**Read-only this run** (audit phase):
- `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx` — routing + nav inventory.
- `backend/app/api/router_registry.py`, `backend/main.py` — router registrations.
- `frontend/src/pages/*.tsx` (32 files) — D1/D4/D5 grep sources.
- `backend/app/services/*.py` — D5 grep sources.
- `backend/tests/**/*.py`, `frontend/src/**/__tests__/*.tsx` — D6 inventory.

**May edit during remediation** (Phase C — only S/M effort):
- Any service file with bare excepts / unsafe datetime / string enums (top 5 offenders).
- New `backend/tests/services/test_*.py` files for low-D6 features.
- `frontend/src/pages/*.tsx` — minimal deep-link additions.

**Knowledge files updated** (Phase D):
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/audit_history.json`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/feature_catalog.json`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/code_quality_baseline.json`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/dead_features.json`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/duplication_registry.json`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/dimension_weights.json`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/improvement_log.md`
- `c:/code/Legion/.claude/skills/legion-platform-auditor/knowledge/improvement_patterns.md`

## Verification

After remediation, the audit is verified end-to-end by:

1. **Backend rebuild + health re-check**: `docker-compose build legion-backend && docker-compose up -d && curl http://localhost:8005/health` returns `healthy`.
2. **Per-fix verification**: every code edit followed by either a curl on the affected endpoint (backend) or a re-grep showing the anti-pattern count dropped (D5), or `pytest` showing new tests passing (D6).
3. **Score delta**: re-run only the affected dimensions for fixed features, compute post-remediation platform grade, compare to run #7's C- baseline.
4. **Sprint visibility**: any L-effort sprint shows up in `SELECT id, name, status FROM sprints WHERE project_id=1 ORDER BY id DESC LIMIT 5`.
5. **History persistence**: `python -c "import json; d=json.load(open('audit_history.json')); print(d['runs'][-1]['date'], len(d['runs']))"` shows today's date and 8 runs.

## Out of Scope

- Browser-based UI verification (skill rule #3 — uses curl + grep, not Playwright). UI bugs surfaced will be noted but visual verification deferred to `/qa` if any are landed.
- Watchdog / deep-review knowledge files — not touched.
- Running the full backend pytest suite — only tests for newly written files this session.
- The 41 pre-existing test failures noted in CLAUDE.md (sprint manager status tests, LLM review mocks) — not in scope unless directly tied to a graded dimension.
