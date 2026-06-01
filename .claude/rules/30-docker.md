# 30 — Docker + restart-policy (always loaded)

## Container layout

- **Backend** (`backend/`): FastAPI on `:18792`, container `zero-api`. Code is COPY'd; rebuild required on changes.
- **Frontend** (`frontend/`): React 19 + Vite on `:5173`, container `zero-ui`. `src/` is volume-mounted.
- **Gateway** (`zero-gateway`): channels (WhatsApp, etc.).
- **Mobile PWA**: Installable surface at `/m/*` served by `zero-ui`.

## Restart policy (2026-05-17 pivot)

Containers use `restart: unless-stopped`. The legacy autostart-everything model — Windows scheduled tasks, NSSM service, daemon watchdog — was removed on 2026-05-17 after two outages (2026-04-24 and 2026-05-11) caused by silent watchdog failures.

Retired:
- Scheduled tasks `Zero AI Auto-Start`, `ZeroHostAgent`, `ZeroHostAgentHealthCheck`.
- NSSM service `Zero-Stack`.
- The daemon watchdog endpoint (`POST /daemon/watchdog`).
- Legacy self-healing installers moved to `attic/autostart-legacy/`.

The Docker stack IS the personal assistant. The robot (host_agent + Reachy daemon) is one subsystem inside it — turning the robot off must not take the assistant down.

## User-launched flow

The Docker stack uses `restart: unless-stopped` — containers auto-restart after reboot or crash without any scheduled tasks or shortcuts.

**Docker stack** (starts automatically via Docker Desktop's restart policy):
- If containers are stopped: `docker compose -f docker-compose.sprint.yml up -d`
- Or use Docker Desktop UI to start the stack.

**Reachy/Robot** (optional, user-launched when robot is wanted):
1. Run `host_agent\start-zero.bat` from the Zero directory in a terminal window. This starts the host_agent supervisor on :18796.
2. Open `/reachy` in the dashboard and click **Start daemon** in `DaemonPanel` to bring up Reachy hardware.
3. Closing the host_agent terminal window stops the robot cleanly.

**No desktop shortcut required.** All management is via the Zero dashboard at `http://localhost:5173/` or Docker Desktop.

**Do NOT** re-run `attic/autostart-legacy/install-task-scheduler.ps1`, re-add the daemon watchdog, or re-introduce scheduled tasks. If you find yourself reaching for one of those to "fix" something, **stop**: the symptom is real and needs a clear UI status + recovery button, not a hidden watchdog.

## Post-change deployment (MANDATORY)

After ANY code change, ALWAYS rebuild and restart the affected Docker containers before declaring the task done. The user should NEVER run Docker rebuild commands themselves.

**Backend** (`zero-api`): code is COPY'd, not volume-mounted. ALL backend changes require rebuild:
```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && \
docker compose -f docker-compose.sprint.yml up -d zero-api
```

**Frontend** (`zero-ui`): source files (`src/`, configs) ARE volume-mounted, so code changes are live. But `node_modules` is NOT mounted — **new npm packages require rebuild**:
```bash
# After npm install (new packages):
docker compose -f docker-compose.sprint.yml build --no-cache zero-ui && \
docker compose -f docker-compose.sprint.yml up -d zero-ui

# After source-only changes: just restart
docker compose -f docker-compose.sprint.yml restart zero-ui
```

Verify containers are healthy:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
```

## Common commands

```bash
# Start the sprint UI stack
docker compose -f docker-compose.sprint.yml up -d

# Tail backend logs
docker logs -f zero-api

# Restart gateway after config changes
docker compose restart zero-gateway

# Check vLLM served models (Qwen3-32B-AWQ)
curl http://localhost:18801/v1/models

# Tail host-agent / daemon logs
Get-Content c:\code\zero\host_agent\logs\host-agent-foreground.log -Tail 20 -Wait
Get-Content c:\code\zero\host_agent\logs\reachy-daemon-$(Get-Date -Format yyyyMMdd).log -Tail 20 -Wait
```
