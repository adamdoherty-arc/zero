# Plan: `ecosystem-audit` — self-learning Claude Code skill

## Context

`c:\code\ArchitectureMaster\docs\` holds five canonical documents (`README.md`, `MANDATE.md`, `ARCHITECTURE.md`, `AgenticOs.md`, `SecondBrain.md`) that describe a three-pillar personal AI ecosystem — **Zero** (chief-of-staff, `c:\code\zero`), **Legion** (24/7 orchestrator + LLM-ops owner, `c:\code\Legion`), **Ada** (autonomous financial advisor, `c:\code\ADA`) — sharing a single Postgres, an Obsidian vault at `c:\code\vault\ObsidianZero`, and a vLLM/LiteLLM stack at `c:\code\shared-infra`. The projects are decoupled in code but share a constitution (`docs/MANDATE.md`) and a 12-week rollout plan (`C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md`).

Today there is no recurring mechanism that:
1. Re-reads the master docs and confirms each project's `MANDATE.md` / `CLAUDE.md` still matches the canonical mandate quotes.
2. Verifies the runtime (Docker stacks, vLLM endpoints, Postgres databases, Obsidian vault structure, MCP servers) actually matches `ARCHITECTURE.md`.
3. Carries learning forward between sessions — drift found last week should not need to be re-discovered this week.
4. Keeps the model layer fresh — researches new HuggingFace / NVIDIA NVFP4 / supply-chain advisories daily.

This plan delivers a project-scoped Claude Code skill (`ecosystem-audit`) that does all four every time it is invoked, persists what it learned, and self-heals where the MANDATE.md tier system allows.

## Skill identity (decisions locked from clarifying questions)

- **Location**: project-local — `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\`. Invoked from any session whose cwd is under `c:\code\ArchitectureMaster`. (User-global mirror is *not* added — running it from inside Zero/Legion/Ada would conflict with their own per-project `CLAUDE.md` cwd context.)
- **Autonomy**: self-heal where possible *within MANDATE tier discipline*. The skill auto-applies anything that is `read` or `write_local` in scope (doc fixes, scaffolding, vault `_agent/proposals/` writes, state files). It **never** auto-applies anything `write_external` (git push, gh PR, model swap, container restart, code edit in zero/Legion/Ada source) — those land in `ACTION_QUEUE.md` for human approval. This honors the constitution at [docs/MANDATE.md](c:/code/ArchitectureMaster/docs/MANDATE.md#L31-L41).
- **Live research** every run: new LLM releases · second-brain/PKM patterns · Legion↔desktop-control state of art · LiteLLM/vLLM supply-chain advisories.

## Deliverables (file tree)

Create under `c:\code\ArchitectureMaster\`:

```
.claude/
  skills/
    ecosystem-audit/
      SKILL.md                          # the skill itself
      lib/
        canonical-mandates.md           # extracted verbatim mandate quotes (Zero/Legion/Ada)
        port-map.md                     # extracted port table from ARCHITECTURE.md (single source of truth)
        managed-projects.md             # registry: paths, MANDATE.md path, compose files, ports
        plugin-baseline.md              # required Obsidian plugin list from SecondBrain.md
        models-baseline.md              # current vLLM/LiteLLM model registry snapshot
      checks/
        docs-parity.md                  # check definitions (read-only inputs to the skill body)
        runtime-health.md
        obsidian.md
        vllm-litellm.md
        per-project-alignment.md
  state/
    ecosystem-audit/
      INSIGHTS.md                       # rolled-up persistent knowledge (the "learning")
      ACTION_QUEUE.md                   # open items dedup'd across runs
      EVOLUTION.md                      # how the audit itself has changed (skill self-improvement log)
      baseline/
        snapshot-<YYYY-MM-DD>.json      # canonical state snapshot, written once and on intentional updates
      runs/
        <YYYY-MM-DD-HHMM>.md            # one report per run (timestamped, never edited)
      research/
        models/<YYYY-MM-DD>.md          # daily model-watch findings
        pkm/<YYYY-MM-DD>.md             # daily second-brain findings
        desktop-control/<YYYY-MM-DD>.md
        supply-chain/<YYYY-MM-DD>.md
