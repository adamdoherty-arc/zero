# Reasoning Capture — Persist All 8 Ephemeral Decision Paths

## Context

Legion auto-generates sprints from 11 different paths (Plan-NN, Fix-NN, Health-NN, Improve-NN, LLM-Fix, Consistency, brain-driven, etc.). Today only **3 of those 11 paths** persist usable reasoning to the database (`PlanGradeDB`, `CouncilVerdictDB`, `LLMCallDetailDB`). The other **8 paths drop their thinking on the floor**:

| # | Path | What's lost |
|---|---|---|
| 1 | `autonomous_brain.BrainDecision` | 100% ephemeral — `self.decisions: List[BrainDecision]` is a Python list, no DB table. Every START_SPRINT / SKIP / ESCALATE / CHAIN_SPRINT / CREATE_FIX_SPRINT decision is lost on container restart. |
| 2 | `root_cause_analysis.cluster_errors()` | Cluster keywords + count are stuffed into `sprint.description` text. Cluster members, similarity threshold, sample errors all in-memory. Can't query "this error pattern recurred 5x in 7 days." |
| 3 | `self_improvement_daemon._report_history` | In-memory list capped at 30 reports. The 4-hour cycle that creates Fix/Health/Consistency sprints leaves zero audit trail across restarts. |
| 4 | `SprintQualityGrade` | In-memory only — **no `SprintQualityGradeDB` table**. Returned in API responses then garbage collected. Can't query "all sprints with `learning_capture < 50`" or trend grades. |
| 5 | `health_sprint_creator.FINDING_PATTERNS` | `[key:finding_key]` tag in description text only. Diagnostic context (Docker logs, subsystem state at the time) not snapshotted with the sprint. |
| 6 | `work_discovery_service.discover_work()` | Priority scoring runs in-memory. The winning sprint doesn't carry "I beat 9 other candidates because…" Losing candidates vanish. |
| 7 | `agentic_loop_service._handle_sprint_failure` | `RollbackHistoryDB` stores WHAT, never WHY. No record of why rollback vs retry vs new Fix sprint was chosen. |
| 8 | `daily_sprint_generator_service` task→area mapping | `PlanGradeDB.improvement_areas` exists, the tasks exist, but the bridge "this task addresses area X" is dropped during decomposition. |

**Goal:** Capture every autonomous decision the system makes from now forward, expose them through one unified `/api/reasoning` endpoint, and surface them in a new **"Reasoning"** tab in the Learning Dashboard. Forward-only — no historical backfill.

**Outcome:** The user can answer "why did Legion just create that Fix sprint?" by clicking through to the originating brain decision / RCA cluster / health finding / grade row, and can audit the system's autonomous behaviour over time.

---

## Architecture

```
┌──────────────────────────────────────────┐
│  8 services persist reasoning rows       │
│  ─────────────────────────────────────   │
│  autonomous_brain          → BrainDecisionDB
│  root_cause_analysis       → RcaClusterDB
│  self_improvement_daemon   → SelfImprovementCycleDB
│  sprint_quality_grader     → SprintQualityGradeDB
│  health_sprint_creator     → HealthFindingSnapshotDB
│  work_discovery_service    → WorkDiscoveryRunDB
│  agentic_loop_service      → RollbackHistoryDB.decision_reason (column add)
│  daily_sprint_generator    → SprintTaskDB.source_improvement_area (column add)
└────────────────┬─────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│  Unified read endpoint                    │
│  GET /api/reasoning/timeline             │
│  GET /api/reasoning/decisions/{kind}     │
│  GET /api/reasoning/sprint/{id}/provenance │
└────────────────┬─────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│  Learning Dashboard → new "Reasoning" tab│
│  - Decision timeline (all 8 sources)     │
│  - Filter by kind / project / time       │
│  - Drill into single decision            │
│  - "Why this sprint?" provenance view    │
└──────────────────────────────────────────┘
```

---

## Phase 1 — New DB Tables (6 new + 2 column extensions)

### Migration: `backend/alembic/versions/029_reasoning_capture.py` (new)

