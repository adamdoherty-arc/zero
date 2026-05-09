# Plan: Consolidate Legion onto the Native Postgres + Fix Plan/Docs

## Context

The master plan and ecosystem docs at `C:\code\` describe **three separate Postgres instances** (`:5432` Ada, `:5433` Zero, `:5434` Legion) and reference Legion's container `legion-db` as the home for LangMem / Letta / Mem0 / pgvector. **The reality is different**:

- **Native PostgreSQL 17** is already running on the Windows host at `localhost:5432` with `pgvector 0.8.0` + `pg_trgm`. Config: `C:\Program Files\PostgreSQL\17\data\postgresql.conf` (`max_connections=200`, `shared_buffers=2GB`).
- **Ada** was migrated to native on 2026-03-17 — its `docker-compose.yml` no longer ships a Postgres service (only `postgres-exporter` for metrics and `pgbouncer` pointing at `host.docker.internal:5432/adam`). ✅ already correct.
- **Zero** already uses the native instance via `host.docker.internal:5432/zero`. ✅ already correct.
- **Legion** still spins up `legion-db` (`postgres:16-alpine`) on host port `5434` with volume `legion-postgres-data`, plus `legion-db-backup` (uses the same image for `pg_dump` cron) and `legion-pgbouncer` pointing at `legion-db:5432`. ❌ rogue.

Result: Legion's data is isolated from Ada/Zero, the planned cross-project memory layer (LangMem + Letta + Mem0 + shared pgvector) cannot coexist with `adam` and `zero` databases on different instances, and the docs (`C:\code\README.md`, `C:\code\ARCHITECTURE.md`, `C:\code\Legion\docs\ARCHITECTURE.md`, the master plan) all still describe the multi-instance world.

This plan migrates Legion onto the native PG17, removes the redundant container, and rewrites the plan + ecosystem docs to match the single-Postgres reality.

> **Re: Ada** — the user's premise was that "new Postgres implementations were set up for Ada and Legion". Ada is already correct (migrated 2026-03-17, comment at `C:\code\ADA\docker-compose.yml:44`). Only Legion needs migration. This plan documents Ada's state as part of the verification step so the docs stop misrepresenting it.

---

## Decisions locked

1. **Migrate existing Legion data** via `pg_dump`/`pg_restore` (preserve sprints, learning_events, brain_decisions, episodes, sprint_quality_grades, llm_call_details, etc.).
2. **Bulk sed-replace** `docker exec legion-db psql -U legion -d legion` → `psql -h localhost -U legion -d legion` across all `C:\code\Legion\.claude\skills\**` and `C:\code\Legion\.agents\skills\**` files.
3. **Re-point `legion-pgbouncer`** at the native instance via `host.docker.internal:5432` (same pattern Ada already uses). Keep pgbouncer as the production pooler.

---

## Target end-state

- Single Postgres: native PG17 at `localhost:5432` with three databases: `adam`, `zero`, `legion`.
- `pgvector` enabled in all three.
- Legion's docker-compose retains `legion-redis`, `legion-qdrant`, `legion-litellm`, `legion-backend`, `legion-frontend`, monitoring stack, optional `legion-pgbouncer` (re-pointed) and `legion-db-backup` (re-pointed). The `legion-db` service is gone; the `legion-postgres-data` volume is removed after a successful migration soak.
- Plan + ecosystem docs reference `:5432` (single instance) instead of `:5432`/`:5433`/`:5434` (three instances).

---

## Critical files

### To migrate / modify
- `C:\code\Legion\docker-compose.yml` — remove `legion-db` service (lines 4–27), update `legion-db-backup` (lines 424–447) and `legion-pgbouncer` (lines 449–470) to use `host.docker.internal:5432`, remove `legion-postgres-data` from the `volumes:` section.
- `C:\code\Legion\.env` — replace `DB_HOST=legion-db`/`DB_PORT=5434` with `DB_HOST=host.docker.internal`/`DB_PORT=5432`. Verify `DATABASE_URL` and `LITELLM_DATABASE_URL` are derived or rewritten consistently.
- `C:\code\Legion\backend\app\config.py` (or wherever `DATABASE_URL` is composed) — confirm it picks up the new env vars without code changes.
- `C:\code\Legion\backend\alembic.ini` — verify `sqlalchemy.url` is interpolated from env, not hardcoded.
- `C:\code\Legion\docker\db-backup.sh` — update `pg_dump` host argument to point at `host.docker.internal` instead of `legion-db`.

### Skill files (sed-replace pass)
- `C:\code\Legion\.claude\skills\**\*.md` (legion-watchdog, legion-sprint-auditor, legion-employee, legion-ship, legion-qa-guide, legion-docker-health, legion-ollama-experimenter, knowledge files)
- `C:\code\Legion\.agents\skills\**\*.md` (mirrored copies)
- Pattern A: `docker exec legion-db psql -U legion -d legion` → `psql -h localhost -U legion -d legion`
- Pattern B: any standalone `legion-db` hostname references in psql/pg_dump invocations → `localhost` (or `host.docker.internal` when run from inside a container)
- Pattern C: in `legion-docker-health` SKILL.md line 77 expected-containers list and line 297 troubleshooting: drop `legion-db` from the expected list.

### Doc files (port + topology rewrite)
- `C:\code\README.md` — lines 16–18 port table: collapse three Postgres rows into one (`5432 | Postgres (shared) | Native PG17 — pgvector 0.8.0 + pg_trgm; databases: adam, zero, legion`).
- `C:\code\ARCHITECTURE.md` — line 13, line 54: `:5434` → `:5432`; reframe "Legion's existing Postgres" as "the host's native PG17".
- `C:\code\Legion\docs\ARCHITECTURE.md` — line 3 (`Postgres on :5434` → `Postgres on host :5432 (shared native PG17)`), line 34 (subgraph label `Memory (single Postgres :5434 + pgvector)` → `:5432`), line 172, line 253 (table row: `container legion-db` → `native PG17 (host.docker.internal:5432)`).
- `C:\code\Legion\MANDATE.md` — no port references found, leave alone.
- `C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md` — Stage 3 deliverables 2 + 3 (line 211, 212), Risks section line 371, "Three Postgres instances" → "Single native Postgres on `:5432`". The old plan's `:5434` references become `:5432`.

### Memory / vault
- `40_Resources/llm-models.md` and other vault docs — only update if they cite the port. Defer; not blocking.
- `C:\Users\hadam\.claude\projects\C--code-claude\memory\` — write a new `project_postgres_consolidation_20260425.md` summarizing the consolidation outcome (see Verification step 7).

### Reuse, don't rewrite
- `C:\code\ADA\docker-compose.yml` — already correct. Only verify.
- `C:\code\zero\docker-compose.sprint.yml` — already correct. Only verify.
- Native `pg_hba.conf` — confirm Docker subnet is allowed (likely already is, since Ada and Zero work).

---

## Phases

### Phase 1 — Pre-flight verification (read-only)

1. `docker ps --filter name=legion-db --format "{{.Status}}"` — confirm container is up and healthy.
2. `psql -h localhost -U postgres -c "\l"` — list native databases. Note whether `legion` already exists (the Explore agent's audit suggested it might).
3. `psql -h localhost -U postgres -d adam -c "\dx"` and `\dx` on `zero` — confirm `pgvector`/`pg_trgm` extensions present.
4. `docker exec legion-db psql -U legion -d legion -c "SELECT pg_database_size('legion'); SELECT count(*) FROM pg_tables WHERE schemaname='public';"` — capture size + table count baseline.
5. `docker exec legion-db psql -U legion -d legion -c "\dx"` — note which extensions Legion actually uses (likely none beyond defaults today; pgvector planned).
6. Capture connection string baseline: read `C:\code\Legion\.env` so the rewrite is exact.

### Phase 2 — Native PG17 prep

1. As `postgres` superuser:
   ```sql
   CREATE ROLE legion WITH LOGIN PASSWORD 'legion_secret_2025';
   CREATE DATABASE legion OWNER legion;
   \c legion
   CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector (Stage 3 dependency)
   CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- parity with adam
   GRANT ALL PRIVILEGES ON DATABASE legion TO legion;
   ```
   If the role/database already exist, this is a no-op; verify password matches `LEGION` `.env`.
2. Confirm Docker → host network path: `docker run --rm postgres:16-alpine psql -h host.docker.internal -U legion -d legion -c "SELECT 1"` (using `PGPASSWORD` env). This is the same path Ada and Zero already use.

### Phase 3 — Stop writes, dump, restore

1. `cd C:\code\Legion && docker compose stop legion-backend legion-frontend legion-litellm` (stop everything that writes; keep `legion-db` up so we can dump).
2. `docker exec legion-db pg_dump -U legion -d legion -Fc -f /tmp/legion.dump` then `docker cp legion-db:/tmp/legion.dump C:\code\Legion\backups\legion-pre-migration-$(date +%Y%m%d-%H%M).dump`.
3. Restore into native: `pg_restore -h localhost -U legion -d legion --clean --if-exists --no-owner --no-acl C:\code\Legion\backups\legion-pre-migration-*.dump`.
4. Sanity check: `psql -h localhost -U legion -d legion -c "SELECT count(*) FROM sprints; SELECT count(*) FROM episodes;"` matches the Phase 1 baseline.
5. `docker compose stop legion-db` (do not remove yet — keep the container + volume around for one week as rollback insurance).

### Phase 4 — Config rewrite

1. **`Legion/.env`**: change `DB_HOST=legion-db` → `DB_HOST=host.docker.internal`, `DB_PORT=5434` → `DB_PORT=5432`, leave `DB_USER=legion`, `DB_PASSWORD=legion_secret_2025`, `DB_NAME=legion`. Update any composed `DATABASE_URL`/`LITELLM_DATABASE_URL` strings the same way.
2. **`Legion/docker-compose.yml`**:
   - Delete the `legion-db:` service block (lines ~4–27).
   - Delete the `depends_on: legion-db: condition: service_healthy` clauses elsewhere in the file (`legion-backend`, `legion-pgbouncer`, `legion-db-backup`).
   - In `legion-pgbouncer` (line 455): change `DATABASE_URL: postgresql://legion:legion_secret_2025@legion-db:5432/legion` → `…@host.docker.internal:5432/legion`.
   - In `legion-db-backup` (lines 431–432): change `DB_HOST: legion-db` → `DB_HOST: host.docker.internal`, `DB_PORT: "5432"` (already correct).
   - At the bottom of the file: remove `legion-postgres-data:` from the named-volumes section.