```

Also write a one-line pointer in `c:\Users\hadam\.claude\projects\c--code-ArchitectureMaster\memory\MEMORY.md` so that future sessions know where the skill state lives:

```
- [Ecosystem audit state](../../../../code/ArchitectureMaster/.claude/state/ecosystem-audit/) — INSIGHTS.md, ACTION_QUEUE.md, runs/ — read INSIGHTS.md before doing ecosystem-wide work.
```

(plus a single `project_ecosystem_audit.md` memory file with type `reference` describing the skill).

## SKILL.md design

### Frontmatter

```yaml
---
name: ecosystem-audit
description: |
  Read the five docs in c:\code\ArchitectureMaster\docs\ and audit Zero,
  Legion, Ada, the shared vLLM/LiteLLM stack, and the Obsidian vault for
  drift from MANDATE.md and ARCHITECTURE.md. Self-heals safe items
  (doc parity, scaffolding, vault _agent/proposals/) and queues anything
  write_external. Each run produces a timestamped report under
  .claude/state/ecosystem-audit/runs/, updates INSIGHTS.md, and dedupes
  ACTION_QUEUE.md. Researches new models, PKM patterns, desktop-control
  advances, and supply-chain advisories every run.
  Use when asked to "ecosystem audit", "review the docs", "sync the
  ecosystem", "check drift", or to invoke the project's audit loop.
  Run on every new session in c:\code\ArchitectureMaster — it is
  designed to learn more and more across runs.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - WebSearch
  - WebFetch
  - AskUserQuestion
  - Agent
---
```

### Body (run protocol)

The body of `SKILL.md` is the procedure Claude follows. Structured as ten phases:

#### Phase A — Boot & memory load
1. Read [docs/MANDATE.md](c:/code/ArchitectureMaster/docs/MANDATE.md), [docs/ARCHITECTURE.md](c:/code/ArchitectureMaster/docs/ARCHITECTURE.md), [docs/README.md](c:/code/ArchitectureMaster/README.md) in full. Read `docs/AgenticOs.md` and `docs/SecondBrain.md` headings + any sections referenced by `INSIGHTS.md`.
2. Read `lib/canonical-mandates.md`, `lib/port-map.md`, `lib/managed-projects.md`, `lib/plugin-baseline.md`, `lib/models-baseline.md` (the skill's own extracted source of truth).
3. Read `state/ecosystem-audit/INSIGHTS.md` and `ACTION_QUEUE.md`. Read the most recent two files in `runs/`. Note any open items or recurring drift.
4. If `state/ecosystem-audit/baseline/` is empty → mark this as **first run** and branch to the first-run flow at the bottom.

#### Phase B — Per-project doc parity (parallel via Agent)
Spawn three `Explore` agents in parallel, one per project. Each compares:
- The verbatim mandate quote in the project's `MANDATE.md` against `lib/canonical-mandates.md` (extracted from `docs/MANDATE.md` lines 7–29).
- The project's `CLAUDE.md` for stale references, missing partition tags, missing reference to global `MANDATE.md`.
- The project's `.mcp.json` against the MCP server list in `ARCHITECTURE.md` (cyanheads-obsidian, ada-mcp, zero-mcp, legion-mcp, postgres-mcp, …).

Per project, the agent reports a short diff summary. Self-heal: if a verbatim mandate quote diverges from the canonical one, fix the project's `MANDATE.md` (this is `write_local` — agent-owned doc, not source code). All other project edits → queue.

Files to compare:
- `c:\code\zero\MANDATE.md` and `c:\code\zero\CLAUDE.md`
- `c:\code\Legion\MANDATE.md` and `c:\code\Legion\CLAUDE.md`
- `c:\code\ADA\MANDATE.md` and `c:\code\ADA\CLAUDE.md`

#### Phase C — Runtime & container health
1. `docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'` — list all running containers.
2. For each compose file in the registry (`Legion/docker-compose*.yml`, `ADA/docker-compose*.yml`, `shared-infra/docker-compose.vllm.yml`, `c:\code\docker\dockge-compose.yml`, `homeassistant/docker-compose.yml`), read it and confirm the containers it declares are either running or expected-down.
3. Check ports 4444, 8001, 18800, 11434, 18792, 8005, 8006, 5432, 5433 with `Test-NetConnection` (PowerShell) or curl. Cross-check against `lib/port-map.md`.
4. Health endpoints: `curl http://localhost:4444/health`, `curl http://localhost:18800/health`, `curl http://localhost:8001/health`. Capture HTTP status, latency, model list.
5. Check that the Reachy `:8000` reservation is not being squatted by another service (the docs flag this as a known collision risk).

