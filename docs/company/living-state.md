---
owner: company
status: generated-or-audit-maintained
source_of_truth: living-state
last_verified: 2026-05-05
verified_against:
  - C:\code\shared-infra\litellm\config.yaml
  - C:\code\shared-infra\docker-compose.vllm.yml
  - C:\code\zero\.mcp.json
  - C:\code\Legion\.mcp.json
  - C:\code\ADA\.mcp.json
  - C:\code\zero\docs\company\ruflo-incorporation.md
drift_policy: Legion may update after read-only verification; external writes stay queued
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Company Living State

This file records current ecosystem facts that can drift. It should be refreshed
by the ecosystem audit or, later, Legion's company operations subgraph.

## Verification Snapshot

| Field | Value |
|---|---|
| Last manual verification | 2026-05-02 |
| Active execution plan | `C:\code\zero\docs\company\plans\active\review-the-two-lively-cascade.md` |
| Company operating root | `C:\code\zero` |
| Company OS dashboard | `C:\code\zero\frontend` routes under `/company` |
| Company OS database contract | Zero SQLAlchemy/Alembic models, seeded from migrated Company OS data |
| Company OS task extension | Zero task, approval, context, and docs endpoints |
| Legacy constitution root | `C:\code\ArchitectureMaster` compatibility mirror only |
| Vault root | `C:\code\vault\ObsidianZero` |
| Company vault mirror | `C:\code\vault\ObsidianZero\30_Efforts\38_Doherty_Applied_AI\README.md` |
| Runtime truth checked | `shared-infra` LiteLLM config and compose |
| Ruflo evaluation root | `C:\code\sandbox\ruflo-eval` |

## Runtime Facts

| Port | Current owner | Notes |
|---|---|---|
| 4444 | `shared-litellm` | LiteLLM gateway for Zero, Legion, and Ada |
| 18800 | `llama-cpp-chat` | OpenAI-compatible local chat endpoint for `qwen3-chat` |
| 8001 | `vllm-embed` | `Qwen/Qwen3-Embedding-0.6B` embeddings |
| 8000 | Reachy Mini daemon | Hard reserved; model serving must not bind this host port |
| 18792 | Zero backend | FastAPI |
| 8005 | Legion backend | FastAPI |
| 8006 | Ada backend host mapping | Container API is commonly `:8003` |
| 5173 | Zero UI | Vite |
| 5420 | Ada UI | Vite |
| 3005 | Legion UI | Current primary UI port |
| 3011 | Legacy Company OS dashboard | Historical Next.js reference only; active UI is Zero on `:5173` |

## Model Registry

| Canonical name | Backend | Current state |
|---|---|---|
| `qwen3-chat` | `http://host.docker.internal:18800/v1` | Active local chat model served by llama.cpp from `Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K_M.gguf` |
| `qwen3-chat-thinking` | Same endpoint | Reasoning-enabled variant in LiteLLM config |
| `Qwen/Qwen3.6-35B-A3B-abliterated` | Same endpoint | Explicit model-id alias |
| `qwen3-embed` | `http://vllm-embed:8001/v1` | Active local embedding model |
| `qwen3-coder` | Not active in current LiteLLM config | Legacy docs/callers should be audited or routed to `qwen3-chat` until a dedicated coder model returns |

LiteLLM is pinned in compose to `ghcr.io/berriai/litellm:main-v1.83.7-stable`.
Do not downgrade to the compromised `1.82.7` / `1.82.8` window or the vulnerable
`<=1.81.14` line.

## MCP State

| Project | MCP status |
|---|---|
| Zero | `.mcp.json` references `zero-mcp`, `legion-mcp`, `ada-mcp`, `cyanheads-obsidian`, `postgres-mcp`, memory, qmd, Kimi, and Playwright |
| Legion | `.mcp.json` references `zero-mcp`, `legion-mcp`, `ada-mcp`, `cyanheads-obsidian`, `postgres-mcp`, and Playwright |
| Ada | `.mcp.json` currently references Playwright and codebase-memory only |

Known MCP drift: `C:\code\ADA\mcp_servers\ada_mcp.py` was referenced by Zero and
Legion configs but was not present during the 2026-05-02 inspection. Treat this
as a queued implementation gap, not a silent runtime assumption.

## Open Drift

| Item | Severity | Target |
|---|---|---|
| Ada MCP server missing while other projects reference it | high | Create `ada-mcp` or remove references until implemented |
| Ada MCP config is thinner than Zero/Legion configs | medium | Align after `ada-mcp` exists |
| Some project docs still say local execution is `qwen3-coder` or `Qwen3-32B-AWQ` | medium | Update docs/callers to current `qwen3-chat` routing |
| Legion daemon heartbeat surface is still required for trustworthy daily state | medium | Implement `daemon_heartbeats` and expose API/UI |
| Graphify/code graph layer is not yet piloted | low | Run against one repo and compare token/usefulness metrics |
| Ruflo lockfile audit reports critical dependency vulnerabilities | high | Keep evaluation-only; review or replace vulnerable dependency paths before command execution beyond narrow sandbox tests |
| Ruflo sandbox evaluation is prepared but not adopted | low | Package inspection and protected-file diff have run; low-risk command/scenario testing is still pending |

## Future Legion Interfaces

These are the contracts the company operating system expects Legion to own:

| Interface | Purpose |
|---|---|
| `company.audit.run(read_only: bool)` | Run the ecosystem audit and optionally apply whitelisted local doc fixes |
| `company.drift.list()` | Return current drift grouped by severity and owner |
| `company.queue.add/fetch/resolve()` | Manage queued external, financial, service, and product-compliance actions |
| `projects.graph.query(project, question)` | Query Graphify/codebase graph output for architecture and impact questions |
| `llm_ops.models.current()` | Report active model routes from LiteLLM/compose/runtime |
| `llm_ops.models.candidates()` | Report researched candidate models and eval status |

## Company OS Runtime

The Company OS first milestone now has:

| Surface | State |
|---|---|
| Dashboard app | React/Vite Company routes in `C:\code\zero\frontend` |
| Legion bridge | Zero should read Legion status from `http://localhost:8005` |
| Database schema | Zero SQLAlchemy/Alembic models seeded from migrated Company OS data |
| Approval guardrail | High-risk and critical actions require human approval and cannot be auto-executed |
| Task source of truth | Zero Company OS database tasks and dashboard; Obsidian mirrors context; Notion deferred |
| Obsidian mirror | Summary effort note created under `30_Efforts/38_Doherty_Applied_AI` |
| Ruflo | Evaluation-only pattern source in `C:\code\sandbox\ruflo-eval`; no production adapter enabled |

Legacy `architecture_master.*` names may remain as aliases during migration, but
new work should use the `company.*` namespace.