3. **`docker/db-backup.sh`**: confirm it uses `$DB_HOST`/`$DB_PORT` env vars (no hardcoded `legion-db`); patch any literals.
4. **Sed pass over skill files**:
   - Find: `Grep` for `docker exec legion-db psql -U legion -d legion` across `C:\code\Legion\.claude\skills` and `C:\code\Legion\.agents\skills`.
   - Replace with: `psql -h localhost -U legion -d legion` (set `PGPASSWORD` upstream in the skill if interactive).
   - Drop `legion-db` from the expected-containers lists in `legion-docker-health/SKILL.md` (line 77, 297) and other skill manifests.
   - Note: skills `.claude/` and `.agents/` mirror; both must be updated.
5. **Plan rewrite** (`C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md`):
   - Stage 3 deliverable 2 (line 211): `Legion's existing Postgres (port 5434)` → `the native PG17 instance on host (localhost:5432)`.
   - Stage 3 deliverable 3 (line 212): same.
   - Risks (line 371): replace the "Three Postgres instances stay siloed" bullet with "Single native PG17 on `:5432` hosts `adam` (Ada), `zero` (Zero), `legion` (Legion). Cross-project pgvector queries are now trivially possible — revisit row-level policies if Eightfold IP boundary requires hard isolation."
   - Add a new bullet under Stage 3 verification: "Migration confirmed: `legion` database lives on native PG17, no `legion-db` container running, sprints/episodes counts match pre-migration baseline."
   - Stage 0 status block: add a new line under "Stage 0 EXTRAS shipped" or a new "Post-Stage-0 hotfix" section recording the consolidation outcome.
