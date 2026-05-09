# Plan: Fix-51 — Complete Execution Pipeline Recovery

## Context

**The problem.** Legion's sprint quality audit (run twice on 2026-04-06) revealed an overall health score of **40.8/100** with a **100% task failure rate** across all recent sprints (0 completed out of 53 tasks across 10 sprints). Every dimension of the learning pipeline was blocked downstream of execution:

- **Execution Success: 14.8/100** — at the floor
- **Learning Capture: 0.0/100** — no episodes for any recent sprint
- **QA Gate: 40.0/100** — only rejections, no approvals
- **Task Decomposition: 76.4/100** — tasks are well-formed; the executor cannot run them

**What we already tried.** A first round of session-isolation fixes (Fix-50) added `_refresh_db_session()` calls in 3 spots inside [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) and replaced the broad `except Exception` at the top-level task handler with specific `TimeoutError` / `greenlet` detection. Result: **task 9295 completed** — the first successful Auto-Sprint task in project history. But:

1. **Two sibling tasks (9292, 9293) still failed** with `Stuck task recovered: Task ran for 6.2 minutes`
2. **The episodes table did NOT grow** despite 9295 completing, because 9295 ran through a different execution path (`sprint_execution_graph`, not `autonomous_sprint_executor`)
3. **Five additional LLM call sites in the autonomous executor still have no session refresh** — the same greenlet bug will fire on any task that hits them

**The intended outcome.** Drive task completion rate from 0% to >50% on the next sprint cycle and unblock all downstream learning subsystems (episodic memory, prompt evaluator, routing optimizer, QA gate). This is a focused 4-area surgical fix — no refactors, no new features.

---

## Findings (from 3 parallel Explore agents)

