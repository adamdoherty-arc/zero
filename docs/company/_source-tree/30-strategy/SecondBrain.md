---
owner: company
status: strategy-reference
source_of_truth: strategy
last_verified: 2026-05-02
verified_against:
  - C:\code\company\docs\10-constitution\MASTER_PLAN.md
  - C:\code\company\docs\40-operations\LIVING_STATE.md
drift_policy: preserve as research context; do not treat runtime facts as current without LIVING_STATE
---

# Legion++: An autonomous second brain for a polymath operator

> Operational note: this is a strategy reference. Current runtime facts live in
> [`LIVING_STATE.md`](LIVING_STATE.md), and policy lives in
> [`MANDATE.md`](MANDATE.md).

**Bottom line up front.** Build your second brain as an **Obsidian vault (source of truth) + Legion (single LangGraph runtime) + Postgres/pgvector (memory & retrieval) + cyanheads Obsidian MCP (write-back) + vLLM Qwen3-Coder on the 5090 + Claude Code via LiteLLM router (cloud escalation) + LiveKit-bridged Zoey voice**. The content pipeline is a separate LangGraph DAG sharing Legion's memory. Do not spin up a second "PKM agent" microservice; model PKM as a specialist subgraph inside Legion. Work in 12 phased weeks, starting with vault structure and git-backed reversibility — everything else is useless if the vault isn't trustworthy. The two highest-leverage early wins are (a) an opinionated daily-note YAML schema that lets the agent reason about energy, trades, and project health, and (b) a cyanheads MCP server plus mandatory `obsidian-git` auto-commit, which together give you free undo on every agent write. The content quality problem is almost certainly seven specific Wan 2.2 config bugs, not a model-choice problem.

The rest of this report is organized by your ten objectives plus a concrete 12-week rollout.

## 1. Vault architecture — ACE + JD-addressed Efforts + Zettelkasten Atlas

PARA is too action-only, pure Zettelkasten has no home for trade logs or tax receipts, and Johnny Decimal's rigidity fights emergent domains. The hybrid that wins for a polymath with an AI layer is **ACE at the top level** (Atlas / Calendar / Efforts — Nick Milo's LYT evolution) with **Johnny-Decimal-numbered Effort folders** so the agent has stable, addressable project IDs it can cite and never duplicate. Atomic notes live in a Zettelkasten-flavored `10_Atlas/Concepts/`, densely wikilinked to MOCs.

```
00_Meta/         CLAUDE.md, Templates/, Bases/, _agent/
10_Atlas/        MOCs/, Concepts/, People/, Sources/
20_Calendar/     Daily/, Weekly/, Monthly/, Quarterly/
30_Efforts/      31_Eightfold, 32_Legion, 33_Magnus_Trading, 34_Marvel_DC_Pipeline,
                 35_Sought_Supply, 36_Zoey_Reachy, 37_Tax_475MTM, 38_Ascend_LLC
40_Resources/    SOPs, API docs, playbooks (no secrets)
90_Archive/      >90d dormant
_Inbox/          QuickAdd lands here first
```

JD prefixes give the agent unambiguous path roots for MCP operations, ACE separates cognitive modes so you can tell the agent *"for status, read 30_Efforts + 20_Calendar/Daily; for knowledge, read 10_Atlas,"* and `_Inbox/` plus `00_Meta/_agent/` explicitly segregate human capture from AI output to prevent signal-to-noise collapse.

**Folders are location, tags are cross-cutting facets.** Never duplicate folder meaning in tags. Use nested tags for domains (`#domain/legion`), types (`#type/decision`), and status (`#status/active`); use **frontmatter properties** for anything you'll filter on in Bases or Dataview. Obsidian 1.9+ deprecated singular `tag`/`alias`/`cssclass`; use plural list forms and run the Linter plugin on save.

**Two-vault consideration:** you have Eightfold employer IP alongside an `Ascend` consulting brand. A single combined vault is a moonlighting-clause risk. Strongly consider splitting **Work vault** (Eightfold only) from **Personal+Ventures vault** (everything else), with separate OS user accounts or at least separate Cursor/VSCode/Chrome profiles.

## 2. Daily note and project frontmatter schemas

The daily note schema is where the AI gets its reasoning handles. Every field earns its place; none are decorative.

```yaml
---
id: 2026-04-22
type: daily
date: 2026-04-22
week: 2026-W17
quarter: 2026-Q2
status: active              # active | closed | skipped
energy: 8                   # 1–10 self-rated at morning check-in
mood: focused               # focused | scattered | drained | flow | anxious
sleep_hours: 7.5
focus_domain: [32_Legion, 33_Magnus_Trading]
blockers:
  - waiting on Eightfold legal re: moonlighting clause
top_3:
  - "[[32 Legion]] — ship orchestrator v0.3 spike"
  - "[[37 Tax 475MTM]] — finalize election letter draft"
  - "[[33 Magnus_Trading]] — close expiring SPY puts"
trading:
  trades_opened: 2
  trades_closed: 1
  realized_pnl: 347.22
  wheel_positions_active: 6
  margin_used_pct: 42
commits: 7
deep_work_minutes: 185
meetings_count: 3
reviewed: false
agent_reviewed: false
agent_session: null
tags: [daily, log]
---
```

The **`energy`, `mood`, `sleep_hours` triad is the secret weapon** — correlate with trade P&L and commit quality over weeks and you get your first genuinely novel insight out of the system. Keep nesting one level deep; Obsidian's Properties UI gets flaky below that.

**Project frontmatter** exposes "current state at a glance" plus an explicit agent-write contract:

```yaml
---
id: 32_Legion
type: project
status: active          # idea | active | simmering | blocked | done | archived
stage: build            # discovery | design | build | ship | maintain
priority: p1
health: yellow
last_reviewed: 2026-04-19
next_review: 2026-04-26
objective: "Production-quality autonomous orchestrator that plans, delegates, writes back to vault."
success_criteria:
  - "End-to-end task runs >15min unattended"
  - "All vault writes gated by proposal loop"
depends_on: ["[[38 Ascend_LLC]]"]
blocks: ["[[34 Marvel_DC_Pipeline]]"]
tech_stack: [python, langgraph, mcp, vllm, postgres]
current_focus: "MCP server hardening; vault write sandboxing"
blockers:
  - "Flaky tool use >20 steps"
open_questions:
  - "Streaming proposals vs batched?"
tasks_open: 14
tasks_done_7d: 9
commits_7d: 23
agent_writable: [status, updated, health, tasks_open, tasks_done_7d, commits_7d]
agent_append_section: "## Agent Log"
agent_proposals_to: "00_Meta/_agent/proposals/"
tags: [project, domain/legion, stage/build]
---
```

The **`agent_writable` / `agent_append_section` convention is yours to enforce** — the CLAUDE.md rule becomes *"before writing, read the target note's `agent_writable` list; if the field isn't whitelisted, write a proposal instead."* This is not yet a community standard, and it's the single cleanest contract I've seen for safe write-back.

