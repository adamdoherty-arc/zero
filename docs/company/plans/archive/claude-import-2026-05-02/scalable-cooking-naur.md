# Fix-54: Unblock Sprint Execution Pipeline + E2E QA Verification

## Context

Sprint execution has been failing consistently. The screenshot shows Deps-02 for ADA Trading Platform FAILED (3/6 tasks failed) and a new Deps-02 ACTIVE at 0% progress. Investigation revealed 5 root causes:

1. **Two ACTIVE sprints stuck in infinite loop** (3010, 3019) — DB session corruption ("the connection is closed") prevents task pickup. Executor re-initializes every 3-5 min but never picks up PENDING tasks.
2. **15-minute task timeout kills dependency tasks** — The only 15-min threshold is `autonomous_sprint_executor.py:184` (`MAX_TASK_TIMEOUT_MINUTES = 15`). All other call sites use 30 min. Dependency upgrades consistently need >15 min.
3. **No per-package failure dedup** — `dependency_review_service.create_update_sprint()` has a 3-sprint circuit breaker but doesn't skip packages that individually failed. `rich 14.3.4→15.0.0` produced 434 blocking issues yet keeps being scheduled.
4. **Read-only filesystem for AIContentTools** — `docker-compose.yml:200` mounts with `:ro` while all other managed projects are `:rw`. Every file-write task for this project structurally fails.
5. **Jaeger down** — OpenTelemetry gRPC errors spamming logs (cosmetic but noisy).

## Plan

### Phase 1: DB Triage — Cancel Stuck Sprints
**No code changes. DB operations only.**

Cancel sprints 3010 and 3019 which are in an infinite session-corruption loop.

**IMPORTANT**: Use `SKIPPED` for task status (taskstatus enum has no CANCELLED), use `CANCELLED` for sprint status.

```sql
-- Sprint 3010 tasks → SKIPPED, sprint → CANCELLED
UPDATE sprint_tasks SET status = 'SKIPPED',
  last_error = 'Fix-54: session corruption death loop — manual triage'
WHERE sprint_id = 3010 AND status IN ('PENDING','RUNNING');

UPDATE sprints SET status = 'CANCELLED', updated_at = NOW(),
  description = COALESCE(description,'') || E'\n[Fix-54: cancelled — session corruption death loop]'
WHERE id = 3010;

-- Sprint 3019 tasks → SKIPPED, sprint → CANCELLED
UPDATE sprint_tasks SET status = 'SKIPPED',
  last_error = 'Fix-54: session corruption death loop — manual triage'
WHERE sprint_id = 3019 AND status IN ('PENDING','RUNNING');

UPDATE sprints SET status = 'CANCELLED', updated_at = NOW(),
  description = COALESCE(description,'') || E'\n[Fix-54: cancelled — session corruption death loop]'
WHERE id = 3019;
```

**Verify**: `SELECT id, name, status FROM sprints WHERE id IN (3010, 3019);` → both CANCELLED.

---

### Phase 2: Increase Task Timeout for Deps Sprints

