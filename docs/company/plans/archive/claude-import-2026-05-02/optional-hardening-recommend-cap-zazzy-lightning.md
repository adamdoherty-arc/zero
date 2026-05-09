# PC + Docker Optimization Plan

## Context

After switching Zero from Ollama to vLLM, the machine started hard-crashing. Root cause was GPU oversubscription (two duplicate vLLM stacks + Ollama + a 34 GiB FP8 model on a 32 GB card). That is now fixed: shared-infra owns the single chat+embed pair, Zero points at it via `host.docker.internal`.

User now wants (1) the optional 5090 power cap to eliminate PSU transient crashes, and (2) a broader optimization pass across Docker, WSL2, and stale state.

## Current state (measured)

- **Hardware**: RTX 5090, 64 GB DDR5, 32 logical CPUs (Corsair Vengeance i7500).
- **GPU power limit**: 575 W default / 600 W max. Not yet capped.
- **GPU VRAM**: 30.7 / 32.6 GB used (chat + embed loaded — expected).
- **WSL2** (`~/.wslconfig`): `memory=32GB`, `swap=16GB`, `processors=12`.
- **Docker disk** (massive reclaim available):
  - Images: **197 GB, 84 GB reclaimable**
  - Volumes: **300 GB, 190 GB reclaimable**
  - Build cache: **26 GB, 5 GB reclaimable**
  - Total reclaimable: **~280 GB**
- **Container pressure points**:
  - `zero-api` is pinned at **99.96 %** of its 6 GB limit — imminent OOM, likely causing the unhealthy state.
  - Everything else has healthy headroom.
- **Stale images** (not referenced by any running compose): `zero:latest` (11 GB), `aicontenttools-*` (~52 GB across 3 tags), `legion-legion-backend` (9.7 GB, legion is idle), `open-webui` (6.68 GB), `n8n`, `chromadb`, `langfuse` x2, old `litellm:main-latest`, old `qdrant:latest`.

## Changes

### 1. GPU power cap (explicit user ask)

```
nvidia-smi -pl 450
```

Eliminates the 575 W → transient-spike crash vector. ~1 % perf cost on sustained inference. This does **not** persist across reboots on consumer drivers; to make it permanent, add to a scheduled task on login (documented in verification below).

### 2. Raise `zero-api` memory limit — it is OOM-ing

File: `C:\code\zero\docker-compose.sprint.yml` (zero-api service, around line ~203).

```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 10G   # was 6G — currently running at 5.998/6G (99.96%)
```

Triggers a recreate of `zero-api` only.

### 3. WSL2 — give Docker more headroom

File: `C:\Users\hadam\.wslconfig`

```ini
[wsl2]
memory=48GB        # was 32GB — host has 64GB total, leave 16GB for Windows
swap=8GB           # was 16GB — overkill when memory is generous
processors=16      # was 12 — 32 logical cores, leave 16 for host
```

Requires `wsl --shutdown` + Docker Desktop restart to take effect. This is the single biggest quality-of-life change — Docker stops fighting Windows for RAM during heavy loads.

### 4. Reclaim ~280 GB of Docker disk

Run in this exact order (non-destructive → aggressive):

```
docker container prune -f                     # only the exited ones
docker image prune -a -f --filter "until=168h" # images unused for 7 days
docker builder prune -af                      # all build cache
docker volume ls -qf dangling=true | xargs docker volume rm  # orphaned volumes only
```

**Do NOT run `docker system prune -a --volumes`** — would wipe the huggingface model cache (`shared-hf-cache`, `zero-hf-cache`) and force a 40-minute model redownload.

### 5. Remove specifically-identified stale images

Only images confirmed not referenced by any active compose file:

```
docker rmi aicontenttools-backend aicontenttools-celery-worker aicontenttools-celery-beat   # ~52 GB
docker rmi zero:latest                                                                      # 11 GB, old build
docker rmi ghcr.io/open-webui/open-webui:main                                               # 6.7 GB, unused
docker rmi n8nio/n8n:latest chromadb/chroma:latest                                          # ~3 GB
docker rmi ghcr.io/berriai/litellm:main-latest                                              # keep main-stable, drop old
docker rmi qdrant/qdrant:latest                                                             # keep v1.17.0
```

Expected reclaim: **~75 GB images** on top of the prune.

### 6. Delete the now-orphan `zero-hf-cache` volume

The earlier consolidation removed the volume declaration but the data still exists:

```
docker volume rm zero-hf-cache        # ~30 GB of duplicated HF model weights
```

### 7. Confirm Ollama service is disabled, not just stopped

```
Get-Service Ollama
Set-Service Ollama -StartupType Manual   # prevents auto-start on reboot
```

Ollama auto-start is what caused the VRAM conflict with vLLM originally.

## Files modified

- `C:\Users\hadam\.wslconfig` — RAM/CPU allocation
- `C:\code\zero\docker-compose.sprint.yml` — zero-api memory bump

Everything else is live commands (GPU cap, Docker prune, service config).

## Verification

1. **GPU cap**:
   ```
   nvidia-smi --query-gpu=power.limit --format=csv
   # expect: 450.00 W
   ```
2. **zero-api healthy**:
   ```
   docker ps --filter name=zero-api --format "{{.Status}}"
   # expect: Up X minutes (healthy)
   docker stats --no-stream zero-api
   # expect: MEM % well under 99%
   ```
3. **Disk reclaimed**:
   ```
   docker system df
   # expect: images down ~75 GB, volumes down ~30 GB, build cache ~0
   ```
4. **WSL2 new limits live** (after `wsl --shutdown` + Docker Desktop restart):
   ```
   wsl -d docker-desktop -- cat /proc/meminfo | head -3
   # expect: MemTotal around 48 GB
   ```
5. **End-to-end**: `curl http://localhost:8000/v1/models` (chat), `curl http://localhost:8001/v1/models` (embed), `curl http://localhost:18792/health/ready` (zero-api). All return 200.

## Persistence notes

- `nvidia-smi -pl 450` does not survive reboot on GeForce driver. To persist, create a Windows Task Scheduler job: Trigger "At log on", Action `nvidia-smi -pl 450`, run with highest privileges. I can create the XML for this as a follow-up if you want.
- `.wslconfig` changes persist.
- Ollama startup-type change persists.

## Risks / not doing

- Not running `docker system prune -a --volumes` — would nuke `shared-hf-cache` (your downloaded LLM weights).
- Not touching ada stack — it's healthy, all services have sensible limits.
- Not touching legion — already shut down, no action needed until you restart it.
- Not changing the vLLM model args again — last round's changes are correct; want to observe 24 h of stability first.
