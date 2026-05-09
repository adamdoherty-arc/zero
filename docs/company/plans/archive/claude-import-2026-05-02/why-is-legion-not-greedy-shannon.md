# Why Legion wasn't running (and what to do about the DB)

## Context

User reported `localhost:3005` showing `ERR_CONNECTION_REFUSED` in Chrome. By the time I investigated, Docker Desktop's Linux engine had recovered and all `legion-*` containers were back up — health is green. So the immediate "no UI" symptom is resolved. But the recovery exposed a real follow-up: today's docker-compose.yml change reverted Legion to its own containerized Postgres, which means the data that accumulated on the Windows-host PG between 2026-04-25 and today is not in the new container.

## Root cause of the outage

Docker Desktop processes were alive (`Docker Desktop.exe`, `wsl*`) but the Linux engine named pipe `npipe:////./pipe/dockerDesktopLinuxEngine` was missing — so `docker ps` returned `failed to connect to the docker API`. With no daemon, none of the `legion-*` containers were running, so nothing was listening on `:3005` or `:8005`. Chrome's `ERR_CONNECTION_REFUSED` is the literal symptom of "nothing bound to that port."

This isn't a Legion bug. It's a Docker Desktop transient — most likely WSL2/engine restart, OS sleep/wake, or Docker auto-update — and `restart: unless-stopped` on every Legion service brought the stack back up automatically once the engine returned.

Verified live now:
- `docker ps | grep legion` → 9 containers, all healthy, all "Up 3 minutes"
- `curl http://localhost:8005/health` → `{"status":"healthy", ..., "alive":33,"total":41,"healthy":true}`
- `curl http://localhost:3005` → React HTML served
- LLM router: `active_provider=vllm`, circuit breaker closed, queue depth 0

## The follow-up problem: data gap on the new Postgres container

Today's `docker-compose.yml` diff (uncommitted) reverts the 2026-04-25 migration that moved Legion onto the Windows host's native PG17 (port 5432, shared with ADA). The new config:

- Brings back service `legion-postgres` (image `pgvector/pgvector:pg17`)
- Maps host port **5433** → container 5432 (avoiding ADA's 5432)
- Mounts a **new** volume `legion-postgres-data` (empty)
- Backend `DATABASE_URL` now points at `legion-postgres:5432` over the docker network
- LiteLLM `LITELLM_DATABASE_URL` likewise

The new container is healthy, but its volume is fresh — no projects, no sprints, no episodes, no learnings from the last 2 days. The data that accrued between 2026-04-25 and 2026-04-27 lives only on the Windows-host PG17 on `:5432`. The dump at `backups/legion-pre-migration-20260425-201325.dump` is from 2026-04-25 20:13 — it captures the pre-migration state but misses the 2 days of host-PG sprint activity.

So Legion is "running" with an empty DB. The agentic loop, Plans, Sprints, Daily Standup, etc. will all show fresh-install state until the data is restored.

## Plan: dump host PG → restore into legion-postgres container

User confirmed (a) the new containerized-PG layout is intentional and stays, (b) preserve the 2 days of sprint/episode/learning data by dumping from the Windows-host PG17 and restoring into the new `legion-postgres` container.

### Step 1 — sanity-check the host PG before dumping

Before touching anything, confirm the host PG actually still has Legion data and identify what we're dumping. Run from Windows (PowerShell or cmd, since `psql` isn't on the bash PATH):

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h localhost -p 5432 -U legion -d legion -c "SELECT count(*) FROM projects;"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h localhost -p 5432 -U legion -d legion -c "SELECT count(*) FROM sprints WHERE project_id=1;"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h localhost -p 5432 -U legion -d legion -c "SELECT max(created_at) FROM sprints;"
```

Expected: projects ≥ 1, sprints in the dozens-to-hundreds, max(created_at) on or near 2026-04-27. If the counts are zero, the host PG has been wiped and we should fall back to the 2026-04-25 dump on disk.

### Step 2 — pg_dump the host PG to a custom-format file

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h localhost -p 5432 -U legion -d legion -Fc -f C:\code\Legion\backups\legion-host-20260427.dump
```

Custom format (`-Fc`) is required so `pg_restore` can use `--clean --if-exists` against the new container, which already has empty tables created by the entrypoint's `create_all()`.

Verify the dump is non-trivial:

```bash
ls -la C:/code/Legion/backups/legion-host-20260427.dump   # expect multiple MB
```

### Step 3 — restore into legion-postgres

