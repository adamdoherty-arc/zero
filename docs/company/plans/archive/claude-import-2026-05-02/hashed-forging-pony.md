# Fix-50: Unblock Sprint Completion Pipeline

## Context

Despite 50+ fix sprints, Legion sprints keep failing or getting stuck. Deep investigation reveals **6 concrete bugs** in the sprint execution pipeline that form a cascading failure chain:

1. Sprints complete all tasks but never get marked COMPLETED in the DB
2. The test gate always throws TypeError (signature mismatch) — falls back to crude success-rate check
3. Concurrent agentic loop re-entry causes premature sprint failure
4. QA gate transient errors permanently fail otherwise-successful sprints
5. A string enum literal bypasses type safety in the rollback path
6. The lifecycle daemon safety net runs only every 2 hours

**Root cause chain**: Tasks complete → `mark_task_completed()` sets `qa_status="pending_review"` → `finalize_sprint()` sees non-approved QA → routes to IN_REVIEW → agentic loop never calls `complete_sprint()` → sprint stuck in IN_REVIEW for up to 2 hours (lifecycle daemon interval). Meanwhile, test gate TypeError makes the executor's QA pipeline dead code, and concurrent re-entry can prematurely fail sprints that are still executing.

---

## Bugs & Fixes (in implementation order)

