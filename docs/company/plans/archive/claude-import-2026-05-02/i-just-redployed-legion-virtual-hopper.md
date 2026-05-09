# Legion Recovery — Post-Redeploy Data Loss Audit & Fix

## Context

You redeployed Legion and found the UI empty: projects, sprints, plans, Learn/Fix/Audit history, and everything else from CLAUDE.md's sprint audit trail are gone. After a deep investigation of the running system, the disk, volumes, logs, migrations, and backup infrastructure, here's what actually happened and what it takes to get Legion fully operational again.

### What the data actually shows (current state, 2026-04-22 03:20Z)

- **Containers**: All healthy — `legion-backend`, `legion-frontend`, `legion-db`, `legion-redis`, `legion-qdrant`, `legion-litellm` up for ~5–13 minutes.
- **Postgres volume `legion-postgres-data`**: Same volume since 2026-01-09. `PG_VERSION` file unchanged since Jan 9. Data files on disk have modern mtimes from today's activity. **The volume was never wiped by this redeploy.**
- **Legion DB contents**:
  - 5 projects (Legion=1, Ollama Manager=2, GPU Manager=3, ProfStudio=4, ADA=5) — **all created 2026-04-22 03:12:05**, one minute after backend startup.
  - 1 sprint: `Infra-04: Direct vLLM routing + compose env wiring` (created 03:14 today post-redeploy).
  - 8 plans (seeded defaults), 16 prompt templates (seeded defaults), 2 llm_call_details.
  - 115 non-LiteLLM tables present (most of the schema is there via `create_all()`).
  - `alembic_version = 001_baseline` — **wrong** (real schema is way past baseline).
- **Missing tables** referenced by running code (observed as errors in backend logs):
  - `project_scans` (referenced by `work_discovery_service._get_brain_suggestions`)
  - `episodic_memories` (Migration 020 — but may be aliased as `episodes` in the model, which does exist)
- **No backup exists anywhere**:
  - `legion-backups` volume was only created **today at 2026-04-22T03:19:27Z** (same redeploy).
  - `docker/db-backup.sh` runs `sleep 86400; backup` — so the first backup would not have run yet anyway. Bootstrap ordering is wrong.
  - No `*.sql`, `*.sql.gz`, `*.dump` files anywhere under `c:\code\Legion` or `C:\Users\hadam`.

### Why the data disappeared (root cause)

The boot log from `legion-backend` at startup shows it exactly:

```
Running database migrations...
  Existing database detected (66 tables) — stamping baseline...
  Running stamp_revision  -> 001_baseline
  [OK] Stamped baseline
  Running upgrade 001_baseline -> 002_add_sprint_task_columns
  File "/app/alembic/versions/002_add_sprint_task_columns.py", line 34, in upgrade
    ...
  [WARN] Migration upgrade returned non-zero
```

