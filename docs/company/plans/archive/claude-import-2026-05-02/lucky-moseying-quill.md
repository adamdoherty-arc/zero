# Fix-54: Sprint Execution Pipeline — Timeout, QA Gate, and Dedup Fixes

## Context

Deps sprints for ADA Trading Platform (project 6) and Legion (project 3) are failing due to multiple interacting issues:
- Task timeout of 15 min is too short for dependency upgrades (pip, rich, batch updates)
- Cross-sprint timeout contamination: a non-Deps executor kills Deps tasks using the global 15-min limit
- QA gate circular dependency: gate checks `status == COMPLETED` but task is still `RUNNING` at that point
- Verification level `standard`/`full` runs project-wide lint/type checks, producing hundreds of pre-existing failures that reject every task
- Dependency retry storms: same packages keep failing and getting re-created in new sprints
- AIContentTools project mounted read-only, blocking autonomous execution

The user has already written the fixes in 4 files (unstaged). This plan covers: reviewing the fixes for correctness, addressing one bug found during review, building, deploying, cleaning up stuck sprints, and verifying the pipeline works end-to-end.

## Current State

**Stuck sprints:**
- Sprint 3023 (ADA Deps-03) — ACTIVE, 2 tasks stuck in RUNNING (9841, 9845)
- Sprint 3024 (Legion Deps-06) — ACTIVE, 5 tasks PENDING, stalled after 1 failure
- Sprint 3029 (Test-16) — IN_REVIEW, 2/2 completed, stuck waiting for lifecycle promotion

**Sprints 3010 and 3019** — already CANCELLED, no action needed.

**Pending code changes (unstaged, all correct except one bug):**
1. `agent_swarm_service.py` — QA gate fix (pre-mark COMPLETED) + verification level downgrade
2. `autonomous_sprint_executor.py` — 30-min Deps timeout + cross-sprint scoping
3. `dependency_review_service.py` — 7-day per-package failure dedup
4. `docker-compose.yml` — AIContentTools mount writable

## Plan

### Step 1: Fix phantom sprint bug in dependency_review_service.py
**File:** [dependency_review_service.py:361-367](backend/app/services/dependency_review_service.py#L361-L367)

The sprint is created at line 361 BEFORE task dedup filtering at line 364. If all tasks are filtered out, line 367 returns `None` but leaves an empty sprint in the DB — a phantom sprint (same pattern as Sprint-Cleanup-01/Fix-51).

**Fix:** Move the dedup check BEFORE sprint creation. Build the tasks list first, check if empty, return early before touching the DB.

```python
# Group findings into tasks (excluding recently-failed packages)
tasks = self._build_tasks_from_findings(findings, project_name, excluded_packages=recently_failed_packages)
if not tasks:
    logger.info(f"No actionable findings for project {project_id} after dedup — no sprint needed")
    return None

# Create sprint (only after confirming there are tasks)
manager = SprintManager(self.db)
sprint_data = SprintCreate(...)
sprint = await manager.create_sprint(sprint_data)

for order, task_info in enumerate(tasks, 1):
    ...
```

### Step 2: Cancel stuck sprints via DB

Cancel the 2 stalled sprints and their stuck tasks:

```sql
-- Sprint 3023 (ADA Deps-03): Mark 2 stuck RUNNING tasks as FAILED
UPDATE sprint_tasks SET status = 'FAILED', last_error = 'Fix-54: cancelled stuck task'
WHERE sprint_id = 3023 AND status = 'RUNNING';
UPDATE sprints SET status = 'CANCELLED',
  description = description || E'\n[Fix-54: cancelled — stuck RUNNING tasks]'
WHERE id = 3023;

-- Sprint 3024 (Legion Deps-06): Mark 5 PENDING tasks as SKIPPED
UPDATE sprint_tasks SET status = 'SKIPPED', last_error = 'Fix-54: cancelled stalled sprint'
WHERE sprint_id = 3024 AND status = 'PENDING';
UPDATE sprints SET status = 'CANCELLED',
  description = description || E'\n[Fix-54: cancelled — stalled after timeout]'
WHERE id = 3024;

-- Sprint 3029 (Test-16): Promote from IN_REVIEW to COMPLETED (2/2 tasks done)
UPDATE sprints SET status = 'COMPLETED' WHERE id = 3029 AND status = 'IN_REVIEW';
```

### Step 3: Rebuild and restart backend + verify health

```bash
docker-compose build legion-backend legion-frontend
docker-compose up -d
sleep 15
curl -s http://localhost:8005/health | python -m json.tool
docker logs legion-backend --tail 30
```

### Step 4: Verify fixes are live

1. Check timeout constant is visible:
   ```bash
   docker exec legion-backend python -c "
   from app.services.autonomous_sprint_executor import AutonomousSprintExecutor
   print('Deps timeout:', AutonomousSprintExecutor.MAX_TASK_TIMEOUT_MINUTES_DEPS)
   "
   ```

2. Check verification default is "quick":
   ```bash
   docker exec legion-backend python -c "
   from app.services.agent_swarm_service import tester_node
   # Verify _LEVEL_MAP default is 'quick'
   "
   ```

3. Check dedup query works:
   ```bash
   docker exec legion-db psql -U legion -d legion -c "
   SELECT st.title, st.status FROM sprint_tasks st
   JOIN sprints s ON st.sprint_id = s.id
   WHERE s.name LIKE 'Deps-%' AND s.project_id = 6
   AND st.status = 'FAILED'
   AND st.updated_at > NOW() - INTERVAL '7 days'
   ORDER BY st.updated_at DESC LIMIT 10;
   "
   ```

### Step 5: Track in sprint-auditor skill

Create Fix-54 sprint in Legion DB (project_id=3) with tasks for each fix component.

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| [agent_swarm_service.py](backend/app/services/agent_swarm_service.py) | QA pre-mark + verification level | ~618, ~769-787 |
| [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) | 30-min Deps timeout + sprint scoping | ~132, ~304-340, ~1175 |
| [dependency_review_service.py](backend/app/services/dependency_review_service.py) | Package dedup + phantom fix | ~310-367, ~652-689 |
| [docker-compose.yml](docker-compose.yml) | AIContentTools writable mount | 1 line |

## Verification

1. Backend healthy after rebuild (`/health` returns connected + all daemons alive)
2. Stuck sprints 3023/3024 show CANCELLED in DB
3. Test-16 (3029) shows COMPLETED
4. Next Deps sprint creates with 30-min timeout (visible in logs: `timeout_minutes=30`)
5. Previously-failed packages (protobuf, wrapt, pip, watchdog) are excluded from next Deps sprint
6. No phantom sprints created when all packages are deduped out