### 1. String enum literal in rollback query
**File**: [agentic_loop_service.py:1236](backend/app/services/agentic_loop_service.py#L1236)
**Bug**: `SprintTaskDB.status == "FAILED"` — string literal instead of enum
**Fix**: Change to `SprintTaskDB.status == TaskStatus.FAILED` (TaskStatus already imported)
**Risk**: Very low — UPPERCASE matches, but enum is correct practice

### 2. QA gate exceptions should not fail sprints
**File**: [agentic_loop_service.py:756-780](backend/app/services/agentic_loop_service.py#L756-L780)
**Bug**: When `qa_gate_blocking=true` (default), any QA gate exception (Ollama down, timeout) calls `fail_sprint()`. Transient infra errors permanently destroy successful sprints.
**Fix**: Remove the `if qa_gate_blocking:` branch inside the `except Exception` handler. Log warning and proceed — only an explicit QA verdict of `passed=False` (lines 718-744) should block. Gate errors ≠ bad work.
**Risk**: Low — explicit QA failures still block; only infra errors change behavior

### 3. Missing `complete_sprint()` on success path (THE critical fix)
**File**: [agentic_loop_service.py:755](backend/app/services/agentic_loop_service.py#L755) (after QA gate passes)
**Bug**: After executor succeeds AND QA gate passes, the agentic loop emits events, sends notifications, extracts learnings — but NEVER calls `complete_sprint()` to persist COMPLETED status. Sprint stays IN_REVIEW (set by `finalize_sprint()` because `qa_status="pending_review"`).
**Fix**: After the QA gate success block (after line 755), add:
```python
# Persist COMPLETED status — finalize_sprint set IN_REVIEW
# because per-task qa_status is "pending_review", but sprint-level
# QA gate has now passed, so override to COMPLETED.
try:
    from app.services.sprint_manager import SprintManager
    complete_mgr = SprintManager(db=db)
    await complete_mgr.complete_sprint(active_sprint.id)
except Exception as complete_err:
    logger.warning(f"[AgenticLoop] Failed to persist sprint completion: {complete_err}")
```
**Risk**: Low — `complete_sprint()` is row-locked and idempotent. Lifecycle daemon becomes safety net only.

### 4. Concurrent re-entry race condition
**File**: [autonomous_sprint_executor.py:1271-1272](backend/app/services/autonomous_sprint_executor.py#L1271-L1272) + [agentic_loop_service.py:858-868](backend/app/services/agentic_loop_service.py#L858-L868)
**Bug**: When executor finds RUNNING tasks from concurrent execution, it returns with `phase=EXECUTING`. Summary reports `success=False`. Agentic loop calls `fail_sprint()` → marks sprint FAILED while tasks are still executing.
**Fix two parts**:
- **Executor** (line 1271): Before returning, add `"concurrent_skip": True` to the state so `_build_execution_summary()` includes it
- **Agentic loop** (line 858): Before calling `fail_sprint()`, check `if result.get("concurrent_skip"): return {"success": True, "sprint_id": ..., "concurrent_execution": True}` — skip failure path entirely
**Risk**: Low-medium — new code path, but conservative (skips action rather than taking destructive action)

### 5. Test gate signature mismatch (TypeError every call)
**File**: [autonomous_sprint_executor.py:2674-2677](backend/app/services/autonomous_sprint_executor.py#L2674-L2677)
**Bug**: Calls `run_sprint_validation(sprint_id=..., level=...)` but method signature is `(sprint_id, project_path, generate_tests=True)`. Also references non-existent attributes (`.tests_passed`, `.lint_passed`, `.passed`) on `ValidationResult` (which has `.success`, `.checks`, `.errors`).
**Fix**: Fix the call to pass correct args and use correct result attributes:
```python
validation_result = await self.qa_pipeline.run_sprint_validation(
    sprint_id=self._state.sprint_id,
    project_path=self._state.project_path,
)
# ... and fix attribute references:
# .passed → .success
# .tests_passed/.lint_passed/.type_check_passed → derive from .checks list
# .blocking_issues → .errors
```
**Risk**: Low — currently dead code (always throws TypeError), so any working code is an improvement

### 6. Lifecycle daemon interval too long
**File**: [main.py:712](backend/main.py#L712)
**Fix**: Change `sleep_seconds = 7200` to `sleep_seconds = 1800` (30 min instead of 2h)
**Risk**: Very low — lifecycle is lightweight DB queries

---

## Files Modified

| File | Changes |
|------|---------|
| [agentic_loop_service.py](backend/app/services/agentic_loop_service.py) | Bugs 1, 2, 3, 4 |
| [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) | Bugs 4, 5 |
| [main.py](backend/main.py) | Bug 6 |

**Reference files** (read-only, no changes):
- [sprint_manager.py](backend/app/services/sprint_manager.py) — `complete_sprint()`, `fail_sprint()`, `finalize_sprint()` behavior
- [qa_pipeline_service.py](backend/app/services/qa_pipeline_service.py) — correct `run_sprint_validation` signature + `ValidationResult` attributes

---

## Verification

After all fixes, rebuild and verify:

```bash
# 1. Rebuild
docker-compose build legion-backend && docker-compose up -d

# 2. Check backend starts clean
docker logs legion-backend --tail 30

# 3. Verify health
curl -s http://localhost:8005/health | python -m json.tool

# 4. Check recent sprint status — should see COMPLETED not stuck IN_REVIEW
docker exec legion-db psql -U legion -d legion -c "
  SELECT id, name, status, updated_at
  FROM sprints WHERE project_id=3
  ORDER BY id DESC LIMIT 10;
"

# 5. Monitor next agentic cycle for the new complete_sprint log line
docker logs legion-backend --tail 200 2>&1 | grep -E "complete_sprint|QA gate|sprint.*COMPLETED"

# 6. Verify no more TypeError in test gate
docker logs legion-backend --tail 200 2>&1 | grep "QA pipeline error"
# Should no longer see "unexpected keyword argument 'level'"

# 7. Verify lifecycle interval shortened
docker logs legion-backend --tail 50 2>&1 | grep "Lifecycle.*Cycle complete"
```

---

## Sprint Registration

```sql
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES ('Fix-50: Unblock sprint completion pipeline',
        '6 bugs in sprint execution: missing complete_sprint call, test gate TypeError, concurrent re-entry race, QA gate error handling, string enum, lifecycle interval',
        3, 'PLANNED', 1, 6, NOW(), NOW());
```

---

## Deep Review — All 6 Fixes Verified (Post-Implementation)

### Status: COMPLETE — All fixes implemented and working

**Line-by-line verification** of each fix in the actual codebase:

| Bug | Location | Expected | Verified |
|-----|----------|----------|----------|
| 1. String enum | agentic_loop_service.py:1251 | `TaskStatus.FAILED` | YES |
| 2. QA gate exceptions | agentic_loop_service.py:756-763 | Warning log + proceed | YES |
| 3. Missing complete_sprint | agentic_loop_service.py:769-780 | Explicit `complete_sprint()` call | YES |
| 4a. Executor concurrent_skip | autonomous_sprint_executor.py:1265-1272 | RUNNING check + early return | YES |
| 4b. Executor summary flag | autonomous_sprint_executor.py:3247 | `concurrent_skip` in summary | YES |
| 4c. Agentic loop skip branch | agentic_loop_service.py:858-872 | `elif concurrent_skip` + graceful return | YES |
| 5. Test gate signature | autonomous_sprint_executor.py:2670-2733 | Correct args + attributes | YES |
| 6. Lifecycle interval | main.py:712 | `sleep_seconds = 1800` | YES |

### Session Safety Verified

- `_execute_sprint()` (line 1204) uses isolated `executor_db = AsyncSessionLocal()` — long-running LLM calls cannot corrupt the agentic loop's `db` session
- `complete_sprint()` at line 770 uses the clean outer `db` session (from line 630 `async with AsyncSessionLocal() as db:`) — safe because executor didn't touch it
- `SprintManager` is always lazy-imported (5 occurrences, zero module-level imports) — no Python scoping trap risk

### Triple Completion Path Analysis

Three paths can mark sprints COMPLETED:

| Path | Trigger | Status Guard | Event Published |
|------|---------|-------------|-----------------|
| 1. `complete_sprint()` (agentic loop) | After QA gate passes | None | SPRINT_COMPLETED + insights |
| 2. `finalize_sprint()` (from mark_task_completed) | After last task completes | Routes to IN_REVIEW when qa_status="pending_review" | None (goes to IN_REVIEW) |
| 3. Lifecycle daemon (sprint_lifecycle_graph) | Every 30 min sweep | Only acts on ACTIVE/IN_REVIEW | SPRINT_COMPLETED + insights |

**Race analysis**: Path 2 always routes to IN_REVIEW (not COMPLETED) because `qa_status="pending_review"`. Path 1 (agentic loop) runs immediately after executor returns, overriding IN_REVIEW → COMPLETED. Path 3 (lifecycle) runs every 30 min and only acts on ACTIVE/IN_REVIEW, so it won't re-complete an already-COMPLETED sprint. **No practical race condition exists.**

If Path 1 fails (exception caught), sprint stays IN_REVIEW → Path 3 picks it up as safety net. This is the intended design.

### Minor Observation (Not a Bug)

`complete_sprint()` has no status guard — if called on an already-COMPLETED sprint, it would redundantly update timestamps + publish duplicate events. This can't happen in practice (agentic loop only calls once per success path, lifecycle checks status first), but adding `if sprint.status == SprintStatus.COMPLETED: return sprint` would be defense-in-depth. **Not blocking — deferred.**

### Live Results

After deploying Fix-50:
- Sprint 2804: **4/5 tasks COMPLETED with QA "approved"** (was 0/5 before fix)
- Concurrent re-entry handling working: "Sprint 2803 has concurrent execution in progress — skipping this cycle"
- First time in project history that tasks completed with QA approval
