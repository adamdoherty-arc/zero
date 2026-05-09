# Docker Ecosystem Health — Diagnosis & Recovery Plan

## Context

Docker Desktop's container log panel won't load. The diagnosis: the engine itself is wedged, not the UI. Same engine API that the dashboard uses to fetch logs is also what `docker ps` calls — both hang. Underneath that one symptom is a stack of related issues across the whole ecosystem (25 compose files, 26 containers defined).

### What's actually wrong (evidence)

| Layer | Finding | Evidence |
|---|---|---|
| Engine state | `dockerd` PID 161 alive but blocked in `futex_wait_queue` (kernel lock contention) — not crashed, deadlocked | `/proc/161/status` `State: S`, `/proc/161/wchan` |
| Engine API | Named pipes `docker_engine` and `dockerDesktopLinuxEngine` accept connect, never reply to `/_ping` | 5s read timeout on raw pipe HTTP probe |
| CPU burn | Docker Desktop GUI ~7,272s CPU, `com.docker.backend` ~2,665s since yesterday — abnormal idle behavior | `Get-Process` |
| Host disk | C:\ has **23.3 GB free** of 1.86 TB. Only drive on the system. | `Get-PSDrive C` |
| WSL VHDX | `docker_data.vhdx` = **641 GB on host**, but interior shows only **256 GB used** of a 1 TB ext4 fs (27%) — ~385 GB phantom/reservation that compaction can reclaim | `Get-Item`, `df` inside `docker-desktop` distro |
| Volume bloat | `/var/lib/docker/volumes` = **154.6 GB**, `rootfs` (image layers) = 68.2 GB, `containers` (incl. json logs) = 353 MB. The fat is in **named volumes**, not logs | `du -sh` inside docker-desktop |
| Log driver | `~/.docker/daemon.json` only configures BuildKit GC — **no global log rotation**. All containers using default json-file grow unbounded | Daemon config read |
| Compose sprawl | 25 compose files, redundant vLLM (Legion + LLMRouter + shared-infra), redundant LiteLLM, dead Postgres stacks (sportshub, fortressOS/temp_extract) | Static audit |
| Port collisions | 3000, 5432, 6379, 8000, 9090, 4000, 5555 all bound by 2–3 stacks each | Static audit |
| Stale stacks | 4 composes are dead/archived but still discoverable: `sportshub`, `fortressOS/docs/temp_extract`, `zero/docker-compose.openclaw.archive.yml`, `LLMRouter/infra/docker-compose.vllm.yml` (last is marked DEPRECATED) | File enumeration |

### Why log clicks spin forever

Docker Desktop's UI fetches container logs by calling `GET /containers/{id}/logs` on the same wedged API. The pipe accepts the connection (so the UI doesn't error), but the daemon never streams a response (futex deadlock). The UI shows a spinner indefinitely. **Fixing this requires unwedging dockerd**, which means restarting Docker Desktop. There is no UI-side workaround.

---

## Recovery Plan

The plan has 5 phases. Phases 1–2 are urgent (today). Phases 3–5 are improvement work that can be staged.

### Phase 1 — Unwedge the engine + bring up dashboards (one-time, ~20 min)

Goal: dockerd answering API calls, logs visible — and a *better* log viewer (Portainer) running so you don't depend on the Docker Desktop UI.

1. **Free C:\ disk first.** With 23 GB free and a 641 GB VHDX, restarting risks a stalled boot. Target ≥ 80 GB free before restart. Quick wins:
   - Empty Recycle Bin (`Clear-RecycleBin -Force`)
   - `cleanmgr /sageset:1` then `cleanmgr /sagerun:1` (Windows Update cleanup, delivery optimization, temp files — usually 10–30 GB)
   - Inspect `C:\Users\hadam\AppData\Local\Temp` and `%TEMP%` (often multi-GB stale)
   - `npm cache clean --force`, `pip cache purge`, `cargo cache --autoclean` if applicable
   - Move `node_modules`/`venv` of any one large project to another disk if you have one *external* (none currently mounted)
