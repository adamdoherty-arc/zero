# Legion Quality Sweep — radiant-blum

## Context

The user dropped a punch list of ~15 issues spanning four subsystems:
1. **LLM display & routing** is leaky — UI shows "ollama-qwen3-coder-next / pending / no prompt / no response" while the system is on vLLM, execution logs cite Ollama in fallback chains, LLM Console clicks open blank, LLM Review claims 222 pending against an empty list, and dependency-update tasks are burning LLM calls instead of running through script_executor.
2. **Sprint lifecycle** is unreliable — task retry returns 400 without explaining why, "Sprint 0: Product Documentation" exists with 0 tasks, Deps-02 was created instead of fixing/retrying Deps-01, Test Gate always shows `PENDING / N/A / 0`, and there is no watchdog that periodically reconciles stuck/phantom state.
3. **Quality & improvement loops are dormant** — Sprint Quality dimensions show numeric scores with no rationale, the Prompt Manager has produced 0 improvements since launch, and the prompt-evaluator → improver → verifier pipeline is wired but gated so tightly nothing fires.
4. **Dead UI surfaces** — Ollama Manager has been superseded by LLM Operations and should be removed; an unlabeled green icon on each sprint card is unclear.

Goal: land a single coordinated change set that fixes the worst symptoms, surfaces honest data in the UI, removes the duplicate Ollama Manager surface, and adds a sprint watchdog so future regressions are visible. Then re-grade the system from 0–100 against CLAUDE.md and outline the next two sprints.

## Tracking

Sprint name: **Fix-47: Quality Sweep — UI truth, retry, watchdog, deps routing**
Project: Legion (`project_id=1` post-wipe; verify by name).
Categories follow CLAUDE.md naming: most rows are `Fix-`, the new watchdog feature is `Dev-`.

## Fixes

