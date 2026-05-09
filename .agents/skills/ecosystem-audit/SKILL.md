---
name: ecosystem-audit
description: |
  Read the canonical docs in c:\code\zero\docs\company\ and audit
  Zero, Legion, Ada, the shared vLLM/LiteLLM stack, and the Obsidian vault for
  drift from MANDATE.md and ARCHITECTURE.md. Self-heals safe items (doc parity,
  scaffolding, vault _agent/proposals/, skill state) and queues anything
  write_external. Each run produces a timestamped report under
  state/ecosystem-audit/runs/, updates INSIGHTS.md, dedupes
  ACTION_QUEUE.md, and researches new models, PKM patterns, desktop-control
  advances, and supply-chain advisories.
  Use when asked to "ecosystem audit", "review the docs", "sync the
  ecosystem", "check drift", or to invoke the project's audit loop.
  Designed to be re-run every session in c:\code\zero - it
  learns more across runs.
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

# ecosystem-audit

You are auditing Adam's three-pillar personal AI ecosystem. The constitution is
[docs/company/mandate.md](../../../docs/company/mandate.md). The locked topology is
[docs/company/architecture.md](../../../docs/company/architecture.md). The company rollout this
audit must respect (not duplicate or override) is at
`C:\code\zero\docs\company\plans\active\review-the-two-lively-cascade.md`.

This skill is **self-learning**: it persists findings, dedupes them across runs,
and only promotes patterns that recur. It is **tier-disciplined**: it auto-heals
inside `read` and `write_local`; it never auto-applies anything `write_external`
or `financial`.

## Identity & ground rules

1. **Tier discipline (non-negotiable).** Honor the matrix at
   [docs/company/mandate.md#approval-tier-matrix](../../../docs/company/mandate.md). Auto-apply
   only the actions whitelisted in Phase H below. Anything else -> append to
   `state/ecosystem-audit/ACTION_QUEUE.md` and continue.
2. **Audit footer.** Every file you write under this skill carries:
   `<!-- agent-run-id: {uuid} source: ecosystem-audit at: {iso8601} -->` as the
   last line. Generate a UUID once at boot and reuse it for the whole run.
3. **Never touch.** `.obsidian/` (except via proposals to `_agent/`),
   `.git/`, `.trash/`, code under `c:\code\zero\backend\`,
   `c:\code\Legion\backend\`, `c:\code\ADA\backend\`,
   `shared-infra/docker-compose*.yml`, any `.env`. Read freely, never edit.
4. **DND respect.** If current time in America/New_York is between 22:00 and
   07:00, suppress all interrupts. Findings still go to the report and queue;
   no AskUserQuestion calls.
5. **Frontmatter merge, never replace.** When patching YAML frontmatter, edit
   the one field; never rewrite the whole header. (MANDATE.md invariant #4.)

## Boot

1. Generate the run UUID (use `python -c "import uuid;print(uuid.uuid4())"` if
   needed) and record the run start ISO timestamp in America/New_York.
2. Read these in order; stop if any is missing and queue it as a fatal finding:
   - [docs/company/mandate.md](../../../docs/company/mandate.md)
   - [docs/company/architecture.md](../../../docs/company/architecture.md)
   - [README.md](../../../README.md)
3. Load the skill's extracted source-of-truth from `lib/`:
   - `lib/canonical-mandates.md` â€” verbatim mandate quotes for Zero/Legion/Ada
   - `lib/port-map.md` â€” the canonical port table
   - `lib/managed-projects.md` â€” registry of projects (path, mandate file, compose, ports)
   - `lib/plugin-baseline.md` â€” required Obsidian community plugins
   - `lib/models-baseline.md` â€” the LiteLLM/vLLM canonical model registry
4. Load skill state:
   - `state/ecosystem-audit/INSIGHTS.md` (entire file)
   - `state/ecosystem-audit/ACTION_QUEUE.md` (entire file)
   - `state/ecosystem-audit/EVOLUTION.md` (any check additions from past runs)
   - The two most recent files under `state/ecosystem-audit/runs/`
5. Decide branch: if `state/ecosystem-audit/baseline/` is empty â†’ **first run**,
   jump to "First-run flow" at the bottom, then return here for Phases Bâ€“J.
   Otherwise continue.
6. Skim AgenticOs.md and SecondBrain.md ONLY if `INSIGHTS.md` references them
   for an open thread. They are 50 KB+ each â€” do not load them blindly.

## Phase B â€” Per-project doc parity (parallel)

Spawn three Explore agents in **one message, parallel**, one per project. Each
agent's prompt:

> You are checking project drift against `c:\code\zero\docs\company\`.
> Inputs: the canonical mandate quote in `lib/canonical-mandates.md` (the section
> for {Zero|Legion|Ada}), and the project root `c:\code\{zero|Legion|ADA}`.
>
> Compare:
> 1. The verbatim mandate quote in the project's `MANDATE.md` against the
>    canonical quote - character-by-character. Report any diff.
> 2. The project's `AGENTS.md` for stale references (paths that no longer exist,
>    project names that have changed) and confirm it links to
>    `c:\code\zero\docs\company\mandate.md`.
> 3. The project's `.mcp.json` (if present) against the MCP fabric in
>    `ARCHITECTURE.md` - flag missing servers (cyanheads-obsidian, ada-mcp,
>    zero-mcp, legion-mcp, postgres-mcp, etc.).
>
> Report concise findings under 250 words: drift y/n, severity, suggested fix.
> Do NOT edit any file.

After all three return, consolidate findings. **Self-heal**: if a verbatim
mandate quote diverges from canonical, fix the project's `MANDATE.md` quote
ONLY (the leading blockquote). Use Edit, preserve everything else. All other
items -> queue.

## Phase C - Runtime & container health

Run these checks. PowerShell tool is fine for Windows-native health checks.

1. `docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}'` - capture full output.
2. For each compose file in `lib/managed-projects.md`, `Read` it and confirm
   each declared service is in the `docker ps` output (or note as expected-down).
