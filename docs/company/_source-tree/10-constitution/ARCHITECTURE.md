---
owner: company
status: canonical
source_of_truth: topology
last_verified: 2026-05-02
verified_against:
  - C:\code\shared-infra\litellm\config.yaml
  - C:\code\shared-infra\docker-compose.vllm.yml
  - C:\code\Legion\docs\LEGION_OVERVIEW.md
drift_policy: Legion may propose doc updates after runtime verification
---

# Personal AI Ecosystem — Target Architecture

This is the architecture the company plan at `C:\code\company\plans\active\review-the-two-lively-cascade.md` is building toward. Some pieces (LiteLLM, vLLM, vault scaffolding, Legion approval service) already exist; others (LangGraph supervisor, Pydantic AI specialists, Letta + Mem0, Not Diamond router, llm-ops subgraph) are being added.

## Stack decisions (locked)

Adopted from `docs/30-strategy/AgenticOs.md` "Do This First" section:

1. **Orchestration spine**: LangGraph 1.0 + manual `Command(goto=, graph=PARENT)` handoffs (skip the deprecated `langgraph-supervisor` library).
2. **Typed agents**: Pydantic AI for individual specialist nodes — schema-enforced contracts between subgraphs, not prose.
3. **Tool fabric**: MCP everywhere. `cyanheads-obsidian`, `ada-mcp`, `zero-mcp`, `legion-mcp`. Same servers serve Claude Code, Cursor, Claude Cowork, ChatGPT Agent, and any future client.
4. **Routing**: LiteLLM proxy `:4444` (gateway) + Not Diamond client-side router (sub-token decisions, eval-trained). Fallback: Qwen3-4B semantic classifier.
5. **Memory**: Letta (agent runtime, OS-style core/recall/archival) + Mem0 (cross-agent user prefs) + LangMem (typed namespaces) + pgvector (RAG). All on the Windows host's native PostgreSQL 17 install at `localhost:5432` (shared with Ada `adam` and Zero `zero`; databases stay logically separate).
6. **Desktop control — DO NOT BUILD**: Microsoft UFO³ (Windows-native apps), Claude Computer Use (IDE/shell), ChatGPT Agent (web/SaaS).
7. **Legion path**: evolve in place — build new LangGraph supervisor + llm-ops subgraph in `Legion/backend/app/supervisor/`, validate via Daily Brief Agent + drift output, then port the custom sprint engine logic node-by-node.

## Topology

```
User surfaces
  ├─ Voice: "Hey Zero" → Reachy Mini (USB-C)
  ├─ Claude Code (CLI + IDE)
  ├─ Obsidian (vault edits)
  ├─ Phone: Claude Cowork / ChatGPT Agent
  └─ Web UIs: Zero :5173, Ada :5420, Legion :3001/:3005
                      ↓ MCP stdio/HTTP + Anthropic Messages API

Desktop control (integrate, do not build)
  ├─ UFO³ → Windows-native apps via UIA + OmniParser-V2
  ├─ Claude Computer Use → IDE / shell agentic coding
  └─ ChatGPT Agent → web / SaaS workflows
                      ↓

Routing layer
  ├─ Not Diamond client-side router — task-class + sensitivity + latency + cost
  └─ LiteLLM proxy :4444 — providers, retries, $50/24h budget
                      ↓                                                    ↓
Local: llama.cpp + vLLM on RTX 5090                                Cloud passthrough
  • llama-cpp-chat :18800 (host) → Qwen3.6-35B-A3B GGUF Q4_K_M       • Anthropic (Sonnet 4.6, Haiku 4.5, Opus 4.7)
  • vllm-embed :8001 → Qwen3-Embedding-0.6B                         • Gemini (Pro/Flash latest aliases)
  • Stage 1 add: Qwen3-Reranker-0.6B                                • Kimi K2.5
                                                                    • MiniMax M2
                                                                    • OpenRouter
                      ↓

Legion supervisor (LangGraph 1.0 + Pydantic AI typed agents)
  manual handoffs via Command(goto=name, graph=Command.PARENT)
  ├─ pkm subgraph        → cyanheads-obsidian MCP, vault R/W, daily/weekly digest
  ├─ projects subgraph   → git, gh, ruff, pytest, cross-repo PR creation
  ├─ trading subgraph    → ada-mcp + Tradier hosted MCP, Bull/Bear/Risk debate, HITL
  ├─ content subgraph    → ComfyUI API, 9-agent reflexion DAG (week 12+)
  └─ llm-ops subgraph    → vLLM health, HF/NVIDIA model research, A/B eval, swap proposals

Memory (native PG17 :5432 + pgvector — shared host install)
  databases: adam (Ada) · zero (Zero) · legion (Legion + LangMem/Letta/Mem0 stores)
  ├─ AsyncPostgresSaver — checkpoints
  ├─ AsyncPostgresStore — long-term
  ├─ LangMem — episodic | semantic | procedural | shared
  ├─ Letta — agent runtime (core/recall/archival, self-edits)
  └─ Mem0 — cross-agent user preferences (risk tolerance, comm style, DND)
                      ↓

MCP tool fabric (NEW)
  • cyanheads-obsidian (vault write-back, frontmatter patch, heading append)
  • ada-mcp (Tradier, Alpaca, Robinhood, FRED, Discord/XTrades, paper-default)
  • zero-mcp (vault read/write, journal, habits, goals, ecosystem health)
  • legion-mcp (sprints, drift queries, learning council, llm-ops)
  • tradier-hosted (mcp.tradier.com/mcp — paper-default, interrupt before live)
  • fred-mcp, gcal-mcp, gmail-mcp, github-mcp, postgres-mcp, playwright-mcp
                      ↓

Approval queue (Postgres `approvals` table) + Agent Inbox UI (extends Legion's)
  Tiers enforced:
    read           — no gate
    write_local    — auto if salience < 0.6 in DND, else inbox
    write_external — always interrupt, salience-batched
    financial      — always interrupt, never auto, requires explicit confirm
                      ↓

Observability
  ├─ Langfuse (self-host Docker) — OTel traces, cost, evals
  └─ Pydantic Logfire — Pydantic AI nodes
                      ↓

24/7 substrate
  ├─ NSSM Windows services for: Legion-Stack, Zero-Stack, Ada-Stack-DevOnly,
  │                             vLLM-Service, LiteLLM-Proxy, Reachy-Daemon
  ├─ APScheduler in each backend (Postgres job store)
  ├─ ZeroHostAgent Scheduled Task (Reachy supervision — already exists)
  └─ Legion llm-ops daemon: health every 5min, research daily 03:00, full eval Sunday 02:00
```

