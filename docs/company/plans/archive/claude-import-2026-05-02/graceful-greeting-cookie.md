# Sprint-Cleanup-02: Cleanup + Controlled Sprint Creation Gate

## Context

Legion is creating sprints faster than it can execute them, and a large fraction of auto-created sprints fail. The user wants a controlled-execution mode that pauses almost all automatic sprint creation until we have a stable process and zero failing sprints.

**Current state (from live PostgreSQL inspection on 2026-04-07):**

- **245 sprints total** — 165 COMPLETED (67%), **61 FAILED (25%)**, 15 CANCELLED, 3 ACTIVE, 1 PLANNED
- **3 stalled ACTIVE Auto-Sprints**: 2895, 2903, 2904 — all 0% complete, blocking the queue
- **272 PENDING tasks** in the backlog with **0 RUNNING** — pipeline jammed
- **57 sprints created in last 24h** — agentic loop cycles every ~35s
- **Auto-Sprint category: 27/42 FAILED last 7d (64% failure)** — biggest spammer
- **Fix-NN category: 6/16 FAILED, only 2 COMPLETED** — RCA loop creating sprints that fail
- **Recent infra-failure Fix sprints** (Fix-55/56 MiniMax overload, Fix-58/59 task-stuck) are still escaping the existing `_RCA_INFRA_ONLY_PATTERNS` ignore-list and poisoning the category failure rate

**Why the existing knobs aren't enough:**
- `AGENTIC_MODE=false` is too coarse — also disables project bootstrap, brain, lifecycle daemon
- `LEGION_MAX_CONCURRENT_SPRINTS=1` is an *execution* gate, not a creation gate — sprints still pile up in PLANNED state
- `_RCA_INFRA_ONLY_PATTERNS` + 70% circuit breaker only cover RCA path; 8 other creation paths bypass it entirely
- Per-project health gate kicks in *after* the failure has happened

**Outcome we want:**
- Cleanup the stuck queue and stop the failure rate from being poisoned by infra failures
- Add a single controllable gate that blocks every auto-creation path with one toggle
- Keep manual sprint creation (UI / `POST /api/sprints`) and user-triggered dependency reviews working
- Be able to flip the gate live (no redeploy) when ready to resume

## Strategy

Three layers, in order:

1. **Phase 1 — One-time DB cleanup** (SQL only, no code): cancel stuck sprints, sweep orphaned tasks, reclassify infra-failure FAILED sprints to CANCELLED so they stop poisoning the per-category failure-rate gate.
2. **Phase 2 — New universal creation gate**: a single `LEGION_SPRINT_CREATION_MODE` env var (`paused | safe | on`) plus a tiny in-process gate function checked at the top of every auto-creation entry point. Default `safe` allows only `manual_api` and `dependency_review` sources.
3. **Phase 3 — Live toggle API**: `POST /api/sprints/creation-mode/{mode}` + `GET /api/sprints/creation-mode` so you can flip the gate without restarting the backend.

User confirmed decisions:
- **Throttle level: `safe` mode** — allow `manual_api` + `dependency_review` only
- **Cleanup scope:** cancel stuck Auto-Sprints + reclassify infra-failure FAILED sprints + sweep orphaned PENDING tasks
- **Toggle mechanism:** env var (boot default) + live API endpoint (in-process override)

## Phase 1 — DB Cleanup (SQL only)

Run via `docker exec legion-db psql -U legion -d legion -c "..."`. Read-only inspection results are already captured above; the writes below are intentional.

### 1a. Cancel the 3 stalled ACTIVE Auto-Sprints + 1 PLANNED sprint

```sql
-- Cancel the three known-stuck Auto-Sprints (verified 0/N tasks complete)
UPDATE sprints
SET status = 'CANCELLED',
    updated_at = NOW(),
    description = COALESCE(description, '') || E'\n[Sprint-Cleanup-02: cancelled — 0% progress, queue jammed]'
WHERE id IN (2895, 2903, 2904)
  AND status = 'ACTIVE';

-- Cancel the lone PLANNED sprint as well so the monitor can't auto-promote it
UPDATE sprints
SET status = 'CANCELLED',
    updated_at = NOW(),
    description = COALESCE(description, '') || E'\n[Sprint-Cleanup-02: cancelled — clean slate before throttle]'
WHERE status = 'PLANNED'
  AND project_id = 3;
```