**File**: [autonomous_sprint_executor.py:184](backend/app/services/autonomous_sprint_executor.py#L184)

**Change 1** — Add category-aware timeout constant:
```python
MAX_TASK_TIMEOUT_MINUTES = 15  # Default
MAX_TASK_TIMEOUT_MINUTES_DEPS = 30  # Extended for dependency upgrades
```

**Change 2** — [autonomous_sprint_executor.py:307-309](backend/app/services/autonomous_sprint_executor.py#L307-L309): Make `_check_for_timed_out_tasks` select timeout based on sprint name:
```python
# After line 305 (self._last_timeout_check = now), before the get_stuck_tasks call:
sprint_name = ""
if self._state and self._state.sprint:
    sprint_name = getattr(self._state.sprint, "name", "") or ""
timeout_minutes = self.MAX_TASK_TIMEOUT_MINUTES_DEPS if sprint_name.startswith("Deps-") else self.MAX_TASK_TIMEOUT_MINUTES

# Line 308-309: pass timeout_minutes instead of the constant
timed_out_tasks = await self.sprint_manager.get_stuck_tasks(
    max_running_minutes=timeout_minutes
)
```

**Change 3** — [autonomous_sprint_executor.py:320-323](backend/app/services/autonomous_sprint_executor.py#L320-L323): Use `timeout_minutes` in the error message:
```python
timeout_msg = (
    f"Task timed out after {running_minutes:.1f} minutes "
    f"(limit: {timeout_minutes} minutes). "
    f"Task may be stuck or taking too long to complete."
)
```

---

### Phase 3: Add Per-Package Failure Dedup to Dependency Review

**File**: [dependency_review_service.py:311](backend/app/services/dependency_review_service.py#L311)

**Change 1** — After the circuit breaker check (line 311) and before the sprint number query (line 313), add a per-package dedup query:
```python
# Per-package failure dedup: skip packages that failed in the last 7 days
recently_failed_packages: set = set()
try:
    import re as _re
    failed_tasks_result = await self.db.execute(
        select(SprintTaskDB.title)
        .join(SprintDB, SprintTaskDB.sprint_id == SprintDB.id)
        .where(
            SprintDB.project_id == project_id,
            SprintDB.name.like("Deps-%"),
            SprintTaskDB.status == TaskStatus.FAILED,
            SprintTaskDB.completed_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7),
        )
    )
    for (title,) in failed_tasks_result.all():
        pkg_match = _re.search(r"Upgrade\s+(\S+)\s+", title or "")
        if pkg_match:
            recently_failed_packages.add(pkg_match.group(1).lower())
    if recently_failed_packages:
        logger.info(
            f"[DepsReview] Excluding {len(recently_failed_packages)} recently-failed packages: "
            f"{sorted(recently_failed_packages)[:10]}"
        )
except Exception as dedup_err:
    logger.debug(f"[DepsReview] Failure dedup query error: {dedup_err}")
```

**Change 2** — [dependency_review_service.py:651-656](backend/app/services/dependency_review_service.py#L651-L656): Add `excluded_packages` parameter to `_build_tasks_from_findings`:
```python
def _build_tasks_from_findings(
    self,
    findings: List[ProjectDependencyDB],
    project_name: str,
    excluded_packages: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Group findings into sprint tasks by type/severity."""
    excluded = excluded_packages or set()
    # Filter out excluded packages
    findings = [f for f in findings if f.name.lower() not in excluded]
    if not findings:
        return []
    tasks: List[Dict[str, Any]] = []
    # ... rest unchanged
```

**Change 3** — [dependency_review_service.py:338](backend/app/services/dependency_review_service.py#L338): Pass the set to the builder:
```python
tasks = self._build_tasks_from_findings(findings, project_name, excluded_packages=recently_failed_packages)
if not tasks:
    logger.info(f"No actionable findings for project {project_id} after dedup — no sprint needed")
    return None
```

Required imports at top of file (add if not present): `SprintTaskDB` from `app.models.sprint_execution`, `TaskStatus` from `app.models.sprint_execution`.

---

### Phase 4: Fix Read-Only Filesystem for AIContentTools

**File**: [docker-compose.yml:200](docker-compose.yml#L200)

**Change**: Remove `:ro` suffix to match the other 3 managed projects:
```yaml
# Before:
- ${AITOOLS_PATH:-C:/code/AIContentTools}:/managed/aicontenttools:ro
# After:
- ${AITOOLS_PATH:-C:/code/AIContentTools}:/managed/aicontenttools
```

---

### Phase 5: Rebuild & Restart Backend

```bash
docker-compose build legion-backend && docker-compose up -d legion-backend
# Wait 30s for healthy startup
sleep 30
curl -s http://localhost:8005/health | python -m json.tool
docker logs legion-backend --tail 30 2>&1 | grep -iE "error|fail|stuck"
```

**Verify**:
- Health returns 200 with `"database": "connected"`
- No "the connection is closed" errors
- Sprint creation gate still `safe`

---

### Phase 6: Run Controlled Test Sprints with QA

Create 3 simple, achievable sprints manually via API and monitor E2E execution.

**Sprint A — "Test-13: Verify sprint completion pipeline"**
- Project: Legion (id=3)
- 2 trivial tasks: add a comment to two files
- Expected: completes in <3 min, validates the full swarm cycle works

**Sprint B — "Doc-02: Update CLAUDE.md Fix-54 results"**
- Project: Legion (id=3)
- 1 task: update Known Remaining Items section
- Expected: LLM handles simple text edit, completes in <5 min

**Sprint C — "Deps-XX: Safe dependency update for Legion"**
- Project: Legion (id=3)
- 1-2 tasks: only patch-level upgrades with clean history (NOT rich, setuptools, importlib_metadata)
- Expected: script executor handles it without LLM, completes in <10 min with new 30-min timeout

**Monitoring**:
```bash
# Watch sprint transitions
watch -n 5 'docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, name, status, completed_tasks, failed_tasks, total_tasks FROM sprints WHERE id >= 3020 ORDER BY id;"'

# Watch swarm execution
docker logs legion-backend -f 2>&1 | grep -E "\[Swarm\]|COMPLETED|FAILED|timeout"

# After completion, check grade
curl -s http://localhost:8005/api/sprints/{id}/grade | python -m json.tool
```

---

### Phase 7: Track in Sprint-Auditor Skill

Invoke `/legion-sprint-auditor` to:
1. Grade each test sprint across all 7 dimensions
2. Record the Fix-54 findings (session corruption, timeout pattern, dedup gap, read-only mount)
3. Update improvement patterns with the new learnings
4. Compare before/after failure rates

---

## Critical Files

| File | Lines | Change |
|------|-------|--------|
| [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) | 184, 305-323 | Category-aware timeout (15→30 for Deps-) |
| [dependency_review_service.py](backend/app/services/dependency_review_service.py) | 311, 338, 651-656 | Per-package failure dedup (7-day window) |
| [docker-compose.yml](docker-compose.yml) | 200 | Remove `:ro` from AIContentTools mount |

## Verification

1. **Stuck sprints cleared**: `SELECT id, status FROM sprints WHERE id IN (3010, 3019)` → CANCELLED
2. **Timeout extended**: Create a Deps- sprint, check logs for `(limit: 30 minutes)`
3. **Dedup working**: Check logs for `[DepsReview] Excluding N recently-failed packages`
4. **Read-only fixed**: `docker exec legion-backend touch /managed/aicontenttools/.test && docker exec legion-backend rm /managed/aicontenttools/.test` succeeds
5. **Test sprints pass**: All 3 controlled sprints reach COMPLETED status with grade > 70
6. **No regressions**: Non-Deps sprints still use 15-min timeout; sprint creation gate still in `safe` mode