3. Port checks via PowerShell:
   ```powershell
   foreach ($p in 4444,8001,18800,11434,18792,8005,8006,5432,5433,8000) {
     $r = Test-NetConnection -ComputerName localhost -Port $p -WarningAction SilentlyContinue
     "$p : $($r.TcpTestSucceeded)"
   }
   ```
4. Health endpoints (best-effort, 5s timeout each):
   - `curl -m 5 http://localhost:4444/health`
   - `curl -m 5 http://localhost:18800/health`
   - `curl -m 5 http://localhost:8001/health`
   - `curl -m 5 http://localhost:18792/healthz` (Zero)
   - `curl -m 5 http://localhost:8005/healthz` (Legion)
   - `curl -m 5 http://localhost:8006/healthz` (Ada)
5. Reachy `:8000` collision check â€” if `:8000` answers and is **not** Reachy
   (no `/api/info` or wrong banner), this is the documented vLLM/Reachy
   collision. Flag as critical.

**Self-heal**: nothing here auto-runs. All findings â†’ queue with severity
`{ok | degraded | down | port-collision}`.

## Phase D â€” Obsidian vault verification

Vault root: `c:\code\vault\ObsidianZero\`.

1. Required ACE+JD folders: `00_Meta`, `10_Atlas`, `20_Calendar`, `30_Efforts`,
   `40_Resources`, `_Inbox`, `Zero`. For each missing folder, create it with a
   `.gitkeep`. (Self-heal â€” write_local in vault structure, not constitutional.)
2. Read `00_Meta\AGENTS.md` (vault constitution). If missing â†’ queue (do not
   auto-write â€” it is load-bearing).
3. Read `.obsidian/community-plugins.json` and diff against
   `lib/plugin-baseline.md`. For each missing plugin, write a proposal:
   ```
   c:\code\vault\ObsidianZero\00_Meta\_agent\proposals\plugin-<name>.md
   ```
   Include: why (one sentence from SecondBrain.md), install URL, frontmatter
   `{type: proposal, status: open, source: ecosystem-audit, run_id: <uuid>}`,
   audit footer.
4. Obsidian Git liveness: read `.obsidian/plugins/obsidian-git/data.json` if
   present, and check the most recent commit time on the vault repo
   (`git -C c:/code/vault/ObsidianZero log -1 --format=%ai`). If silent >24h
   â†’ queue.
5. Confirm `40_Resources/llm-models.md` exists. If missing, scaffold it from
   `lib/models-baseline.md` (this is the Legion LLM-ops journal â€”
   write_local, agent-owned namespace per Legion mandate).

## Phase E â€” vLLM, LiteLLM, model registry

1. Read `c:\code\shared-infra\docker-compose.vllm.yml` â€” extract `image:` and
   `command:` for each service. Diff served models against `lib/models-baseline.md`.
2. `curl -m 5 http://localhost:4444/v1/models` and `:18800/v1/models`. Confirm
   canonical names resolve: `qwen3-chat` and `qwen3-embed`. Flag `qwen3-coder`
   as legacy caller/doc drift unless Legion intentionally reintroduces a
   dedicated coder model.