Translation:
1. **Something cleared the business data** from the Legion DB *before* this redeploy. Most likely an earlier `python -c "init_db(drop_all=True)"` or `TRUNCATE`-equivalent, but no direct evidence in the container logs. The schema survived partially (66 tables were still present from prior `create_all()`) but the `alembic_version` table was gone.
2. **On redeploy, `backend/docker-entrypoint.sh`** (see [docker-entrypoint.sh](backend/docker-entrypoint.sh#L80-L91)) hit the middle branch (tables exist but no alembic_version), stamped at `001_baseline`, and tried `alembic upgrade head`.
3. **Migration 002 crashed** because `sprint_tasks.updated_at` / `story_points` already existed (prior `create_all()` had added them). Every subsequent migration was skipped.
4. **Backend startup continued** regardless (`|| echo "[WARN]"`), `init_db()` hadn't been called in the middle branch, and `project_bootstrap` + `plan_service.seed_default_plans()` re-created the default 5 projects and 8 plans at 03:12–03:13.
5. **The app is technically running** — agentic loop is cycling (Cycle 6 at 03:17, project 1 selected, score=6.0), smoke tests pass, LLM calls succeed — but the history in CLAUDE.md (Learn-19, Audit-Remediation-01, Fix-46, etc.) is **gone for good** and the Alembic state is wrong.

### The real answer to "how do we get it back"

- **The history cannot be restored.** There's no backup anywhere (disk, volume, cloud, git). The `legion-db-backup` daily service was only added/activated today, so it never ran before the wipe.
- **What we can recover**: get Legion's schema + migrations correctly aligned, resume the agentic loop cleanly, re-seed the Learn-18/19 canary rows so Ollama re-introduction keeps working, and put real backups in place so this never happens again.

---

## Plan

### Step 1 — Snapshot current state (forensic pg_dump)

Before any changes, capture what's there in case we want to diff later.

```bash
# Dump the current legion DB to host filesystem
docker exec legion-db pg_dump -U legion -d legion --format=custom --compress=6 -f /tmp/legion_postwipe_20260422.dump
docker cp legion-db:/tmp/legion_postwipe_20260422.dump ./legion_postwipe_20260422.dump
```

### Step 2 — Drop and recreate the Legion DB cleanly

Schema is in a half-broken state (Alembic says baseline, real schema is beyond 037, `project_scans` missing, `episodic_memories` missing). The data is already gone; the cleanest path is to let `init_db()` rebuild the schema from `app.models` and Alembic stamp `head`. This is the same "Fresh DB" branch of `docker-entrypoint.sh`.

```bash
# Stop backend (leave DB up)
docker-compose stop legion-backend

# Drop and recreate the legion database
docker exec legion-db psql -U legion -d postgres -c "DROP DATABASE legion WITH (FORCE);"
docker exec legion-db psql -U legion -d postgres -c "CREATE DATABASE legion OWNER legion;"

# Restart backend — docker-entrypoint will take the "Fresh DB" branch:
#   - init_db() creates all tables from models
#   - alembic stamp head
docker-compose start legion-backend
docker logs legion-backend -f 2>&1 | head -200
```

Expected log output:

```
Fresh database — creating schema from models...
  [OK] Schema created via create_all()
  [OK] Stamped at head
```

### Step 3 — Verify schema and migration alignment

```bash
# Alembic must report the latest revision, not 001_baseline
docker exec legion-backend alembic current

# Must show: 037_queue_infrastructure (head) or whatever the latest revision is
# Listing:
docker exec legion-backend alembic heads
```

Sanity check the previously missing tables now exist:

```bash
docker exec legion-db psql -U legion -d legion -c "
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN (
    'projects','sprints','sprint_tasks','plans',
    'project_scans','episodic_memories','episodes',
    'llm_call_details','prompt_templates','prompt_annotations',
    'chat_sessions','proactive_messages','legion_queue_messages'
  )
ORDER BY table_name;"
```

### Step 4 — Verify bootstrap ran and app is healthy

```bash
# Health endpoint
curl -s http://localhost:8005/health | python -m json.tool | head -50

# Projects seeded
docker exec legion-db psql -U legion -d legion -c "SELECT id, name, path FROM projects ORDER BY id;"

# Plans seeded (should be ~8: Legion, Ollama Manager, GPU Manager, ProfStudio)
docker exec legion-db psql -U legion -d legion -c "SELECT project_id, name, plan_type FROM plans ORDER BY project_id, id;"

# Daemons running
curl -s http://localhost:8005/health | python -c "import json, sys; d=json.load(sys.stdin); print('alive:', d['background_tasks']['alive'], '/', d['background_tasks']['total'])"

# Agentic cycle running (wait ~60s, then look for 'Cycle N' log lines)
docker logs legion-backend --tail 200 2>&1 | grep -E "Scheduler|Agentic cycle" | tail -10

# Smoke test
docker logs legion-backend --tail 200 2>&1 | grep "Smoke tests" | tail -5
```

### Step 5 — Re-seed Learn-18/19 Ollama canary rows (optional but recommended)

Per memory, the Ollama re-introduction infra lived in `prompt_templates` with `provider_override='ollama'` and `canary_traffic_pct` set to 10 for Tier 1 and Tier 2 sources. With the DB reset, those rows are gone. If we want the Tier 1/Tier 2 Ollama routing to keep running, re-seed from [backend/alembic/seed_learn18_canaries.sql](backend/alembic/seed_learn18_canaries.sql) and [backend/scripts/learn19_seed.sql](backend/scripts/learn19_seed.sql).

```bash
docker cp backend/alembic/seed_learn18_canaries.sql legion-db:/tmp/
docker cp backend/scripts/learn19_seed.sql legion-db:/tmp/
docker exec legion-db psql -U legion -d legion -f /tmp/seed_learn18_canaries.sql
docker exec legion-db psql -U legion -d legion -f /tmp/learn19_seed.sql

# Verify
docker exec legion-db psql -U legion -d legion -c "
SELECT slug, provider_override, source_filter, canary_traffic_pct, is_active
FROM prompt_templates
WHERE evolved_by IN ('learn18_seed', 'learn19_seed')
ORDER BY slug;"
```

If either file is missing or doesn't reflect the final Learn-19 state, skip this step — the agentic loop will create its own routing over time via the DSPy/GEPA evolution daemons (`prompt_evaluator`, `dspy_evolution`).

### Step 6 — Fix the backup service so this doesn't happen again

The current `docker/db-backup.sh` runs a daily cadence via `while true; do sleep 86400; ./db-backup.sh; done` in `docker-compose.yml`. That ordering means **the first backup only happens 24 hours after container startup**. If the container restarts, the clock resets. Fix the entrypoint to run the backup FIRST, then sleep.

Change needed in [docker-compose.yml](docker-compose.yml):

```yaml
# Before:
entrypoint: ["/bin/sh", "-c", "while true; do sleep 86400; /backup/db-backup.sh; done"]

# After:
entrypoint: ["/bin/sh", "-c", "while true; do /backup/db-backup.sh || true; sleep 86400; done"]
```

Then:

```bash
docker-compose up -d legion-db-backup
docker logs legion-db-backup  # should show 'Backup completed: /backups/legion_<ts>.sql.gz'

# Verify a backup file exists
docker run --rm -v legion-backups:/b alpine ls -la /b
```

Also add a manual/on-demand backup script helper for operator use under `scripts/db-backup-now.sh` that just runs `docker exec legion-db-backup /backup/db-backup.sh`.

### Step 7 — Create a "Recovery-01" sprint in Legion to track this

Per CLAUDE.md convention, every change to Legion is tracked as a sprint in project_id=1 (Legion). Create:

```sql
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES (
  'Recovery-01: Post-redeploy data loss audit, schema repair, backup fix',
  'DB was wiped before 2026-04-22 redeploy; alembic stuck at 001_baseline; rebuilt schema via drop/recreate + create_all + stamp head; fixed legion-db-backup to run immediately on startup; re-seeded Learn-18/19 canaries.',
  1, 'COMPLETED', 1, 4, NOW(), NOW()
);
```

Add 4 tasks documenting each step so the audit trail is in the DB.

### Step 8 — Final verification

- [ ] `alembic current` reports head (037 or later)
- [ ] All 5 projects visible in UI at http://localhost:3005
- [ ] `/health` shows `alive >= 34`, circuit breakers closed
- [ ] Agentic loop cycling (log line `[Scheduler] Cycle N: selected project 1` appears within 60s)
- [ ] Smoke tests PASS (`7/7`)
- [ ] LLM call works: `curl -s -X POST http://localhost:8005/llm/execute -H "Content-Type: application/json" -d '{"prompt":"Say hello","task_type":"general","_source":"recovery_verification"}'`
- [ ] `legion-db-backup` container has written at least one `.sql.gz` in `/backups`
- [ ] Recovery-01 sprint exists in DB with status=COMPLETED

---

## Critical files referenced

- [backend/docker-entrypoint.sh](backend/docker-entrypoint.sh#L71-L111) — DB bootstrap branching (the source of the Alembic stuck-at-baseline bug)
- [docker-compose.yml](docker-compose.yml) — `legion-db-backup` service entrypoint fix
- [docker/db-backup.sh](docker/db-backup.sh) — backup script (already correct; only ordering is the issue)
- [backend/alembic/versions/](backend/alembic/versions/) — 37 migrations; none needed to run manually with the Fresh DB path
- [backend/alembic/seed_learn18_canaries.sql](backend/alembic/seed_learn18_canaries.sql) — Learn-18 canary re-seed
- [backend/scripts/learn19_seed.sql](backend/scripts/learn19_seed.sql) — Learn-19 canary re-seed
- [backend/app/services/plan_service.py:853](backend/app/services/plan_service.py#L853) — plan seeding (already runs on bootstrap)
- [backend/app/services/project_bootstrap_service.py](backend/app/services/project_bootstrap_service.py) — project seeding (already runs on bootstrap)

## What this plan does NOT do

- **It does not restore the deleted sprint/plan/learning/episodic history.** That data is gone. No backup exists. The 10+ Learn sprints, Fix sprints, Audit sprints, Audit-Remediation-01 findings, and Learn-18/19 live scoreboards documented in CLAUDE.md and memory are not recoverable from the current system. CLAUDE.md remains the textual record of what was done, and the running agentic loop will generate new sprint history going forward.
- **It does not "investigate" who/what caused the initial wipe.** Container logs don't show a DROP or TRUNCATE event and the PostgreSQL log config doesn't retain DDL history. Plausible explanations include a manual `init_db()` call with drop, a `docker volume rm` at some prior point, or a partial restore that didn't complete. None are fixable after the fact; the backup fix in Step 6 is what prevents recurrence.

## Risk / reversibility

- **Step 1** (pg_dump) is pure read — no risk.
- **Step 2** (drop+recreate DB) **destroys the 5 fresh projects and 1 sprint created today**. That's an acceptable tradeoff because (a) they were auto-seeded, not authored by the user, and (b) they'll be re-seeded immediately on restart. If you'd rather preserve the 1 sprint (`Infra-04`), we can `pg_dump -t sprints -t sprint_tasks` first and reload it after Step 3.
- **Steps 3–8** are additive/verification only.
- **The pg_dump from Step 1** is your rollback artifact. If Step 2+ breaks something unexpected, `pg_restore --clean` it back.