2. **Quit Docker Desktop fully** (system tray → Quit, not just close window).
3. **`wsl --shutdown`** — terminates all WSL distros including the wedged engine. ⚠ This also stops Ubuntu and any other WSL workloads; fine since nothing else is running there.
4. **Start Docker Desktop**, wait ~60s for engine to come up.
5. Verify: `docker version`, `docker ps -a`, click a container in the dashboard → logs should now load.
6. **Bring up the dashboards stack** from `c:\code\docker\`:
   - `docker compose -f c:\code\docker\portainer-compose.yml up -d` → Portainer at http://localhost:9000 (set admin pw on first load)
   - `docker compose -f c:\code\docker\dockge-compose.yml up -d` → Dockge at http://localhost:5001
   - `docker compose -f c:\code\docker\monitoring-compose.yml up -d` → Grafana at :3000, Prometheus at :9090, cAdvisor at :8080
   - From here on Portainer is your primary log viewer (better tail, search, multi-container view than Docker Desktop).

If logs still don't load after restart, the cause is something else (disk full mid-startup, corrupt VHDX); we'll re-diagnose then.

### Phase 2 — Reclaim space and put guardrails on the engine (one-time, ~30 min)

Goal: Engine can't bloat back into a corner. Host disk recovered.

1. **Inspect volume contents before deleting anything.** 154 GB in volumes is mostly Postgres data dirs, Qdrant indexes, vLLM/HF model caches, Grafana storage. Run `docker volume ls` and `docker system df -v` to see what's eating space. Several stacks (Ada Postgres, Legion Postgres) already migrated to native PG17 per project memory dated 2026-04-25 — those volumes are now *orphaned* and safe to drop.
2. **Selective cleanup** (in this order, with confirmation between each):
   - `docker container prune` — stopped containers
   - `docker image prune -a` — unused images (this alone often recovers 30–60 GB)
   - `docker builder prune -a` — BuildKit cache
   - **Volume cleanup (you approve each):** I run `docker volume ls` + `docker volume inspect` + `docker system df -v` to identify orphans, then present a table of candidates with sizes and last-used info (e.g. `legion_postgres_data` 12 GB — orphaned by PG17 migration on 2026-04-25; `sportshub_redis_data` 0.5 GB — retired stack). You approve each `docker volume rm` individually. **No `docker volume prune` blanket runs.**
3. **Compact the VHDX** to return phantom 385 GB to C:\. Quit Docker Desktop, then in PowerShell as admin:
   ```
   wsl --shutdown
   Optimize-VHD -Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx" -Mode Full
   ```
   (Requires Hyper-V module — alternative: use the Docker Desktop Settings → Resources → "Clean / Purge data" with care.)
4. **Add daemon.json log rotation + size cap.** Edit `C:\Users\hadam\.docker\daemon.json`:
   ```json
   {
     "builder": { "gc": { "defaultKeepStorage": "20GB", "enabled": true } },
     "log-driver": "json-file",
     "log-opts": { "max-size": "50m", "max-file": "3" },
     "default-ulimits": { "nofile": { "Hard": 65536, "Soft": 65536 } }
   }
   ```
   Restart Docker Desktop to apply. From this point all *new* containers cap logs at 150 MB; existing ones inherit on recreate.
5. **Cap Docker Desktop resources** via Settings → Resources:
   - Disk image size: 250 GB (currently unlimited; this is the upper bound on the VHDX)
   - Memory: 16–24 GB (depending on host RAM; today vmmemwsl shows ~18% CPU spin, often a memory-pressure tell)
   - CPUs: leave default unless host is choking

### Phase 3 — Retire dead and duplicate stacks (one afternoon)

Goal: Fewer compose files, no port collisions, no zombie projects.

**Rename to `*.disabled.yml`** (reversible, prevents tooling from picking them up, keeps history visible):
- `c:\code\sportshub\docker-compose.yml` → `docker-compose.disabled.yml` — 2023 trading PoC, owns 5432/5555/6379
- `c:\code\fortressOS\docs\temp_extract\docker-compose.yml` → `.disabled.yml` — extracted-archive temp dir
- `c:\code\zero\docker-compose.openclaw.archive.yml` → `.disabled.yml` — archived openclaw, has `restart: always`
- `c:\code\LLMRouter\infra\docker-compose.vllm.yml` → `.disabled.yml` — already marked DEPRECATED
- `c:\code\Legion\docker-compose.vllm.yml` → `.disabled.yml` — tombstone for the same vLLM, redundant with shared-infra

**Clarify before action:**
- `c:\code\litellm-proxy\docker-compose.yml` vs Legion's litellm vs `shared-infra` LiteLLM at :4444 — pick one
- `c:\code\ADA\docker\docker-compose.ada.yml` and `c:\code\ADA\managed\ada\docker-compose.yml` — superseded by `c:\code\ADA\docker-compose.yml`?

**Resolve port collisions** by env-var remapping (most files already support this; check each for `${VAR:-default}` patterns). Standard you can adopt:
- 3000 (Grafana): monitoring stack keeps it; Legion Grafana → 3030
- 9090 (Prometheus): monitoring stack keeps it; Ada/Legion → 9091/9092
- 5432, 6379: only run native PG17 + native Redis; remove from compose files

### Phase 4 — Add log caps to active stacks (~1 hour)

Goal: No compose-defined service can ever fill the disk again, even before daemon.json rotation kicks in for legacy containers.

Append to each service that lacks one:
```yaml
logging:
  driver: json-file
  options:
    max-size: "50m"
    max-file: "3"