### 1b. Sweep orphaned PENDING tasks inside cancelled/failed sprints to SKIPPED

```sql
-- taskstatus enum has NO 'CANCELLED' (per Sprint-Cleanup-01 memory) — use SKIPPED
UPDATE sprint_tasks
SET status = 'SKIPPED',
    updated_at = NOW(),
    last_error = COALESCE(last_error, '') || ' [Sprint-Cleanup-02: parent sprint cancelled/failed]'
WHERE status = 'PENDING'
  AND sprint_id IN (
    SELECT id FROM sprints WHERE status IN ('CANCELLED', 'FAILED')
  );
```

### 1c. Reclassify recent infra-failure FAILED Fix sprints to CANCELLED

These poisoned the per-category failure rate. Pattern matches the same keywords already in `_RCA_INFRA_ONLY_PATTERNS` plus the two recent ones (`overloaded_error`, `task minutes timed`) that slipped through.

```sql
UPDATE sprints
SET status = 'CANCELLED',
    updated_at = NOW(),
    description = COALESCE(description, '') || E'\n[Sprint-Cleanup-02: infra failure not real failure — reclassified to stop poisoning health gate]'
WHERE status = 'FAILED'
  AND created_at >= NOW() - INTERVAL '14 days'
  AND project_id = 3
  AND (
       lower(COALESCE(last_error, '')) LIKE '%overloaded_error%'
    OR lower(COALESCE(last_error, '')) LIKE '%insufficient_balance%'
    OR lower(COALESCE(last_error, '')) LIKE '%task stuck recovered%'
    OR lower(COALESCE(last_error, '')) LIKE '%task timed out after%'
    OR lower(COALESCE(last_error, '')) LIKE '%task ran for%'
    OR lower(COALESCE(last_error, '')) LIKE '%task minutes timed%'
    OR lower(COALESCE(last_error, '')) LIKE '%minimax api%overloaded%'
    OR lower(COALESCE(description, '')) LIKE '%overloaded_error%'
    OR lower(COALESCE(description, '')) LIKE '%task stuck recovered%'
  );
```

### 1d. Verification queries (read-only)

```sql
-- Should show 0 ACTIVE / 0 PLANNED in project 3 right after Phase 1
SELECT status, COUNT(*) FROM sprints WHERE project_id = 3 GROUP BY status ORDER BY 1;

-- Should show 0 PENDING tasks for cancelled/failed sprints
SELECT COUNT(*) FROM sprint_tasks t
  JOIN sprints s ON t.sprint_id = s.id
 WHERE s.status IN ('CANCELLED','FAILED') AND t.status = 'PENDING';

-- Confirm Fix-NN failure rate dropped after reclassification
SELECT
  COUNT(*) FILTER (WHERE status='FAILED')::float / NULLIF(COUNT(*),0) AS fix_failure_rate,
  COUNT(*) FILTER (WHERE status='FAILED') AS failed,
  COUNT(*) AS total
FROM sprints
WHERE project_id = 3 AND name LIKE 'Fix-%' AND created_at >= NOW() - INTERVAL '7 days';
```

## Phase 2 — Universal Creation Gate

### 2a. New module: [backend/app/services/sprint_creation_gate.py](backend/app/services/sprint_creation_gate.py) (NEW FILE)

Tiny module with:

- A module-level `_runtime_mode: Optional[str] = None` (set by API endpoint, overrides env)
- `MODES = {"paused", "safe", "on"}`
- `SAFE_ALLOWLIST = {"manual_api", "dependency_review"}` (matches user choice)
- `def get_mode() -> str` — returns `_runtime_mode` if set, else `os.getenv("LEGION_SPRINT_CREATION_MODE", "safe").lower()`
- `def set_mode(mode: str) -> str` — validates and sets `_runtime_mode`
- `def is_creation_allowed(source: str, *, category: Optional[str] = None) -> tuple[bool, str]`
  - `paused` → only `source == "manual_api"` allowed
  - `safe` → `source in SAFE_ALLOWLIST`
  - `on` → always allowed
  - Returns `(False, reason)` for blocked, `(True, "ok")` for allowed