## Model routing table (canonical names → backend)

| Canonical name | Backend | Used by |
|---|---|---|
| `qwen3-chat` | **vLLM** `vllm-chat:8000` inside docker net, **host `:18801`** outside (`Qwen/Qwen3-32B-AWQ`, AWQ Marlin Int4) | **Single shared local chat model** — Zero, Ada, and Legion route through Bifrost `:4445`; backend changes are made in `shared-infra/docker-compose.vllm.yml`. Re-swapped 2026-05-18 from llama.cpp Q5_K_M GGUF. |
| `qwen3-chat-thinking` | Same llama.cpp endpoint | Reasoning-enabled variant for callers that intentionally want Qwen3.6 thinking mode |
| `qwen3-embed`, `Qwen/Qwen3-Embedding-0.6B` | vLLM `vllm-embed:8001` | All vault chunking, Ada RAG |
| `qwen3-coder` | Legacy name; not active in the current shared LiteLLM config | Audit any remaining callers and route them to `qwen3-chat` unless Legion reintroduces a dedicated coder model through `llm_ops` |
| `claude-sonnet-4-6` | Anthropic | Supervisor, long-context synthesis, complex code |
| `claude-haiku-4-5` | Anthropic | Classification, simple summaries, intent detection |
| `claude-opus-4-7` | Anthropic | Tax/legal/architecture (rare, $-gated) |
| `kimi-k2.5`, `moonshot-v1-128k` | Moonshot | Cloud fallback, planning |
| `minimax-m2` | MiniMax | Cloud fallback chain |
| `gemini-flash-latest`, `gemini-pro-latest` | Google | Vision, long-context cheap |
| `openrouter-auto` | OpenRouter | Last-resort passthrough |

Privacy gate: anything tagged `vault-write | trading-decision | personal-journal | finance-pii | health` is forced LOCAL (no cloud egress).

## Partition tags

Every event producer (Zero, Ada, Legion, Reachy, MCP servers) attaches one of:

- `partition: personal` — life, journal, vault
- `partition: zero-dev` — Zero codebase work
- `partition: trading` — Ada / brokerage / FRED
- `partition: work` — Eightfold material (BLOCKED — single-vault constraint hard-drops these)

The vault constitution at `C:\code\vault\ObsidianZero\00_Meta\CLAUDE.md` enforces this at write time.

## Approval tier matrix

| Tier | Examples | Default behavior |
|---|---|---|
| `read` | vault read, FRED query, Tradier positions | No gate |
| `write_local` | vault `_agent/` write, Postgres update, daily-note `## Agent Summary` append | Auto if salience < 0.6 OR DND active → batch to inbox; else execute |
| `write_external` | git push, gh PR create, GCal event create, gmail send, Discord post | Always `interrupt()`, batched if salience < 0.6 |
| `financial` | `place_live_order` on any broker, large fund moves | Always `interrupt()` + explicit `confirm: True` flag, never auto |

## Attention economy

- DND window: 22:00–07:00 local (configurable per partition)
- Salience score 0–1 attached to every nudge; only ≥0.6 interrupts immediately
- Hard cap: 5 interruptions/day
- Tiering: `notify | question | review`
- Implementation: `Legion/backend/app/middleware/attention.py` (Stage 4)

## Diagram conventions used elsewhere

- Mermaid only (renders in GitHub, Obsidian, Logseq).
- Subgraphs grouped by lifecycle layer (perception → cognition → action → integration).
- Color scheme: Zero blue, Ada green, Legion purple, Reachy red, infra amber.
