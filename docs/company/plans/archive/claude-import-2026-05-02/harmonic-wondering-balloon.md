# Sprint System Full Audit & Fix Plan

## Context

Legion's sprint system is fundamentally broken. After 2000+ agentic loop cycles across all projects, **zero sprints have ever completed successfully**. The system creates sprints, "executes" tasks that produce no real code changes, marks them as completed anyway, then fails at the test gate. Failed sprints pile up forever with no cleanup. The Ideas system mixes auto-generated noise with user input. The frontend crashes on the ADA sprints page.

This plan is a comprehensive audit + fix, organized by priority.

---

## AUDIT FINDINGS

### Finding 1: Empty Code Changes Marked as Success (ROOT CAUSE)
**File**: [autonomous_sprint_executor.py:1872-1888](backend/app/services/autonomous_sprint_executor.py#L1872-L1888)

When the LLM returns no files to change (`code_changes.get("files")` is empty), the task is marked COMPLETED with "No code changes required". This happens after:
1. Agent produces intent-only output ("I'll refactor...") → falls through
2. Claude CLI path returns None → falls through
3. Direct LLM returns `{}` → **marked as success**

Then the test gate runs, finds zero changes, and fails the entire sprint.

### Finding 2: No Sprint Cleanup Daemon
Failed and cancelled sprints accumulate forever. Legion has 50+, ADA has 41+. Only a manual API endpoint exists (`POST /api/sprints/cleanup`).

### Finding 3: Frontend Crash on ADA Sprints
**File**: [SwarmPanel.tsx:142](frontend/src/components/sprint/SwarmPanel.tsx#L142)
`<SelectItem value="">` crashes Radix UI — empty string not allowed.

### Finding 4: Ideas Mix Auto-Generated with Manual
Work discovery creates ideas from 10 sources (TODO scanning, council verdicts, GitHub issues, etc.) mixed with user-typed ideas. No way to distinguish.

### Finding 5: Sprint Failure Detail is Poor
Failed sprints show "5 tasks failed - requires attention" with no summary of WHY. Must drill into each task individually.

### Finding 6: Test Gate Always Fails
**File**: [autonomous_sprint_executor.py:969-1017](backend/app/services/autonomous_sprint_executor.py#L969-L1017)
`_run_test_gate()` runs the project's test suite. Since no code changes were applied (Finding 1), it either finds nothing to test or tests fail on pre-existing issues, failing every sprint.

### Finding 7: Agent Output is Intent-Only
Agents consistently produce planning statements ("I'll implement...", "Let me analyze...") instead of actual code. The `_is_intent_only()` check (line 82-92) catches this, but the fallback paths also fail.

---

## FIX PLAN (7 Phases)

### Phase 1: Fix Frontend Crash
**Priority**: Critical (blocks ADA page)
**File**: [SwarmPanel.tsx:142](frontend/src/components/sprint/SwarmPanel.tsx#L142)

Change `<SelectItem value="">` to `<SelectItem value="all">` and update `handleRunLifecycle()` to treat `"all"` as unfiltered.

---

### Phase 2: Fix Empty Code Changes Bug
**Priority**: Critical (root cause of 100% failure rate)
**File**: [autonomous_sprint_executor.py:1872-1888](backend/app/services/autonomous_sprint_executor.py#L1872-L1888)

Current (broken):
```python
if not code_changes.get("files"):
    # No changes generated, mark as completed (might be documentation-only)
    completion_note = code_changes.get("explanation", "No code changes required")
    await self.sprint_manager.mark_task_completed(task.id, completion_notes=completion_note)
```

Fix: When ALL three execution paths fail to produce code changes (agent → CLI → direct LLM), the task should be marked **FAILED**, not completed. Only allow "no changes needed" for explicitly documentation/research tasks.

```python
if not code_changes.get("files"):
    if self._is_documentation_task(task) or self._is_research_task(task):
        # Legitimate no-code tasks
        completion_note = code_changes.get("explanation", "No code changes required")
        await self.sprint_manager.mark_task_completed(task.id, completion_notes=completion_note)
        # ... existing completion logic
    else:
        # Code task produced no changes — this is a failure
        error_msg = "All execution paths failed to produce code changes"
        return await self._intelligent_retry(
            task, error_msg, None, self._state.current_model, execution.id
        )
```

Also add a `_is_research_task()` helper similar to `_is_documentation_task()` that checks for analysis/research/planning task types.

---

### Phase 3: Add Daily Sprint Cleanup Daemon
**Priority**: High (hygiene)
**Files**:
- [sprint_manager.py](backend/app/services/sprint_manager.py) — add `scheduled_cleanup()` method
- [main.py](backend/main.py) or scheduler — wire as daily background task

Add a daily cleanup (3 AM UTC) that:
1. Deletes FAILED sprints older than 7 days
2. Deletes CANCELLED sprints older than 3 days
3. Preserves learning data (existing `cleanup_sprints()` already does this)
4. Logs summary of what was cleaned

Wire into the existing background task supervisor in `main.py` startup, alongside other daemon tasks.

---

### Phase 4: Improve Sprint Failure Detail
**Priority**: High (visibility)
**File**: [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py)

When a sprint fails, aggregate task-level errors into a sprint-level summary:
```
"3/5 tasks failed: No code changes produced (2), LLM timeout (1)"
```

Store this in `SprintDB.last_error` so it's visible in the sprint list without drilling into tasks. Currently `fail_sprint()` gets a generic "Test gate failed" message.

Add error categorization in `_execute_all_tasks()`:
- Count failures by type (no_code_changes, llm_timeout, test_failure, parse_error)
- Build summary string
- Pass to `fail_sprint(reason=summary)`

---

### Phase 5: Separate Ideas by Source (UI)
**Priority**: Medium (UX)
**Frontend files**:
- Ideas page component (add sub-tabs: "My Ideas" / "Auto-Discovered")
- Ideas list component (filter by `source` field)

**Backend**: No changes needed — `IdeaDB` already has a `source` field that distinguishes manual vs auto-discovered. The frontend just needs to filter:
- "My Ideas" tab: `source` is null or "manual" or "user"
- "Auto-Discovered" tab: `source` is "code_scan", "work_discovery", "council_verdict", etc.

---

### Phase 6: One-Time Cleanup of Existing Failed Sprints
**Priority**: Medium (immediate cleanup)

Run via API after deploying the cleanup daemon:
```bash
# Dry run first
curl -X POST http://localhost:8005/api/sprints/cleanup \
  -H "Content-Type: application/json" \
  -d '{"statuses": ["FAILED", "CANCELLED"], "dry_run": true}'

# Then actual cleanup
curl -X POST http://localhost:8005/api/sprints/cleanup \
  -H "Content-Type: application/json" \
  -d '{"statuses": ["FAILED", "CANCELLED"], "dry_run": false}'
```

---

### Phase 7: Improve Agent Output Quality
**Priority**: Medium (longer-term fix)
**File**: [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py)

The agent pipeline consistently returns intent-only output. Two improvements:

1. **Better prompting**: When `_is_intent_only()` detects planning statements, retry with an explicit instruction: "Do NOT describe what you'll do. Output the actual code changes in JSON format with file paths and content."

2. **Structured output enforcement**: Use `execute_structured()` with a Pydantic model for code changes instead of free-form text parsing. This forces the LLM to return parseable JSON.

---

## Files to Modify (Summary)

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | `frontend/src/components/sprint/SwarmPanel.tsx` | Fix SelectItem empty value | Critical |
| 2 | `backend/app/services/autonomous_sprint_executor.py` | Fix empty code changes bug (line 1872) | Critical |
| 3 | `backend/app/services/sprint_manager.py` | Add `scheduled_cleanup()` method | High |
| 4 | `backend/main.py` | Wire daily cleanup background task | High |
| 5 | `backend/app/services/autonomous_sprint_executor.py` | Sprint failure error summary | High |
| 6 | `frontend/src/pages/` (Ideas page) | Add source tabs (My Ideas / Auto-Discovered) | Medium |
| 7 | `backend/app/services/autonomous_sprint_executor.py` | Better agent retry prompting | Medium |

## Verification

1. **Frontend crash**: Navigate to `localhost:3005/projects/6/sprints` — should load without error
2. **Empty changes fix**: Create a test sprint with a code task, verify it gets marked FAILED (not COMPLETED) when no files are produced
3. **Cleanup daemon**: Check logs for cleanup execution at 3 AM; verify old FAILED sprints are removed
4. **Error summary**: Fail a sprint, check `SprintDB.last_error` contains categorized error breakdown
5. **Ideas tabs**: Navigate to Ideas page, verify "My Ideas" and "Auto-Discovered" tabs filter correctly
6. **Build**: `cd frontend && npm run build` + `cd backend && python -m pytest tests/ -v`
