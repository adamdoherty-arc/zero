# Managed projects registry

Mirror of `Legion/backend/app/core/legion_config.py::MANAGED_PROJECTS`
(verified 2026-04-27), augmented with audit metadata.

> **Path correction (2026-04-27)**: legion_config.py lives under
> `backend/app/core/`, not `backend/app/services/`. Original lib entry was
> wrong. Future audit Phase F should glob for `legion_config.py` rather than
> hardcoding the path.

## Tier 0 - company operating root

| component | path | mandate / canonical doc | purpose |
|---|---|---|---|
| company | `c:\code\zero` | `docs\company\mandate.md`, `docs\company\master-plan.md`, `docs\company\architecture.md`, `docs\company\living-state.md` | Canonical home for company docs, plans, audit state, and operating model |

`c:\code\ArchitectureMaster` is now a compatibility pointer only. Future audit
state and planning should live under `c:\code\zero`.

## Tier 1 â€” projects in legion_config.py::MANAGED_PROJECTS (the canonical registry)

| project | path | mandate / canonical doc | docker compose | ports | auto_learn | legion_may_pr |
|---|---|---|---|---|---|---|
| zero | `c:\code\zero` | `MANDATE.md`, `CLAUDE.md`, [docs/ARCHITECTURE.md](c:/code/zero/docs/ARCHITECTURE.md) | (project-internal compose if any; runs alongside shared-infra) | api 18792, ui 5173, **postgres 5434** | yes | yes |
| legion | `c:\code\Legion` | `MANDATE.md`, [docs/ARCHITECTURE.md](c:/code/Legion/docs/ARCHITECTURE.md) (post-pivot canonical) | `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.observability.yml`, `docker-compose.prod.yml` (`docker-compose.vllm.disabled.yml` is **legacy** â€” vLLM moved to `shared-infra/`) | api 8005, ui 3001/3005, **postgres 5433** | yes | yes |
| ada | `c:\code\ADA` | `MANDATE.md`, `CLAUDE.md` | `docker-compose.yml`, `docker-compose.prod.yaml` | api 8006 (host) â†’ 8003 (container), ui 5420 | yes | yes (`write_external`) |
| fortressos | `c:\code\fortressOS` | (no project-level MANDATE.md yet â€” gap flagged in active 12-week plan) | (per-project) | api 8001, postgres 5436 (per legion_config) | paused (2026-04-27 â€” intentional pause; standalone job-hunting app, not active core ecosystem work) | yes |
| aicontenttools | `c:\code\AIContentTools` | (no MANDATE.md) | (per-project) | n/a in registry | no (`auto_learn: false`) | n/a |
| profstudio | `c:\code\profstudio` | n/a | (Electron + FastAPI) | n/a in registry | yes | n/a |

## Tier 2 â€” infrastructure (NOT in MANAGED_PROJECTS, but the audit must check them)

| component | path | docker compose | ports |
|---|---|---|---|
| shared-infra | `c:\code\shared-infra` | `docker-compose.vllm.yml` | litellm 4444, vllm-embed 8001, **llama-cpp-chat 18800 (host) -> 8000 (container)** |
| vault | `c:\code\vault\ObsidianZero` | n/a | n/a; constitution at `00_Meta\CLAUDE.md` |
| reachy | `c:\code\reachy-apps` | n/a | **8000 (hardcoded â€” owns the host port; vLLM moved to 18800 to clear)** |
| docker-hub | `c:\code\docker` | `dockge-compose.yml`, `portainer-compose.yml`, `monitoring-compose.yml` | dockge 5001, monitoring stack |
| homeassistant | `c:\code\homeassistant` | `docker-compose.yml` | 8123 |

## Health gates the audit applies

- **mandate_file** missing â†’ critical for {zero, legion, ada}.
- **claude_file** missing â†’ high.
- **docker_compose** referenced in this table but not on disk â†’ high (drift).
- **last commit > 14d** AND `auto_learn: yes` â†’ medium "stale".
- **last commit > 14d** AND `auto_learn: paused` â†’ no finding (intentional pause).
- **last commit > 60d** â†’ high "abandoned?" â€” surface as open question (regardless of auto_learn).

## Cross-project invariants

1. `Legion/backend/app/core/legion_config.py::MANAGED_PROJECTS` should
   declare zero, ada, fortressos, aicontenttools, legion (self), and any
   addtl entries (currently: profstudio). Drift from this
   table â†’ queue.
2. Vault writes from any project must funnel through Zero's
   `vault_writer_service` (which uses cyanheads MCP). Direct cyanheads MCP
   from Legion or Ada bypassing Zero is a violation. (Search per-project
   `.mcp.json` and source for `cyanheads` outside zero â€” flag.)
3. Live broker order code path in Ada must always have `interrupt()` or env
   gate. Audit Phase F enforces.

