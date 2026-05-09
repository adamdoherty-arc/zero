# Zero as Chief-of-Staff — Second Brain Integration Plan

## Context

You have a comprehensive 12-week strategy in [docs/SecondBrain.md](c:/code/zero/docs/SecondBrain.md) — it's unusually well-thought-out. This plan translates it into concrete work against the Zero codebase, taking into account what already exists (a lot) and what's genuinely greenfield (less than you'd think).

**Goal:** Zero becomes your main employee. It knows everything you're doing (Obsidian vault + passive observability), accepts tasks + runs check-ins (Obsidian + Reachy voice + existing UI), manages your software projects (via Legion as a subgraph), and self-improves daily (existing `daily_improvement_service` + `employee_checkin_service` extended).

**Not in scope for Phase 1:** content pipeline rework (Wan 2.2 config fixes) — that's a separate post-week-12 workstream in SecondBrain.md and the existing character-content system already grades itself via `/zero-character-content`.

## Review of SecondBrain.md

### What's excellent and should stay verbatim
- **ACE + JD hybrid vault structure** (§1). Right call. PARA alone would fail on trade logs.
- **Daily note + project frontmatter schemas** (§2). The `energy/mood/sleep_hours` triad is the reasoning-handle. The `agent_writable` + `agent_append_section` contract is the cleanest safe-write pattern in PKM right now — keep it.
- **cyanheads Obsidian MCP** (§4). Plus a thin read-only FS server for when Obsidian is closed. Don't route batch reindex through REST.
- **pgvector partitioning** (§4): `reference | projects | journal | inbox` with time-decay only on journal. Single biggest retrieval-quality win.
- **Manual LangGraph handoffs** (§5) over `langgraph-supervisor`. Library was deprecated late 2025.
- **Drift detection SQL** (§6): six rules are concrete, bounded, and valuable on day one.
- **Guardrails stack** (§6): `legion/auto` git branch, DRY_RUN=true, circuit breakers, approval queue, DND window, 5-interrupt/day cap. All load-bearing.
- **Partition tag at the producer** (§7). Retrofitting privacy is painful — do it upfront.

### Where the plan needs adjusting for your actual stack

1. **"Legion" is overloaded.** SecondBrain.md uses "Legion" to mean "the LangGraph supervisor runtime." You ALSO have [C:\code\Legion](file:///C:/code/Legion) as a separate FastAPI app Zero already talks to via `legion_client.py` (project_id=8). **Resolution:** rename the SecondBrain "Legion" to **"Zero supervisor"** (extend `orchestration_graph.py`). Keep real Legion as a specialist subgraph Zero delegates code-improvement work to. One name, one system.

2. **You have way more substrate than the doc assumes.** `employee_checkin_service.py`, `daily_improvement_service.py` (scan→plan→execute→verify→learn), `agent_company_service.py` (CEO/Analyst/Engineer/Validator), `orchestration_graph.py` (LangGraph router with 12 routes), 127 scheduler jobs, `reachy_service.py` + device detection, Ask Zero chat UI, Employee Dashboard — all production. Don't rebuild; extend.

3. **Voice loop is the hardest and least ready.** No Kokoro, Parakeet, Silero, LiveKit, wakeword. Reachy hardware is wired but no AI on top. **Resolution:** defer to Phase 6 (weeks 11–12). Don't block the rest on it.

4. **Work-vault split decision is real.** You have Eightfold + Ascend consulting brand + personal. Single vault = moonlighting-clause risk. Needs your call before Phase 1 (see questions below).

5. **Content pipeline (§8) is out of scope for Phase 1.** Existing `/zero-character-content` already runs a self-grading loop. Seven Wan 2.2 fixes are a separate 1–2 day job — schedule for after Phase 3.

### What's missing from SecondBrain.md that Zero needs
- **Task-in-vault ↔ Zero TaskModel sync.** You want to enter tasks in Obsidian daily notes (`- [ ] …`) and have them flow into `backend/app/routers/tasks.py`. Round-trip: task status update in Zero writes back to the vault via cyanheads MCP.
- **Legion supervisor pattern.** Zero's CEO role should monitor Legion task completion + retry/escalate — SecondBrain.md assumes only one Legion.
- **Per-subsystem grade → vault promotion.** `.claude/memory/grades/*.md` cards should mirror into `30_Efforts/32_Legion/Health/` so the vault is the source of truth when you're offline.

## Substrate already in Zero (reuse map)

| SecondBrain.md requirement | Existing Zero surface | Action |
|---|---|---|
| Supervisor agent (§5) | [backend/app/services/orchestration_graph.py](c:/code/zero/backend/app/services/orchestration_graph.py) | Add `pkm` + `legion_ops` subgraph nodes. Keep existing routes. |
| Specialist roles (§5) | [backend/app/services/agent_company_service.py](c:/code/zero/backend/app/services/agent_company_service.py) + [models/agent_company.py](c:/code/zero/backend/app/models/agent_company.py) | Instantiate CEO/Analyst/Engineer/Validator as `AgentRoleModel` rows; Kimi plans, Gemma executes (already the pattern) |
| Memory: episodic/semantic/procedural (§5) | Postgres + pgvector already present | Add LangMem layer + namespace hierarchy |
| Daily rollup (§6) | [backend/app/services/daily_report_service.py](c:/code/zero/backend/app/services/daily_report_service.py) | Extend with vault-write via cyanheads MCP under `## Agent Summary` |
| Drift detection (§6) | [backend/app/services/daily_improvement_service.py](c:/code/zero/backend/app/services/daily_improvement_service.py) scan phase | Add 6 SQL drift rules to its scanner |
| Approval queue (§6) | `ActivityFeed` in [AgentPage.tsx](c:/code/zero/frontend/src/pages/AgentPage.tsx) | New `ApprovalQueue` component; new table + router |
| Employee check-in (§6) | [employee_checkin_service.py](c:/code/zero/backend/app/services/employee_checkin_service.py) + `/zero-employee-checkin` skill | Already does this. Add vault promotion of grade cards. |
| Legion as specialist (§5) | [backend/app/services/legion_client.py](c:/code/zero/backend/app/services/legion_client.py) + `zero_legion_project_id=8` | Wrap as LangGraph node with `interrupt()` before destructive ops |
| MCP fabric (§9) | `mcp_servers/zero_api_mcp.py` (30 tools) + `kimi_mcp.py` | Add `obsidian_mcp` (cyanheads) + `obsidian_fs_ro` (custom) |
| Observability (§9) | structlog already everywhere | Add Arize Phoenix single Docker container |
| Tradier/FRED/GCal MCPs (§7) | Not wired | Add post-Phase 2 |
| Voice loop (§7) | [reachy_service.py](c:/code/zero/backend/app/services/reachy_service.py) + `meeting_audio_capture.py` device hints | Phase 6 only |

## Execution plan — 6 phases mapped to your environment

Each phase is gated on the previous. Each ends with a verification step you can sign off on. Weeks are elapsed-calendar estimates; real work is sporadic.

### Phase 1 — Vault foundation (Weeks 1–2)

**Goal:** an Obsidian vault you'd trust an agent to write to.

**Deliverables:**
- Vault at path TBD (see question 1). ACE+JD skeleton:
  ```
  00_Meta/CLAUDE.md, Templates/, _agent/proposals/
  10_Atlas/MOCs/, Concepts/, Sources/
  20_Calendar/Daily/, Weekly/
  30_Efforts/31_Eightfold, 32_Legion, 33_Magnus, 34_Zero, 35_Ascend, 36_Reachy_Zoey, 37_Tax, 38_Content
  40_Resources/SOPs/, playbooks/
  90_Archive/
  _Inbox/
  ```
- Daily and project frontmatter templates exactly per SecondBrain.md §2.
- Plugins: Templater, QuickAdd, Obsidian Tasks, Periodic Notes, Obsidian Git, Bases, Advanced URI, Linter, Local REST API.
- **`obsidian-git` auto-commit every 10 minutes** — non-negotiable.
- [00_Meta/CLAUDE.md](file:) — the constitution. Encodes: `agent_writable` contract, append-only under `## Agent Summary` for daily, free write only in `_agent/`, never touch `.obsidian/`.
- **Seed content:** copy `docs/SecondBrain.md` → `10_Atlas/MOCs/SecondBrain_Strategy.md` (per your request). Create first daily note.

**Verification:** run the vault for 7 days. Git log shows ~1000 auto-commits. Zero schema drift (Linter clean). You can QuickAdd into `_Inbox/` from Raycast/URI.

### Phase 2 — Retrieval + write-back bridge (Weeks 3–4)

**Goal:** Zero (and Claude Code) can read + write the vault via MCP.

**Deliverables:**
- **cyanheads Obsidian MCP** wired into `.mcp.json` + `~/.claude.json`. Point at Local REST API plugin.
- **Filesystem read-only MCP** at `mcp_servers/obsidian_fs_ro.py` — 100 lines, used for batch reindex.
- **New service:** [backend/app/services/vault_indexer_service.py](c:/code/zero/backend/app/services/vault_indexer_service.py) — `watchdog` with 30s debounce + hash dedup + `PollingObserver` fallback for Dropbox/iCloud paths.
- **New DB:** `vault_chunks` table in pgvector with columns `id, path, partition (enum: reference|projects|journal|inbox), chunk_idx, content, tags[], embedding vector(1024), updated_at, content_hash`. HNSW index `m=16 ef_construction=128`.
- **Chunking:** `MarkdownHeaderTextSplitter` preserving `[[wikilinks]]`, 512-token cap, 15% overlap. Atomic notes <300 tokens stay single-chunk.
- **Embedder:** Qwen3-Embedding-0.6B via local endpoint (use existing [backend/app/infrastructure/llm_router.py](c:/code/zero/backend/app/infrastructure/llm_router.py) patterns). Matryoshka-truncate: 512 dims journal, 1024 reference.
- **Retrieval:** hybrid BM25 (Postgres `tsvector`) + dense + RRF fusion, Qwen3-Reranker over top-50. Query classifier chooses partition.
- **New MCP tools on `zero_api_mcp.py`:** `vault_search`, `vault_get`, `vault_propose_write`.

**Verification:** 30 hand-written queries return correct note in top-3. 5k-note index rebuild <5 min. File save → searchable <45s. Partition routing: "what did I do Monday" hits journal only.

### Phase 3 — Zero supervisor + Legion subgraph (Weeks 5–6)

**Goal:** Zero actually acts as chief-of-staff. Can delegate to Legion for code work.

**Deliverables:**
- Extend [orchestration_graph.py](c:/code/zero/backend/app/services/orchestration_graph.py) with nodes:
  - `pkm` — reads/writes vault, runs daily rollup, promotes grade cards
  - `legion_ops` — wraps `legion_client` calls (`create_task`, `monitor`, `pull_results`) with `interrupt()` before destructive ops
  - `projects` — wraps git + gh MCPs (add them) for cross-repo status
- **Agent roles in DB (`AgentRoleModel` rows):**
  - CEO (Kimi k2.5): daily orchestration + priority ranking + approval gatekeeper
  - Analyst (Kimi): research, drift investigation, pre-briefing prep
  - Engineer (Gemma4-e4b): `LEGION_TASK` execution, code edits
  - Validator (Claude Haiku): pre-write review, QA before CEO sign-off
- **Manual handoff pattern** per SecondBrain.md §5 code block — rewrite orchestration_graph routing to use `Command(goto=..., graph=Command.PARENT)` with `task:` string argument.
- **Approval queue:** new table `agent_approvals` + router + React `ApprovalQueue` component slotted into [AgentPage.tsx](c:/code/zero/frontend/src/pages/AgentPage.tsx). Gate every `write_external` and `financial` tool on it.
- **Legion supervision:** CEO role polls Legion for task status; retry once, escalate after 2 failures.
- **Bidirectional task sync:** Obsidian daily note `- [ ] task` → `TaskModel` row (new scanner in vault_indexer). Status updates in Zero write back to the vault under the same checkbox.

**Verification:** 20 evaluation prompts route correctly. CEO delegates a real Legion task end-to-end. Vault task → Zero task → completion status back to vault.

### Phase 4 — Passive observability + summarization loop (Weeks 7–8)

**Goal:** Zero knows what you did today without asking.

**Deliverables:**
- **Redis Streams capture bus** (Redis is already in stack). Flat schema per SecondBrain.md §7.
- **Producers:**
  - Global git `post-commit` hook appending to today's daily note via `## Commits` (gated on `user.email` — separate work identity).
  - Claude Code JSONL tailer at `~/.claude/projects/**/*.jsonl` — per-session summaries.
  - Tradier EOD poller (if you want Magnus integration now — see Q3).
  - GCal MCP (`nspady/google-calendar-mcp`) with account filter excluding Eightfold.
  - ActivityWatch + Wakapi if you want them (optional for Phase 4).
- **Partition tag** on every producer: `work | personal | trading | zero-dev`. Aggregator hard-drops `partition=work` from personal vault.
- **Summarization graph:** 6:30am cron (APScheduler, already running). Consumes last 24h events, writes 7-section daily summary into today's daily note under `## Agent Summary` via cyanheads patch-heading.
- **Weekly review graph:** Friday PM, interactive. Emits `reviews/2026-W##.md` + updates project-status JSON.
- **LangMem** on top of AsyncPostgresStore. Namespaces: `episodic|semantic|procedural|shared` × domain × user.
- **Arize Phoenix**: single Docker container, OpenInference on every LangGraph node.
- **DRY_RUN=true** flag in `config.py` — all `write_external` MCP tools replaced with mocks. Run 72h before promoting.

**Verification:** 7 consecutive daily summaries you approve ≥5/7 unedited. First weekly review flags a real blocker you hadn't noticed. Phoenix dashboard shows per-agent cost.

### Phase 5 — Drift + attention-economy (Weeks 9–10)

**Goal:** Zero interrupts rarely but meaningfully.

**Deliverables:**
- **Six drift SQL rules** per SecondBrain.md §6, versioned in `backend/app/services/drift_rules/*.sql`. Write alerts to new `agent_alerts` table. Run nightly.
- **Attention middleware**: salience 0–1 score, DND 22:00–07:00, hard cap 5 interrupts/day, `notify|question|review` tiering.
- **Circuit breakers**: $-spend/hour, error-rate/10-min. Flip supervisor to read-only + page.
- **`legion/auto` git branch** in the vault — every agent write committed there, can `git revert` in one command.
- **Agent Inbox UI** promoted from `ActivityFeed` to dedicated `/inbox` route. Shows approvals + drift alerts + batched non-urgent nudges.

**Verification:** 7 days running. ≥3 useful proactive nudges. Zero false-alarms during DND. Drift detection surfaces one real idle project.

### Phase 6 — Voice (Reachy/Zoey) (Weeks 11–12)

**Goal:** You can talk to Zero through Reachy; every turn logs to daily note.

**Deliverables:**
- Voice pipeline on host (not Docker — WASAPI audio):
  - Silero VAD → openWakeWord (`"Hey Zero"`) → faster-whisper `distil-large-v3` (or Parakeet TDT 1.1B if English-only) → Zero orchestration graph via MCP → Kokoro 82M TTS via Kokoro-FastAPI → Reachy speaker + head motion.
  - Barge-in via Silero-interrupt.
- **LiveKit Agents** as the bridge (native MCP support since early 2026).
- New service: [backend/app/services/voice_bridge_service.py](c:/code/zero/backend/app/services/voice_bridge_service.py) — subscribes to LiveKit, dispatches to orchestration_graph with `source=reachy`.
- Every Zoey turn appends to daily note under `## Mic`.

**Verification:** 1 week. Voice → daily-note entry without manual intervention. Wakeword false-positive rate <1/day.

## Critical files this plan modifies

- [backend/app/services/orchestration_graph.py](c:/code/zero/backend/app/services/orchestration_graph.py) — add pkm, legion_ops, projects nodes
- [backend/app/services/daily_improvement_service.py](c:/code/zero/backend/app/services/daily_improvement_service.py) — add drift rules to scanner
- [backend/app/services/daily_report_service.py](c:/code/zero/backend/app/services/daily_report_service.py) — vault-write extension
- [backend/app/services/employee_checkin_service.py](c:/code/zero/backend/app/services/employee_checkin_service.py) — vault promotion of grade cards
- [backend/app/services/legion_client.py](c:/code/zero/backend/app/services/legion_client.py) — wrap in LangGraph node with interrupts
- [backend/app/services/scheduler_service.py](c:/code/zero/backend/app/services/scheduler_service.py) — add morning digest (6:30am), weekly review (Fri PM), drift scan (nightly)
- [backend/app/services/agent_company_service.py](c:/code/zero/backend/app/services/agent_company_service.py) — instantiate 4 roles
- [mcp_servers/zero_api_mcp.py](c:/code/zero/mcp_servers/zero_api_mcp.py) — add vault_search, vault_get, vault_propose_write
- [frontend/src/pages/AgentPage.tsx](c:/code/zero/frontend/src/pages/AgentPage.tsx) — ApprovalQueue component
- [frontend/src/components/layout/AppSidebar.tsx](c:/code/zero/frontend/src/components/layout/AppSidebar.tsx) — elevate Employee to top-level

## New files to create

- `backend/app/services/vault_indexer_service.py`
- `backend/app/services/vault_writer_service.py` (cyanheads patch wrappers with mtime-check)
- `backend/app/services/drift_rules/` (6 SQL files + runner)
- `backend/app/services/voice_bridge_service.py` (Phase 6)
- `backend/app/routers/vault.py`, `approvals.py`, `drift.py`
- `backend/app/migrations/versions/NNN_vault_chunks_approvals_drift.py`
- `mcp_servers/obsidian_fs_ro.py` (read-only FS server)
- `frontend/src/pages/ApprovalQueuePage.tsx`, `DriftAlertsPage.tsx`
- `<vault>/00_Meta/CLAUDE.md` — agent constitution
- `<vault>/00_Meta/Templates/daily.md`, `project.md`
- `<vault>/10_Atlas/MOCs/SecondBrain_Strategy.md` (the reviewed plan)

## Anti-patterns I'll avoid

- Spinning up a second "PKM agent" microservice. Zero's orchestration_graph IS the supervisor.
- Replacing working systems. `employee_checkin_service` stays. `daily_improvement_service` stays. `agent_company_service` stays.
- Blocking Phase 1 on voice. Defer to Phase 6.
- Building on `langgraph-supervisor` library. Use manual handoffs.
- Wiring `write_external` before DRY_RUN passes 72h.
- Single combined vault if you actually care about the Eightfold clause.

## Verification end-to-end

After Phase 3 (MVP usable): open the vault, add `- [ ] ship Zero Phase 3` under today's `## Inbox`. Within 60s, task appears in Zero's board. Mark it in progress in Zero UI — checkbox state and `started_at` appear in the vault note. Ask Zero in chat: "what's my status on Legion?" — it reads the Legion project MOC + last 7 daily notes + runs `legion_client.get_metrics(project_id=8)`, returns a 3-line answer.

After Phase 6: say "Hey Zero, add a task to refactor the vault_indexer debounce." Reachy's head turns, Zero responds via Kokoro, and the task lands in both Zero's DB and today's daily note under `## 🎙️`.

## Known risks

1. **Vault bloat** — agent writes > you read. Mitigations: `_agent/` ghetto, 90-day archive, `shelf_life: 90d` field on fast-moving notes.
2. **Eightfold privacy** — handled by vault-split + partition tag + separate git identity. Not optional.
3. **Cyanheads + Local REST API churn** — both <1 year old. Treat as replaceable. Re-evaluate Q3 2026.
4. **Phoenix on top of 127 scheduler jobs** — may be noisy. Start with instrumentation on `orchestration_graph` nodes only; expand deliberately.
5. **Reachy voice latency** — if >1.5s round-trip, unusable. Parakeet TDT on 5090 is the insurance policy.

## Locked decisions

1. **Vault split.** Two vaults:
   - `C:\Users\hadam\VaultWork` — Eightfold only. Separate git identity (`user.email` = Eightfold address). Global post-commit hook routes to this vault when identity matches.
   - `C:\Users\hadam\Vault` — personal + Zero + Legion + Magnus + Ascend. Default git identity.
   - Separate OS/editor profiles recommended but not blocking (Cursor/VSCode profiles suffice).
2. **Scope: all 6 phases end-to-end.** 12 weeks elapsed. Each phase gated on previous. No skipping Phase 6 voice.
3. **Legion audit before wiring.** Insert **Phase 2.5 — Legion audit + harden (1 week)** between Phase 2 and Phase 3. Runs `/zero-deep-review` pattern against C:\code\Legion. Fixes top issues (circuit-breaker coverage, task-status webhook reliability, error surfacing to Zero). Zero delegates to Legion only after Phase 2.5 passes.

## Revised phase timeline

| Phase | Weeks | Goal |
|---|---|---|
| 1 | 1–2 | Vault foundation (both vaults, templates, git, CLAUDE.md) |
| 2 | 3–4 | Retrieval + cyanheads MCP (personal vault indexed; work vault indexed separately) |
| 2.5 | 5 | Legion audit + harden |
| 3 | 6–7 | Zero supervisor + Legion subgraph + vault task sync |
| 4 | 8–9 | Passive observability + summarization loop + DRY_RUN 72h |
| 5 | 10–11 | Drift rules + attention economy + approval queue |
| 6 | 12–13 | Reachy voice (Silero → Parakeet → Zero → Kokoro) |

## Phase 2.5 detail — Legion audit + harden

**Goal:** Legion is healthy enough for Zero to delegate to without babysitting.

**Deliverables:**
- Run `/zero-deep-review` pattern against [C:\code\Legion](file:///C:/code/Legion). Score all Legion features across 5 dimensions.
- Fix top 3 regressions surfaced by the audit (expected: error surfacing, task-status webhook, circuit-breaker coverage).
- **Legion → Zero webhook:** Legion posts task status changes to `http://zero-api:18792/api/webhooks/legion`. Replaces current polling in `legion_client.py`.
- Harden `legion_client.py` with retries, timeouts, and `interrupt()` wrapping before any Legion task that touches git pushes or Docker builds.
- Acceptance: run 10 real tasks through the delegation path. Success rate ≥ 8/10 end-to-end without Zero intervention.

## Vault-specific scoping

Because Phase 1 locks in a split:

- **Personal vault** `C:\Users\hadam\Vault` — full ACE+JD. Contains `30_Efforts/34_Zero`, `32_Legion`, `33_Magnus`, `35_Ascend`, `36_Reachy_Zoey`.
- **Work vault** `C:\Users\hadam\VaultWork` — minimal ACE. Only `10_Atlas`, `20_Calendar`, `30_Efforts/31_Eightfold`, `40_Resources`. No agent write access in Phase 1; cyanheads MCP points at personal vault only. Revisit agent access for work vault in Phase 4.
- **Partition tag `partition: work | personal | trading | zero-dev`** at every producer. Aggregator hard-drops `work` events from personal vault.
- **Separate git identity via `includeIf`** in global `.gitconfig`: paths under `VaultWork` use Eightfold email; everything else uses personal.
- **`CLAUDE_CONFIG_DIR=~/.claude-work`** in the Eightfold shell profile — separate Claude Code transcript dir prevents work content from leaking into personal projects tailer.
