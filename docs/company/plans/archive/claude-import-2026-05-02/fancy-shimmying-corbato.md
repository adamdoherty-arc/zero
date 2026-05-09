# Sprint System Overhaul - Root Cause Analysis & Fix Plan

## Context

The sprint management system has multiple fundamental architectural problems causing:
1. Sprints fail to complete or show incorrect data
2. UI doesn't update / shows stale data
3. QA agent system never runs
4. Prompt analysis system stores data in-memory only (lost on restart)

After thorough investigation of **all** sprint files (2 routers, 3 services, 1 store, 2 pages, 1 DB schema), here are the root causes and fixes.

---

## ROOT CAUSE ANALYSIS

### BUG 1: DUAL DATA SOURCE - Frontend uses BOTH local Zustand store AND backend API (CRITICAL)

**Files:** `frontend/src/pages/SprintDashboard.tsx`, `frontend/src/store/sprintStore.ts`

The SprintDashboard page imports from **both** the Zustand local store AND makes API calls to the backend:
- Line 52-64: Imports `useSprintStore`, `useSprintActions`, `useTaskActions` etc. from Zustand store
- Line 71-161: Also defines `useSprintsAPI`, `useCurrentSprintAPI`, `useSprintTasksAPI` etc. calling the real backend

**Result:** The page creates sprints in one source but reads from another. The Zustand store persists to localStorage with client-generated IDs (`Date.now()-random`), while the backend uses PostgreSQL serial IDs. They never sync. The UI shows stale localStorage data, not the real DB state.

### BUG 2: DB schema missing `number` column but code references it (CRITICAL)

**Files:** `database/schemas/sprint_management_schema.sql`, `backend/services/sprint_management_service.py`

The `sprints` table schema has NO `number` column, but:
- `_row_to_sprint()` reads `row["number"]`
- `get_sprint_by_number()` queries `WHERE number = $1`
- `get_sprint_history()` does `ORDER BY number DESC`
- The `sprint_to_dict()` serializer outputs `sprint.number`
- Sprint numbers are shown in the UI

If the column was added via a migration but not in the base schema, it may be missing on fresh installs. More importantly, the `create_sprint()` method doesn't always set the `number` field, leading to NULL numbers.

### BUG 3: SprintManagerAgentV2 references non-existent attributes (CRITICAL)

**File:** `backend/services/sprint_manager_agent_v2.py`

Line 185-202: The code references `s.completed_tasks` and `s.total_tasks` on Sprint objects, but the Sprint dataclass has NO such attributes. It has `completed_points` and `planned_points`. This causes `AttributeError` on every health assessment, silently caught by the `except Exception` on line 228.

### BUG 4: Completion gates are too strict / impossible to pass

**File:** `backend/services/sprint_management_service.py` (lines 394-513)

- **Gate 1 (QA Health >= 95%):** Requires `qa_agent._current_report` to exist, but the QA agent is never automatically started. Falls through to "passed=True" with "No recent QA report" - so it vacuously passes but provides no value.
- **Gate 2 (UI Verification):** Requires a task comment containing "ui verified" or "ui test" - this NEVER happens automatically. Claude Code doesn't add these comments.
- **Gate 4 (Task Completion):** Checks for status NOT IN `('done', 'cancelled')` but TaskStatus enum has BOTH `DONE = "done"` AND `COMPLETED = "completed"`. Tasks marked as "completed" (from external systems) DON'T pass the gate.

### BUG 5: Sprint intelligence service `_store_signals` has type mismatch

**File:** `backend/services/sprint_intelligence_service.py` (lines 277-355)

Line 311: `estimated_effort` is typed as `str` in `SourceSignal` (e.g., "medium") but the UNNEST casts it as `$6::int[]`. String → int[] will fail on every batch insert, falling through to the slow individual insert path (which also fails, silently).

### BUG 6: Prompt analysis system is in-memory only

**File:** `backend/routers/qa.py` (lines 738-907)

`_prompt_analyses` is a module-level Python list. Every Docker restart wipes it clean. It provides no persistence, no learning, no feedback loop. It's a dead-end logging endpoint.

### BUG 7: SprintDashboard uses `api` import instead of `axiosInstance`

**File:** `frontend/src/pages/SprintDashboard.tsx` (line 50)

Imports `api` from `@/services/api` but should use `axiosInstance` from `@/lib/axios`. The `api` client may not have the correct baseURL (`/api` prefix), causing double-prefix or missing-prefix issues depending on how it's configured.

### BUG 8: SprintManagerAgentV2 never auto-starts

**File:** `backend/services/sprint_manager_agent_v2.py`

The agent has a `start()` method that creates an `asyncio.Task` for `_run_loop()`, but nothing in `backend/main.py` or any startup hook calls `start()`. The only way to start it is via the `/api/sprints/intelligence/start` endpoint - which nobody calls. So the entire feature health / auto-suggestion system is inert.

---

## FIX PLAN

