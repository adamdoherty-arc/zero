# Plan: Zero + Legion + Ada → 24/7 Agentic Personal OS

> Sources: `C:\code\claude\docs\SecondBrain.md`, `C:\code\claude\docs\AgenticOs.md`, vault MOC at `C:\code\vault\ObsidianZero\10_Atlas\MOCs\Zero_As_Chief_of_Staff.md`.
> Decisions locked: single combined vault • evolve Legion in place • full 12-week roadmap with gates • all three validators in parallel.

---

## Context

Adam wants three of his existing projects to operate as true 24/7 AI agents under one coherent personal operating system:

- **Zero** = personal employee / second brain — captures, organizes, surfaces, and acts on his life graph (calendar, email, notes, goals, trading, voice via Reachy Mini).
- **Legion** = orchestration layer — runs continuously to review, fix, debug, update, and improve every project under `C:\code\` without supervision.
- **Ada** = financial advisor — autonomous research, monitoring, and signal generation; deterministic execution stays human-gated.

The two strategy documents converge on one architecture, and we adopt the AgenticOs.md "Do This First" stack verbatim: **LangGraph 1.0 (orchestration) + Pydantic AI (typed agents) + MCP (tool fabric) + LiteLLM proxy + Not Diamond / semantic classifier (router) + Letta + Mem0 + pgvector (memory) + Microsoft UFO³ / Claude Computer Use / ChatGPT Agent (desktop control — do NOT build)**, with Legion ported into LangGraph as the second project once the architecture validates. Substantial scaffolding already exists (vault with ACE+JD layout, vault retrieval service, LiteLLM proxy, Legion sprint engine, Ada agents). What's missing is the **connective tissue**, the **24/7 daemonization**, the **per-project mandate documentation**, **Legion's vLLM-management mandate**, and the **safety/approval discipline layer**.

This plan delivers the full 12-week rollout in five stages with explicit gates, plus the rewritten prompt for the user.

---

## Project mandates (the one-liners)

These should be written verbatim into each project's `CLAUDE.md` and a new top-level `MANDATE.md`:

- **Zero**: *"I am Adam's chief-of-staff. I capture every signal from his life, write to the vault as the source of truth, surface what matters, and act on his behalf within the approval contract. I never write to `.obsidian/`, never touch Eightfold material, never bypass the `agent_writable` whitelist."*
- **Legion**: *"I am Adam's 24/7 ecosystem orchestrator and LLM ops owner. I keep every project under `C:\code\` healthy — review, fix, debug, update, improve. I also keep the model layer fresh: monitor vLLM health, research new model releases, A/B-test candidates against the active routes, and propose swaps with measured wins. I do all of this via LangGraph subgraphs, Pydantic-typed contracts, MCP tools, and an explicit approval tier. I never make irreversible changes without a tier-appropriate gate."*
- **Ada**: *"I am Adam's autonomous financial advisor. I research, monitor, and surface signals; I never place a live order without `interrupt()` approval. Paper-default. Tradier hosted MCP. TradingAgents-style Bull/Bear/Risk debate before any committed signal."*

---

## Target architecture

```
User surfaces: Zero (voice via Reachy) │ Claude Code │ Obsidian │
               Phone (Claude Cowork / ChatGPT Agent) │ CLI
                        ↓ MCP stdio/HTTP + Anthropic Messages API
                Desktop control (DO NOT BUILD — integrate)
                  ├─ Microsoft UFO³ / UFO² for Windows-native apps (UIA + OmniParser)
                  ├─ Claude Computer Use (CLI + Cowork) for IDE/shell agentic coding
                  └─ ChatGPT Agent for web/SaaS workflows
                        ↓
                Routing layer
                  ├─ Not Diamond client-side router (sub-token decisions, eval-trained)
                  └─ LiteLLM proxy :4444 (existing — providers, retries, budget caps)
                        ↓                                      ↓
                Local: vLLM on RTX 5090                Cloud: Anthropic, OpenAI,
                  Qwen3-Coder-Next, Qwen3-32B,           Google, Kimi, MiniMax,
                  Qwen3-Embedding-0.6B,                  OpenRouter (passthrough)
                  Qwen3-Reranker-0.6B                    via passthrough endpoints
                        ↓
         Legion supervisor (LangGraph 1.0 + Pydantic AI typed agents)
           manual Command(goto=, graph=PARENT) handoffs, NOT langgraph-supervisor lib
           ├─ pkm subgraph        → cyanheads-obsidian MCP, vault R/W, daily/weekly digest
           ├─ projects subgraph   → git, gh, ruff, pytest, cross-repo PR creation
           ├─ trading subgraph    → ada-mcp + Tradier hosted MCP, debate, HITL
           ├─ content subgraph    → ComfyUI API, 9-agent reflexion DAG (week 12+)
           └─ llm-ops subgraph    → vLLM health, model research, A/B eval, swap proposals
         Memory: AsyncPostgresSaver (checkpoints) + AsyncPostgresStore (long-term)
                + LangMem (typed namespaces) + Letta (agent runtime) + Mem0 (cross-agent prefs)
                all backed by pgvector on Legion's existing Postgres :5434
                        ↓
         MCP tool fabric (NEW): cyanheads-obsidian, ada-mcp, zero-mcp, legion-mcp,
                                tradier-hosted, fred-mcp, gcal-mcp, gmail-mcp,
                                github-mcp, postgres-mcp, playwright-mcp
                        ↓
         Approval queue (Postgres `approvals`) + Agent Inbox UI (reuse Legion's)
         Tiers enforced: read | write_local | write_external | financial
                        ↓
         Observability: Langfuse (self-host Docker) + Pydantic Logfire on Pydantic AI nodes
                        ↓
24/7 substrate: NSSM Windows services for Docker compose stacks + APScheduler in each
                project's backend + ZeroHostAgent Scheduled Task (already exists for Reachy)
                + Legion llm-ops daemon doing continuous model research
```

---

## Stack decisions (locked)

Adopting AgenticOs.md "Do This First" verbatim:

1. **Orchestration spine**: LangGraph 1.0 — durable execution, checkpointing, manual handoff via `Command(goto=, graph=PARENT)`. Skip the deprecated `langgraph-supervisor` library. Wrap individual specialist nodes as **Pydantic AI** typed agents so contracts between subgraphs are enforced by schema, not prose.
2. **Tool fabric**: MCP everywhere. Ada → `ada-mcp` (was "Magnus" in the docs — Adam's project is named Ada, no separate Magnus repo), Obsidian → cyanheads, Legion exposes itself, Zero exposes itself. This is the portability insurance — the same servers serve Claude Code, Cursor, Claude Cowork, ChatGPT Agent, and any future client.
3. **Routing**: keep the existing **LiteLLM proxy at `:4444`** as the gateway; add **Not Diamond** client-side as a layered decision-maker (task-class classification + sensitivity gating + latency budget + cost ceiling). Sub-token-time decisions, train custom routers from eval data Legion accumulates. Fallback: a small Qwen3-4B semantic classifier hosted on the 5090.
4. **Memory**: three layers, single Postgres+pgvector. **Letta** as the agent runtime (OS-style core/recall/archival, agent self-edits via tool calls). **Mem0** for cross-agent user preferences. **pgvector** for raw RAG on the vault. **LangMem** typed namespaces (`episodic | semantic | procedural | shared`) sit on top of `AsyncPostgresStore` for the supervisor.
5. **Desktop control — DO NOT BUILD**: integrate Microsoft **UFO³** (Win UIA + OmniParser-V2) for native Windows apps, **Claude Computer Use** in CLI/Cowork for IDE/shell agentic coding, and **ChatGPT Agent** for web/SaaS. UFO² already beats prior CUAs by 10%+ on Windows OSWorld; building our own is wasted effort.
6. **Legion port path**: build new LangGraph supervisor + llm-ops subgraph in `legion/backend/app/supervisor/` first, validate against Daily Brief Agent + drift output, then port specialist sprint engine logic node-by-node into LangGraph until the custom engine is unused. This is the "evolve in place" path the user picked, with the new architecture growing inside Legion's existing repo so dashboards/approval queue/notifications keep working.

---

## Existing-state snapshot (verified 2026-04-25)

| Piece | Status | Where |
|---|---|---|
| Obsidian vault (ACE+JD) | ✓ exists, daily notes through 04-24, MOCs seeded | `C:\code\vault\ObsidianZero\` |
| Vault constitution | ✓ enforced | `00_Meta\CLAUDE.md` |
| Vault retrieval (pgvector + BM25 + RRF + partitions) | ✓ working | `zero/backend/app/services/vault_indexer_service.py`, `vault_retrieval_service.py` |
| Vault writes via cyanheads MCP | ✗ filesystem-only to `_agent/` | gap |
| LiteLLM proxy at `:4444` | ✓ all 3 projects route through it | `C:\code\litellm-proxy\` |
| vLLM Qwen3-32B-AWQ + Qwen3-Embedding-0.6B | ✓ running | host `:18800` (chat) and `:8001` (embed); container internal `:8000` (chat) — moved off host `:8000` |
| ~~**PORT 8000 CONFLICT**~~ | ✓ **RESOLVED 2026-04-27** — vLLM chat host port moved to `:18800` in `shared-infra/docker-compose.vllm.yml` (`18800:8000`); Reachy keeps host `:8000`. All project references updated by ecosystem-audit run 2026-04-27. | `shared-infra/docker-compose.vllm.yml:39` |
| Legion death-spiral fixes (8cfd7abd) | ✓ intact | `legion/backend/app/services/circuit_breaker.py`, `enums.py`, `qa_gate_service.py` |
| Legion supervisor (LangGraph) | ✗ tactical use only, custom engine primary | `legion/backend/app/services/agentic_loop_service.py` |
| MCP servers (any project) | ✗ none exposed, none consumed | `legion`, `zero`, `ada` all REST-only |
| Drift detection (6 SQL rules) | ✗ none | gap |
| Attention economy (DND, salience, 5-cap) | ✗ none | gap |
| Ada HITL gate before live orders | ✗ env-var only | `ada/backend/routers/broker_orders.py` |
| Ada Bull/Bear/Risk debate | ✗ no reflexion | gap |
| Reachy daemon | ✗ apps cloned, daemon not running | `C:\code\reachy-apps\` |
| Wake word service | ✓ exists (memory underestimated) | `zero/backend/app/services/reachy_wake_word_service.py` |
| `start-ecosystem.bat` | ✓ exists (manual launch only) | `C:\code\start-ecosystem.bat` |
| 24/7 NSSM service / Task Scheduler auto-start | ✗ only `ZeroHostAgent` scheduled task | gap |
| Per-project ARCHITECTURE.md | ✗ Ada missing entirely; Zero is ~100 LOC; Legion has fragments | gap |
| Ecosystem `C:\code\README.md` / `ARCHITECTURE.md` | ✗ none | gap |

---

## Stage 0 — Foundation & 24/7 (Week 1)

**Goal**: every container restarts on boot, every project has a written mandate, every reader can answer "what is this?" in 30 seconds.

### Deliverables
1. **Resolve the `:8000` port conflict** — Reachy Mini Lite daemon defaults to `:8000`; vLLM also serves on `:8000`. Decision: move vLLM to `:8100` (chat) and `:8101` (embed); leave Reachy on `:8000` because the SDK and many tutorials assume that. Update LiteLLM `litellm_config.yaml` model `api_base` URLs (`localhost:8100/v1` for chat, `localhost:8101/v1` for embed). Update Zero's `ZERO_VLLM_*` env vars and Reachy daemon `:8000` mention in start scripts. Verify with `netstat -an | findstr ":8000\|:8100\|:8101"` after restart.
2. **`C:\code\README.md`** — one-page ecosystem overview: what each project does, **the resolved port map** (4444 LiteLLM, 5432/5433/5434 Postgres, 8000 Reachy, 8003 Ada, 8005 Legion, 8100/8101 vLLM, 11434 Ollama, 18792 Zero), links, who calls whom.
3. **`C:\code\ARCHITECTURE.md`** — one mermaid diagram of the target architecture (Not Diamond + LiteLLM + LangGraph + MCP + Letta/Mem0 + UFO³/Computer-Use), partition tags, MCP fabric, model routing table.
4. **`C:\code\MANDATE.md`** — the three project mandate one-liners + the gate rules (`read | write_local | write_external | financial`), DND window, salience cap.
5. **Per-project `MANDATE.md`** copied into Zero/Legion/Ada repos and referenced from each `CLAUDE.md`. Legion's mandate must explicitly include the **LLM-ops responsibility** (vLLM health, model research, A/B eval, swap proposals).
6. **`C:\code\zero\docs\ARCHITECTURE.md` rewrite** — bring in sync with the 175 services + 73 routers reality; document the partition routing, write-back contract, scheduler loops, port reassignments.
7. **`C:\code\ADA\ARCHITECTURE.md`** (new) — distill the 26 topic files into one navigable diagram. Note that "Magnus" in `SecondBrain.md` and `AgenticOs.md` refers to Ada — the trading-agent project. There is no separate Magnus repo; `ada-mcp` is what those docs call `magnus-mcp`.
8. **`C:\code\Legion\ARCHITECTURE.md` rewrite** — reframe from "Learning-First AI App Builder" to "24/7 Ecosystem Orchestrator + LLM Ops Owner"; document the existing engine + the planned LangGraph supervisor migration path + the new llm-ops subgraph.
9. **NSSM services for Docker stacks** — install NSSM and register three services (`Legion-Stack`, `Zero-Stack`, `Ada-Stack-DevOnly`) that run `docker compose up -d` from each project directory at boot, with watchdog restart. Reference: `C:\code\start-ecosystem.bat` is the source for the compose commands. Also register `vLLM-Service` and `Reachy-Daemon` as NSSM services on the new ports.
10. **Ecosystem health watchdog** — small Python service that hits `/health` on `:4444`, `:8000` (Reachy), `:8003`, `:8005`, `:8100`, `:8101`, `:11434`, `:18792` every 60s and writes results to today's vault daily note under `## System Health` (proposal-only at first).
11. **Verify rebuilt vault paths** — confirm `C:\code\vault\ObsidianZero` is the source of truth (the `Zero\` subfolder with its own `.obsidian/` is suspicious — investigate and document).
12. **Bootstrap llm-ops baseline** — record current vLLM model + throughput + p50/p99 latency + GPU memory in `40_Resources/llm-models.md` so Stage 3's llm-ops subgraph has a baseline to compare against.

### Verification
- Reboot the machine. All three stacks come up unattended within 5 minutes.
- `curl localhost:8005/health && curl localhost:18792/health && curl localhost:8003/api/health` returns 200 from a fresh user session.
- Reading `C:\code\README.md` + the three mandates explains the system to a stranger in <5 minutes.
- Today's daily note has a `## System Health` block written by the watchdog.

### Gate to Stage 1
All Stage 0 verification passes for 72 hours straight.

---

## Stage 1 — Vault write-back & retrieval polish (Weeks 2–3)

Closes the **cyanheads MCP gap** and finishes the existing vault MOC's Phase 2.

### Deliverables
1. **Install Local REST API plugin** in the Obsidian vault; configure JWT.
2. **Run cyanheads-obsidian-mcp-server** in WSL2 or as a Windows service; register it with Claude Desktop and Claude Code (`~/.claude.json` mcpServers entry).
3. **Switch Zero's `vault_writer_service.py`** from filesystem-direct to cyanheads MCP for all writes outside `_agent/`. Keep the filesystem path as the fallback for `_agent/` namespace.
4. **Enforce `agent_writable` whitelist** at the writer level; route un-whitelisted writes to `00_Meta/_agent/proposals/`.
5. **`obsidian-git` plugin auto-commit every 10 min** + a `legion/auto` git branch for agent mutations. (`obsidian-git` already prescribed; verify it's installed.)
6. **Add Qwen3-Reranker-0.6B** to the LiteLLM proxy as a separate route; wire `vault_retrieval_service.py` to rerank top-50 hybrid candidates.
7. **Add Contextual Retrieval pre-embed prefix** to the `reference` partition only.
8. **30-query retrieval eval** — hand-write 30 queries, measure top-3 accuracy, baseline before/after rerank.

### Verification
- Daily note's `## Agent Summary` is written by Zero via cyanheads MCP without touching the rest of the file.
- A read-modify-write race is caught by mtime check + retry.
- Retrieval eval ≥ 80% top-3 with rerank vs. baseline.
- `git log` in vault shows `auto: agent writes` commits at ~10-min cadence.

---

## Stage 2 — MCP-ify the projects + Ada HITL (Weeks 4–5)

Three validators in parallel per the user's choice.

### Track A — `ada-mcp` (FastMCP wrapping Ada)
1. New repo / package `C:\code\ada-mcp\` (FastMCP, Python).
2. Tools: `get_positions`, `get_balances`, `evaluate_signal`, `fred_series`, `discord_xtrades_recent`, `place_paper_order`, `place_live_order` (latter requires `confirm: True`).
3. Wraps Ada's existing `OrderService`, FRED client, sentiment service.
4. Register with Claude Code + Legion's MCP fabric.

### Track B — Ada Bull/Bear/Risk debate + LangGraph `interrupt()`
1. New `ada/backend/agents/trading_council.py` LangGraph subgraph: bull researcher → bear researcher → risk manager → fund manager (TradingAgents pattern).
2. Insert `interrupt()` before any `place_live_order` tool call in `ada-mcp` and Ada's direct path.
3. Approval surfaces in Legion's existing `approval_service.py` queue + a new web endpoint at `/api/safety/live-order-pending`.
4. Verify `ROBINHOOD_PAPER_TRADING=true` is the only path that doesn't require approval.

### Track C — `zero-mcp` and `legion-mcp` exposure
1. Wrap Zero's vault read/write/retrieval, journal append, habit log, goal check-in, ecosystem-health as a FastMCP server.
2. Wrap Legion's sprint creation, project status, drift query, learning council read as a FastMCP server.
3. Register all three (zero-mcp, legion-mcp, ada-mcp) in `~/.claude.json` so Claude Code and Cursor can call into them.

### Validator: Daily Brief Agent (also in parallel)
1. New LangGraph in `legion/backend/app/services/daily_brief_graph.py`.
2. APScheduler job at 06:30 ET pulls: GCal MCP events for next 12h, ada-mcp positions/PnL, FRED overnight releases, vault retrieval for "today's calendar entities", inbox count.
3. Writes 7-section brief into today's daily note `## Agent Summary` via cyanheads MCP.
4. Routes via LiteLLM: synthesis on Sonnet 4.6, classification on Haiku 4.5, embeddings on local Qwen3.

### Verification
- Live order attempt blocks on `interrupt()` and surfaces in approval queue.
- Trading council produces a debate transcript saved under `00_Meta/_agent/proposals/<date>-trade-debate.md`.
- Three MCP servers respond to `tools/list` from Claude Code.
- Daily Brief Agent writes for 5 consecutive mornings; ≥3 are useful unedited.

---

## Stage 3 — Legion LangGraph supervisor + memory + llm-ops (Weeks 6–7)

Evolve in place per the user's choice. Don't delete the custom engine yet.

### Deliverables
1. **New module `legion/backend/app/supervisor/`** with the manual-handoff LangGraph pattern from `SecondBrain.md` §5 lines 140–198. Specialists are **Pydantic AI typed agents**, not bare prompts.
2. **AsyncPostgresSaver checkpoints** on the Windows host's native PG17 (`host.docker.internal:5432/legion` — Legion was consolidated onto the shared native instance on 2026-04-25; see follow-up plan `i-just-noticed-that-eventual-candy.md`).
3. **AsyncPostgresStore + pgvector** for long-term memory (reuse the same native PG17 — pgvector 0.8.0 already enabled).
4. **LangMem on top** with the four namespaces from `SecondBrain.md` §5 lines 192–204: `episodic|semantic|procedural|shared`.
5. **Letta runtime** for any specialist that needs OS-style core/recall/archival memory and self-edits via tool calls (start with the `pkm` and `trading` subgraphs). Run Letta server in WSL2 Docker.
6. **Mem0** for cross-agent user preferences (risk tolerance, comm style, DND window). Single-source-of-truth for "what does Adam want."
7. **Migrate cross-sprint learning service** to write into LangMem semantic namespace; keep the read path through both for one month.
8. **Manual handoff tools** to: `pkm`, `projects`, `trading`, `content`, `llm-ops`. Supervisor model = Claude Sonnet 4.6; specialists default to local Qwen3-Coder per the routing table.
9. **`privacy_tag` on every tool schema** with `LOCAL` forced for vault-write, trading-decision, personal-journal, finance-pii, health.
10. **HumanInTheLoopMiddleware** on anything past `write_local`.

### Track L — `llm-ops` subgraph (the new Legion responsibility)

This is what makes Legion "always working to make better" the model layer.

1. **`legion/backend/app/subgraphs/llm_ops.py`** — Pydantic AI typed agent with tools:
   - `vllm_health()` — query `:8100/health`, GPU memory, RPS, p50/p99 latency.
   - `litellm_usage(window_h)` — per-model token counts, fallback hit rate, error rate (LiteLLM exposes these).
   - `hf_search_releases(category, since)` — query HuggingFace for new model releases in `code|reasoning|embeddings|vision|tts|stt`, filter by license + size that fits the 5090.
   - `nvidia_namespace_check()` — scan `huggingface.co/nvidia/` for new NVFP4 checkpoints (the AgenticOs §2 acceleration path).
   - `ab_eval(model_a, model_b, eval_set, n=200)` — run the same eval set through two models via LiteLLM, compute pairwise win rate + cost delta + latency delta. Eval sets stored in `legion/backend/app/eval/`: `vault_qa.json`, `code_review.json`, `reasoning.json`, `summary.json`.
   - `propose_swap(from, to, evidence_path)` — write a proposal to `00_Meta/_agent/proposals/<date>-llm-swap-<slug>.md` summarizing the eval, cost, and rollback. Surfaces in Agent Inbox at `tier=write_external`.
   - `apply_swap(proposal_id, dry_run=True)` — patch LiteLLM model alias, run smoke tests, monitor for 1h, auto-rollback if error rate > 2× baseline.
2. **APScheduler jobs** in Legion: `llm_ops.health_check` every 5 min, `llm_ops.research` daily at 03:00 ET, `llm_ops.weekly_eval` Sunday 02:00 ET (re-runs the eval matrix and writes a digest to `40_Resources/llm-models.md`).
3. **Vault output**: `40_Resources/llm-models.md` becomes the rolling LLM ops journal — current models, last eval results, swap history, candidates being researched.

### Verification
- Supervisor routes correctly on 20 evaluation prompts (mix of trading, code, vault, content, llm-ops questions).
- LangMem `aput` and `aget` work across all four namespaces; Letta + Mem0 round-trip.
- A `write_external` call hits the approval queue, not the tool.
- `llm_ops.health_check` runs every 5 min for 7 days without false alarms; one synthetic vLLM kill triggers an immediate alert.
- Custom sprint engine still runs in parallel; new supervisor handles the daily brief + drift output + llm-ops without crashes for 7 days.
- `40_Resources/llm-models.md` has at least one swap proposal generated automatically with measured win/loss/cost.

---

## Stage 4 — Drift detection + attention economy + Not Diamond router + observability (Weeks 8–9)

The discipline layer.

### Deliverables
1. **Six SQL drift rules** from `SecondBrain.md` §6 lines 230–236, versioned at `legion/backend/app/drift/*.sql`. Idle project, calendar-vs-actual, commit decay, intent drift, inbox bloat, trading skip. Run nightly via APScheduler, write to a new `agent_alerts` table.
2. **Attention-economy middleware** (`legion/backend/app/middleware/attention.py`):
   - DND window 22:00–07:00 local (configurable per partition).
   - Salience score 0–1 attached to every nudge; ≥0.6 interrupts immediately, the rest batch.
   - Hard cap 5 interruptions/day.
   - `notify | question | review` tiering.
3. **Agent Inbox UI** — extend Legion's existing approval frontend with a `/agent-inbox` view: pending approvals, salience score, DND state, batched queue.
4. **Not Diamond router** — install `notdiamond` Python SDK; train a custom router on Legion's accumulated traces (LangMem episodic + Langfuse spans) to decide `local | cheap_cloud | frontier_cloud` per request. Wrap the LiteLLM call so Not Diamond decides which alias to hit. Fallback to a small Qwen3-4B semantic classifier hosted on the 5090 if Not Diamond is unavailable. Re-train weekly via the llm-ops subgraph.
5. **Self-host Langfuse** on Docker (Adam's preferred per AgenticOs §4) + **Pydantic Logfire** on every Pydantic AI agent — both speak OTel so Datadog/Phoenix can be added later.
6. **Per-key budget caps** in LiteLLM: `$5/day` Opus, `$10/day` Sonnet, unlimited Haiku, unlimited local. Daily spend alarm to Discord at 50/80/100% via `scripts/notify-telegram.sh` (already wired in `C:\code\claude\CLAUDE.md`) or Discord webhook.
7. **Circuit breakers** on $-spend/hour and error-rate/10-min that flip the supervisor read-only.
8. **`DRY_RUN=true`** env flag wraps every `write_external` tool with mocks; run for 72h before any new specialist promotes.

### Verification
- Six drift queries surface on a manually-injected idle project / commit-decay / inbox-bloat fixture.
- A test alert at 22:30 local goes to inbox, not interrupt.
- Langfuse dashboard shows per-agent latency + token cost.
- A simulated $-spend spike trips the supervisor to read-only and Discord alerts fire.

---

## Stage 5 — Voice / Reachy + content pipeline (Weeks 10–12)

### Voice (weeks 10–11)
1. **Silero VAD + openWakeWord** ("Hey Zero") — verify `reachy_wake_word_service.py` actually uses these (it exists but unverified).
2. **faster-whisper distil-large-v3** or NVIDIA Parakeet TDT 1.1B — Zero already has Whisper warmed; consider Parakeet swap for English-only RTFx >2000.
3. **Kokoro 82M TTS** via Kokoro-FastAPI on `:8880` — replace edge-tts as primary.
4. **LiveKit Agents bridge** to Reachy daemon — newest 2026 frameworks ship native MCP support; cleanly bridges Reachy daemon to Legion supervisor.
5. **Every Zero turn appends to today's daily note `## 🎙️`** via `voice_bridge_service.py` (already partially wired).
6. **Reachy daemon as NSSM service** so it survives reboots.

### Content pipeline (week 12+, optional this cycle)
- Fix the seven Wan 2.2 config bugs from `SecondBrain.md` §8 lines 251–270 first (1–2 days, no model swap).
- Build the 9-agent LangGraph DAG with reflexion loop (`SecondBrain.md` §8 line 280) only after the supervisor is stable.

### Verification
- Wake-word "Hey Zero" → conversation turn → daily-note entry round-trips end-to-end without manual intervention.
- One full week with Legion proactively surfacing ≥3 useful nudges and zero false-alarms during DND.

---

## Per-project documentation deliverables

Track these as concrete files; each is a Stage 0 or Stage 1 artifact:

| File | Stage | Purpose |
|---|---|---|
| `C:\code\README.md` | 0 | Ecosystem overview, ports, who-calls-whom |
| `C:\code\ARCHITECTURE.md` | 0 | Target architecture, model routing table, MCP fabric |
| `C:\code\MANDATE.md` | 0 | Approval tiers, DND, salience cap, mandate one-liners |
| `C:\code\zero\docs\ARCHITECTURE.md` | 0 | Rewrite to match 175 services + 73 routers reality |
| `C:\code\zero\MANDATE.md` | 0 | Zero one-liner + write contract excerpt |
| `C:\code\Legion\docs\ARCHITECTURE.md` | 0 | Reframe as 24/7 orchestrator; document evolution path |
| `C:\code\Legion\MANDATE.md` | 0 | Legion one-liner + tier matrix |
| `C:\code\ADA\ARCHITECTURE.md` | 0 | NEW — distill the 26 topic files |
| `C:\code\ADA\MANDATE.md` | 0 | Ada one-liner + paper-default + interrupt() rule |
| `C:\code\zero\docs\obsidian-mcp-install.md` | 1 | cyanheads runbook (placeholder exists) |
| `C:\code\Legion\docs\supervisor.md` | 3 | Manual-handoff pattern, Pydantic AI contracts, namespace design |
| `C:\code\Legion\docs\llm-ops.md` | 3 | vLLM management, A/B eval, swap-proposal workflow |
| `C:\code\vault\ObsidianZero\40_Resources\llm-models.md` | 3 | Rolling LLM ops journal — current models, eval history, candidates |
| `C:\code\Legion\docs\drift-rules.md` | 4 | Six SQL rules + their thresholds |
| `C:\code\Legion\docs\attention-economy.md` | 4 | DND, salience, batching policy |
| `C:\code\Legion\docs\not-diamond-router.md` | 4 | Router training data, decision policy, fallback path |
| `C:\code\zero\docs\voice-stack.md` | 5 | Silero → Whisper/Parakeet → Kokoro → LiveKit pipeline |

---

## Files to modify or create (key code paths)

- **Port reassignment**: `C:\code\litellm-proxy\litellm_config.yaml` (rewrite vLLM `api_base` to `:8100/:8101`), `C:\code\zero\docker-compose.sprint.yml` (`ZERO_VLLM_*_URL`), Reachy daemon launch script (leave `:8000`)
- **Cyanheads MCP wiring**: `C:\code\zero\backend\app\services\vault_writer_service.py` (switch to MCP client), `~/.claude.json` (register server)
- **HITL gate**: `C:\code\ADA\backend\routers\broker_orders.py` (add `interrupt()` before live), new `C:\code\ADA\backend\agents\trading_council.py`
- **Daily Brief**: new `C:\code\Legion\backend\app\services\daily_brief_graph.py`, APScheduler job in `C:\code\Legion\backend\app\scheduler\`
- **Drift rules**: `C:\code\Legion\backend\app\drift\*.sql`, runner in `C:\code\Legion\backend\app\services\drift_service.py`, table migration in `C:\code\Legion\backend\app\migrations\`
- **Attention middleware**: new `C:\code\Legion\backend\app\middleware\attention.py`, integration with existing `approval_service.py` and `notification_service.py`
- **LangGraph supervisor + Pydantic AI**: new `C:\code\Legion\backend\app\supervisor\` package
- **llm-ops subgraph**: new `C:\code\Legion\backend\app\subgraphs\llm_ops.py`, eval sets under `C:\code\Legion\backend\app\eval\*.json`
- **Not Diamond router**: new `C:\code\Legion\backend\app\routing\not_diamond_router.py`; small fallback classifier under `C:\code\Legion\backend\app\routing\semantic_classifier.py`
- **Letta + Mem0**: `docker-compose.yml` additions in `C:\code\Legion\` for Letta server + Mem0; client wrappers in `C:\code\Legion\backend\app\memory\`
- **MCP servers**: new packages `C:\code\ada-mcp\`, `C:\code\zero-mcp\`, `C:\code\legion-mcp\` (or sub-packages within each project)
- **NSSM services**: scripts under `C:\code\scripts\nssm\install-services.ps1` (new) — register `Legion-Stack`, `Zero-Stack`, `vLLM-Service`, `Reachy-Daemon`, `LiteLLM-Proxy`
- **Health watchdog**: new `C:\code\scripts\health-watchdog.py`

Reuse, don't rewrite:
- LiteLLM proxy at `:4444` (no changes; add new model routes only)
- Existing `vault_indexer_service.py` chunking + partition routing
- `circuit_breaker.py`, `approval_service.py`, `qa_gate_service.py` in Legion
- `reachy_wake_word_service.py` and the Reachy persona stack in Zero
- `start-ecosystem.bat` becomes the source for the NSSM services

---

## Verification (end-to-end)

After Stage 5 the following must work without manual intervention:

1. Machine reboots → all three stacks online in <5 min, health watchdog writes to today's daily note.
2. 06:30 ET → Daily Brief Agent writes 7-section summary to today's daily note (cyanheads MCP, agent-run-id footer).
3. Market open → trading subgraph debates a candidate signal, queues for approval if salience ≥ 0.6, otherwise batches.
4. Live-order attempt → blocks on `interrupt()`, surfaces in Agent Inbox.
5. 22:30 → DND active, no interrupts; vault writes to `_agent/inbox` table.
6. Friday 18:00 → weekly review LangGraph runs; immutable `reviews/2026-W17.md` plus drift summary.
7. "Hey Zero, what did I do today?" → Reachy answers via voice, the turn lands in today's `## 🎙️` block.
8. Sunday 02:00 → llm-ops subgraph runs full eval matrix, writes digest to `40_Resources/llm-models.md`, files swap proposal if any candidate beats baseline by ≥10% on the win-rate × cost-per-token product.
9. Langfuse + Pydantic Logfire dashboards show per-agent latency, token cost, Not Diamond routing accuracy, drift hits.

Each stage gate has its own verification block above; promote only when its checks pass for the prescribed soak period.

---

## Rewritten prompt (for future use)

> Review `C:\code\claude\docs\SecondBrain.md`, `C:\code\claude\docs\AgenticOs.md`, and the active vault MOC at `C:\code\vault\ObsidianZero\10_Atlas\MOCs\Zero_As_Chief_of_Staff.md`. Map current state of Zero (`C:\code\zero`), Legion (`C:\code\Legion`), and Ada (`C:\code\ADA`) against the prescribed architecture. Produce a 12-week phased plan with explicit gates that delivers: (1) **Zero as 24/7 chief-of-staff** writing to the Obsidian vault as source of truth, voice via Reachy Mini ("Hey Zero"); (2) **Legion as 24/7 ecosystem orchestrator + LLM-ops owner** that reviews/fixes/debugs/updates every project under `C:\code\` AND continuously researches, A/B-tests, and proposes swaps for the local model layer, all via a LangGraph 1.0 supervisor with Pydantic AI typed specialists, manual `Command(goto=, graph=PARENT)` handoffs to PKM/Projects/Trading/Content/llm-ops subgraphs; (3) **Ada as autonomous trading research with HITL-gated execution** via a Bull/Bear/Risk debate and `interrupt()` before live orders. Adopt the AgenticOs "Do This First" stack: LangGraph 1.0 + Pydantic AI + MCP for orchestration; LiteLLM + Not Diamond (or Qwen3-4B semantic classifier fallback) for routing; Letta + Mem0 + pgvector + LangMem for memory; Microsoft UFO³ + Claude Computer Use + ChatGPT Agent for desktop control (DO NOT BUILD). Expose Ada (called "Magnus" in the docs but the actual project is named Ada — `ada-mcp`), Obsidian (cyanheads), Zero, and Legion as MCP servers. Resolve the `:8000` port conflict between Reachy daemon and vLLM (move vLLM to `:8100/:8101`). Each stage must have deliverables, files to create or modify, a verification block, and a soak-period gate before promotion. Per-project deliverables include `MANDATE.md`, `ARCHITECTURE.md`, and `CLAUDE.md` updates. Reuse existing infrastructure (LiteLLM proxy `:4444`, vault retrieval, Legion approval service, Reachy wake-word, vLLM Qwen3.6-35B-A3B-FP8) and only add what's missing. Decisions to lock before planning: vault scope (single vs work/personal split), Legion approach (evolve vs rewrite), plan horizon, validating projects.

---

## Risks & open items

- **Port 8000 conflict** between Reachy daemon and vLLM is the highest-priority Stage 0 fix. Mitigation: vLLM moves to `:8100/:8101`. Validation: `netstat` after reboot, smoke test both endpoints.
- **Vault path duplication**: `C:\code\vault\ObsidianZero\Zero\` has its own `.obsidian/` config — sub-vault or accidental nest? Investigate in Stage 0.
- **Single native PG17 on `:5432`** hosts `adam` (Ada), `zero` (Zero), and `legion` (Legion + LangMem + Letta + Mem0). Cross-project pgvector queries are now trivially possible — revisit row-level policies if the Eightfold IP boundary requires hard isolation. Consolidated 2026-04-25 from Legion's old Docker `legion-db` container on `:5434`.
- **MCP server churn** — cyanheads, ada-mcp, zero-mcp, legion-mcp are all <1 year old, expect breaking changes; wrap behind thin adapters so swap-out is one file each.
- **vLLM single-GPU contention** — Qwen3.6-35B + embed + reranker share the 5090; the llm-ops subgraph will A/B-test smaller MoE candidates (Qwen3-30B-A3B, Llama-3.3-70B-NVFP4) against the current dense model and propose swaps. Monitor `kv-cache-dtype fp8` headroom.
- **Not Diamond cold start** — initial routing decisions will be poor until enough eval data accumulates. Mitigation: ship the Qwen3-4B semantic classifier as fallback first, switch primary to Not Diamond only after 4 weeks of trace data.
- **Pydantic AI version churn** — v1.85.x in April 2026 per AgenticOs §1; pin via `uv lock` and revisit quarterly.
- **Letta + LangMem overlap** — both store agent memory; risk of double-source-of-truth. Convention: Letta owns *agent-internal* (core/recall/archival per agent); LangMem owns *cross-cutting* (episodic/semantic/procedural across the whole supervisor). Document the split in `legion/docs/supervisor.md`.
- **Eightfold IP boundary** — single-vault decision means the partition tag at every event producer is non-optional. Re-validate at end of Stage 2.
- **24/7 actual uptime** depends on Docker Desktop stability on Windows; if it drifts, fallback is WSL2 Linux Docker (per `AgenticOs.md` §5).
- **PyPI supply-chain risk** — pin LiteLLM ≥ 1.81.14 (1.82.7/1.82.8 were compromised per `SecondBrain.md` §5). Run `trufflehog` over `~/.claude/projects/` nightly per `SecondBrain.md` §7.

---

## Status

> **Audit note (2026-04-28):** Stage 1+ daemons are largely present in code but not auto-registered at FastAPI startup (Legion `register_llm_ops_jobs()` only called from CLI; Ada APScheduler is in-memory and lost on restart). See `~/.claude/plans/lets-do-a-full-bubbly-shore.md` and `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\state\ecosystem-audit\ACTION_QUEUE.md` (Q1, Q2, Q6) for the fixes.

### Planning phases
- Phase 1 Exploration: complete (Zero/Legion/Ada current-state mapped, vault scaffolding verified, ecosystem script read, decisions locked).
- Phase 2 Design: this document.
- Phase 3 Review: this document is the review artifact.
- Phase 4 Final plan: complete.
- Phase 5: ExitPlanMode complete (approved 2026-04-25).

### Stage 0 — Foundation & 24/7 — DELIVERABLES SHIPPED 2026-04-25

| # | Deliverable | Status | Path |
|---|---|---|---|
| 1 | Resolve `:8000` port conflict | ✅ already resolved in code; corrected stale README | `C:\code\shared-infra\README.md`, `docker-compose.vllm.yml` |
| 2 | `C:\code\README.md` | ✅ shipped | new |
| 3 | `C:\code\ARCHITECTURE.md` | ✅ shipped | new |
| 4 | `C:\code\MANDATE.md` | ✅ shipped | new |
| 5 | Per-project `MANDATE.md` (Zero, Legion, Ada) | ✅ shipped | new in each repo |
| 6 | Rewrite `zero/docs/ARCHITECTURE.md` | ✅ shipped | rewritten |
| 7 | Create `ADA/ARCHITECTURE.md` | ✅ shipped | new |
| 8 | Rewrite `Legion/docs/ARCHITECTURE.md` | ✅ shipped | rewritten (Builder Mode framing replaced) |
| 9 | NSSM service install script | ✅ shipped (em-dash bug fixed; parses clean) | `C:\code\scripts\nssm\install-services.ps1` |
| 10 | Ecosystem health watchdog | ✅ shipped | `C:\code\scripts\health-watchdog.py` |
| 11 | Investigate vault `Zero/` subfolder duplicate | ✅ confirmed stale nested vault, safe to delete | (no action; documented) |
| 12 | Bootstrap `40_Resources/llm-models.md` | ✅ shipped | new vault file |

### Stage 0 EXTRAS shipped same session (covers some Stage 1+ scaffolding ahead of schedule)

| Deliverable | Status | Path |
|---|---|---|
| Morning brief script + WST registration | ✅ shipped, smoke-tested live (7/8 services up) | `C:\code\scripts\morning-brief.py`, `register-morning-brief.ps1` |
| Six drift SQL rules + README (Stage 4 work pre-done) | ✅ shipped | `C:\code\Legion\backend\app\drift\` |
| Four eval-set JSON skeletons + README (Stage 3 work pre-done) | ✅ shipped (bootstrap counts; expand in Stage 3) | `C:\code\Legion\backend\app\eval\` |
| Cyanheads MCP runbook extension (Stage 1 prep) | ✅ shipped | `C:\code\zero\docs\obsidian-mcp-install.md` (sections 6–9 appended) |
| Vault session log proposal | ✅ shipped | `C:\code\vault\ObsidianZero\00_Meta\_agent\proposals\2026-04-25-stage-0-shipped.md` |
| Memory: terminology corrections + Stage 0 record | ✅ shipped | `~/.claude/.../memory/project_terminology_corrections.md`, `project_stage_0_complete_20260425.md` |

### Stage 0 verification gate — REMAINING

These are blocked on admin/reboot actions only:

- [ ] Run `powershell -ExecutionPolicy Bypass -File C:\code\scripts\nssm\install-services.ps1` as Administrator
- [ ] Run `powershell -ExecutionPolicy Bypass -File C:\code\scripts\register-morning-brief.ps1` as Administrator
- [ ] Reboot the machine
- [ ] Confirm `Get-Service Legion-Stack, Zero-Stack, SharedInfra-Stack, Reachy-Daemon, Health-Watchdog` all show `Running`
- [ ] Confirm today's daily note has a fresh `## System Health` block within 5 minutes of boot
- [ ] Maintain green watchdog status for 72h straight
- [ ] On Monday 07:00 ET, confirm a `## Morning Brief` block appears in that day's daily note

When all checked → Stage 0 gate passes → start Stage 1 (cyanheads MCP + reranker + retrieval eval).

### Post-Stage-0 hotfix — Postgres consolidation (2026-04-25)

User noticed Legion was still spinning up its own Docker Postgres (`legion-db` on host port 5434) instead of using the Windows host's native PG17 install. Investigation also revealed Ada's `ada-postgres` Docker container was still running with 40 GB of live data despite a 2026-03-17 docker-compose comment claiming it had been migrated. Both were migrated to native PG17 in one pass per the follow-up plan at `C:\Users\hadam\.claude\plans\i-just-noticed-that-eventual-candy.md`.

**Legion (33 MB)** — outcomes:
- Pre-migration row counts (sprints 5, sprint_tasks 16, episodes 5, brain_decisions 1, llm_call_details 108, projects 8, sprint_learnings 339) preserved via `pg_dump -Fc` → `pg_restore`. Rollback dump at `C:\code\Legion\backups\legion-pre-migration-*.dump` retained for 7 days.
- **Lesson**: `legion-litellm` (Prisma) ran a destructive `migrate deploy` schema diff on first connect to the consolidated DB and dropped Legion's app tables. Fixed by giving LiteLLM its own `litellm` database. **Never put Prisma-managed schemas in the same database as another app.**
- 21 skill files with `docker exec legion-db psql ...` rewritten to `psql -h localhost ...`.

**Ada (40 GB Docker → 4 GB native after dump/restore)** — outcomes:
- Native PG17 had stale `adam` (171 GB bloat, 0 live rows, alembic at Jan 26) and `ada` (198 MB bloat, 0 live rows, alembic at Jan 22) — both empty schema husks from past failed migration attempts. Dropped both, recreated `adam` clean, restored from the live `ada-postgres` container (alembic head `20260421_enhanced_daily_reports`).
- 4.8M prediction_markets / 324K prediction_whale_trades / 95K company_info / 35K discord_messages all preserved.
- ada-backend env switched from `DB_HOST: pgbouncer` to `DB_HOST: host.docker.internal`. PgBouncer bypassed (compose comment already noted "No PgBouncer needed — native PG + GlobalJobSemaphore handles concurrency").
- Rollback dump at `C:\code\ADA\backups\adam-pre-migration-*.dump` (328 MB compressed) retained for 7 days.
- **Side fix**: ada-backend was unhealthy — root cause was uvicorn `--reload` mode losing its server child without auto-restart. Container restart fixed it. Recommend removing `--reload` from `C:\code\ADA\Dockerfile` line 180 or building from `Dockerfile.backend` (production) instead.

**Final state (2026-04-25)**:
- All four projects share native PG17 at `localhost:5432` / `host.docker.internal:5432`
- Databases: `adam` 4 GB (Ada) · `zero` 367 MB · `legion` 31 MB · `litellm` 11 MB (LiteLLM, isolated)
- pgvector 0.8.0 + pg_trgm + pgcrypto + uuid-ossp enabled across the board
- Orphan containers (`legion-db`, `legion-db-backup`, `ada-postgres`, `ada-pgbouncer`) stopped and `restart: no` policy applied; volumes preserved 7 days for rollback
- Docs rewritten: `C:\code\README.md`, `C:\code\ARCHITECTURE.md`, `C:\code\Legion\docs\ARCHITECTURE.md`, `C:\code\ADA\docker-compose.yml`, this plan

### Stage 1 — pending Stage 0 gate

Runbook ready at `C:\code\zero\docs\obsidian-mcp-install.md`. Code skeleton for `vault_writer_service.py` switch is in section 6 of that runbook. Negative tests in section 7. Verification gate in section 8.