```

**Files needing this:**
- `c:\code\docker\portainer-compose.yml`
- `c:\code\docker\dockge-compose.yml`
- `c:\code\docker\monitoring-compose.yml` (prometheus, grafana, cadvisor)
- `c:\code\shared-infra\docker-compose.vllm.yml` (highest priority — GPU workloads spam logs)
- `c:\code\homeassistant\docker-compose.yml`

### Phase 5 — Operationalize the dashboards (the ones we brought up in Phase 1)

Goal: Lock in the dashboards as your daily-driver views and add the polish.

- **Portainer hardening:** Set strong admin password, add a non-admin user for read-only viewing, label your stacks for easy navigation.
- **Dockge:** Import the active compose files (Ada, Legion, zero, AIContentTools, fortressOS, shared-infra) so you can stop/start stacks from the UI.
- **Grafana dashboards:** Import the standard cAdvisor dashboard (id `14282`) and the Docker overview (id `893`). Set retention to 30 days (already done in Phase 1 monitoring-compose.yml).
- **Alert rules:** Add a Prometheus alert for `container disk usage > 80%` and `container restart count > 5/hour`. These two rules catch most "container is misbehaving" cases before they wedge the engine again.
- **Make Portainer the bookmark:** Replace any reflex of opening Docker Desktop with `localhost:9000`. The native PG17 work you've already done points the same direction — pull workflow off the Docker Desktop GUI.

---

## Critical files referenced

- **Daemon config:** `C:\Users\hadam\.docker\daemon.json` (Phase 2 step 4)
- **VHDX:** `C:\Users\hadam\AppData\Local\Docker\wsl\disk\docker_data.vhdx` (Phase 2 step 3)
- **Settings UI source:** `C:\Users\hadam\AppData\Roaming\Docker\settings-store.json` (read-only — change via Docker Desktop UI)
- **Stacks to retire:** listed in Phase 3
- **Stacks to harden:** listed in Phase 4

## Verification

After Phase 1: `docker ps -a` returns within 1s; clicking a container in Docker Desktop shows logs immediately.

After Phase 2: `Get-Item` on the VHDX shows it shrunk by ~300 GB; C:\ free space ≥ 300 GB; `docker system df` shows volumes < 50 GB.

After Phase 3: `Get-ChildItem c:\code -Recurse -Filter "docker-compose*.yml"` returns ≤ 18 files; no two services bind the same host port unless intentional.

After Phase 4: `grep -L "logging:" c:\code\**\docker-compose*.yml` returns empty (every active compose has caps).

After Phase 5: Portainer at :9000 shows all containers across stacks; Grafana at :3000 has cAdvisor dashboards live.

## Risk and rollback

- **Phase 1 step 3 (`wsl --shutdown`):** Stops all WSL distros (Ubuntu too). If you have unsaved work in Ubuntu, save it first.
- **Phase 2 step 2 (`volume rm`):** Destructive. Confirm orphan-volume identity (volume name vs running container) before removing. Ada/Legion Postgres volumes are orphans per memory dated 2026-04-25 but verify with `docker volume inspect` first.
- **Phase 2 step 3 (`Optimize-VHD`):** Read-only; safe. Can be cancelled mid-run.
- **Phase 3 (compose deletion):** Reversible via git for tracked files. Take a `git stash`/branch snapshot first.

## Decisions locked in

- **Volume cleanup:** I'll list candidates and you approve each `docker volume rm`. No blanket pruning.
- **Stale composes:** Rename to `*.disabled.yml` (reversible, keeps history).
- **Dashboards:** Bring up Portainer + Dockge + monitoring at the tail of Phase 1, not Phase 5, so you have a working log viewer immediately.