### Fix 1: Eliminate Zustand store - Use backend API as single source of truth

**Files to modify:**
- `frontend/src/pages/SprintDashboard.tsx` - Remove all Zustand store imports and usage. Use ONLY the React Query API hooks.
- `frontend/src/store/sprintStore.ts` - Keep file but add deprecation comment. Don't delete yet (other pages may import types).

**Approach:**
- Remove imports of `useSprintStore`, `useSprintActions`, `useTaskActions`, `useErrorActions`
- All sprint CRUD operations go through React Query mutations → backend API
- All sprint reads go through React Query queries → backend API
- Remove localStorage persistence of sprint data (the persist middleware)
- Keep the TypeScript types (re-export from store or move to a types file)

### Fix 2: Fix DB schema - ensure `number` column exists and auto-increments

**Files to modify:**
- `backend/services/sprint_management_service.py` - In `create_sprint()`, auto-assign `number` as `MAX(number) + 1`

**Approach:**
- Add `number` to `create_sprint()` INSERT if not provided: `COALESCE($X, (SELECT COALESCE(MAX(number), 0) + 1 FROM sprints))`
- Verify the column exists (it likely does from a migration, but the create logic should be defensive)

### Fix 3: Fix SprintManagerAgentV2 attribute references

**File to modify:** `backend/services/sprint_manager_agent_v2.py`

**Changes:**
- Line 185: `s.completed_tasks` → `s.completed_points`
- Line 186: `s.completed_tasks` → calculate from tasks or use `completed_points`
- Line 201-202: `last.completed_tasks` / `last.total_tasks` → derive from Sprint fields or query tasks

### Fix 4: Fix completion gates to be realistic

**File to modify:** `backend/services/sprint_management_service.py`

**Changes:**
- Gate 4: Change `NOT IN ('done', 'cancelled')` to `NOT IN ('done', 'completed', 'cancelled')` to handle both status values
- Gate 1: If no QA report exists, mark as "warning" not "passed" - but don't block
- Gate 2: Make UI verification optional (warn but don't block) since it's never automated

### Fix 5: Fix signal storage type mismatch

**File to modify:** `backend/services/sprint_intelligence_service.py`

**Change:** Line 311: `$6::int[]` → `$6::text[]` (estimated_effort is a string like "medium", not an integer)

### Fix 6: Persist prompt analyses to DB

**File to modify:** `backend/routers/qa.py`

**Approach:** Store prompt analyses in a DB table instead of in-memory list. Create a simple `prompt_analyses` table with columns: id, source, intent, warnings (jsonb), prompt_preview, timestamp, created_at.

Actually - given this is a low-value diagnostic feature and the user said "it doesn't seem to be helping", the simpler fix is to **remove the in-memory storage and just log it** via structlog. If the user wants historical analysis, they can check structured logs. This avoids adding yet another table for a feature that isn't providing value.

### Fix 7: Fix API client import

**File to modify:** `frontend/src/pages/SprintDashboard.tsx`

**Change:** Replace `import { api } from '@/services/api'` with `import axiosInstance from '@/lib/axios'` and update all `api.get/post` → `axiosInstance.get/post`. Remove the `/api/` prefix from all URL paths since axiosInstance already has baseURL `/api`.

### Fix 8: Auto-start SprintManagerAgentV2 on backend startup

**File to modify:** `backend/main.py` (or wherever lifespan/startup hooks are)

**Approach:** Add `sprint_manager_v2.start()` call in the FastAPI lifespan startup. This enables the 6-hour health scan loop.

---

## Implementation Order

1. **Fix 5** (signal type mismatch) - 1 line change, unblocks signal collection
2. **Fix 3** (V2 agent attributes) - 4 line changes, unblocks health assessment
3. **Fix 4** (completion gates) - 3 line changes, unblocks sprint completion
4. **Fix 2** (number column) - small change to create_sprint
5. **Fix 7** (API client) - find/replace in SprintDashboard
6. **Fix 1** (eliminate Zustand dual-source) - largest change, refactor SprintDashboard to use only API
7. **Fix 8** (auto-start agent) - add startup hook
8. **Fix 6** (prompt analysis) - simplify to just logging

## Verification

After implementing:
1. `docker restart ada-backend` and check `docker logs ada-backend --tail 30` for no startup errors
2. `curl http://localhost:8006/api/sprints/current` - should return current sprint or null (not 500)
3. `curl http://localhost:8006/api/sprints` - should return sprint list
4. `curl -X POST http://localhost:8006/api/sprints -H 'Content-Type: application/json' -d '{"name":"Test Sprint","goal":"Test"}'` - should create with auto-number
5. `curl http://localhost:8006/api/sprints/intelligence/status` - should show agent running
6. Open `http://localhost:5420/sprint-dashboard` (or wherever the page is routed) - should show real DB data, not stale localStorage
7. Complete a sprint: `curl -X POST http://localhost:8006/api/sprints/{id}/complete?force=true` - should succeed