### F1. Dependency tasks bypass LLM (script_executor regex misses ecosystem-tagged titles)
- **Root cause**: `script_executor.DependencyUpgradeExecutor._BATCH_RE = r"Update\s+(\d+)\s+minor/patch\s+dependencies"` does not match real task titles like `"Update 28 minor/patch pip dependencies"` or `"Update 2 minor/patch npm dependencies"` — the ecosystem word in the middle breaks the regex. `can_handle()` returns False, supervisor falls through to LLM, Ollama circuit breaker bites. This is the actual root of the Deps-01 / Deps-02 failure cascade and the long stream of `Ollama circuit breaker open` errors in the screenshots.
- **File**: [backend/app/services/script_executor.py:128-142](c:/code/Legion/backend/app/services/script_executor.py#L128-L142)
- **Fix**: change `_BATCH_RE` to `r"Update\s+(\d+)\s+minor/patch\s+(?:pip|npm)\s+dependencies"` and update `_parse_batch_packages` if it consumed the same pattern. Add a regression unit test in `backend/tests/services/test_script_executor.py` covering both `pip` and `npm` titles.
- **Secondary**: in `try_handle`, when sprint name starts with `Deps-` AND no executor matched, return a `TaskResult(success=False, should_fallback_to_llm=False, error="No script executor matched a Deps-* task — refusing to burn LLM on mechanical work")` instead of None. Deps work must never reach the LLM path.

### F2. Sprint task retry returns 400 with no actionable message (#2, #6)
- **Root cause**: [backend/app/services/sprint_manager.py:1208](c:/code/Legion/backend/app/services/sprint_manager.py#L1208) raises `ValueError("Task {id} has exceeded max retries")` when `retry_count >= sprint.max_retries` (default 20). Endpoint catches and returns 400. The frontend hook [frontend/src/hooks/useSprints.ts useRetryTask](c:/code/Legion/frontend/src/hooks/useSprints.ts) never offers `?force=true` for the normal Retry button, so the user is stuck.
- **Fix (backend)**: in `retry_task`, replace the bare `ValueError` with a structured payload via a new `RetryBlocked` exception that the endpoint translates to HTTP 409 with body `{"reason": "max_retries_exceeded", "retry_count": N, "max_retries": M, "force_available": true}`. 400 is reserved for genuine input errors.
- **Fix (frontend)**: in [frontend/src/components/sprint/SprintDetailDialog.tsx](c:/code/Legion/frontend/src/components/sprint/SprintDetailDialog.tsx), when retry returns 409 with `force_available`, pop a `confirm("Task hit retry cap (N/M). Force re-run?")` dialog and resubmit with `force=true`. Show the cap on the task row even before clicking.

### F3. Phantom sprints (creation is non-atomic) (#4)
- **Root cause**: [backend/app/services/sprint_manager.py:105-129 create_sprint](c:/code/Legion/backend/app/services/sprint_manager.py#L105-L129) commits `SprintDB` *before* tasks are added by callers. Any subsequent failure or skipped loop leaves a sprint with `total_tasks=0`. Audit-Remediation-01 added phantom *detection* in the grader but no creation-time prevention.
- **Fix**: add `SprintManager.create_sprint_with_tasks(sprint_data, tasks_data)` that wraps `add(sprint) → flush → add_all(tasks) → commit` in a single transaction and raises if `tasks_data` is empty. Migrate the obvious callers:
  - [backend/app/services/dependency_review_service.py:432-450](c:/code/Legion/backend/app/services/dependency_review_service.py#L432-L450)
  - [backend/app/services/sprint_library_service.py](c:/code/Legion/backend/app/services/sprint_library_service.py) (built-in template instantiation, including "Sprint 0: Product Documentation")
  - any `seed_*_sprints` and `auto_sprint_service` paths
- Leave the legacy `create_sprint` callable for now (deprecation comment), but log a WARNING when used.

### F4. Duplicate Deps sprints (#7)
- **Root cause**: [backend/app/services/dependency_review_service.py:317-331](c:/code/Legion/backend/app/services/dependency_review_service.py#L317-L331) only blocks creation when an existing Deps sprint is `PLANNED`/`ACTIVE`/`IN_REVIEW`. A `FAILED` Deps-01 lets Deps-02 through.
- **Fix**: when a recent (≤24h) Deps sprint exists in `FAILED` state for the same project AND its task signature overlaps with the new findings, **retry the existing sprint** instead of creating a new one — reset failed tasks to `PENDING`, reset `retry_count=0`, append a note to `description` ("Auto-retried <ts> by dependency_review_service: regex fix in F1"), set sprint back to `PLANNED`. Only create a new Deps-NN if the existing failed sprint is older than 24h or has a non-overlapping task set.

### F5. Sprint watchdog with self-heal report (#5)
- **New service**: `backend/app/services/sprint_watchdog_service.py` — runs every 4h via `_supervised_task` registered alongside `sprint_sync_scheduler` in [backend/main.py:354-360](c:/code/Legion/backend/main.py#L354-L360). Detects and either heals or reports:
  - Phantom sprints (`total_tasks > 0` AND 0 rows in `sprint_tasks`) → mark `CANCELLED` with phantom note.
  - `IN_PROGRESS` tasks with no `updated_at` change in >2h → reset to `PENDING` with retry, log to `last_error`.
  - Tasks at retry cap still `PENDING` → mark `BLOCKED` with `last_error="retry cap reached, manual intervention required"`.
  - `ACTIVE` sprints where all tasks are `COMPLETED`/`SKIPPED`/`CANCELLED` → transition to `COMPLETED`.
  - LLM call rows in `pending` for >30 min → mark `failed` with `error_type="abandoned"`, scrubs the empty rows polluting LLM Console.
- **New table**: `WatchdogReportDB(id, ran_at, phantoms_healed, stuck_tasks_reset, blocked_tasks, abandoned_calls_cleaned, summary_json)` via Alembic migration.
- **New endpoint**: `GET /api/health/watchdog` returns last 10 reports. Surface on the Dashboard ("Watchdog" panel showing last run + counts + a "Run now" button).

### F6. Sprint Quality explainability (#9)
- **Root cause**: grader at [backend/app/services/sprint_quality_grader.py:54-77](c:/code/Legion/backend/app/services/sprint_quality_grader.py#L54-L77) computes a `details` dict per dimension and persists it. Frontend [frontend/src/components/sprint/SprintQualityCard.tsx:87-115](c:/code/Legion/frontend/src/components/sprint/SprintQualityCard.tsx#L87-L115) renders only `dim.score` and discards `dim.details`.
- **Fix (frontend)**: make each row a `<button>` (keyboard-accessible) that toggles an inline panel under the bar showing `details` as a key/value table plus the new `improvement_hint`. No new API call — the data is already in the response.
- **Fix (backend)**: each dimension function returns an `improvement_hint` string in `details` (e.g., QA Gate when no reviews: `"0 of 0 tasks reviewed. Get task QA approvals to raise this score."`). Hint is hard-coded per dimension based on what the score would need to improve.

### F7. Test Gate always identical (#10)
- **Root cause**: [backend/app/api/endpoints/test_feedback.py:169-218](c:/code/Legion/backend/app/api/endpoints/test_feedback.py#L169-L218) reads `SprintTestGateDB` rows but **nothing in the codebase writes them** for normal sprint completion.
- **Fix**: in `sprint_manager._transition_sprint_status` (or wherever sprints transition to `COMPLETED`), call `sprint_test_gate_service.evaluate(sprint_id)` to populate the row with: total task tests run, pass rate, gate status (`passed` / `failed` / `pending`). Keep the endpoint default for sprints that genuinely have no tests, but make it explicit: `gate_status="not_applicable"` when no tasks ever invoked the test runner.

### F8. LLM Console "no prompt / no response" on click (#11) and stale pending rows
- **Root cause**: [backend/app/services/llm_call_tracker.py:428-450](c:/code/Legion/backend/app/services/llm_call_tracker.py#L428-L450) persists rows with `status="pending"` and empty `prompt_full`/`response_full` when a call enters the tracker, hits a circuit breaker, and never completes. These accumulate as stale rows that look broken in the UI.
- **Fix (backend)**: in `_persist_to_db`, only persist when `status in {"completed","failed"}` OR the call has been pending >60s (write-through for long-running streams). The watchdog F5 sweeps stragglers.
- **Fix (frontend)**: in the LLM Call Detail modal, when `status === "pending"` AND prompt is empty, show a clear `"In flight or abandoned (no prompt captured yet) — try again in a moment"` banner instead of two empty boxes.

### F9. LLM Review pending count vs empty list mismatch (#13)
- **Root cause**: [backend/app/services/llm_review_service.py](c:/code/Legion/backend/app/services/llm_review_service.py) — `get_review_stats()` counts ALL rows with `review_status="pending"`. `fetch_unreviewed()` lists only rows that are ALSO `status in {"completed","failed"}` AND have `response_full`. The 222 vs 0 gap is rows whose execution never finished (the same stale rows from F8).
- **Fix**: change the count query in `get_review_stats()` to use the identical WHERE clause as `fetch_unreviewed()`. Now "Pending: N" matches the visible list. Add a separate "Awaiting completion: M" stat tile showing the gap so the operator can see how many calls never completed (these will drop to 0 once F8 + F5 land).

### F10. Execution log mentions Ollama while system is on vLLM (#15)
- **Root cause**: `unified_llm_service.execute_with_recovery` walks the fallback chain through Ollama even when `LOCAL_LLM_BACKEND=vllm`. The error string is correct (it shows what was *attempted*), but Ollama should not have been attempted at all when vLLM is the active backend.
- **Fix**: in `_build_fallback_chain` (or equivalent in [backend/app/services/unified_llm_service.py](c:/code/Legion/backend/app/services/unified_llm_service.py)), when `get_llm_health()["active_provider"] == "vllm"`, exclude Ollama from the fallback chain unless an explicit per-source override (Learn-18/19) is in effect for that call. This makes the error chain show only `[vllm/...]` and stops the misleading Ollama mentions.

### F11. Prompt-improvement loop dormant (#12)
- **Root cause**: [backend/app/services/prompt_manager_service.py:973-1046 auto_apply_improvements](c:/code/Legion/backend/app/services/prompt_manager_service.py#L973-L1046) requires `≥3 annotations per template` before auto-applying. With 16 templates and 11 reviewed calls, no template has crossed the gate. The daemon IS running (registered in [backend/main.py:532-536](c:/code/Legion/backend/main.py#L532-L536)).
- **Fix**: lower threshold to `≥2 annotations` for the first 30 days after a template's first annotation (warm-up phase), then back to 3. Track via a `first_annotated_at` column on `prompt_templates` (Alembic migration). Add a "Propose Improvement Now" button on the Prompt Manager Annotation Queue tab that calls a new endpoint `POST /api/prompt-manager/templates/{id}/propose-now` to force a proposal regardless of the gate.

### F12. Remove Ollama Manager (#8)
- **Frontend**: delete [frontend/src/pages/OllamaManager.tsx](c:/code/Legion/frontend/src/pages/OllamaManager.tsx), the route in [frontend/src/App.tsx](c:/code/Legion/frontend/src/App.tsx), the sidebar entry in [frontend/src/components/Sidebar.tsx](c:/code/Legion/frontend/src/components/Sidebar.tsx), and the existing test file `frontend/src/pages/__tests__/OllamaManager.test.tsx`.
- **Backend**: remove [backend/app/api/endpoints/ollama_manager.py](c:/code/Legion/backend/app/api/endpoints/ollama_manager.py) and its router registration in `main.py` and `router_registry.py`. Verify LLM Operations covers everything the old page did before deleting.
- **Data**: if `ensure_ollama_project()` exists (memory mentions virtual project id=13), have it set the project to `archived` and stop seeding plans. Verify with `SELECT id, name, status FROM projects WHERE name LIKE '%Ollama%'`.

### F13. Mystery green button on sprint card (#3)
- **Root cause**: [frontend/src/components/sprint/SprintCard.tsx:62-70](c:/code/Legion/frontend/src/components/sprint/SprintCard.tsx#L62-L70) — the leftmost button is a green Bot icon for "Ask AI about this sprint" with `title=` attr only.
- **Fix**: add `aria-label="Ask AI about this sprint"`, replace the bare Bot icon with `<Bot /> + <span className="sr-only">Ask AI</span>` and a visible tooltip via the existing `Tooltip` component. Keep the green color but add a subtle border so it reads as a button.

## Files modified (summary)

**Backend**
- `backend/app/services/script_executor.py` — F1
- `backend/app/services/sprint_manager.py` — F2, F3, F7
- `backend/app/services/dependency_review_service.py` — F3, F4
- `backend/app/services/sprint_watchdog_service.py` — **NEW** for F5
- `backend/app/models/watchdog_report.py` — **NEW** for F5
- `backend/alembic/versions/0XX_watchdog_report_and_first_annotated.py` — **NEW** for F5, F11
- `backend/app/services/sprint_quality_grader.py` — F6 (improvement_hint per dimension)
- `backend/app/services/llm_call_tracker.py` — F8
- `backend/app/services/llm_review_service.py` — F9
- `backend/app/services/unified_llm_service.py` — F10
- `backend/app/services/prompt_manager_service.py` — F11
- `backend/app/api/endpoints/sprints.py` — F2 (409 handling)
- `backend/app/api/endpoints/health.py` (or `service_health.py`) — F5 (new endpoint)
- `backend/app/api/endpoints/prompt_manager.py` — F11 (propose-now endpoint)
- `backend/app/api/endpoints/ollama_manager.py` — F12 (delete)
- `backend/main.py` — F5 (register watchdog), F12 (drop ollama_manager router)

**Frontend**
- `frontend/src/components/sprint/SprintQualityCard.tsx` — F6
- `frontend/src/components/sprint/SprintDetailDialog.tsx` — F2 (force confirm), F7 (gate display)
- `frontend/src/components/sprint/SprintCard.tsx` — F13
- `frontend/src/pages/LLMConsole.tsx` (and Detail modal) — F8
- `frontend/src/pages/LLMReview.tsx` — F9
- `frontend/src/pages/PromptManager.tsx` — F11 (propose-now button)
- `frontend/src/pages/Dashboard.tsx` — F5 (watchdog panel)
- `frontend/src/App.tsx`, `frontend/src/components/Sidebar.tsx` — F12
- `frontend/src/pages/OllamaManager.tsx` — F12 (delete)
- `frontend/src/hooks/useSprints.ts` — F2

**Tests**
- `backend/tests/services/test_script_executor.py` — F1 regression cases (`pip` and `npm` titles)
- `backend/tests/services/test_sprint_watchdog.py` — **NEW** F5
- `backend/tests/services/test_dependency_review_service.py` — F4 (FAILED-Deps retry instead of duplicate)

## Verification

Per CLAUDE.md, every fix runs in Docker (`docker-compose build legion-backend legion-frontend && docker-compose up -d`). Verification is spontaneous-fire (Audit-Remediation-01 / Learn-18 rule): if a code path doesn't fire within ~2 min of restart in a busy system, the wiring is broken.

1. **F1**: trigger or wait for next Deps cycle, check `legion_script_executor_total{result="success",executor="dependency_upgrade"}` counter increments. Confirm no new `Ollama circuit breaker open` errors on Deps tasks.
2. **F2**: in the UI, click "Retry Task" on a task with `retry_count >= 20` — expect a confirm dialog, accept, expect retry to run.
3. **F3**: run `SELECT id, name, total_tasks, (SELECT COUNT(*) FROM sprint_tasks WHERE sprint_id=s.id) FROM sprints s WHERE total_tasks > 0` and confirm no new mismatches show up after the next sprint creation cycle.
4. **F4**: leave a Deps sprint failing, confirm the next dependency_review_service tick reuses it instead of creating Deps-NN+1.
5. **F5**: hit `GET /api/health/watchdog` after first run, confirm a report row exists with non-zero counters for healed phantoms.
6. **F6**: open Sprint Quality panel, click each dimension row, confirm details panel renders with `improvement_hint`.
7. **F7**: complete a sprint with a passing test run, confirm Test Gate shows `PASSED / 100% / 1` (not `PENDING / N/A / 0`).
8. **F8**: click any pending LLM Console row, confirm the new banner replaces the empty boxes; check `LLMCallDetailDB` count of `pending` rows >30 min old drops to 0 within one watchdog cycle.
9. **F9**: confirm LLM Review's "Pending" count equals the number of rows in the Pending tab list.
10. **F10**: tail `legion-backend` logs for the next minute; on a triggered failure, confirm the error chain mentions only `[vllm/...]`, not Ollama (unless an override fired).
11. **F11**: click "Propose Improvement Now" on a template with 1 annotation, confirm a proposal row appears; reduce gate to 2 and confirm next cycle auto-applies one.
12. **F12**: confirm `/ollama-manager` returns 404 in the browser; confirm sidebar entry is gone; confirm LLM Operations still loads.
13. **F13**: hover the green icon on a sprint card, confirm tooltip "Ask AI about this sprint" shows.

## System grade and forward plan

**Pre-fix baseline**: CLAUDE.md self-rates Legion at **38/100** (April 2026). Symptoms in this batch (broken retry, phantom sprints, dormant improvement loop, dead UI surfaces, dep tasks burning LLM, no watchdog, no rationale on grades) are consistent with that grade.

**Post-fix estimated grade**: **55/100**. The biggest jumps come from F1 (Deps work no longer wastes LLM cycles), F5 (watchdog turns invisible drift visible), F6 (operator can now act on quality scores), F8/F9 (UI tells the truth), F11 (improvement loop wakes up). Routing/fallback hygiene (F10) brings active-provider clarity back.

**Why not higher**: 126 services should still consolidate to ~80 (CLAUDE.md goal); 41 pre-existing test failures still exist; learning system episodic retrieval still 0; PR end-to-end still unverified. These are out of scope for this sweep.

**Next two sprints (proposed, do NOT create until this one lands and verifies)**:
- **Quality-09: Service consolidation pass 1** — pick 20 dead/duplicate services from the 126 inventory and either delete or merge. Target ~110 services.
- **Learn-22: Activate episodic retrieval** — wire `episodic_memory.retrieve()` into `agent_swarm.coder_node` enrichment so the 9 captured episodes start contributing to live decisions. Track via the existing `legion_learning_engine_enrichments_total{source="episodic_memory"}` counter (already added in Audit-Remediation-01).