- Module-level Prometheus counter: `legion_sprint_creation_blocked_total{source, mode, category}` (reuse existing `prometheus_client` import pattern from `middleware.py`)
- All blocks log at `logger.info` so you can see what's being suppressed without log spam

This module is the only new file. Keep it under 100 lines.

### 2b. Wire the gate into every auto-creation entry point

For each site, add **3 lines** at the very top of the function (after the existing infra-only ignore-list check where one exists). Pattern:

```python
from app.services.sprint_creation_gate import is_creation_allowed
allowed, reason = is_creation_allowed("<source-name>", category="<Category->")
if not allowed:
    logger.info(f"[<Source>] Sprint creation blocked: {reason}")
    return None  # or appropriate "did nothing" return for the function
```

Wire sites and their `source` strings:

| File | Function / line | Source string |
|---|---|---|
| [daily_sprint_generator_service.py:65](backend/app/services/daily_sprint_generator_service.py#L65) | `_generate_sprint_inner` (top) | `"daily_sprint_generator"` |
| [root_cause_analysis.py:284](backend/app/services/root_cause_analysis.py#L284) | `generate_fix_sprint` — **after** the existing `_RCA_INFRA_ONLY_PATTERNS` check at line 297 | `"rca_auto_fix"` |
| [agentic_loop_service.py:507](backend/app/services/agentic_loop_service.py#L507) | Top of the `try:` block before `imp_db.execute(...INSERT INTO sprints...)` at line 533-537 | `"agentic_loop_improve"` |
| [llm_review_service.py:631](backend/app/services/llm_review_service.py#L631) | Inside the high-flagged-rate branch right before `SprintDB(...)` constructor | `"llm_review_fix"` |
| [health_sprint_creator.py:379](backend/app/services/health_sprint_creator.py#L379) | Inside `create_sprints_from_diagnostics` per-finding loop, before `SprintDB(...)` | `"health_diagnostics"` |
| [self_improvement_daemon.py:382](backend/app/services/self_improvement_daemon.py#L382) | Inside the `Consistency:` creation branch, before `SprintDB(...)` | `"self_improvement_consistency"` |
| [sprint_chain_service.py:268](backend/app/services/sprint_chain_service.py#L268) | Top of `create_fallback_sprint` | `"recovery_fallback"` |
| [sprint_chain_service.py:195](backend/app/services/sprint_chain_service.py#L195) | Top of `create_next_sprint_in_chain` | `"sprint_chain"` |
| [sprint_orchestrator.py:70](backend/app/services/sprint_orchestrator.py#L70) | Top of `create_autonomous_sprint` | `"sprint_orchestrator"` |
| [sprint_sync_service.py:183](backend/app/services/sprint_sync_service.py#L183) | Before each raw INSERT (lines 183 and 312) | `"sprint_sync"` |
| [autonomous_brain.py:630](backend/app/services/autonomous_brain.py#L630) | Right before the `SprintManager.create_sprint(...)` call inside the brain decision branch | `"autonomous_brain_decision"` |
| [service_health.py:697](backend/app/api/endpoints/service_health.py#L697) | Inside per-finding loop in `POST /api/health/create-sprints` | `"health_endpoint"` |

**Allowlisted sources (NOT gated, must still call manager directly):**

- [sprints.py:104](backend/app/api/endpoints/sprints.py#L104) `POST /api/sprints` — already manual; pass `source="manual_api"` through `SprintCreate` (or just don't gate the endpoint at all — the gate function isn't called from this path).
- [dependency_review_service.py:320](backend/app/services/dependency_review_service.py#L320) `create_update_sprint` — gated, but with `source="dependency_review"` so it survives `safe` mode.
- [sprint_library_service.py:439](backend/app/services/sprint_library_service.py#L439) `create_sprint_from_template` — user-initiated POST, also pass `source="sprint_library"` and add it to `SAFE_ALLOWLIST` if you want template runs to survive safe mode (user picked manual+deps so we leave this OUT of allowlist; templates only run in `on` mode).

### 2c. New env var in [docker-compose.yml](docker-compose.yml)

Add to the `legion-backend` service `environment:` block, near the other `ENABLE_*` flags:

```yaml
LEGION_SPRINT_CREATION_MODE: ${LEGION_SPRINT_CREATION_MODE:-safe}
```

Default `safe` so even a fresh checkout boots in the throttled mode.

## Phase 3 — Live Toggle API

### 3a. New endpoints in [backend/app/api/endpoints/sprints.py](backend/app/api/endpoints/sprints.py)

Add at the end of the file (no router registration changes needed — this router is already wired in `router_registry.py`):

- `GET /api/sprints/creation-mode` → `{"mode": "<current>", "env_default": "<env value>", "runtime_override": <bool>, "allowlist": [...]}`
- `POST /api/sprints/creation-mode` body `{"mode": "paused"|"safe"|"on"}` → calls `set_mode()`, returns the new state. Validate and 400 on bad input.

Both endpoints just call into the gate module — no DB writes, no auth changes (Legion is single-user). Keep them under 30 lines combined.

### 3b. Surface mode in `/health` (optional, 2 lines)

[backend/app/api/endpoints/service_health.py](backend/app/api/endpoints/service_health.py) — in the existing `/health` aggregation, add `"sprint_creation_mode": get_mode()` so you can curl it to verify state.

## Files Modified (summary)

**New files (1):**
- `backend/app/services/sprint_creation_gate.py`

**Edited files (~13):**
- `backend/app/services/daily_sprint_generator_service.py`
- `backend/app/services/root_cause_analysis.py`
- `backend/app/services/agentic_loop_service.py`
- `backend/app/services/llm_review_service.py`
- `backend/app/services/health_sprint_creator.py`
- `backend/app/services/self_improvement_daemon.py`
- `backend/app/services/sprint_chain_service.py`
- `backend/app/services/sprint_orchestrator.py`
- `backend/app/services/sprint_sync_service.py`
- `backend/app/services/autonomous_brain.py`
- `backend/app/services/dependency_review_service.py` (just pass `source="dependency_review"` through)
- `backend/app/api/endpoints/sprints.py` (2 new endpoints)
- `backend/app/api/endpoints/service_health.py` (gate the `POST /create-sprints` path + surface mode in `/health`)
- `docker-compose.yml` (1 new env var)

Each edited service file gets a 3-line gate insertion. Total LOC delta ≈ 80 lines new + 13 × 3 lines = ~120 lines.

## Sprint Tracking

Per CLAUDE.md, register this work as a tracked sprint:

```sql
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES (
  'Sprint-Cleanup-02: Universal creation gate + queue cleanup',
  'Cancel stuck Auto-Sprints, reclassify infra-failure Fix sprints, add LEGION_SPRINT_CREATION_MODE gate (paused|safe|on) checked at every auto-creation entry point, expose live toggle API.',
  3, 'ACTIVE', 1, 4, NOW(), NOW()
);
```

Four tasks: Phase 1 cleanup SQL, Phase 2 gate module + wiring, Phase 3 API endpoints, Phase 4 verification.

## Verification

After Phases 1-3, rebuild + restart per CLAUDE.md (NEVER use `restart` alone — always `build` then `up -d`):

```bash
docker-compose build legion-backend
docker-compose up -d legion-backend
```

### Verification checklist

1. **Gate is wired and defaulted to `safe`:**
   ```bash
   curl -s http://localhost:8005/api/sprints/creation-mode | python -m json.tool
   # Expect: {"mode": "safe", "env_default": "safe", "runtime_override": false, "allowlist": ["manual_api","dependency_review"]}
   ```

2. **No new auto-sprints after restart (watch first 5 minutes):**
   ```bash
   docker logs legion-backend --since 5m 2>&1 | grep -i "Sprint creation blocked"
   # Expect: multiple "blocked" lines from agentic loop, RCA, daily generator
   ```
   ```sql
   -- In a separate terminal, after waiting 5 min:
   SELECT id, name, status, created_at FROM sprints
    WHERE created_at >= NOW() - INTERVAL '5 minutes' ORDER BY id DESC;
   -- Expect: 0 rows (or only manual ones you create)
   ```

3. **Manual creation still works:**
   ```bash
   curl -s -X POST http://localhost:8005/api/sprints \
     -H 'Content-Type: application/json' \
     -d '{"name":"Test-Manual-01: gate verification","description":"verify manual still works","project_id":3,"priority":3}'
   # Expect: 200 with new sprint id
   ```

4. **Live toggle works without restart:**
   ```bash
   curl -s -X POST http://localhost:8005/api/sprints/creation-mode \
     -H 'Content-Type: application/json' -d '{"mode":"paused"}'
   curl -s http://localhost:8005/api/sprints/creation-mode
   # Expect: mode=paused, runtime_override=true
   curl -s -X POST http://localhost:8005/api/sprints/creation-mode \
     -H 'Content-Type: application/json' -d '{"mode":"safe"}'
   ```

5. **Cleanup landed:**
   ```sql
   SELECT status, COUNT(*) FROM sprints WHERE project_id = 3 GROUP BY status ORDER BY 1;
   -- Expect: 0 ACTIVE, 0 PLANNED in project 3 immediately after cleanup;
   -- ACTIVE may go back to 1 if you ran the manual test sprint above.
   ```

6. **Failure rate stopped being poisoned:**
   ```sql
   SELECT COUNT(*)::float FILTER (WHERE status='FAILED') / NULLIF(COUNT(*),0) AS fix_failure_rate
   FROM sprints WHERE project_id=3 AND name LIKE 'Fix-%' AND created_at >= NOW() - INTERVAL '7 days';
   -- Expect: substantially lower than the 0.375 baseline
   ```

7. **Backend healthy, daemons still alive:**
   ```bash
   curl -s http://localhost:8005/health | python -m json.tool | grep -E '"status"|sprint_creation_mode|agentic'
   ```

## Resume Criteria (when to flip back to `on`)

Flip via `POST /api/sprints/creation-mode` body `{"mode":"on"}` once **all** of these are true:

- 5 consecutive sprints have completed without a single FAILED status
- The 14-day Fix-NN failure rate is below 30%
- `legion_sprint_creation_blocked_total` Prometheus counter has stopped climbing rapidly (means daemons aren't pounding the gate)
- You've explicitly checked the cleanup of any new infra-failure clusters (no new MiniMax overload, no new "task stuck recovered")

Until then, use `safe` (default) for normal operation and `paused` only if you need to do a hard pause (e.g., during a redeploy or when investigating a runaway loop).

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Gate misses a creation path I didn't enumerate | Phase 4 verification step #2 watches the DB for any new sprint in the first 5 min after restart — any unexpected source surfaces immediately |
| Daemons spam the log with "blocked" messages | Use `logger.info` (not warning) and rely on Prometheus counter for volume tracking; no alert rules added |
| RCA still creates sprints because the gate is added *after* the existing infra-pattern check | This is intentional — the existing infra-pattern check is a stronger filter and should fire first; the gate is a backstop |
| Forgot to rebuild after edit (per Sprint-Cleanup-01 memory: `docker-compose restart` ≠ rebuild) | Verification step explicitly says `build` then `up -d`, never `restart` alone |
| Manual sprint creation also goes through `SprintManager.create_sprint` which is NOT gated | This is desired — `POST /api/sprints` is the manual path; not gating `SprintManager.create_sprint` itself preserves manual+library+brain-via-manager paths. The gate sits at the service layer above, where automation lives. |
| User expects also a frontend toggle | Out of scope; the curl recipe above is sufficient until we ship a small UI in a follow-up sprint |

## Out of Scope (deferred to a follow-up)

- Frontend UI control for the mode (Sprint Center could grow a "Creation Mode: safe/paused/on" pill)
- Lengthening daemon cycles (agentic loop ~35s → 5min etc.) — not needed once the gate suppresses creation
- Removing the now-unused `Improve-NN` SQL block — leaving it intact behind the gate so we can re-enable later
- Adding the mode to the `/api/agentic/health-gate/reset` flow — orthogonal concern