The new container already ran `create_all()` + `alembic stamp head` on first boot, so empty tables exist. We need `--clean --if-exists` to drop them before reloading from dump, AND we need to either disable the backend during restore OR restart it after — otherwise the agentic loop will be writing to tables that are getting recreated under it.

```bash
# Pause the backend so daemons don't fight the restore
docker-compose stop legion-backend

# Copy dump into the container and restore
docker cp backups/legion-host-20260427.dump legion-postgres:/tmp/host.dump
docker exec legion-postgres pg_restore -U legion -d legion --clean --if-exists --no-owner --no-privileges /tmp/host.dump
docker exec legion-postgres rm /tmp/host.dump

# Bring the backend back; entrypoint will see Alembic-tracked DB and just upgrade head
docker-compose start legion-backend
docker logs -f legion-backend --tail 50   # watch for healthy startup, no migration errors
```

`--no-owner --no-privileges` is defensive against ownership mismatches between the host's `legion` role and the container's `legion` role — they should match given the same DB_USER/DB_PASSWORD env vars, but the flags cost nothing.

### Step 4 — verify

```bash
docker exec legion-postgres psql -U legion -d legion -c "SELECT id, name FROM projects ORDER BY id;"
docker exec legion-postgres psql -U legion -d legion -c "SELECT count(*) FROM sprints WHERE project_id=1;"
docker exec legion-postgres psql -U legion -d legion -c "SELECT max(created_at) FROM sprints;"
curl -s http://localhost:8005/health | python -m json.tool   # status=healthy after restart
curl -s http://localhost:8005/api/projects | python -m json.tool | head -40   # Legion project visible
```

Browser-verify per the CLAUDE.md rule:
- Load `http://localhost:3005/projects` → Legion project shows
- Load `http://localhost:3005/sprints` → sprint history populated, recent dates visible
- Load `http://localhost:3005/llm-console` → recent LLM call rows visible (may take a minute or two of fresh agentic activity)

### Step 5 — commit the compose change

```bash
git add docker-compose.yml docker-compose.vllm.disabled.yml
git status   # confirm only the intended files
git diff --staged docker-compose.yml | head -50   # final eyeball
git commit -m "infra: restore Legion's own postgres container on :5433"
```

The `docker-compose.vllm.yml` → `docker-compose.vllm.disabled.yml` rename is a separate concern (vllm stack disabled) but lives in the same workspace state — confirm with the user whether to bundle or split.

`backend/app/services/llm_clients/vllm_client.py` and the two test files are also dirty in the working tree — not related to this outage; leave them out of this commit and address separately.

## Critical files referenced

- `docker-compose.yml` — modified, uncommitted; introduces `legion-postgres` service on `:5433` and updates `DATABASE_URL`/`LITELLM_DATABASE_URL`
- `docker-compose.vllm.disabled.yml` — renamed from `docker-compose.vllm.yml` (vllm stack disabled, not relevant to this outage)
- `backend/app/services/llm_clients/vllm_client.py` — modified, unrelated to the outage
- `backups/legion-pre-migration-20260425-201325.dump` — pre-2026-04-25 dump on disk
- `backend/docker-entrypoint.sh` — handles fresh-DB / existing-DB / Alembic-tracked-DB cases automatically; will run `create_all()` + `alembic stamp head` on the empty container, which is why the new stack came up green even with no data

## Verification (end-to-end)

```bash
# Outage resolved
docker ps --format "{{.Names}} {{.Status}}" | grep legion        # 9 containers healthy
curl -s http://localhost:8005/health | python -m json.tool       # status=healthy, alive>=30
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3005   # 200

# After restore (Option A or B)
docker exec legion-postgres psql -U legion -d legion -c "SELECT id, name FROM projects ORDER BY id;"
docker exec legion-postgres psql -U legion -d legion -c "SELECT count(*) FROM sprints WHERE project_id=1;"

# Browser verification (gstack /browse skill)
# - Navigate /projects → Legion row visible
# - Navigate /sprints → sprint history populated
# - Navigate /llm-console → recent LLM calls visible (after a few minutes of agentic loop activity)
```

## Note on the screenshot

The Chrome `ERR_CONNECTION_REFUSED` shown in the user's screenshot is no longer reproducible — the engine recovered before I finished investigating. If it recurs, the diagnostic command is `docker ps`; if that errors with the npipe message, Docker Desktop's Linux engine is the culprit (restart Docker Desktop, or `wsl --shutdown` then relaunch). Legion itself does not need to be touched.