3. **Pin check (critical)**: parse `c:\code\shared-infra\.env` and the compose
   file for the LiteLLM image tag. Per
   [MANDATE.md invariant #7](../../../docs/company/mandate.md): must be
   `main-v1.83.7-stable` or newer in the 1.83 stable line. Versions `1.82.7`
   / `1.82.8` were compromised, and versions `<=1.81.14` carry April 2026
   CVEs. Any match to those windows â†’ escalate as **critical** in the report.
4. VRAM (best-effort, skip on failure):
   ```bash
   nvidia-smi --query-gpu=memory.used,memory.total,name --format=csv,noheader
   ```
   Compare to the 22 GB pinned / 10 GB headroom budget from ARCHITECTURE.md.

## Phase F â€” Per-project freshness

For each project in `lib/managed-projects.md`:
1. `git -C <path> log -1 --format='%ai|%h|%s'` â€” last commit. If `auto_learn: true`
   and the last commit is >14 days old â†’ queue as "stale".
2. **Ada-specific**:
   - Read `c:\code\ADA\requirements.docker.txt` (and `requirements.txt` if exists).
     For `tradier`, `alpaca-trade-api`, `robin-stocks`, capture installed
     versions. Promote to research/models bucket if a major-version bump exists.
   - Grep `c:\code\ADA\backend\routers\broker_orders.py` for any
     `place_live_order` path. Confirm an `interrupt()` or env-var gate is
     present on every code path that places live orders. If a path lacks a
     gate â†’ queue as **critical** (this is the paper-default invariant).
3. **Legion-specific**: confirm `Legion/backend/app/services/legion_config.py`
   declares the MANAGED_PROJECTS registry consistent with `lib/managed-projects.md`.
4. **Zero-specific**: confirm `c:\code\zero\backend\app\services\vault_writer_service.py`
   exists (it is the choke point for vault writes â€” Legion routes through it).
   Missing or renamed â†’ queue.

## Phase G â€” Live research (parallel WebSearch)

Spawn four Agent calls in **one message, parallel**, each with subagent_type
`general-purpose`. Each writes its own findings file directly:

1. **Models** â†’ `state/ecosystem-audit/research/models/<YYYY-MM-DD>.md`.
   Search HuggingFace + NVIDIA NVFP4 namespace + Qwen / Llama / DeepSeek
   release feeds in the last 7 days. Filter to RTX 5090 fit (â‰¤32 GB VRAM at
   â‰¥4-bit, supports vLLM or TensorRT-LLM). Top 5 candidates with link, size,
   quant, and one-line "why it might beat current registry."
2. **PKM** â†’ `state/ecosystem-audit/research/pkm/<YYYY-MM-DD>.md`. New
   Obsidian community plugins, Letta/Mem0/LangMem releases, retrieval
   technique papers/blogs (contextual retrieval, hybrid, rerankers). Top 5.
3. **Desktop control** â†’ `state/ecosystem-audit/research/desktop-control/<YYYY-MM-DD>.md`.
   UFOÂ³ release notes, Codex Computer Use Windows status, ChatGPT Agent
   connector adds. Anything new that lets Legion reach into more applications.
4. **Supply chain** â†’ `state/ecosystem-audit/research/supply-chain/<YYYY-MM-DD>.md`.
   PyPI/npm advisories for `litellm`, `langgraph`, `pydantic-ai`, `langfuse`,
   any `mcp-*` server. Watch for the LiteLLM compromise pattern.

After agents return, promote actionable items to `ACTION_QUEUE.md` and append
candidate models to `c:\code\vault\ObsidianZero\40_Resources\llm-models.md`
under a `## Candidates` section (one row per candidate; not a swap).

## Phase H â€” Self-heal pass

Apply ONLY actions in this whitelist:

| Action | Tier | Auto |
|---|---|---|
| Patch verbatim mandate quote in per-project `MANDATE.md` | write_local | âœ“ |
| Create missing vault ACE+JD folder + `.gitkeep` | write_local | âœ“ |
| Scaffold `40_Resources/llm-models.md` if absent | write_local | âœ“ |
| Write to `00_Meta/_agent/proposals/*.md` | write_local | âœ“ |
| Update `state/ecosystem-audit/{INSIGHTS,ACTION_QUEUE,EVOLUTION}.md` | local | âœ“ |
| Write `state/ecosystem-audit/runs/<ts>.md` | local | âœ“ |
| Write `state/ecosystem-audit/research/*/<date>.md` | local | âœ“ |
| Edit any code file in zero/Legion/ADA repos | write_external | âœ— queue |
| `docker compose up/down/restart` anything | write_external | âœ— queue |
| Apply LiteLLM model swap | write_external | âœ— queue |
| Install Obsidian community plugin | write_external | âœ— queue |
| `git push`, `gh pr create` | write_external | âœ— queue |

Every auto-write must end with the audit footer.

## Phase I â€” Run report

Write `state/ecosystem-audit/runs/<YYYY-MM-DD-HHMM>.md`:

```markdown
---
run_id: <uuid>
started: <iso8601 ET>
ended: <iso8601 ET>
phase_durations: {B: ..s, C: ..s, ...}
---

# Ecosystem audit â€” <date>

## TL;DR
- 5 lines max. Top item first.

## Drift found
- **B (doc parity)**: ...
- **C (runtime)**: ...
- **D (vault)**: ...
- **E (vLLM/LiteLLM)**: ...
- **F (project freshness)**: ...

## Self-healed
- file:line â€” what changed (link).

## Queued
- New items added to ACTION_QUEUE.md (count + titles).
- Items removed (resolved): count + titles.

## Research highlights
- Models: ...
- PKM: ...
- Desktop control: ...
- Supply chain: ...

## Open questions
- Any clarification needed before next run.

## Run metrics
- Wall time, files read, queue length delta.

<!-- agent-run-id: <uuid> source: ecosystem-audit at: <iso8601> -->
```

## Phase J â€” INSIGHTS & EVOLUTION

1. Compare current findings against the previous run report.
2. Promote into `INSIGHTS.md` any finding that has now appeared in **two** consecutive
   runs (it is a real pattern). Demote / strike out items resolved this run.
3. If during the run the user added a new check ("also confirm X"), append a
   dated entry to `EVOLUTION.md`. Phase A on subsequent runs will load it.
4. Print a one-screen summary to the user (â‰¤30 lines): "Run N complete.
   Healed X. Queued Y. Research filed at Z. Top item: â€¦."

If interrupts are allowed (not DND) and there is exactly one blocking
ambiguity, ask via `AskUserQuestion`. Otherwise log it under "Open questions"
and end.

## First-run flow

When `state/ecosystem-audit/baseline/` is empty:

1. Generate the snapshot:
   ```
   state/ecosystem-audit/baseline/snapshot-<date>.json
   ```
   Capture: SHA-256 of each docs/*.md; verbatim mandate quotes from
   docs/company/mandate.md (lines 7â€“29); the port table from README.md; current
   `.obsidian/community-plugins.json` if vault healthy else the SecondBrain.md
   plugin baseline; `docker ps` output; `:4444/v1/models` output if reachable.
2. The `lib/*.md` files in this skill are pre-populated by the human installer -
   do NOT regenerate them on first run. Confirm they exist and are non-empty;
   queue if any is missing.
3. Append to `INSIGHTS.md`:
   ```
    ## Run 1 - <date> - baseline established
   ```
4. Resume at Phase B.

## What this skill is NOT

- Not a replacement for the active 12-week plan at
  `C:\code\zero\docs\company\plans\active\review-the-two-lively-cascade.md`. It complements it.
- Not a model swapper - proposes only. Legion's `llm_ops` subgraph (Stage 3 of
  the plan) does swaps with A/B and rollback.
- Not a deployer - never starts/stops services or pushes code.
- Not a vault constitution writer - only verifies and proposes inside `_agent/`.

<!-- agent-run-id: 00000000-0000-0000-0000-000000000000 source: ecosystem-audit at: install-time -->

