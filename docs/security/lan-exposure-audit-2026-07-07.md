# LAN exposure audit — Zero API surface (2026-07-07, supervise run 8cfa4a8a)

## Finding

The Zero API is reachable from the home LAN with no authentication on most routers.

Measured facts (all verified live this run):

- `docker-compose.sprint.yml` publishes `18792:18792` (and vllm `18801`) on `0.0.0.0`, not loopback.
- The physical network ("dNet 2", 192.168.4.0/22) is categorized **Public**, and the
  "Docker Desktop Backend" firewall rule **Allows inbound on the Public profile** — so
  LAN devices pass the firewall to every Docker-published port.
- 31 routers require auth (`Depends(require_auth)`: approvals, email_drafts, vault, brain,
  experiments, reachy_memory, tax_summary, company_*, media/content, faceprints, voiceprints, …).
- ~72 routers have **no auth dependency at all**, including write-heavy surfaces:
  `reachy.py` (60 writes), `email.py` (19), `meetings.py` (15), `meals.py` (14),
  `knowledge.py` (10), `calendar.py` (7), `system.py` (6 — includes scheduler enable/disable),
  `tasks.py`, `sprints.py`, `projects.py`, `llm.py`, `browser_control.py`, `integrations.py`.
  Verified live: `GET /api/tasks` returns 200 with no Authorization header.
- vLLM on 18801 accepts unauthenticated completions (free GPU for anyone on the LAN).
- The zero-ui nginx (`location /api/ { proxy_pass http://zero-api:18792; }`) also exposes the
  full unauthenticated API on port 5173 — this path cannot be closed without breaking the
  mobile PWA, which legitimately calls `/api/*` through it.

## Why it is not fully fixed in this run

1. **Backend-wide auth** requires the frontend to attach Bearer tokens on every call. Today only
   ~14 components use `getAuthHeaders()` (`frontend/src/lib/auth.ts`). A global fetch wrapper +
   rebuild of `zero-ui` is required — but rebuilding bakes the operator-WIP tree (standing gate
   G2), and recreating containers discards the docker-cp'd fix layer.
2. **Loopback port binding** (`127.0.0.1:18792:18792`) requires a container recreate — same
   writable-layer problem, and Legion's backend (stack_monitor, project_registry,
   skill_sync_service) calls Zero via `host.docker.internal:18792`, which a loopback bind breaks.
3. **Interim firewall block** (scoped, reversible) was prepared but requires elevation, which this
   agent cannot obtain (PowerShell non-elevated; native `sudo` disabled in Developer Settings;
   no gsudo).

## One-command interim mitigation (operator, elevated PowerShell)

```powershell
New-NetFirewallRule -DisplayName 'Zero hardening: block LAN inbound zero-api+vllm' `
  -Direction Inbound -Action Block -Protocol TCP -LocalPort 18792,18801 `
  -RemoteAddress 192.168.4.0/22 -Profile Any -Enabled True
```

Scope analysis (why this is safe):
- Loopback traffic does not traverse the firewall — host tools, supervise runs, host_agent keep working.
- Docker-internal traffic (zero-ui→zero-api, gateway→api) uses compose DNS, never touches the host firewall.
- Legion→Zero via `host.docker.internal` arrives from Docker NAT subnets (not 192.168.4.0/22) — unaffected.
- Tailscale addresses are outside 192.168.4.0/22 — unaffected.
- The phone PWA uses port 5173 (nginx proxy) — unaffected.

Rollback: `Remove-NetFirewallRule -DisplayName 'Zero hardening: block LAN inbound zero-api+vllm'`

## The real fix (when G2 clears and a rebuild is possible)

1. Add a global router-level auth dependency at `include_router` time (or an HTTP middleware with
   an allowlist: `/health*`, `/api/google-oauth/*`, `/api/reachy-intent/providers/status`, docs).
2. Add a global fetch wrapper in the frontend that attaches `getAuthHeaders()` to every `/api` call;
   the PWA already has a login page + token store (`lib/auth.ts`).
3. Rebind published ports to loopback where no LAN consumer exists (vllm 18801 first), or keep
   0.0.0.0 + rely on auth.
4. Re-audit: `meeting_ws.py` websockets and the nginx-proxied host-agent paths need token-in-query
   or cookie auth (browsers cannot set WS headers).
