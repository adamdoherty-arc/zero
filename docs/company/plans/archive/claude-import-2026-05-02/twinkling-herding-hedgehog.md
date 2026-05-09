# Plan: Fix Plan Archive UX + Ollama Manager Plan Cleanup

## Context

Two related issues on `http://localhost:3005/projects/13/plans` (Ollama Manager virtual project):

1. **"Plans don't seem to archive when I archive them."** The user clicks the red Archive icon, confirms in the dialog, and the row stays visible on the "All" tab with no obvious change. The backend DOES persist `status=ARCHIVED` (verified via [plan_service.py:276-284](backend/app/services/plan_service.py#L276-L284)), but the UX is confusing because (a) the "All" tab still shows archived plans and (b) the React Query invalidation may have stale-cache edge cases.

2. **Ollama Manager has the wrong default plans seeded.** [plan_service.py:835-916](backend/app/services/plan_service.py#L835-L916) seeds these 4 plan types for *every* project regardless of type:
   - `project_review` ✓ (correct for Ollama Manager)
   - `docker_logs_review` ✗ (Ollama runs on the host — there are no Ollama Docker logs to review)
   - `dependency_check` ✗ (virtual project — no `requirements.txt`/`package.json`)
   - `ollama_management` ✓ (only seeded when `key == "ollama_manager"` — this one is correct)

   The user wants Ollama Manager to instead have:
   - **Ollama version check** — confirm the Ollama binary itself is on the latest release (currently *no* code anywhere queries `/api/version` or compares against the GitHub release feed)
   - **Ollama model update check** — confirm installed models are up to date (the `_grade_ollama_management()` grader at [project_grader_service.py:559-713](backend/app/services/project_grader_service.py#L559-L713) ALREADY does this — it just needs to be the only thing the user sees, plus the binary version dimension added)

The intended outcome: a clean Ollama Manager Plans tab with exactly the plans that make sense for a virtual Ollama-monitoring project, an obviously-working Archive button, and a way to clean up the existing wrong plans without manual SQL.

## Investigation findings (already done — no need to redo)

### Plan archive flow (already verified in code, not buggy at the DB layer)

1. [ProjectPlans.tsx:295](frontend/src/pages/ProjectPlans.tsx#L295) — Archive button → `onDeletePlan(plan)` → `setDeletingPlan(plan)`
2. [ProjectPlans.tsx:848-867](frontend/src/pages/ProjectPlans.tsx#L848-L867) — `DeletePlanDialog` confirmation
3. [ProjectPlans.tsx:912-918](frontend/src/pages/ProjectPlans.tsx#L912-L918) — `handleDeleteConfirm()` calls `deletePlan.mutate(deletingPlan.id)`
4. [usePlans.ts:411-426](frontend/src/hooks/usePlans.ts#L411-L426) — `useDeletePlan()` calls `DELETE /plans/{id}`, on success invalidates `qk.plans.all` and `qk.plans.latestGrades`
5. [plans.py:210-216](backend/app/api/endpoints/plans.py#L210-L216) — `DELETE /plans/{plan_id}` → `service.delete_plan(plan_id)`
6. [plan_service.py:276-284](backend/app/services/plan_service.py#L276-L284) — sets `plan.status = PlanStatus.ARCHIVED` and commits ✓ (works)
7. [plan_service.py:189-195](backend/app/services/plan_service.py#L189-L195) — `get_plans()` returns ALL plans regardless of status (intentional — frontend filters via tabs)

**Why the user perceives the bug:** The "All" tab is the active tab in the screenshot, and even after archive succeeds the row remains visible there with just a small status badge change. The visible "archived" badge is grey on dark background and easy to miss. The chip counts (`Active (3) → (2)`, `Archived (2) → (3)`) DO update on a real refetch, but if React Query's prefix-match invalidation is interrupted by `staleTime` configuration on the `usePlans(projectId)` query, even the badge change can be delayed.

The agent that explored this also flagged a possible query-key prefix-match concern. React Query v5's `invalidateQueries({ queryKey: ['plans'] })` *does* prefix-match `['plans', 13]` by default — so the invalidation is technically correct — BUT the safer fix is to be explicit so future query-key changes don't silently break it.

### Ollama Manager service capabilities (already exist)

[ollama_manager_service.py](backend/app/services/ollama_manager_service.py) (800 lines) already has:
- ✓ `sync_model_inventory()` — `GET /api/tags`
- ✓ `check_for_updates()` — local digest comparison via `POST /api/show` ([ollama_manager_service.py:220-280](backend/app/services/ollama_manager_service.py#L220-L280))
- ✓ `pull_model(model_name)` — `POST /api/pull`
- ✓ `get_health()` — connectivity, running models, VRAM
- ✓ `generate_daily_report()` — daemon-run daily LLM-analyzed report
- ✗ **NO `check_ollama_version()`** — needs to be added

[project_grader_service.py:559-713](backend/app/services/project_grader_service.py#L559-L713) already has `_grade_ollama_management()` with 4 dimensions (Model Freshness, Performance Health, Configuration Quality, Disk Efficiency).

## Recommended approach

### Part A — Fix plan archiving UX (frontend only, low risk)

1. **Make `useDeletePlan()` invalidation explicit and bulletproof.** [usePlans.ts:411-426](frontend/src/hooks/usePlans.ts#L411-L426) currently invalidates `qk.plans.all`. Change to invalidate using a `predicate` that matches any query key whose first element is `'plans'` OR `'plans-latest-grades'` OR `'plans-sparklines'`. This guarantees both the global `['plans']` cache AND the per-project `['plans', projectId]` cache get refetched, regardless of whether the user is on the global Plans page or a project-specific tab.

2. **Improve the "after archive" visual feedback.** In [ProjectPlans.tsx:912-918](frontend/src/pages/ProjectPlans.tsx#L912-L918) `handleDeleteConfirm`, on success **also switch the active filter to `'archived'`** (or to `'active'` if currently on `'all'`) so the user sees their action take effect immediately. The toast already says "Plan archived" but the row appearing in a different tab is the obvious confirmation.

3. **Make the archived status badge more visible** in the row. [ProjectPlans.tsx](frontend/src/pages/ProjectPlans.tsx) renders the status pill — bump archived rows to `opacity-60` so they look visibly "off" when shown on the All tab.

### Part B — Make Ollama Manager seed only the right plans

4. **Add a virtual-project gate to `seed_default_plans()`.** [plan_service.py:835-916](backend/app/services/plan_service.py#L835-L916) currently seeds `docker_logs_review` and `dependency_check` for every project. Wrap these two seed blocks in `if not (project.path or "").startswith("/virtual/"):`. This makes virtual projects (Ollama Manager id=13, GPU Manager id=14) skip both plans automatically on next bootstrap.

5. **Add an Ollama version check to `OllamaManagerService`.** New method `check_ollama_version() -> dict[str, Any]` in [ollama_manager_service.py](backend/app/services/ollama_manager_service.py):
   - Calls `GET http://localhost:11434/api/version` for the running version
   - Calls `GET https://api.github.com/repos/ollama/ollama/releases/latest` for the latest release tag (with 5s timeout, cached for 6h to avoid GitHub rate limits)
   - Returns `{"current": "0.X.Y", "latest": "0.X.Z", "is_outdated": bool, "release_url": str}`
   - On any error (Ollama down, GitHub unreachable), returns `{"current": None, "latest": None, "is_outdated": False, "error": str}` — never raises

6. **Fold the version dimension into `_grade_ollama_management()`** at [project_grader_service.py:559-713](backend/app/services/project_grader_service.py#L559-L713). Add a 5th dimension `ollama_binary_version` worth 20 points (rebalance the existing 4 dimensions from 25 → 20 each), scored as: 100 if `current == latest`, 50 if outdated by 1 minor version, 20 if outdated by 2+ minor versions or unknown. Surface the version info in the report so the daily report shows "Ollama 0.1.45 → 0.1.50 (outdated, see release_url)".

7. **One-shot cleanup of the wrong plans on the existing Ollama Manager project.** Add a tiny migration/bootstrap helper in `ensure_ollama_project()` at [project_service.py:339-365](backend/app/services/project_service.py#L339-L365) that, after creating the project, runs:
   ```python
   # One-shot: archive any wrong plan types previously seeded for virtual projects
   await db.execute(
       update(PlanDB)
       .where(PlanDB.project_id == project.id)
       .where(PlanDB.plan_type.in_(["docker_logs_review", "dependency_check"]))
       .where(PlanDB.status != PlanStatus.ARCHIVED)
       .values(status=PlanStatus.ARCHIVED)
   )
   ```
   This is idempotent — already-archived plans aren't touched. Replicate the same cleanup in `ensure_gpu_project()` for symmetry.

### Part C — Verification (read-only, no schema changes)

8. **Backend pytest** for the new `check_ollama_version()` method (mocked HTTPx responses for 200 OK and timeout paths). Add to `backend/tests/services/test_ollama_manager_service.py` (create if missing).

9. **Live verification after rebuild:**
   - `docker-compose build legion-backend legion-frontend && docker-compose up -d`
   - `curl -s http://localhost:8005/health` → `200 OK`
   - `curl -s http://localhost:8005/api/plans?project_id=13 | python -m json.tool` → confirm only 3 active plans remain (`project_review`, `ollama_management`, no docker/deps), and the previously-existing `docker_logs_review` + `dependency_check` rows are now `status: archived`
   - `curl -s -X POST http://localhost:8005/api/plans/{ollama_management_id}/execute` → wait 30s → confirm grade includes new `ollama_binary_version` dimension
   - Browser at `http://localhost:3005/projects/13/plans` — click Archive on a plan, confirm dialog, observe (a) row immediately moves to Archived tab, (b) Archived chip count increments, (c) Active chip count decrements

## Critical files to modify

| File | What changes |
|---|---|
| [frontend/src/hooks/usePlans.ts](frontend/src/hooks/usePlans.ts) | `useDeletePlan` invalidation predicate (lines 411-426) |
| [frontend/src/pages/ProjectPlans.tsx](frontend/src/pages/ProjectPlans.tsx) | `handleDeleteConfirm` switch tab on success (line 912-918), archived row opacity (line ~280) |
| [backend/app/services/plan_service.py](backend/app/services/plan_service.py) | Virtual-project gate in `seed_default_plans()` around lines 875-896 |
| [backend/app/services/ollama_manager_service.py](backend/app/services/ollama_manager_service.py) | New `check_ollama_version()` method + 6h cache on latest-release lookup |
| [backend/app/services/project_grader_service.py](backend/app/services/project_grader_service.py) | Add 5th dimension `ollama_binary_version` to `_grade_ollama_management()` (lines 559-713), rebalance weights to 20pts each |
| [backend/app/services/project_service.py](backend/app/services/project_service.py) | One-shot wrong-plan archive in `ensure_ollama_project()` and `ensure_gpu_project()` (line 339-365 area) |
| backend/tests/services/test_ollama_manager_service.py | NEW — pytest for `check_ollama_version()` (mocked HTTPx) |

## Reusable functions found during exploration

- `OllamaManagerService.check_for_updates()` ([ollama_manager_service.py:220-280](backend/app/services/ollama_manager_service.py#L220-L280)) — already does model digest update detection. Don't reimplement.
- `OllamaManagerService.get_health()` — already exposes connectivity / VRAM. Reuse via existing `/ollama-manager/health` endpoint.
- `_grade_ollama_management()` ([project_grader_service.py:559-713](backend/app/services/project_grader_service.py#L559-L713)) — extend in place, don't fork.
- `ensure_ollama_project()` ([project_service.py:339-365](backend/app/services/project_service.py#L339-L365)) — already runs idempotently on every bootstrap. Drop the cleanup SQL there.
- `qk.plans` ([queryKeys.ts:58-71](frontend/src/lib/queryKeys.ts#L58-L71)) — central query key registry. Use it, don't hardcode key arrays.

## Verification end-to-end

After Part A + B + C ship, on a fresh `docker-compose up -d`:

1. `GET /api/plans?project_id=13` returns exactly 2 active plans for Ollama Manager: `project_review` and `ollama_management` (plus any archived ones from before, which stay archived).
2. Clicking Archive on an active Ollama plan immediately moves it from "Active" tab to "Archived" tab in the UI, with chip counts updating.
3. Triggering `POST /api/plans/{ollama_management_id}/execute` produces a grade with 5 dimensions including `ollama_binary_version`, and the latest report shows the actual Ollama version vs latest GitHub release.
4. `pytest backend/tests/services/test_ollama_manager_service.py -v` passes.
5. `cd frontend && npm run build` passes (TypeScript clean).
6. Backend `/health` reports healthy with `ollama_manager` daemon alive.