Self-heal: nothing in this phase auto-runs against Docker. All findings → queue with severity (`degraded` vs `down` vs `port-collision`).

#### Phase D — Obsidian vault verification
1. Confirm `c:\code\vault\ObsidianZero\` exists and contains `00_Meta/`, `10_Atlas/`, `20_Calendar/`, `30_Efforts/`, `40_Resources/`, `_Inbox/`, `Zero/`. If any required ACE+JD folder is missing → create it (write_local) with a `.gitkeep`.
2. Read `00_Meta\CLAUDE.md` (vault constitution) — confirm it exists; if missing, queue (do **not** auto-write the constitution; it's load-bearing).
3. Read `.obsidian/community-plugins.json` and confirm the plugin baseline from `lib/plugin-baseline.md` (Templater, QuickAdd, Tasks, Periodic Notes, Calendar, **Obsidian Git**, Dataview, Bases, Advanced URI, Linter). For each missing plugin, write an entry to `00_Meta/_agent/proposals/plugin-<name>.md` describing why and the install URL.
4. Confirm Obsidian Git is configured (look for `.obsidian/plugins/obsidian-git/data.json` and a recent auto-commit in `.git/logs/HEAD`). If silent for >24h → queue.
5. Confirm `40_Resources/llm-models.md` exists (the Legion LLM-ops journal); if missing, scaffold it from `lib/models-baseline.md`.

#### Phase E — vLLM, LiteLLM, model registry
1. From `shared-infra/docker-compose.vllm.yml`, extract the served models. Cross-reference with `lib/models-baseline.md`. Diff → report.
2. Hit `:4444/v1/models` and `:18800/v1/models`. Confirm canonical names (`qwen3-chat`, `qwen3-coder`, `qwen3-embed`) resolve.
3. Pin check: parse `shared-infra/.env` or compose for `litellm` image tag — confirm version ≥ 1.81.14 (per `MANDATE.md` operational invariant #7). Versions 1.82.7 / 1.82.8 are explicitly compromised.
4. VRAM budget sanity: `nvidia-smi --query-gpu=memory.used,memory.total --format=csv` (best-effort; skip if WSL/no nvidia-smi). Compare against the 22 GB pinned / 10 GB headroom budget.

#### Phase F — Per-project freshness (Ada-focused, but applies to all three)
1. For each managed project, run `git log -1 --format='%ai %h %s'` and read the most recent commit. Flag if `MANAGED_PROJECTS` registry in `Legion/legion_config.py` says it's auto-learned but no commits in 14 days (likely stale or paused).
2. Ada-specific: read `ADA/requirements.docker.txt` and check broker SDK versions (tradier, alpaca-trade-api, robin-stocks). For each, WebSearch the latest release; flag major-version drift.
3. Ada-specific: confirm paper-default invariant — grep `ADA/backend/routers/broker_orders.py` for the env-var gate referenced in the canonical plan; flag if the gate has been weakened.
4. Confirm each project's APScheduler / Windows Task / NSSM service is listed and (best-effort) running.

#### Phase G — Live research (parallel WebSearch)
Spawn four searches in parallel:
- **Models**: HuggingFace + NVIDIA NVFP4 namespace + Qwen/Llama/DeepSeek release feeds, filtered to RTX 5090 fit (≤32 GB VRAM at ≥4-bit).
- **PKM**: new Obsidian plugins, Letta/Mem0/LangMem releases, retrieval techniques (contextual retrieval, hybrid search, rerankers).
- **Desktop control**: UFO³ updates, Claude Computer Use Windows GA status, ChatGPT Agent connector additions.
- **Supply chain**: PyPI/npm advisories for `litellm`, `langgraph`, `pydantic-ai`, `mcp-*`. Specifically watch the LiteLLM compromise pattern.

Write each agent's findings to `state/ecosystem-audit/research/<topic>/<date>.md`. Promote anything actionable to `ACTION_QUEUE.md` and (for model candidates) append a one-line entry to `40_Resources/llm-models.md` under "Candidates" — *not* as a swap, just a candidate row. Actual model swaps remain Legion's `llm_ops` subgraph job, gated by approval.

#### Phase H — Self-heal pass
Apply only the items the skill is allowed to auto-apply (per the autonomy ruling and tier matrix):

| Action | Tier | Auto? |
|---|---|---|
| Fix verbatim mandate quote in per-project `MANDATE.md` | write_local | Yes |
| Create missing vault ACE+JD folder + `.gitkeep` | write_local | Yes |
| Scaffold `40_Resources/llm-models.md` if missing | write_local | Yes |
| Write to `00_Meta/_agent/proposals/*.md` | write_local (`_agent/` namespace) | Yes |
| Update `state/ecosystem-audit/INSIGHTS.md` | local skill state | Yes |
| Append to `ACTION_QUEUE.md` | local skill state | Yes |
| Edit project source code, push, open PR | write_external | **Never auto** — queue |
| Restart / `docker compose up -d` containers | write_external | **Never auto** — queue |
| Apply LiteLLM model swap | write_external | **Never auto** — queue |
| Install Obsidian plugin | write_external (touches `.obsidian/`) | **Never auto** — queue |

Every auto-write carries the audit footer required by `MANDATE.md` invariant #3:

```
<!-- agent-run-id: {uuid} source: ecosystem-audit at: {iso8601} -->
```

#### Phase I — Write the run report
Write `state/ecosystem-audit/runs/<YYYY-MM-DD-HHMM>.md` with sections:
1. **TL;DR** — 5-line summary.
2. **Drift found** (per phase, one bullet each).
3. **Self-healed** — what the skill auto-applied with file paths.
4. **Queued** — new items appended to `ACTION_QUEUE.md` (with diff vs prior queue).
5. **Research highlights** — top 3 model/PKM/desktop/supply-chain findings worth attention.
6. **Open questions** — anything that needs the user to clarify before next run.
7. **Run metrics** — wall time, files read, doc-parity diff size, queue length delta.

#### Phase J — Update INSIGHTS and EVOLUTION
1. Promote any finding that has now appeared in **two** consecutive runs into `INSIGHTS.md` (it's a real pattern, not noise). Demote items that have been resolved.
2. If the skill itself learned a new check (e.g. user said "also check X"), append to `EVOLUTION.md` with a date and the new instruction. Future runs read `EVOLUTION.md` in Phase A.
3. End by printing a one-screen status to the user: "Run N complete. Healed X. Queued Y. Research filed under Z. Top item: …".

### First-run flow (different from steady-state)

On the first run there is no baseline, so Phase A branches to:
1. Snapshot the current canonical state into `state/ecosystem-audit/baseline/snapshot-<date>.json`:
   - Hash of each doc in `docs/`.
   - Verbatim mandate quotes extracted from `docs/MANDATE.md`.
   - Port map extracted from `README.md` / `ARCHITECTURE.md`.
   - Plugin list from current `.obsidian/community-plugins.json` (treat as baseline if vault is healthy; otherwise from `SecondBrain.md`).
   - Container list from `docker ps`.
   - LiteLLM model list from `:4444/v1/models`.
2. Generate `lib/*.md` files from the snapshot (the skill's extracted source of truth).
3. Seed `INSIGHTS.md` with a header and a "Run 1: baseline established" entry.
4. Then run Phases B–J normally.

## Critical files (read targets / write targets)

**Read (every run):**
- [c:\code\ArchitectureMaster\docs\MANDATE.md](c:/code/ArchitectureMaster/docs/MANDATE.md)
- [c:\code\ArchitectureMaster\docs\ARCHITECTURE.md](c:/code/ArchitectureMaster/docs/ARCHITECTURE.md)
- [c:\code\ArchitectureMaster\README.md](c:/code/ArchitectureMaster/README.md)
- `c:\code\zero\MANDATE.md`, `c:\code\Legion\MANDATE.md`, `c:\code\ADA\MANDATE.md`
- `c:\code\Legion\backend\app\services\legion_config.py` (MANAGED_PROJECTS registry)
- `c:\code\shared-infra\docker-compose.vllm.yml`, `c:\code\shared-infra\.env`, `c:\code\shared-infra\litellm\` configs
- `c:\code\vault\ObsidianZero\00_Meta\CLAUDE.md`
- `c:\code\vault\ObsidianZero\.obsidian\community-plugins.json`
- `C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md` (active 12-week plan; the skill respects its phase boundaries)

**Write (auto, every run):**
- `c:\code\ArchitectureMaster\.claude\state\ecosystem-audit\runs\<timestamp>.md`
- `c:\code\ArchitectureMaster\.claude\state\ecosystem-audit\INSIGHTS.md`
- `c:\code\ArchitectureMaster\.claude\state\ecosystem-audit\ACTION_QUEUE.md`
- `c:\code\ArchitectureMaster\.claude\state\ecosystem-audit\research\*\<date>.md`
- `c:\code\vault\ObsidianZero\00_Meta\_agent\proposals\*.md` (when proposing plugins, model swaps, drift fixes)

**Write (first run only, then on intentional refresh):**
- `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\SKILL.md`
- `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\lib\*.md`
- `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\checks\*.md`
- `c:\code\ArchitectureMaster\.claude\state\ecosystem-audit\baseline\snapshot-<date>.json`

## Reuse (not reinventing)

- The auto-memory system at `c:\Users\hadam\.claude\projects\c--code-ArchitectureMaster\memory\` already exists; the skill registers itself there with a single pointer line in `MEMORY.md` and one `reference`-type memory file. It does **not** duplicate run logs into auto-memory.
- The `MANDATE.md` approval-tier matrix is the single source of truth for what auto-applies and what queues — the skill body explicitly cites the matrix rather than redefining it.
- Existing `start-ecosystem.bat` / `stop-ecosystem.bat` at the project root remain the launch interface; the skill never starts/stops services itself.
- `Legion/backend/app/subgraphs/llm_ops.py` (Stage 3 in the active plan) is the eventual home for runtime model swaps. The audit skill does *research and propose*; Legion's llm-ops does the actual A/B and swap. They are complementary, not duplicative.

## Verification

After implementation, verify in this order:

1. **Skill discovery**: in a fresh session at `c:\code\ArchitectureMaster`, confirm the skill appears in the available-skills list (it should — project-local skills auto-load).
2. **First run** — invoke `ecosystem-audit`. Expect:
   - `lib/` and `state/ecosystem-audit/baseline/snapshot-<date>.json` created.
   - One run report under `runs/`.
   - `INSIGHTS.md` with one entry.
   - `ACTION_QUEUE.md` populated with whatever drift was found.
   - At least one file under each of `research/{models,pkm,desktop-control,supply-chain}/`.
   - The user-facing summary is ≤30 lines.
3. **Per-project check**: open `c:\code\zero\MANDATE.md`, `c:\code\Legion\MANDATE.md`, `c:\code\ADA\MANDATE.md`. The verbatim mandate quote should now match `docs/MANDATE.md` lines 7–29 byte-for-byte (or already did, in which case Phase B says "no drift").
4. **Container audit truth-test**: `docker stop` one container that should be running (e.g. shared-infra vLLM if it's up). Re-invoke the skill. Phase C should report it as `down`, the run report should call it out, and `ACTION_QUEUE.md` should gain one new item — but the skill should **not** restart it.
5. **Self-learning test**: introduce the same drift (e.g. delete a vault folder) twice. After the second run, the issue should appear in `INSIGHTS.md` (promoted because it appeared twice) — confirming the learning loop works.
6. **Tier discipline test**: confirm no run touched any file under `c:\code\zero\backend\`, `c:\code\Legion\backend\`, `c:\code\ADA\backend\`, `.obsidian/` (excluding `_agent/`), or `.git/`. The git status of those repos must be clean of unintentional changes.
7. **Memory pointer**: `c:\Users\hadam\.claude\projects\c--code-ArchitectureMaster\memory\MEMORY.md` contains the single pointer line, and `project_ecosystem_audit.md` exists with `type: reference` frontmatter.

## What is *not* in scope (for clarity)

- Building `Legion/backend/app/subgraphs/llm_ops.py` — that is Stage 3 of the active 12-week plan.
- Wiring NSSM services for 24/7 — Stage 0 of the active plan.
- Implementing the Obsidian vault constitution at `00_Meta/CLAUDE.md` — pre-existing artifact; the skill only verifies it.
- Replacing the GSD framework or any other existing skill — `ecosystem-audit` lives alongside them.
- Any actual model swap, container restart, code edit, or git push — those are queued, never auto.