**Bases beats Dataview for new work in 2026.** Bases went GA in Obsidian 1.9 (mid-2025), handles 50k+ note vaults at interactive speed, uses YAML formulas an LLM can read and author, and materializes into the vault as `.base` files that agents can create. Dataview is in maintenance mode; keep it only for aggregating in-body task checkboxes (where Bases doesn't yet reach) and inline DataviewJS widgets. Skip Datacore for 6 more months.

## 3. Plugin starter set

**Install day one:** Templater, QuickAdd, Obsidian Tasks, Periodic Notes, Calendar, **Obsidian Git** (non-negotiable — auto-commit every 10–15 min is your undo button for every agent write), Dataview, Bases (core), **Advanced URI** (the hook that lets Raycast, iOS Shortcuts, and external scripts drive Obsidian), **Linter** (normalizes YAML on save).

**Strongly recommended:** Smart Connections (local embeddings, free tier is enough), Homepage (startup dashboard embedding Bases views), Tag Wrangler, Omnisearch, **Local REST API** (required by cyanheads MCP).

**Skip for your setup:** Text Generator and Local GPT are redundant with Claude Code + MCP. Copilot-for-Obsidian only if you want an in-Obsidian chat pane. Smart2Brain is explicitly labeled experimental by its team. File Organizer plugins fight your schema.

Hard cap: ~20 community plugins. Every three months, remove one you don't use.

## 4. Obsidian-to-AI bridge — MCP, embeddings, vector store

**Write-back server:** `cyanheads/obsidian-mcp-server` (TypeScript, REST-API-backed via the Local REST API plugin). It's the most feature-complete in early 2026 — frontmatter patching, heading/block-level patches, in-memory cache with periodic refresh, dual stdio/HTTP transport with JWT. Stable and actively maintained. Use it for Claude Desktop and Claude Code write-heavy paths.

**Read-only background server:** a thin filesystem path for Legion's cron jobs and indexer so indexing keeps working when Obsidian is closed. `StevenStavrakis/obsidian-mcp` or a 100-line custom Python server is fine here. Do not route batch reindexing through Obsidian's REST API.

**Embeddings:** **Qwen3-Embedding-0.6B** as primary (BF16 on the 4090 via text-embeddings-inference or vLLM embedding endpoint; Matryoshka-truncate to 512 dims for the journal partition, 1024 for reference). Qwen3-Reranker-0.6B over the top-50 hybrid candidates matters more than the embedder at your vault size. Swap to **jina-embeddings-v3** only if you adopt late chunking. MTEB scores reshuffle monthly; run a 30-query A/B on your own notes before switching models.

**Vector store: pgvector on your existing Postgres.** Zero new infrastructure, transactional `DELETE old chunks / INSERT new chunks` in one `BEGIN/COMMIT`, frontmatter filters become SQL `WHERE tags @> ARRAY[...]`, and BM25 via `tsvector` fuses cleanly with dense via Reciprocal Rank Fusion. Use HNSW (`m=16, ef_construction=128`) and add `pgvectorscale` if you push past 5M chunks. Qdrant is the fallback only if you outgrow Postgres or want a hard isolation boundary.

**Chunking:** parse frontmatter separately as structured metadata, preserve `[[wikilinks]]` in the chunk text (they're high-signal for the embedder and let the agent follow them), split hierarchically by Markdown headers (`MarkdownHeaderTextSplitter` or Chonkie's `RecursiveChunker(recipe="markdown")`), cap at ~512 tokens with 15% overlap. Apply **Anthropic's Contextual Retrieval pattern** (prepend a 1–2 sentence "where does this chunk fit" summary before embedding) to the **reference partition only** — skip for daily logs because the cost doesn't pay off. Atomic notes under 300 tokens get one chunk, never split.

**Index freshness:** `watchdog` file-watcher with **30-second debounce** (short enough to feel live, long enough to batch autosave). Use `PollingObserver` if the vault lives inside iCloud/Dropbox/Docker — native inotify misses events on cloud-synced paths. Hash-based change detection (`sha256(content)`) eliminates 60–80% of spurious reindex work from editor-save-on-focus-change. Version-hash your embedder config so a model swap triggers full reindex. Nightly orphan sweep catches files deleted while the watcher was down.

**Stable-vs-ephemeral discrimination — the single biggest retrieval quality win.** Partition the index logically: `reference | projects | journal | inbox`. Route queries by partition (agent decides, or weighted union). Apply **time-decay only to the journal partition**: `score = 0.7 * cosine + 0.3 * 0.5^(age_days / 30)`. Hybrid BM25+dense+rerank at every query. A cheap LLM pass classifies the query as "what did I do Monday" (journal, time-filtered) vs "what's my architecture for X" (reference, no decay).

**Write-back discipline the MCP server enforces:** append-only under a dedicated H2 marker (`## Agent Summary`) for daily notes, frontmatter merge (never replace) for projects, free write only in `_agent/` namespace, never touch `.obsidian/`. Mtime-check-before-write as poor-man's optimistic concurrency. Every agent write carries `<!-- agent-run-id: abc123 -->` as a footer for audit and dedup.

## 5. Legion evolved — supervisor agent architecture

**Keep Legion as the single runtime. Do not spin up a separate PKM agent microservice.** Model PKM as a subgraph with its own MCP toolset inside Legion. One checkpointer keeps thread state coherent across Zoey, Claude Code, and CLI entry points; one Store keeps long-term memory coherent across domains; subgraphs let you swap prompts/tools without forking processes.

**Write handoffs manually** using `Command(goto=..., graph=Command.PARENT)` rather than the `langgraph-supervisor` library. LangChain deprecated the library as the *recommended* path in late 2025; the manual pattern is ~40 lines, gives full control over what state transits a handoff, and matches what the library does under the hood.

```python
# legion.py — supervisor + specialists, AsyncPostgresSaver + AsyncPostgresStore
import os
from typing import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import create_react_agent, InjectedState
from langgraph.types import Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from langchain_openai import ChatOpenAI       # vLLM OpenAI-compat
from langchain_anthropic import ChatAnthropic

DB = os.environ["LEGION_PG_DSN"]
qwen = ChatOpenAI(model="qwen3-coder", base_url="http://localhost:18800/v1", api_key="x")  # host port; container internal :8000 (Reachy owns :8000)
claude = ChatAnthropic(model="claude-sonnet-4-5")

def handoff(agent_name: str, desc: str):
    @tool(f"delegate_to_{agent_name}", description=desc)
    def _h(task: Annotated[str, "Self-contained task brief"],
           state: Annotated[MessagesState, InjectedState],
           tc_id: Annotated[str, InjectedToolCallId]) -> Command:
        return Command(goto=agent_name, graph=Command.PARENT,
                       update={"messages": state["messages"] +
                               [ToolMessage(f"Routed to {agent_name}", tool_call_id=tc_id)]})
    return _h

trading  = create_react_agent(qwen,   tools=[...tradier_mcp], name="trading")
projects = create_react_agent(claude, tools=[...git_tools],   name="projects")
pkm      = create_react_agent(qwen,   tools=[...obsidian],    name="pkm")
content  = create_react_agent(claude, tools=[...comfy_tools], name="content")

supervisor = create_react_agent(
    claude, name="supervisor",
    tools=[handoff("trading", "Market/positions/PnL work"),
           handoff("projects","Project status, PRs, deadlines"),
           handoff("pkm",     "Note capture, linking, daily digest"),
           handoff("content", "Character-short production")],
    prompt="You are Legion, Adam's chief-of-staff. Route ONE task at a time. "
           "Prefer local agents for privacy-sensitive work. Delegate; don't answer directly.")

g = (StateGraph(MessagesState)
     .add_node("supervisor", supervisor)
     .add_node("trading", trading).add_node("projects", projects)
     .add_node("pkm", pkm).add_node("content", content)
     .add_edge(START, "supervisor"))
for n in ("trading","projects","pkm","content"): g.add_edge(n, "supervisor")
```

**Specialist decomposition rule of thumb:** promote a domain to its own subagent when its tool count exceeds ~8, its system prompt exceeds ~500 tokens, or it needs a different model. LangChain's 2025 multi-agent benchmark showed naive supervisors underperform single-agent-with-tools under two distractor domains, so don't over-decompose. Low-frequency domains (travel, finance-admin) start as tools on the supervisor.

**Memory stack:** AsyncPostgresSaver for checkpoints, AsyncPostgresStore with pgvector for long-term, **LangMem** on top for episodic/semantic/procedural abstractions. Skip mem0 (duplicate infra over Postgres). Add Graphiti (Apache-2.0, self-host) only if temporal reasoning ("who led project Q1 vs Q2") becomes load-bearing. Namespace design:

```python
NS = lambda *p: tuple(p)
await store.aput(NS("episodic","adam","trading","2026-04-22"), key=str(uuid4()),
                 value={"event":"closed ES long +$430","ts":"..."})
await store.aput(NS("semantic","adam","profile"), key="risk_tolerance",
                 value={"data":"max 1.5% portfolio per trade"})
await store.aput(NS("procedural","legion","supervisor"), key="routing_heuristics",
                 value={"data":"Route 'weekly digest' to pkm, not content"})
await store.aput(NS("shared","adam","calendar"), key="dnd",
                 value={"data":"22:00-07:00 local"})
```

**Task routing Claude vs local:** encode an explicit `privacy_tag` on every tool-call schema. Force LOCAL for `{vault-write, trading-decision, personal-journal, finance-pii, health}`; allow CLOUD for `{public-docs-qa, large-refactor, architecture-review, long-context-synthesis}`. Route through **LiteLLM proxy** (pin ≥ 1.81.14 stable — PyPI 1.82.7/1.82.8 were compromised with credential stealers in March 2026) with the Anthropic pass-through endpoint so Claude Code keeps speaking native format. vLLM on the 5090 serving `Qwen3-Coder-30B-A3B-Instruct-AWQ` with `--enable-prefix-caching --tool-call-parser qwen3_coder --reasoning-parser qwen3 --kv-cache-dtype fp8` benchmarks at ~988 tok/s at MCR=32; stay below 0.90 GPU memory utilization to leave room for Triton's first-call autotune on Qwen3 hybrid-GDN layers.

## 6. Triggers, rollups, and drift detection

**Three trigger surfaces.** Scheduled via APScheduler in-process (`SQLAlchemyJobStore` on the same Postgres so jobs survive restarts). Event-driven via `watchdog` on the vault, git post-commit hooks, and Notion/Discord webhooks. Reactive via Zoey voice, Raycast hotkey, Claude Code CLI, or a Slack/Telegram MCP bot.

**Attention economy is non-optional.** Borrow LangChain's ambient-agent three-tier framing — `notify | question | review`. Enforce a **DND window** (22:00–07:00 local, weekends optional) checked before any push; during DND, writes go to an inbox table. Each proposed nudge carries a **salience score** (0–1); only salience ≥ 0.6 interrupts immediately, the rest batch into the morning digest. **Hard cap at ~5 interruptions/day** — beyond that, the agent becomes another Slack and gets ignored.

**Daily rollup — 400–800 words, readable in 90 seconds, generated ~6:30am.** Seven sections: North Star (single line, today's win condition), Calendar (next 12h with conflicts flagged), Carry-over (yesterday's unfinished with explicit re-plan/drop), Attention queue (overnight alerts), Market briefing (from the trading specialist), PKM surfacing (1–2 old notes relevant to today's calendar, Khoj-style), and Agent log (what Legion did overnight). Append under `## Agent Summary` in the day's daily note plus email/Slack ping.

**Weekly review is GTD-flavored, interactive, 30–60 min Friday PM.** Get Clear (inbox to zero, loose notes filed, open loops extracted from the week's chat transcripts), Get Current (every active project's last-action and next-action, drift flags, waiting-for reconciled), Get Creative (someday/maybe + three candidate next-week experiments). Output is an immutable `reviews/2026-W17.md` plus updated project-status JSON in Postgres.

**Drift detection — six concrete Postgres rules**, versioned in `legion/drift/*.sql`, running nightly and writing to `agent_alerts`:

1. Idle project while sibling-domain active (project priority ≥ 2, last_activity > 7d, other domain has events in last 3d).
2. Calendar-vs-actual divergence (deep-work calendar blocks without matching commits/notes).
3. Commit velocity decay (14-day EMA < 40% of 8-week baseline).
4. Intent drift (last week's stated top-3 not reflected in activity).
5. Inbox bloat (unprocessed Inbox notes > 5 days old).
6. Trading-session skip (market-hours weekday with no trade/journal event).

Surface these in the daily digest and drive the weekly review's Get Current pass.

**Guardrails for near-full autonomy** layer as follows: (a) tool permission tiers `read | write_local | write_external | financial` with LangChain 1.0's `HumanInTheLoopMiddleware` gating anything past `write_local`; (b) LangGraph `interrupt()` + `Command(resume=...)` for out-of-band approval (pair with Auth0 CIBA when you're away from the laptop); (c) Postgres `approvals` table surfaced in an Agent Inbox UI — copy `langchain-ai/agent-inbox` pattern; (d) per-tool `audit_events` row for forensics; (e) **`legion/auto` git branch** so every vault mutation is reversible with `git revert`; (f) `DRY_RUN=true` env flag replaces `write_external` tools with mocks (run 72h before promoting new specialists); (g) circuit breakers on $-spend/hour and error-rate/10-min that flip the supervisor read-only and page you. The threat model isn't hallucination — it's **silent cumulative drift** and Simon Willison's **lethal trifecta** (private data + untrusted content + external comms), which is why `read_note` + `send_email` + `fetch_url` cannot all be enabled on the same un-gated tool loop.

## 7. Unifying signal sources

A **Redis Streams capture bus** is the right plumbing: single binary you probably already run, consumer groups, persistent, replayable by ID. Flat-tagged event schema (`ts, source, partition, project, summary, payload_ref, tags`) with the heavy payload kept by reference so the bus stays small. Plain JSONL files + chokidar is an equally-fine zero-dep alternative for a solo pipeline.

**Developer activity.** A global git `post-commit` hook (`core.hooksPath = ~/.config/git/hooks`) appends `repo@sha – message` under `## Commits` in today's daily note. Install **Wakapi** (self-hosted, point the WakaTime VSCode extension at your host) for language/project time and **ActivityWatch** (with aw-watcher-vscode, aw-watcher-window, aw-watcher-afk) for OS-level focus context — run both and merge at EOD. Switch your shell to **Atuin** for timestamped, cwd-aware, exit-coded history (the `nitsanavni/bash-history-mcp` project exposes it to Claude). Never dump raw shell history; summarize via a small LLM prompt grouped by `$cwd`.

**Claude Code and Cursor logs.** Claude Code transcripts live at `~/.claude/projects/<urlencoded-cwd>/<session-uuid>.jsonl` with turn-by-turn user/assistant/tool messages, token usage, git state snapshots, and `parentUuid` threading. Global prompt log at `~/.claude/history.jsonl`. Raise `cleanupPeriodDays` in `~/.claude/settings.json` to prevent the default 30-day purge. Use `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` in the Eightfold work shell. Tools like `daaain/claude-code-log` parse JSONL to HTML. Cursor stores chat in `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (SQLite, `cursorDiskKV` table with `composerData:` / `bubbleId:` keys); `saharmor/cursor-view` and the `cursor-history` CLI read it. Expect Cursor's schema to change at every major release — pin the tailer carefully. **Claude Desktop's IndexedDB is not a stable contract** — don't build on it.

**Trading.** A Python Tradier poller at 16:15 ET hits `/accounts/{id}/balances`, `/positions`, `/gainloss`, `/history`, writes the results under `## Trading` in today's daily. Use `thammo4/uvatradier` or `kickshawprogrammer/tradier_api` as the wrapper. As of **Dec 22, 2025 Tradier ships a hosted MCP server at `mcp.tradier.com/mcp`** — Magnus should use that directly with `PAPER_TRADING: "true"` as the default header and a LangGraph `interrupt()` before any live order. Unusual Whales has a hosted MCP at `unusualwhales.com/public-api/mcp`; prefer it over scraping. **Do not use a Discord selfbot** — it violates Discord ToS III and gets accounts banned. The compliant path is a sanctioned bot token in an admin-owned channel; the cheat is an RSS/email egress from XTrades if they offer one.

**Calendar and Notion.** `nspady/google-calendar-mcp` (2.6.1, March 2026) is the de facto GCal MCP — use its `account` parameter to hard-filter out the Eightfold calendar. Notion API 2025-09-03 now has **native outgoing webhooks** (subscribe to `page.content_updated`, `data_source.schema_updated`, etc.); pair with polling fallback using `last_edited_time` cursor. Switch old code from `database_id` to `data_source_id`. **Sunset Notion for personal use; keep it only as a publish target** for notes tagged `#share/work` via the Notion MCP.

**Voice — Zoey.** Reachy Mini Lite is USB-tethered, no onboard compute, SDK at `pollen-robotics/reachy_mini`. The reference conversation app (`reachy_mini_conversation_app`) uses fastrtc + OpenAI Realtime or Gemini Live; for full local, point it at vLLM/Kokoro. The right 2026 stack: Silero VAD → openWakeWord (`"Hey Zoey"`) → **faster-whisper distil-large-v3** (or NVIDIA Parakeet TDT 1.1B if you're English-only — RTFx >2000) → Legion via MCP → **Kokoro 82M** TTS (Apache 2.0, streaming via Kokoro-FastAPI on :8880) → Reachy speaker + head motion tool calls → barge-in via Silero-interrupt. Best production framework: **LiveKit Agents** — it shipped native one-line MCP support in early 2026, which cleanly bridges the Reachy daemon to Legion. Every Zoey turn appends to today's daily note under `## 🎙️`.

**Life-logging.** Rewind is effectively discontinued (team pivoted to Limitless). **Recommend ActivityWatch always-on + Screenpipe for high-value screen recall** (has app blacklist for Eightfold hygiene, MCP server built-in). Pensieve is a strong third if you want VLM+OCR. Readwise Reader remains the right reading aggregator; Omnivore and Pocket are both dead.

**Privacy partitioning (priority order):** separate OS user or at minimum separate Cursor/VSCode profile for work → per-app exclusion at every collector (ActivityWatch filters, Wakapi `exclude = ` regex, Screenpipe blacklist, `CLAUDE_CONFIG_DIR=~/.claude-work`, Atuin `history_filter`) → `partition: work | personal | trading` tag at every producer, hard-dropped by the aggregator → separate git identity via `includeIf` — the global post-commit hook gates on `user.email`. Nightly `trufflehog` over `~/.claude/projects/` catches accidentally-logged secrets.

## 8. Content pipeline — why yours doesn't look great yet

Your content problem is almost certainly **seven specific Wan 2.2 configuration bugs**, not a model choice. Before considering Hunyuan, LTX, or SkyReels, fix these:

1. **Sampler/scheduler:** use `euler` + `simple` (matches the training schedule). Karras/exponential/sgm_uniform breaks motion — this is the most common "Wan looks blurry" cause.
2. **Two-expert MoE handoff:** chain two `KSampler (Advanced)` nodes. First runs the high-noise expert steps 0→N/2 (`add_noise=enable`, `return_with_leftover_noise=enable`); second runs the low-noise expert N/2→N (`add_noise=disable`). Shift = 5 for 720p via `ModelSamplingSD3`.
3. **Lightning LoRAs are not optional.** Apply Lightx2v/Kijai Wan2.2-Lightning separately to high- and low-noise UNets. Sweet spots: 6+6 steps @ strength 1.0 for natural motion, or 4+4 @ high=1.5/low=1.2 for iteration. Use the late-Oct 2025 `2.2-Lightning-I2V-1030-H` / `-1022-L` variants — earlier drops had prompt-following regressions.
4. **VAE:** `wan_2.1_vae.safetensors` for A14B, `wan2.2_vae.safetensors` for the 5B TI2V. Mixing silently produces mush.
5. **Text encoder:** `umt5_xxl_fp8_e4m3fn_scaled.safetensors` — do not substitute T5-v1.1.
6. **No FaceDetailer pass** on your keyframe before Wan I2V. Add Impact Pack's FaceDetailer with InstantID @ 0.4–0.6 for eye/nose recovery.
7. **No upscale/interpolation.** Raw Wan 720p/16fps looks rough until you run **FlashVSR → RIFE 2× → 32fps**.

Fix those seven and quality jumps noticeably before any model change.

**Model stack for character-driven 5–15s shorts on your rig (primary):** **Wan 2.2 A14B I2V with Lightning LoRAs** (on the 5090, ~2–4 min per clip) + **Wan 2.2 5B TI2V on the 4090 for previs**. Use **SkyReels V2-DF** for any shot >8s. Skip Hunyuan unless a specific prompt demands it — Wan has eaten its lunch on human-centric content. Wan 2.5/2.6/2.7 are API-only Comfy Partner nodes; don't pin hopes on a local release before Wan 2.8/3.0.

**Character consistency — the stack that works.** Don't rely on a single tool. Ordered combo: (a) generate an 8–16 view **character sheet** via Mickmumpitz's Consistent Character Creator v3 (Qwen-Image-based, free on his YouTube description); (b) **train a Flux dev character LoRA** on those views (AI-Toolkit, rank 32, ~1500 steps, 45 min on a 5090) — this is the single highest-leverage step most users skip; (c) generate shot keyframes with Flux dev + character LoRA @ 0.85–1.0 plus **PuLID v2 @ 0.3–0.5** as a safety net; (d) FaceDetailer + InstantID @ 0.4–0.6 for eye/nose recovery; (e) pass the keyframe through Wan 2.2 I2V; (f) **ReActor face swap only on frames where Wan drifted** (typically the last 1–2s of an 8s clip). Temporal coherence within a shot is Wan's job; cross-shot consistency is the LoRA's job. Don't confuse the two.

**Audio.** **Chatterbox (Resemble, MIT)** is the recommended open TTS — 63.75% preference over ElevenLabs in blind tests, strong voice cloning. F5-TTS is a solid second. Kokoro for narration only (no cloning). For lip-sync, **LatentSync 1.6** (ByteDance, best open-source in ComfyUI) plus **LivePortrait** over the top for micro-expressions. Wan 2.2 S2V with CosyVoice is the lazy single-node path.

**LangGraph content DAG.** Nine specialists with reflexion loop:

- ConceptAgent → ScriptAgent (JSON shot list) → StoryboardAgent (**human review checkpoint**) → CharacterSheetAgent (Mickmumpitz v3 via ComfyUI API; trains Flux LoRA if missing) → ShotPlannerAgent → KeyframeAgent (Flux + LoRA + PuLID + FaceDetailer) → VideoAgent (Wan 2.2, parallelized across 5090 + 4090) → AudioAgent (Chatterbox) → LipSyncAgent (LatentSync) → EditAgent (ffmpeg + LUT + BGM) → **QAAgent** → PublishAgent.

QAAgent runs four automated checks: CLIP similarity vs character reference (>0.72), LAION aesthetic predictor (>5.5), InsightFace ArcFace vs reference (>0.45 cosine), and a Qwen2.5-VL-7B / GPT-4o-vision critique ("does this match the storyboard? rate 1–10, list defects"). Any fail triggers a reflexion loop — regenerate that shot with perturbed seed + modified prompt up to 3 retries before human flag. Use SQLite or Postgres as the LangGraph checkpointer — you don't want to lose 2 hours to a crash during video gen.

**ComfyUI API wrapper from Python** is a 50-line WebSocket client; export workflows via *Settings → Enable Dev mode → Save (API format)*, parameterize by patching node input values before `queue_prompt`, watch `executing` events for completion. Version workflows as semver JSON in a git repo with a `manifest.yaml` pinning ComfyUI version + custom node commits + model hashes — the #1 cause of "it worked yesterday" is an unversioned node update.

**Must-have custom nodes:** ComfyUI-Manager, rgthree, Impact-Pack, KJNodes, WanVideoWrapper (Kijai's bleeding edge), VideoHelperSuite, Frame-Interpolation, GGUF, IPAdapter_plus, Florence2/Qwen2.5-VL, **TeaCache + WaveSpeed** (2–3× Wan speedup), FlashVSR, Use-Everywhere. On a 5090 also install **Sage Attention 2** (compile from source for sm_120 Blackwell), **Flash Attention 3**, and the FP16-accumulation patches from WanVideoWrapper.

**Creators to study:** Mickmumpitz is the gold standard (grab his Consistent Character Creator v3 free workflow); Olivio Sarikas for weekly news; Nerdy Rodent for deep LoRA-training walkthroughs; Theoretically Media and Curious Refuge for production-value filmmaking; Banodoco Discord for real-time "what's broken today" signal — Kijai and the PuLID team hang out there.

**IP reality check.** Disney and WB both actively DMCA AI-generated Marvel/DC content, especially anything with an actor's face (right-of-publicity stacks on top of copyright). Fair use is a defense, not a right; parody (satirizing the character) is stronger than satire (using the character to satirize something else). YouTube Content ID will flag MCU music first; AI-likeness of real actors requires 2024+ synthetic-media disclosure. **For a sustainable revenue channel, build original characters in a superhero style** — "Kosmis, a cosmic-armored protector" instead of Iron Man. You can monetize, license, and merchandise your own IP; you cannot do any of that with Disney's. Treat Marvel/DC AI shorts as demonetized portfolio pieces only. Royalty-free audio always (Stable Audio Open, Suno with commercial license). Label AI-generated content per the EU AI Act.

## 9. Integration — how the pieces click together

```
User surfaces: Zoey (LiveKit) │ Claude Code │ Obsidian │ Raycast/CLI
                        ↓  (MCP stdio/HTTP; Anthropic Messages API)
                    LiteLLM :4000  (routing, retries, budgets, audit)
                        ↓              ↓              ↓
                Claude Sonnet 4.5   Claude Haiku   vLLM Qwen3-Coder (5090)
                Opus 4.5            4.5            Qwen3-VL-30B
                        ↓
         Legion supervisor (LangGraph, manual handoffs)
           ├─ PKM subgraph (vault R/W, daily review)
           ├─ Magnus subgraph (Tradier hosted MCP, FRED, Discord bot)
           ├─ Code/Ops subgraph (git, gh, shell, Claude Code cloud handoff)
           └─ Content subgraph (ComfyUI API, 9-agent DAG)
         AsyncPostgresSaver + AsyncPostgresStore + LangMem + pgvector
                        ↓
         MCP tool fabric: cyanheads-obsidian, git, github, postgres,
                          gmail/gcal/gdrive, notion (publish-only),
                          tradier-hosted, fred, unusual-whales, discord-bot,
                          playwright, fetch, exa, memory
                        ↓
         Arize Phoenix (single Docker, OTel traces + evals)
```

**Observability: Arize Phoenix** over Langfuse for a personal stack — single Docker container (no ClickHouse + Redis + S3 like Langfuse self-host requires), free LLM-as-Judge evals unlocked, OpenInference-native. Langfuse is more polished but heavier; use LangSmith's free tier (5k traces/mo) as a secondary dev signal.

**Notion role:** sunset for personal; keep as a one-way publish target for `#share/work`-tagged notes. Mirror only what collaborators need; everything else stays in Obsidian.

**Claude vs Qwen routing table:**

| Task class | Route | Why |
|---|---|---|
| Vault writes, trading decisions, personal journal, finance PII, health | Local Qwen3-Coder | Privacy non-negotiable |
| Embeddings, classification, intent detection, simple summary | Local small (Qwen3-4B) | Cheap, fast |
| Transcription, voice turns | Local (Whisper/Parakeet + Kokoro) | Latency |
| >200k context, large codebase refactor | Claude Sonnet 4.5 [1m] | Context window |
| Deep reasoning, tax/legal drafts, architecture review | Claude Opus 4.5 | Judgment matters |
| Routine code edits, EOD drafts, pre-market briefs | Local Qwen3-Coder (fallback Haiku) | Cost + privacy |
| Default | Claude Haiku 4.5 | Fast, cheap |

**Tax / LLC / Ascend operational helpers** (not legal advice): Magnus writes every fill with `entity, account, intent` frontmatter so a Dataview query regenerates the Form 4797 worksheet at EOY; a nightly wash-sale detector runs pre-§475 (and stays useful for the segregated investment account post-election); a Gmail/Drive MCP agent scans receipts into `/Finance/Expenses/{YYYY-MM}/` with category tags; a March-15 cron fires the §475 election reminder; a year-end agent compiles CPA prep pack (4797 draft, Schedule C summary, home-office + mileage, 1099-B reconciliation). Everything tagged `privacy: finance-pii` — local-only.

## 10. Phased 12-week rollout

**Each phase lists goal, deliverables, key tools, validation, and the single most important thing.**

**Weeks 1–2 — Foundation.** *Goal:* vault you'd trust an agent to write to. *Deliverables:* ACE+JD folder structure, daily and project templates with the schemas above, Templater + QuickAdd capture hotkeys, Bases dashboards for Active Efforts and Open Trades, `obsidian-git` auto-commit every 10 min, CLAUDE.md constitution, global git post-commit hook appending to today's daily note. *Key tools:* Obsidian 1.9+, Templater, QuickAdd, Bases, Obsidian Git, Linter. *Validation:* one full week of clean daily notes with no schema drift, git log shows `auto: agent writes` commits. *Most important:* git auto-commit. Every later phase depends on free reversibility.

**Weeks 3–4 — Retrieval layer.** *Goal:* Claude Code and Legion can both query the vault semantically. *Deliverables:* pgvector schema with `reference | projects | journal | inbox` partitions, Python indexer using Qwen3-Embedding-0.6B via TEI on the 4090, header-hierarchical chunking preserving wikilinks, `watchdog` watcher with 30s debounce + hash dedup + polling fallback, cyanheads MCP server configured in Claude Desktop/Code, hybrid BM25+dense retrieval with Qwen3-Reranker, query-classifier for partition routing. *Key tools:* pgvector, text-embeddings-inference, watchdog, cyanheads-obsidian-mcp-server, Obsidian Local REST API plugin. *Validation:* 30 hand-written queries return the right note in top-3; index rebuild on a 5k-note vault completes in <5 min; file save → searchable in <45s. *Most important:* partition routing — without it, yesterday's journal drowns out your reference notes.

**Weeks 5–6 — Passive observability.** *Goal:* Legion knows what you did today without asking. *Deliverables:* Tradier EOD poller + Magnus writing EOD notes to `/Trading/Journal/`, Wakapi + ActivityWatch running with Eightfold exclusions, Atuin shell history, global git post-commit hook firing on all repos, Claude Code JSONL tailer producing per-session summaries, GCal MCP pulling personal-calendar events, Redis Streams capture bus with producer scripts, partition-tagged events. *Key tools:* Wakapi, ActivityWatch, Atuin, Tradier MCP (hosted), nspady GCal MCP, Redis, faster-whisper. *Validation:* run for 5 days; aggregator can assemble a 400–800 word daily summary from bus events alone with no human prompt; zero `partition: work` events leak into the personal daily note. *Most important:* the `partition` tag at the producer — retrofitting privacy later is painful.

**Weeks 7–8 — Summarization loop.** *Goal:* automated daily and weekly rollups written to the vault. *Deliverables:* LangGraph graph wired to the Redis bus consuming yesterday's events at 06:30, writing the 7-section daily summary under `## Agent Summary`, Friday PM interactive weekly review graph, LangMem namespaces wired (episodic per-domain, semantic profile, procedural supervisor), approval queue table + Agent Inbox UI, LangGraph `interrupt()` on any `write_external` tool, dry-run mode working. *Key tools:* LangGraph, AsyncPostgresSaver, AsyncPostgresStore, LangMem, Claude Sonnet 4.5 for supervisor. *Validation:* 7 consecutive days of daily summaries you approve unedited ≥5 of 7; first weekly review identifies a real blocker you hadn't noticed. *Most important:* the dry-run flag — run 72h before letting the summarizer write for real.

**Weeks 9–10 — Specialist agents.** *Goal:* domain subagents coordinate under Legion. *Deliverables:* Trading, Projects, PKM, Content subgraphs with the manual handoff pattern; Magnus moved to Tradier hosted MCP with paper-default + `interrupt()` before live orders; PKM subagent handling capture-to-inbox, atomic-note promotion proposals, MOC updates; Projects subagent running commit velocity queries and producing the drift SQL results nightly; Arize Phoenix deployed with OpenInference instrumentation on every node. *Key tools:* LangGraph subgraphs, Tradier MCP, Arize Phoenix, LiteLLM proxy (≥1.81.14). *Validation:* supervisor routes correctly on 20 evaluation prompts; drift detection surfaces one real idle project; Phoenix dashboard shows per-agent latency and cost. *Most important:* explicit `task:` argument on every handoff tool — the LangChain 2025 benchmark showed it's the single biggest lift for supervisor accuracy.

**Weeks 11–12 — Proactive check-ins + Zoey voice.** *Goal:* near-full autonomy with voice interface. *Deliverables:* APScheduler cron jobs for morning digest, market-open briefing, EOD rollup, Friday weekly review, month-end retro; attention-economy middleware (DND window, salience threshold, 5-interrupt budget, notify/question/review tiering); LiveKit Agents bridge to Reachy Mini daemon with Silero VAD + openWakeWord + Parakeet TDT + Kokoro-FastAPI; every Zoey turn appending to the daily note; circuit breakers on $-spend and error rate. *Key tools:* APScheduler, LiveKit Agents (with native MCP support), Reachy Mini SDK, Parakeet, Kokoro. *Validation:* one full week with Legion proactively surfacing ≥3 useful nudges and zero false-alarms during DND; Zoey conversation → daily-note entry works without manual intervention. *Most important:* salience thresholding. An agent that interrupts too often is worse than no agent.

**Beyond week 12 — content pipeline rework.** Fix the seven Wan 2.2 config bugs first (probably 1–2 days of work). Then build the 9-agent LangGraph content DAG with reflexion loop. Train your first Flux character LoRA on an original character in a superhero style — not a Marvel/DC likeness — for a sustainable monetization path. Target: one fully-automated short per week, human review at Storyboard and Character Sheet checkpoints only.

**Anti-patterns to avoid throughout:** building the content pipeline before the second brain is load-bearing; adding mem0/Zep when Postgres+LangMem covers you; turning on `write_external` tools before dry-run has run 72h; letting the agent write outside `_agent/` or append-only sections before the approval queue is live; trying to make one monolithic agent handle trading + PKM + content (even with huge context windows, LangChain's benchmark shows narrow specialists win under distractor load); pinning to `langgraph-supervisor` library when the manual handoff pattern is what LangChain now recommends; using a Discord selfbot.

## Risks, privacy, and the long view

**Vault bloat** is the most likely failure mode. The agent will write more than you read. Defenses: agent outputs ghettoed to `00_Meta/_agent/` unless explicitly promoted; aggressive 90-day archive cadence; monthly \"archive candidates\" report in the weekly review; time-decay scoring in the journal partition so stale auto-content doesn't drown out real notes; `shelf_life: 90d` frontmatter field on fast-moving technical notes with stale-warning agent behavior.

**Privacy.** The layered defenses above (OS profile separation, per-collector exclusion, `partition` tag at ingest, `CLAUDE_CONFIG_DIR=~/.claude-work`, separate git identity, nightly trufflehog sweep) are not optional given an Eightfold moonlighting clause and consulting brand (`Ascend`) living in the same workspace. Consider fully separate vaults for work versus personal — the overhead is low once you have Obsidian URI-driven capture.

**Lock-in.** Plain markdown + wikilinks + YAML is the most portable format in PKM. Keep it that way. Every agent-output convention above (`## Agent Summary` headings, `agent_writable` list, `<!-- agent-run-id -->` footers) renders perfectly in any markdown reader. Dataview is in maintenance mode, so prefer Bases for new dashboards — but Bases files are YAML and portable. Obsidian's own CLI shipped in early 2026 for Insiders; if it stabilizes it eliminates the Local REST API dependency, so treat cyanheads as replaceable plumbing not a commitment. Never depend on Notion for source-of-truth.

**Cost economics.** On a 5090 serving Qwen3-Coder-30B-A3B-AWQ at ~988 tok/s, your marginal inference cost is electricity (~\$0.05–0.10 per million tokens at typical US rates). Claude Sonnet 4.5 is ~\$3/million input + \$15/million output. Anything routine at >1M tokens/week (daily summaries, drift detection, PKM housekeeping) pays back the 5090 fast. Keep Claude Opus for genuinely reasoning-hard tasks (architecture reviews, tax/legal drafts, novel research) where a wrong answer is expensive. Budget caps on LiteLLM virtual keys ($X/day per task class) are the circuit breakers.

**Maintenance burden.** The parts that are set-and-forget: git auto-commit, daily note template, Tradier EOD poller, GCal MCP, ActivityWatch, drift SQL rules. The parts that need monthly tuning: retrieval weights, salience thresholds, supervisor routing prompt, drift rule parameters. The parts that will keep changing: Wan/Hunyuan model versions and custom nodes (expect weekly churn — pin via manifest.yaml), MCP server APIs (cyanheads and friends are <1 year old, expect breaking changes in 2026 — revisit Q3), and Claude/Qwen model versions (router config only). Plan ~2 hours/week tuning and ~1 full weekend every 3 months for stack upgrades. That's the tax for near-autonomy; it's much lower than the time the system saves once it's running.

## Bottom line

You have the hardware, the frameworks, and the projects — what you're missing is the **connective tissue** (vault schema + MCP + memory namespaces + drift detection) and the **discipline layer** (approval queues + DND + partition tags + git reversibility). Legion doesn't need to become something new; it needs four specialist subgraphs, a cyanheads Obsidian write path, the Postgres Store + LangMem namespaces, and the attention-economy middleware. The content pipeline is a separate DAG sharing Legion's memory — fix the seven Wan 2.2 config bugs before rewriting anything. Move to Obsidian primary and sunset Notion to publish-only. Ship the 12 weeks in order; the first two are boring and they matter most. By week 8 you will have a daily summary you trust; by week 12 Zoey will know what you did today, flag what you didn't, and route market-hours work before you notice you forgot.