6. **Ecosystem docs**:
   - `C:\code\README.md` lines 16–18: collapse three rows into one (`5432 | Postgres (shared native PG17) | databases: adam, zero, legion · pgvector 0.8.0 · pg_trgm`).
   - `C:\code\ARCHITECTURE.md` line 13: `Legion's existing Postgres :5434` → `the host's native PG17 :5432 (shared by Ada, Zero, Legion)`. Line 54: `single Postgres :5434 + pgvector` → `native PG17 :5432 + pgvector`.
   - `C:\code\Legion\docs\ARCHITECTURE.md`: same port substitutions on lines 3, 34, 172, 253. In the table row at line 253, change `container legion-db` → `native PG17 (host.docker.internal:5432)`.

### Phase 5 — Restart, smoke, and verify

1. `docker compose up -d` from `C:\code\Legion`. Watch `docker compose logs -f legion-backend` for startup.
2. `curl localhost:8005/health` → 200.
3. Trigger a write through the UI (create a sprint task) → verify the row lands in native `legion` database via `psql -h localhost -U legion -d legion -c "SELECT count(*) FROM sprint_tasks;"`.
4. Confirm Ada still works: `curl localhost:8003/api/health` → 200; `psql -h localhost -U postgres -d adam -c "SELECT count(*) FROM positions;"`.
5. Confirm Zero still works: `curl localhost:18792/health` → 200.
6. Run `C:\code\scripts\health-watchdog.py` once on demand — ensure all services still report green and that today's daily note's `## System Health` block is updated.
7. Run one Legion skill that uses psql (e.g. `legion-sprint-auditor`'s sprint-status query) to confirm the sed-replaced commands work natively.
8. Soak: 72 hours of Legion running on native before we touch the old container.

### Phase 6 — Cleanup (after 7-day soak)

1. `docker compose rm -f legion-db` (the service is already gone from compose; this removes the leftover container).
2. `docker volume rm legion-postgres-data` only after confirming the rollback dump in `C:\code\Legion\backups\` is intact.
3. Remove the rollback dump after one additional week, or rotate to long-term storage if preferred.

---

## Verification (end-to-end)

1. `docker ps` shows no `legion-db` container.
2. `netstat -an | findstr ":5434"` returns nothing.
3. `psql -h localhost -U postgres -c "\l"` lists `adam`, `zero`, `legion`.
4. `psql -h localhost -U legion -d legion -c "\dx"` lists `vector` and `pg_trgm`.
5. Counts of `sprints`, `episodes`, `learning_events`, `brain_decisions`, `llm_call_details` on native match the pre-migration baseline (Phase 1 step 4).
6. Legion UI loads, sprint creation works, drift queries run.
7. `Grep` over `C:\code\Legion\.claude\skills` for `docker exec legion-db` returns zero hits.
8. `Grep` over `C:\code\README.md`, `C:\code\ARCHITECTURE.md`, `C:\code\Legion\docs\ARCHITECTURE.md`, `C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md` for `:5434` returns zero hits (or only inside historical/changelog blocks).
9. Memory file `project_postgres_consolidation_20260425.md` written under `C:\Users\hadam\.claude\projects\C--code-claude\memory\` with: outcome, baseline counts, and the rollback path. Index entry added to `MEMORY.md`.
10. 72-hour soak: Legion-Stack stays green on the watchdog; no error spikes in `legion-backend` logs related to DB connectivity.

---

## Risks & rollback

- **Connection-pool exhaustion on native PG17**: native is configured for 200 max connections + 2GB shared_buffers. Legion + Ada + Zero combined typically need ~120; pgbouncer (Ada and optionally Legion) pools further. Monitor `pg_stat_activity` after cutover; if saturated, raise `max_connections` or enable Legion's pgbouncer in `production` profile.
- **`pg_hba.conf` rejecting Docker subnet**: Ada and Zero already work, so the rule is permissive enough — but confirm before Phase 3.
- **Schema name collisions**: `adam`, `zero`, `legion` are separate databases (not schemas), so no conflict. LangMem/Letta/Mem0 work in Stage 3 will also use distinct databases or schema-prefixed tables.
- **Skill regression**: bulk sed-replace can over-match. Strategy: do a dry-run `Grep` first, eyeball the matches, then `Edit replace_all` per file (not a global search-and-replace) to avoid touching unrelated `docker exec` strings.
- **Rollback path**: container + named volume preserved for 7 days. To roll back: `docker compose up -d legion-db`, restore `.env` from git, restart Legion. The pg_restore step is non-destructive (it created data on native; the Docker side is untouched).
- **Ada/Zero collateral damage**: this plan touches only Legion's compose + docs. Ada and Zero configs are read-only verification.
- **Master-plan continuity**: the existing plan's Stage 0 already shipped. We are editing it post-hoc to correct the Postgres assumption — note the change in the Status section ("Post-Stage-0 hotfix 2026-04-25: Postgres consolidation — see this plan").

---

## Out of scope

- Migrating Legion's `legion-redis`, `legion-qdrant`, or `legion-litellm`. These remain Dockerized.
- Stage 3 LangMem/Letta/Mem0 wiring — that's still Week 6–7 work; this plan only ensures they'll have a single Postgres to land on.
- Rewriting Stage 3's pgvector design beyond the port number.
- Touching ADA's or Zero's compose files (they're already correct).
- Vault `40_Resources/llm-models.md` cleanup (defer; not blocking).