### Finding 1 — Session corruption is widespread, not localized
After ANY long-running operation (LLM call, `asyncio.timeout()` context, sub-graph execution), the original `AsyncSession` becomes greenlet-corrupt. Subsequent ORM ops raise `greenlet_spawn has not been called`. The **gold-standard fix pattern** lives in [claude_executor.py:317-491](backend/app/services/claude_executor.py#L317-L491): cache ORM attrs BEFORE the LLM call, then open a fresh `async with AsyncSessionLocal() as post_db:` for ALL post-LLM DB writes.

**Five unfixed LLM call sites** remain in [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py):
- [Line ~453](backend/app/services/autonomous_sprint_executor.py#L453) — error analysis LLM in `_get_previous_failures()`
- [Line ~536](backend/app/services/autonomous_sprint_executor.py#L536) — fix generation LLM
- [Line ~814](backend/app/services/autonomous_sprint_executor.py#L814) — direct LLM fallback (followed by `mark_task_completed()` at line 858 — high blast radius)
- [Line ~2233](backend/app/services/autonomous_sprint_executor.py#L2233) — recovery fallback LLM
- [Line ~2681](backend/app/services/autonomous_sprint_executor.py#L2681) — debugging LLM
- [Line ~2823](backend/app/services/autonomous_sprint_executor.py#L2823) — code quality fix LLM

**Plus a coordination hazard**: [sprint_manager.py:861-913](backend/app/services/sprint_manager.py#L861-L913) — `mark_task_completed()` and `mark_task_failed()` use `self.db` directly. If a caller passes a corrupted session (which is exactly what happens after an LLM call without refresh), these methods inherit the corruption and silently fail.

### Finding 2 — Episode storage is broken in `sprint_execution_graph`, not in episodic memory
[episodic_memory_service.py](backend/app/services/episodic_memory_service.py) is correctly implemented (`MIN_QUALITY_FOR_STORAGE = 0.5`, fresh `AsyncSessionLocal`, no bugs). The actual problem lives in [sprint_execution_graph.py:1144-1166](backend/app/services/sprint_execution_graph.py#L1144-L1166) — the `extract_learnings` node:

```python
# Line 1145 — test_passed defaults to None (falsy), so this gate is closed by default
if test_passed and project_id:
    try:
        ...
        await mem.store_episode(...)
        logger.debug(f"[Graph] Episode stored ...")   # Line 1164 — DEBUG = INVISIBLE
    except Exception as e:
        logger.debug(f"[Graph] Episode storage skipped: {e}")  # Line 1166 — DEBUG = INVISIBLE
```

Two compounding bugs:
1. **`test_passed` defaults to `None`** (a falsy value). It is only set to `True` somewhere upstream — but [verify_task_qa](backend/app/services/sprint_execution_graph.py#L1045) can override it to `False` and never sets it back to `True` on the success path.
2. **Both success and failure log at DEBUG level**, so we have zero visibility into what's happening. After task 9295 completed, episodes count stayed at 67 — a silent failure we can't even diagnose.

### Finding 3 — Sprint decomposition has a data-consistency hole
Sprint 2848 has `total_tasks=7` in the `sprints` table but **0 actual rows** in `sprint_tasks`. Root cause is non-atomic creation in [daily_sprint_generator_service.py:128-177](backend/app/services/daily_sprint_generator_service.py#L128-L177):

1. Line 137: `total_tasks = len(task_dicts)` is set before validation
2. Line 142: `await db.flush()` — sprint row committed (Commit Point A)
3. Lines 145-174: Each task validated via `_is_prompt_actionable()` (which can drop ALL tasks if VAGUE_MARKERS match)
4. Line 175: Recalculation happens, but if the validation loop crashes between flush and recalc, the sprint exists with `total_tasks=7` and zero children

This is independent of the execution bug but causes phantom sprints that the agentic loop loops on forever.

### Finding 4 — Timeout is observed, not configured
`MAX_TASK_TIMEOUT_MINUTES = 15` ([autonomous_sprint_executor.py:170](backend/app/services/autonomous_sprint_executor.py#L170)). The "6.2 minutes" message in `Stuck task recovered: Task ran for 6.2 minutes` is the **actual elapsed time** when the stuck-task watchdog cycle fired — NOT the timeout limit. So the issue isn't aggressive timeouts; it's that tasks are silently dying mid-execution and the watchdog correctly cleans them up. Fixing Findings 1+2 will eliminate most of these.

---

## Implementation

### Section A — Complete session isolation in autonomous_sprint_executor (Finding 1)

**Pattern to apply at every LLM call site** (mirroring [claude_executor.py:317-491](backend/app/services/claude_executor.py#L317-L491)):

```python
# 1. Cache ORM attrs BEFORE the LLM call
task_id = task.id
sprint_id = task.sprint_id
task_title = task.title
# ... any other attrs needed after the call

# 2. Make the LLM call
response = await self.llm.execute(...)

# 3. Refresh session
await self._refresh_db_session()

# 4. Re-fetch any ORM objects you still need
task = await self.db.get(SprintTaskDB, task_id)
```

**Files to modify:**
- [backend/app/services/autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) — apply pattern at the 5 unfixed sites:
  - Line ~453 (`_get_previous_failures`)
  - Line ~536 (fix generation)
  - Line ~814 (direct LLM fallback) — **highest priority**, immediately followed by `mark_task_completed()`
  - Line ~2233 (recovery fallback)
  - Line ~2681 (debugging LLM)
  - Line ~2823 (code quality fix)

**Existing utilities to reuse** (do NOT create new helpers):
- `self._refresh_db_session()` at [line 211](backend/app/services/autonomous_sprint_executor.py#L211) — already exists, use everywhere
- `AsyncSessionLocal` from `app.core.database` — fresh-session pattern

### Section B — Make sprint_manager status methods session-resilient (Finding 1)

**Files to modify:**
- [backend/app/services/sprint_manager.py](backend/app/services/sprint_manager.py)
  - [`mark_task_completed()` lines 861-890](backend/app/services/sprint_manager.py#L861-L890)
  - [`mark_task_failed()` lines 892-913](backend/app/services/sprint_manager.py#L892-L913)

**Change**: Instead of using `self.db` directly, both methods open a fresh `AsyncSessionLocal()` and re-fetch the task by id. This makes them safe to call from any caller, regardless of whether the caller's session is corrupted. Pattern:

```python
async def mark_task_completed(self, task_id: int, ...):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as fresh_db:
        task = await fresh_db.get(SprintTaskDB, task_id)
        if task is None:
            return False
        task.status = TaskStatus.COMPLETED
        task.qa_status = "pending_review"
        task.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await fresh_db.commit()
        return True
```

**Why**: This is a one-time defensive fix that protects against ALL future LLM-after-session-corruption regressions, not just the ones we know about.

### Section C — Fix episode storage in sprint_execution_graph (Finding 2)

**Files to modify:**
- [backend/app/services/sprint_execution_graph.py](backend/app/services/sprint_execution_graph.py)

**Two changes:**

**C.1 — Set `test_passed=True` explicitly on the QA success path** at [verify_task_qa around line 1045](backend/app/services/sprint_execution_graph.py#L1045). Currently the function only sets `test_passed=False` on failure; on success it leaves the previous value alone (which may still be `None` from initial state). Add an explicit `state["test_passed"] = True` whenever the verification verdict passes.

**C.2 — Upgrade logging in `extract_learnings`** at [lines 1140-1180](backend/app/services/sprint_execution_graph.py#L1140-L1180):
- Line 1140: `logger.debug` → `logger.info` for "Learning engine outcome recorded"
- Line 1142: `logger.debug` → `logger.warning` for "Learning engine record skipped"
- Line 1164: `logger.debug` → `logger.info` for "Episode stored for future few-shot retrieval" (include `episode_id` and `quality` in the message)
- Line 1166: `logger.debug` → `logger.warning` for "Episode storage skipped" (include the exception)
- Line 1180: `logger.debug` → `logger.warning` for "Episode effectiveness tracking skipped"

**C.3 — Add a fallback gate**: If `test_passed is None` but `attempt_count >= 1` and `state.get("cli_output")` is non-empty, treat the task as "passed enough" for episode storage (quality 0.6). Otherwise we lose all the tasks that completed but never explicitly hit the QA verification path.

### Section D — Atomic sprint+task creation (Finding 3)

**Files to modify:**
- [backend/app/services/daily_sprint_generator_service.py](backend/app/services/daily_sprint_generator_service.py)

**Change at [lines 128-177](backend/app/services/daily_sprint_generator_service.py#L128-L177):**

1. Run the validation/filtering loop FIRST (before any DB writes)
2. If `len(filtered_tasks) == 0` after filtering → return without creating the sprint at all
3. Compute `total_tasks = len(filtered_tasks)` from the FINAL list
4. Create the SprintDB row + all SprintTaskDB rows in a single transaction
5. Single `await db.commit()` at the end

**No try/except suppression** — if anything fails, let the exception propagate so the agentic loop sees the failure rather than getting a phantom sprint.

**One-time data cleanup** (script, not part of normal execution): Identify and DELETE phantom sprints where `total_tasks > 0` but no `sprint_tasks` rows exist. SQL:

```sql
DELETE FROM sprints
WHERE total_tasks > 0
  AND id NOT IN (SELECT DISTINCT sprint_id FROM sprint_tasks WHERE sprint_id IS NOT NULL)
  AND status IN ('PLANNED', 'ACTIVE', 'IN_REVIEW');
```

This should be run once after deploying Section D, with a `SELECT COUNT(*)` first to confirm impact.

### Section E — Verification & monitoring (no code changes, just instrumentation review)

Confirm these existing Prometheus counters are exposed and being scraped (they exist already, we just need to monitor them post-fix):
- `legion_episode_stored_total`
- `legion_episodic_retrieval_total`
- `legion_learning_writes_total{store="sprint_learning|enhanced|model_perf"}`
- `legion_session_refresh_total` (add if not present)

If `legion_session_refresh_total` doesn't exist yet, add it as a single-line increment in `_refresh_db_session()`.

---

## Critical Files To Modify

| Section | File | Lines | Purpose |
|---------|------|-------|---------|
| A | [autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py) | 453, 536, 814, 2233, 2681, 2823 | Add session refresh after 6 LLM call sites |
| B | [sprint_manager.py](backend/app/services/sprint_manager.py) | 861-890, 892-913 | Make `mark_task_completed/failed` use fresh session |
| C.1 | [sprint_execution_graph.py](backend/app/services/sprint_execution_graph.py) | ~1045 (`verify_task_qa`) | Set `test_passed=True` on success path |
| C.2 | [sprint_execution_graph.py](backend/app/services/sprint_execution_graph.py) | 1140-1180 (`extract_learnings`) | Upgrade DEBUG logs to INFO/WARNING |
| C.3 | [sprint_execution_graph.py](backend/app/services/sprint_execution_graph.py) | 1144 (gate) | Add fallback gate when `test_passed is None` |
| D | [daily_sprint_generator_service.py](backend/app/services/daily_sprint_generator_service.py) | 128-177 | Atomic sprint+task creation, validate-then-create |

**Reference patterns to copy from (read-only):**
- [claude_executor.py:317-491](backend/app/services/claude_executor.py#L317-L491) — gold-standard session isolation
- [agent_swarm_service.py `advance_task_node`/`mark_failed_node`](backend/app/services/agent_swarm_service.py) — already uses fresh sessions correctly
- [episodic_memory_service.py:46-130](backend/app/services/episodic_memory_service.py#L46-L130) — `store_episode()` is correct as-is, do not modify

---

## Verification

### Build & restart
```bash
docker-compose build legion-backend
docker-compose up -d legion-backend
docker logs legion-backend --tail 50
curl http://localhost:8005/health | python -m json.tool
```

### Smoke test 1 — Single task completion
Wait for the agentic loop to pick a sprint (or trigger one manually). Watch logs for:
```
docker logs legion-backend -f 2>&1 | grep -E "(Episode stored|Stored episode|Task .* completed|greenlet)"
```
**Pass criteria**: At least one `[Graph] Episode stored for future few-shot retrieval` line at INFO level. Zero `greenlet_spawn` errors.

### Smoke test 2 — Database confirmation
```bash
docker exec legion-db psql -U legion -d legion -c "
  SELECT COUNT(*) AS recent_episodes
  FROM episodes
  WHERE created_at > NOW() - INTERVAL '1 hour';
"
```
**Pass criteria**: `recent_episodes > 0` after one full sprint cycle.

### Smoke test 3 — No phantom sprints
```bash
docker exec legion-db psql -U legion -d legion -c "
  SELECT s.id, s.name, s.total_tasks, COUNT(t.id) AS actual_tasks
  FROM sprints s
  LEFT JOIN sprint_tasks t ON t.sprint_id = s.id
  WHERE s.created_at > NOW() - INTERVAL '6 hours'
  GROUP BY s.id, s.name, s.total_tasks
  HAVING s.total_tasks <> COUNT(t.id);
"
```
**Pass criteria**: 0 rows returned (no mismatches between `total_tasks` and actual count).

### Smoke test 4 — Re-run sprint quality audit
```bash
# Trigger via the legion-sprint-auditor skill or directly:
curl -s "http://localhost:8005/api/sprint-quality/grade-recent?limit=10" | python -m json.tool
```
**Pass criteria**:
- Overall health > 50/100 (up from 40.8)
- Execution Success > 30/100 (up from 14.8)
- Learning Capture > 10/100 (up from 0.0)
- At least 1 sprint with completion rate > 0%

### Smoke test 5 — Backend tests still green
```bash
cd backend && python -m pytest tests/services/test_autonomous_sprint_executor.py tests/services/test_sprint_manager.py tests/services/test_episodic_memory.py -v
```
**Pass criteria**: No new failures vs. baseline.

---

## Out of Scope (deliberately deferred)

- ❌ Refactoring `autonomous_sprint_executor.py` (3518 lines) — researched but too risky
- ❌ Email notifications (Discord works fine)
- ❌ Prompt evaluator daemon debug — separate sprint after execution is unblocked
- ❌ Sprint manager full rewrite — only the 2 status methods get touched
- ❌ Adding new tests beyond verifying existing ones still pass — defer to a follow-up Test sprint
- ❌ Touching `episodic_memory_service.py`, `agent_swarm_service.py`, `claude_executor.py` — they're correct