Create one migration file that adds all 6 new tables and 2 new columns. Single migration keeps the change atomic.

### 1. `BrainDecisionDB` — `backend/app/models/brain_decision.py` (new)

Mirrors the existing `BrainDecision` Python class at [autonomous_brain.py:57-83](backend/app/services/autonomous_brain.py#L57-L83):

```
brain_decisions
├── id              SERIAL PK
├── decision_type   VARCHAR(40)  # DecisionType enum (START_SPRINT, SKIP_TASK, …)
├── reason          TEXT
├── confidence      FLOAT          # 0.0–1.0
├── target_id       INTEGER NULL   # sprint_id, task_id, etc.
├── target_kind     VARCHAR(20) NULL  # 'sprint' | 'task' | 'project'
├── project_id      INTEGER NULL FK projects.id
├── cycle_number    INTEGER        # AutonomousBrain.current_cycle
├── brain_state     VARCHAR(20)    # BrainState enum
├── decision_metadata JSONB        # full metadata dict
├── outcome         VARCHAR(20) NULL  # 'success'|'failure'|'pending' (set later by feedback hook)
├── outcome_set_at  TIMESTAMP NULL
└── created_at      TIMESTAMP
```

Indexes: `(project_id, created_at DESC)`, `(decision_type, created_at DESC)`, `(target_kind, target_id)`.

### 2. `RcaClusterDB` — `backend/app/models/rca_cluster.py` (new)

Captures the cluster object that `root_cause_analysis.cluster_errors()` builds at [root_cause_analysis.py:138-158](backend/app/services/root_cause_analysis.py#L138-L158):

```
rca_clusters
├── id                    SERIAL PK
├── signature             VARCHAR(16)    # _signature_for_cluster() output (already exists, just persist it)
├── count                 INTEGER        # cluster size
├── common_keywords       JSONB          # list[str]
├── sample_error          TEXT           # truncated to 500 chars
├── members               JSONB          # full list of {task_id, sprint_id, title, error}
├── similarity_threshold  FLOAT          # 0.25 default — record so we can tune later
├── source_breakdown      JSONB          # {failed_tasks: N, llm_errors: M, docker_events: K}
├── generated_sprint_id   INTEGER NULL FK sprints.id
├── dedup_skipped         BOOLEAN        # true if signature dedup blocked sprint creation
├── circuit_breaker_state JSONB          # {allowed, failure_rate, total, failed, inflight}
└── created_at            TIMESTAMP
```

Indexes: `(signature, created_at DESC)`, `(generated_sprint_id)`.

### 3. `SelfImprovementCycleDB` — `backend/app/models/self_improvement_cycle.py` (new)

Replaces the in-memory `_report_history` list at [self_improvement_daemon.py:39-41](backend/app/services/self_improvement_daemon.py#L39-L41):

```
self_improvement_cycles
├── id                    SERIAL PK
├── started_at            TIMESTAMP
├── completed_at          TIMESTAMP NULL
├── duration_seconds      FLOAT NULL
├── errors_analyzed       INTEGER
├── error_clusters_count  INTEGER
├── docker_errors_24h     INTEGER
├── slow_llm_calls_count  INTEGER
├── dependency_issues_count INTEGER
├── diagnostics_status    VARCHAR(20)
├── diagnostics_unhealthy JSONB
├── sprints_created       JSONB           # [{sprint_id, name, source: 'rca'|'health'|'consistency'}]
├── full_report           JSONB           # the complete report dict for retro analysis
├── status                VARCHAR(20)     # 'success' | 'failed' | 'partial'
└── error_message         TEXT NULL
```

Indexes: `(started_at DESC)`, `(status)`.

### 4. `SprintQualityGradeDB` — `backend/app/models/sprint_quality_grade.py` (new)

Persists what `SprintQualityGrade` already produces at [sprint_quality_grader.py:44-76](backend/app/services/sprint_quality_grader.py#L44-L76):

```
sprint_quality_grades
├── id              SERIAL PK
├── sprint_id       INTEGER FK sprints.id (UNIQUE — one grade per sprint, latest wins)
├── overall_score   FLOAT
├── dimensions      JSONB          # full dimensions dict (per-dim score, weight, weighted, details)
├── task_decomposition_score   FLOAT  # denormalized for easy querying
├── prompt_quality_score       FLOAT
├── routing_effectiveness_score FLOAT
├── execution_success_score    FLOAT
├── learning_capture_score     FLOAT
├── qa_gate_score              FLOAT
├── time_efficiency_score      FLOAT
├── triggered_improve_sprint_id INTEGER NULL FK sprints.id  # the Improve-NN spawned by auto-grade hook (if any)
├── graded_at       TIMESTAMP
└── grader_version  VARCHAR(20)    # bump when grading formula changes
```

Indexes: `(sprint_id)` UNIQUE, `(overall_score)`, `(graded_at DESC)`, plus per-dimension indexes for "show me low learning_capture sprints" queries.

### 5. `HealthFindingSnapshotDB` — `backend/app/models/health_finding_snapshot.py` (new)

Snapshots the diagnostic context `health_sprint_creator` had at the moment a Health-NN was filed:

```
health_finding_snapshots
├── id                  SERIAL PK
├── finding_key         VARCHAR(80)    # the existing tag, now first-class
├── finding_title       VARCHAR(200)
├── severity            VARCHAR(20)    # critical | high | medium | low
├── source              VARCHAR(40)    # 'docker_log_monitor' | 'self_diagnostics' | 'agentic_stale'
├── pattern_matched     VARCHAR(80)    # which FINDING_PATTERNS regex hit
├── diagnostic_context  JSONB          # snapshot of relevant subsystem state at finding time
├── triggered_sprint_id INTEGER NULL FK sprints.id
├── dedup_skipped       BOOLEAN        # true if 48h dedup blocked sprint creation
└── created_at          TIMESTAMP
```

Indexes: `(finding_key, created_at DESC)`, `(triggered_sprint_id)`.

### 6. `WorkDiscoveryRunDB` — `backend/app/models/work_discovery_run.py` (new)

Captures all candidates `work_discovery_service.discover_work()` considered, not just the winner:

```
work_discovery_runs
├── id                   SERIAL PK
├── project_id           INTEGER FK projects.id
├── trigger              VARCHAR(40)    # 'agentic_loop' | 'manual' | 'self_improve'
├── sources_queried      JSONB          # list[str] of the 10 sources
├── candidates           JSONB          # full list of {source, item, priority_score, dedup_status}
├── winner_index         INTEGER NULL   # index into candidates of the chosen item
├── winner_sprint_id     INTEGER NULL FK sprints.id
├── total_candidates     INTEGER
├── filtered_count       INTEGER
├── dedup_drops          INTEGER
└── created_at           TIMESTAMP
```

Indexes: `(project_id, created_at DESC)`.

### Column extensions (no new tables)

7. **`RollbackHistoryDB`** — add `decision_reason TEXT` and `alternatives_considered JSONB` columns. Already exists; just ALTER TABLE in the same migration.

8. **`SprintTaskDB`** — add `source_improvement_area JSONB NULL` column. When `daily_sprint_generator` decomposes an improvement area into N tasks, each task carries `{area_name, area_priority, area_description}` so the task→area bridge is queryable.

### `backend/app/models/__init__.py` — export all 6 new models

---

## Phase 2 — Service Modifications (write paths)

The pattern for every service: open a fresh `AsyncSessionLocal()`, write the row, swallow exceptions with `logger.warning` (per the "learning aggregator was 100% silent" rule from MEMORY.md — never log at debug, always warn). All writes are non-blocking — failure to persist reasoning must NEVER block the actual sprint creation.

### A. [autonomous_brain.py](backend/app/services/autonomous_brain.py)
- Add new helper `_persist_decision(decision: BrainDecision, project_id: int|None)` that writes to `BrainDecisionDB`.
- Find every place that constructs a `BrainDecision(...)` and `self.decisions.append(...)` and immediately call `await self._persist_decision(...)`.
- Add a new `_record_decision_outcome(decision_id, outcome)` hook that backfills `outcome` on a previously persisted row when a decision later succeeds/fails (called from `_learn_from_outcomes` at line 162).

### B. [root_cause_analysis.py](backend/app/services/root_cause_analysis.py)
- In `cluster_errors()` (line 77), after building `results`, write each cluster as a `RcaClusterDB` row and inject the new `id` into the dict (so callers can later set `generated_sprint_id`).
- In `generate_fix_sprint()` (line 184), after creating the sprint, UPDATE the corresponding `RcaClusterDB.generated_sprint_id`.
- When the dedup gate (line 198-218) skips, still write the cluster row with `dedup_skipped=true`.
- When the circuit breaker blocks (line 233-253), still write the cluster row with `circuit_breaker_state` populated.

### C. [self_improvement_daemon.py](backend/app/services/self_improvement_daemon.py)
- Replace the in-memory `_report_history` (line 39-41) with DB writes.
- At the start of `daily_cycle()` (line 43), insert a `SelfImprovementCycleDB` row with `status='running'` and capture the `id`.
- At the end, UPDATE the row with `completed_at`, `duration_seconds`, `full_report`, `sprints_created` list, `status='success'`.
- On exception, UPDATE with `status='failed'`, `error_message`.
- Keep `_report_history` as a 30-item in-memory cache for fast `/health` reads, but the source of truth becomes the DB.

### D. [sprint_quality_grader.py](backend/app/services/sprint_quality_grader.py)
- After `compute_overall()` in `grade_sprint()`, write a `SprintQualityGradeDB` row.
- Use UPSERT semantics (`INSERT … ON CONFLICT (sprint_id) DO UPDATE`) so re-grading the same sprint replaces the previous row instead of duplicating.
- Denormalize the 7 dimension scores into the indexed columns for fast filter queries.
- The auto-grade hook that spawns `Improve-NN` sprints sets `triggered_improve_sprint_id` after the spawn.

### E. [health_sprint_creator.py](backend/app/services/health_sprint_creator.py)
- Inside `_create_health_fix_sprint()`, before the dedup check, write a `HealthFindingSnapshotDB` row capturing the matched pattern, severity, source, and a snapshot of the diagnostic context (Docker log subset, subsystem state).
- After sprint creation, UPDATE the snapshot row with `triggered_sprint_id`.
- When dedup skips (48h window), still write the snapshot with `dedup_skipped=true` so we can see "this finding fired again but was suppressed."

### F. [work_discovery_service.py](backend/app/services/work_discovery_service.py)
- Inside `discover_work()`, after aggregating all 10 sources, write a single `WorkDiscoveryRunDB` row with the full candidate list, dedup drops, and (initially) `winner_sprint_id=NULL`.
- Return the run_id to callers so the agentic loop can update `winner_sprint_id` after it picks one.

### G. [agentic_loop_service.py](backend/app/services/agentic_loop_service.py)
- In `_handle_sprint_failure()` around [line 407-426](backend/app/services/agentic_loop_service.py#L407-L426), when the loop chooses between rollback / retry / new Fix sprint, write the choice and the alternatives into `RollbackHistoryDB.decision_reason` and `RollbackHistoryDB.alternatives_considered`.

### H. [daily_sprint_generator_service.py](backend/app/services/daily_sprint_generator_service.py)
- During task decomposition, when each task is built, set `task.source_improvement_area = {"name": area["area"], "priority": area["priority"], "description": area["description"]}` before the atomic commit.
- This is a one-line addition inside the existing pre-build loop — no new DB writes, just populate the new column.

---

## Phase 3 — Read API: `backend/app/api/endpoints/reasoning.py` (new)

Single new router with three endpoints:

### `GET /api/reasoning/timeline`

Query params: `project_id?`, `kinds?` (comma-separated subset of `brain|rca|self_improve|grade|health|work_discovery|rollback`), `since?` (ISO timestamp), `limit` (default 100).

Returns a unified, time-ordered list of reasoning events. Each event has a discriminated `kind` and a normalized shape:

```json
{
  "events": [
    {
      "kind": "brain",
      "id": 12,
      "timestamp": "2026-04-07T10:30:00",
      "summary": "START_SPRINT (confidence 0.85)",
      "reason": "...",
      "linked_sprint_id": 2891,
      "project_id": 3,
      "details_url": "/api/reasoning/decisions/brain/12"
    },
    {
      "kind": "rca",
      "id": 8,
      "timestamp": "...",
      "summary": "Cluster of 4 errors — keywords: timeout, ollama, connection",
      "linked_sprint_id": 2885,
      "details_url": "/api/reasoning/decisions/rca/8"
    },
    ...
  ],
  "total": 487
}
```

Implementation: 6 parallel SQL queries (one per source table), normalize into the unified shape, sort by timestamp, slice to limit. Wrap in `asyncio.timeout(10)` per the dashboard pattern.

### `GET /api/reasoning/decisions/{kind}/{id}`

Returns the full row for a single reasoning event. `kind` switch dispatches to the right table.

### `GET /api/reasoning/sprint/{sprint_id}/provenance`

Given a sprint ID, returns ALL reasoning events that contributed to its existence:
- The originating `BrainDecisionDB` row (if `target_id == sprint_id`)
- The `RcaClusterDB.generated_sprint_id == sprint_id` row (if Fix-NN)
- The `HealthFindingSnapshotDB.triggered_sprint_id == sprint_id` row (if Health-NN)
- The `SprintQualityGradeDB.triggered_improve_sprint_id == sprint_id` row (if Improve-NN)
- The `WorkDiscoveryRunDB.winner_sprint_id == sprint_id` row (if from work discovery)
- The `PlanGradeDB` row linked via `SprintDB.plan_grade_id` (if Plan-NN)
- All `SprintTaskDB.source_improvement_area` for the tasks

This is the "why does this sprint exist?" view that powers the per-sprint provenance UI.

### Register the router

Add `("reasoning", reasoning.router, "/api/reasoning")` to [backend/app/api/router_registry.py](backend/app/api/router_registry.py).

---

## Phase 4 — Frontend: New "Reasoning" Tab in Learning Dashboard

### `frontend/src/hooks/useReasoning.ts` (new)

Three React Query hooks:
- `useReasoningTimeline(filters)` — calls `/api/reasoning/timeline`, polls every 30s when tab visible, 5min stale time.
- `useReasoningDetail(kind, id)` — calls `/api/reasoning/decisions/{kind}/{id}`, only enabled when both args truthy.
- `useSprintProvenance(sprintId)` — calls `/api/reasoning/sprint/{id}/provenance`.

Follow the existing hook patterns from [useLearning.ts](frontend/src/hooks/useLearning.ts) — visibility-gated polling, retry, staleTime.

### `frontend/src/components/learning/ReasoningTab.tsx` (new)

Layout:
- Top filter bar: project selector, kind multi-select (chips for brain/rca/health/grade/self_improve/work_discovery/rollback), time range (1h/24h/7d/30d).
- Main timeline: vertical list of cards, one per event, sorted newest first. Each card shows kind icon + colored badge, timestamp, one-line summary, linked sprint pill (clickable → opens SprintDetailDialog), confidence bar where applicable.
- Click any card → right-side slide-over panel with the full row JSON pretty-printed + linked entities.
- Empty state: "No reasoning events yet — Legion will start recording its decisions on the next cycle."

### `frontend/src/pages/LearningDashboard.tsx` — add the tab

Insert a new `TabsTrigger value="reasoning">Reasoning</TabsTrigger>` between `decisions` and `features` (so the new tab sits next to the existing decision-related tab). Add the matching `<TabsContent value="reasoning"><ReasoningTab /></TabsContent>`.

### Optional sprint provenance widget (stretch)

Inside `frontend/src/components/sprint/SprintDetailDialog.tsx`, add a small "Why this sprint?" expandable section near the top that calls `useSprintProvenance(sprint.id)` and shows the originating decision/cluster/finding/grade. Pure addition, no rewrites.

---

## Critical Files

**New files (10):**
- [backend/app/models/brain_decision.py](backend/app/models/brain_decision.py)
- [backend/app/models/rca_cluster.py](backend/app/models/rca_cluster.py)
- [backend/app/models/self_improvement_cycle.py](backend/app/models/self_improvement_cycle.py)
- [backend/app/models/sprint_quality_grade.py](backend/app/models/sprint_quality_grade.py)
- [backend/app/models/health_finding_snapshot.py](backend/app/models/health_finding_snapshot.py)
- [backend/app/models/work_discovery_run.py](backend/app/models/work_discovery_run.py)
- [backend/alembic/versions/029_reasoning_capture.py](backend/alembic/versions/029_reasoning_capture.py)
- [backend/app/api/endpoints/reasoning.py](backend/app/api/endpoints/reasoning.py)
- [frontend/src/hooks/useReasoning.ts](frontend/src/hooks/useReasoning.ts)
- [frontend/src/components/learning/ReasoningTab.tsx](frontend/src/components/learning/ReasoningTab.tsx)

**Files to modify (11):**
- [backend/app/models/__init__.py](backend/app/models/__init__.py) — export 6 new models
- [backend/app/services/autonomous_brain.py](backend/app/services/autonomous_brain.py) — persist BrainDecision rows
- [backend/app/services/root_cause_analysis.py](backend/app/services/root_cause_analysis.py) — persist clusters + back-link sprint
- [backend/app/services/self_improvement_daemon.py](backend/app/services/self_improvement_daemon.py) — persist daily cycles
- [backend/app/services/sprint_quality_grader.py](backend/app/services/sprint_quality_grader.py) — persist grades (UPSERT)
- [backend/app/services/health_sprint_creator.py](backend/app/services/health_sprint_creator.py) — persist finding snapshots
- [backend/app/services/work_discovery_service.py](backend/app/services/work_discovery_service.py) — persist discovery runs
- [backend/app/services/agentic_loop_service.py](backend/app/services/agentic_loop_service.py) — write decision_reason
- [backend/app/services/daily_sprint_generator_service.py](backend/app/services/daily_sprint_generator_service.py) — set task.source_improvement_area
- [backend/app/api/router_registry.py](backend/app/api/router_registry.py) — register reasoning router
- [frontend/src/pages/LearningDashboard.tsx](frontend/src/pages/LearningDashboard.tsx) — add Reasoning tab

**Reused existing utilities:**
- `AsyncSessionLocal` from [backend/app/core/database.py](backend/app/core/database.py) — fresh session per write (per CLAUDE.md rule)
- `_signature_for_cluster()` already exists at [root_cause_analysis.py:164-182](backend/app/services/root_cause_analysis.py#L164-L182) — just persist its output
- React Query patterns from [useLearning.ts](frontend/src/hooks/useLearning.ts)
- Tabs/Card primitives from existing [LearningDashboard.tsx](frontend/src/pages/LearningDashboard.tsx)

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Reasoning writes block sprint creation if DB is slow | Every write wrapped in `try/except logger.warning` — never raise. Sprint creation must always succeed even if reasoning persist fails. |
| Brain decision writes inside the 30s cycle slow the loop | Each write is a single INSERT in a fresh session — sub-10ms. Brain currently does ~3-5 decisions per cycle, so worst case +50ms per cycle (negligible vs 30s interval). |
| `WorkDiscoveryRunDB` rows accumulate fast (every 30s × N projects) | Add a daily cleanup in `sprint_cleanup` daemon (already runs at 3:30 AM UTC) that deletes runs older than 30 days. Add to migration as a TODO comment. |
| Migration 029 fails on a fresh DB | Test with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` before deploy. Per CLAUDE.md migration rules. |
| Frontend tab pulls 6 tables on every poll | Backend timeline endpoint runs the 6 queries in parallel via `asyncio.gather` and caches the result for 10s in-process. Keeps p95 < 500ms. |
| `SprintQualityGradeDB.dimensions` JSONB grows large | Each grade is ~2KB. 1000 sprints/month = 2MB/month. Negligible. |
| Schema drift between Python `BrainDecision` class and `BrainDecisionDB` | Keep both — `BrainDecision` stays as the in-memory working object, `_persist_decision()` is the one place that maps it to the ORM. Single conversion point = single source of drift. |

---

## Verification

After implementation, verify in this order:

### 1. Migration applies cleanly
```bash
cd backend && alembic upgrade head
docker exec legion-db psql -U legion -d legion -c "\dt" | grep -E "brain_decisions|rca_clusters|self_improvement_cycles|sprint_quality_grades|health_finding_snapshots|work_discovery_runs"
```
Expect all 6 tables present.

### 2. Rebuild + restart
```bash
docker-compose build legion-backend legion-frontend && docker-compose up -d
docker logs legion-backend --tail 50 | grep -i "error\|reasoning"
```
Expect zero errors mentioning the new models.

### 3. Spontaneous brain decision capture (60s rule from MEMORY.md)
```bash
sleep 60
docker exec legion-db psql -U legion -d legion -c "SELECT id, decision_type, confidence, target_id FROM brain_decisions ORDER BY id DESC LIMIT 5;"
```
Expect at least 1 row — if zero, the wiring is broken. Per the Recovery-01 verification rule, if it doesn't fire spontaneously in 60s, the wiring is wrong.

### 4. RCA cluster persisted on next failure
Wait for or force a sprint failure, then:
```bash
docker exec legion-db psql -U legion -d legion -c "SELECT id, signature, count, generated_sprint_id, dedup_skipped FROM rca_clusters ORDER BY id DESC LIMIT 5;"
```
Expect cluster rows linked to Fix-NN sprints.

### 5. Sprint quality grade persisted
After any sprint completes:
```bash
docker exec legion-db psql -U legion -d legion -c "SELECT sprint_id, overall_score, learning_capture_score, qa_gate_score FROM sprint_quality_grades ORDER BY graded_at DESC LIMIT 5;"
```
Expect a row for the just-completed sprint.

### 6. API endpoint
```bash
curl -s http://localhost:8005/api/reasoning/timeline?limit=20 | python -m json.tool
curl -s http://localhost:8005/api/reasoning/sprint/2891/provenance | python -m json.tool
```
Expect a non-empty `events` array with mixed kinds.

### 7. Frontend tab renders
- Open http://localhost:3005/learning
- Click "Reasoning" tab
- Verify timeline cards render
- Click a card → slide-over opens with full JSON
- Filter by `kind=brain` → only brain decisions shown
- Filter by `kind=rca` → only clusters shown

### 8. Provenance trace
- Open Sprint Center, pick a recently auto-generated sprint
- Verify "Why this sprint?" section in detail dialog shows the originating decision/cluster/finding

### 9. No regressions
```bash
cd backend && python -m pytest tests/services/ -v -k "not Semaphore" --deselect tests/services/test_sprint_manager.py::TestSprintStatusValues --deselect tests/services/test_sprint_manager.py::TestTaskStatusValues
cd frontend && npm run build
```
Expect existing tests still pass and frontend type-checks clean.

### 10. Sprint creation still works under reasoning persist failure
Temporarily add `raise Exception("test")` inside one persist helper, run a brain cycle, verify the sprint is still created and the warning is logged but does NOT fail the cycle. Then revert.

---

## Sprint Tracking

Per the CLAUDE.md "All Changes Managed Through Legion" rule, this work should be tracked as a sprint in Legion's database (`project_id=3`):

- **Suggested name:** `Observe-03: Reasoning capture for all 8 ephemeral decision paths`
- **Category:** `Observe` (matches the existing Observe-01 daily standup and Observe-02 OpenTelemetry sprints)
- **Story points:** ~13 (6 tables + 8 service modifications + 1 endpoint + 1 frontend tab)
- **Status start:** `PLANNED` → `ACTIVE` when work begins
