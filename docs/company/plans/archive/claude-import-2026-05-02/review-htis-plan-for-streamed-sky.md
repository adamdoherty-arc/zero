# Review: Legion 2026 Blueprint — Adapted for Zero

## Context

You asked me to review a 2026 blueprint for an autonomous AI workforce ("Legion") against your actual Zero stack. The blueprint is well-researched but greenfield — it assumes a Linux host, vLLM, a fresh Postgres, and cloud-API billing. Your reality is different: Windows host, Ollama serving Qwen3.6, Kimi K2.5 as brain, Claude Max plan (flat rate, not per-token), existing Postgres+pgvector+APScheduler+LangGraph, 66 scheduler jobs, 33 routers, an existing Legion project tracker (project_id=8), and DailyMeetings running on the host. The plan needs heavy adaptation before it maps to what you actually run.

## Verdict at a glance

**Keep ~60%, rework ~30%, drop ~10%.** The architectural principles are excellent. The specific tooling picks are mostly wrong for your stack because the plan optimizes for per-token cloud cost (irrelevant on Max) and Linux-native isolation (unavailable on Windows).

---

## KEEP (high-value, adopt as-is or close)

### 1. Supervisor + handoffs over swarms
Your current scheduler/LangGraph setup is already closer to supervisor-with-handoffs than to a swarm. Formalize it: typed `Handoff` payload with `success_criteria` and `budget_tool_calls`, specialists never call each other directly, orchestrator holds the ledger. This maps cleanly onto your existing `orchestration_graph.py` routes.

### 2. Three-table memory split (episodic / semantic / procedural)
You already have pgvector. Adopt the explicit cognitive split — it's the single biggest quality lever and costs ~200 lines of SQL. Bitemporal `valid_from/valid_until/superseded_by` on semantic facts is worth the complexity. Procedural playbooks mirror your existing `.claude/skills/` directory — export procedural memory to disk for portability.

### 3. Langfuse v3 for observability
You have no systematic trace capture today. Langfuse v3 is Postgres-first (adds ClickHouse+Redis, acceptable), MIT, and is the substrate for every downstream win: evals, DSPy, audit, cost tracking. Install this before anything else in the learning loop. **This is the highest-leverage single addition.**

### 4. Tiered auto-commit ladder (T0 → T3)
Exactly right framing. Maps onto your existing Legion sprint tracking. Your Dependency Watcher → Test Gate → Git Committer chain is the natural first place to wire this up.

### 5. Agents-as-employees (KPIs, shadow mode, weekly perf review)
The "human-override rate per 100 dispatches" north-star metric is the right one. Start every new agent at 48h shadow mode. Worth the discipline.

### 6. Four cache breakpoints on Anthropic prompts
Still matters on Max plan for **latency and rate-limit** reasons even though billing is flat. Tools + system + repo manifest + rolling tail with `ttl: 1h` is the right default.

### 7. AGENTS.md at repo roots + `.claude/agents/*.md`
Cheap, portable, already aligned with your CLAUDE.md pattern.

### 8. DSPy for weekly optimization
Versioned prompt artifacts beat fine-tuning for your workload. MIPROv2 default, GEPA when you have structured feedback (test diffs are perfect feedback).

### 9. Dataset discipline (train/dev/**test** never touches optimizer)
The "test set touching the optimizer is the one un-correctable sin" rule is the most important sentence in the document. Internalize it.

### 10. Renovate + OSV-Scanner + Socket.dev
Socket.dev specifically — the 2025 npm supply-chain incidents (Shai-Hulud, debug/chalk hijack) are why.

### 11. Rollback via `git revert`, never force-push; feature flags as safer primitive
Non-negotiable. OpenFeature + Flagsmith or Unleash.

### 12. Tamper-evident audit log with hash chain
The `prev_hash` + `row_hash` Merkle pattern is cheap to add to a new Postgres table. External anchoring can wait.

---

## REWORK (good idea, wrong specifics for your stack)

### 1. Model plane: ditch vLLM, keep Ollama + add Kimi as brain
The plan's "vLLM serving Qwen3-Coder-30B-A3B-Instruct-AWQ" is Linux/Blackwell-specific. You're on Windows and already have:
- **Ollama** serving Qwen 3.6 (you upgraded — plan still references Qwen3-Coder-30B)
- **Kimi K2.5** as the brain (8/10 task types, per your router config)
- **Claude Max** for Claude Agent SDK work (flat rate, no per-token cost)

Replace the model matrix with your actual five-provider router (Ollama/Kimi/Gemini/OpenRouter/HuggingFace). Drop DeepSeek V3.2 entirely — you don't use it and Kimi covers that cost tier. Drop the vLLM install. Your `UnifiedLLMClient` already does what LiteLLM would do.

**Updated task-to-model matrix for Zero:**
- Orchestrator / planner: **Kimi K2.5** (not Sonnet — Max plan means Claude is "free" but Kimi is faster and already your brain)
- Complex coding, multi-file refactor: **Claude Sonnet 4.6 via Max** (Agent SDK + MCP tools)
- Simple code gen, commit messages: **Qwen 3.6 local via Ollama**
- Research/summarization: **Kimi K2.5** (moonshot-v1-32k for light, kimi-k2.5 for heavy)
- Bulk classification, triage: **Qwen 3.6 local** with structured output
- Messaging (Discord/WhatsApp): **Claude Haiku 4.5 via Agent SDK** (already wired)
- Embeddings + reranking: Keep local

### 2. Sandboxing: Firecracker is unavailable on Windows
Plan prescribes E2B Firecracker microVMs. On Windows you have:
- **Docker Desktop + WSL2** — the realistic default. Not microVM-strong, but acceptable for code your own agents author in a trusted repo.
- **E2B Pro hosted** — viable if you want real microVM isolation without Linux ops. Worth $150/mo only if you start running agent-authored code from untrusted sources (issue bodies, web fetches).
- **Daytona self-hosted on WSL2** — not meaningfully stronger than Docker alone on Windows.

**Recommendation:** Don't pretend you have microVM isolation. Document the gap honestly. Use Docker+WSL2 for now, plan a migration to E2B Pro when (not if) Research Scout starts fetching untrusted web content that gets fed to code-executing agents.

### 3. Cost math is moot — rewrite it
The plan's entire cost argument ("hybrid $420/mo vs full-Claude $1,650/mo") assumes per-token Anthropic billing. You're on **Max plan — Claude is a flat cost regardless of volume** (within rate limits). Kimi has a real per-token cost but it's ~$0.024/1M on moonshot-v1-32k. Your real cost drivers are:
- Kimi API calls (measure, budget)
- Electricity for Ollama (trivial)
- Any new cloud infra (Langfuse ClickHouse, E2B if adopted)

Replace "RTX 5090 amortization in 6 weeks" with: **"How much Kimi spend per month, and when does a local Qwen 3.6 pass displace a Kimi call without quality loss?"** That's the actual routing decision.

### 4. Message queue: you already have APScheduler + LangGraph + Postgres
Plan prescribes pgmq. You have 66 APScheduler jobs. Don't migrate — **add pgmq only for agent-to-agent dispatch** (the supervisor handoff payloads), keep APScheduler for scheduled jobs. Two queues, different jobs.

### 5. Observability: skip the full Prometheus/Grafana/Alertmanager/Loki/Beszel/cAdvisor stack
That's a weekend of ops you don't need. Start with **Langfuse + your existing docker logs + daily_report_service**. Add Prometheus only when you have a specific metric you can't answer with Langfuse + Postgres queries.

### 6. Agent roster: map onto your existing services, don't greenfield
You already have: `scheduler_service`, `content_swarm_service`, `prompt_breeder_service`, `daily_report_service`, `image_source_service`, `character_content_service`. The "8 agents" framing should wrap these, not replace them. Specifically:
- **Orchestrator** → extend `orchestration_graph.py`
- **Test/Regression Gate** → new, wrap `pytest` runs
- **Git Committer** → new, gated role
- **Learning Curator** → new, 6-hour cron job added to scheduler
- **Dependency Watcher, Docker Monitor, Research Scout, Code Reviewer** → new specialists

Don't build all 8 at once. Start with Curator + Test Gate + Git Committer — they unlock everything else.

### 7. GitHub Apps with 1-hour tokens
Good pattern, but you're solo. One `agent-committer` App is enough for v1. Three Apps is right when you have multiple humans + multiple agent classes.

---

## DROP (doesn't apply or wrong tradeoff)

### 1. "Build on Blackwell RTX 5090" framing
You're not buying a 5090. Your hardware story is Windows + Ollama + whatever GPU you have. The plan's entire hardware chapter is irrelevant.

### 2. DeepSeek V3.2 as "bulk cheap fallback"
You don't use it. Kimi's moonshot-v1-32k at $0.024/1M covers the cheap tier.

### 3. llama.cpp MoE offload for 80B overflow
Overkill. Your current Kimi K2.5 brain is already smarter than any local 80B you'd run.

### 4. Infisical / SOPS+age for secrets
You have `.env` + Docker. Good enough for solo. Revisit if you add teammates.

### 5. Merge queues / rulesets / required signatures
Solo dev doesn't benefit from merge queues. Keep branch protection simple: no force-push to main, that's enough.

### 6. CaMeL capability-based interpreter
Research-grade. The Dual-LLM + Spotlighting combo at the policy layer is sufficient for your threat model (you are the primary user; your agents mostly read your own repo).

### 7. Visual regression, mutation testing, benchmark regression in CI
Nice-to-have for a team. Solo + Max plan means your time is the constraint, not test depth. Add unit + integration + type + lint + Socket. Stop there until something actually breaks.

---

## Critical files to update / create (when executing)

- `backend/app/services/orchestrator_handoff.py` — new, typed `Handoff` payload
- `backend/app/services/memory_service.py` — new, three-table memory split
- `backend/app/db/models.py` — add `mem_episodic`, `mem_semantic`, `mem_procedural`, `audit_log` tables
- `backend/app/services/langfuse_client.py` — new, OTel GenAI instrumentation
- `backend/app/services/curator_service.py` — new, 6-hour cron
- `backend/app/services/test_gate_service.py` — new, pytest wrapper
- `backend/app/services/git_committer_service.py` — new, tiered commit ladder
- `.claude/agents/*.md` — per-agent HR forms
- `AGENTS.md` at repo root — interop file
- `renovate.json` — copy the plan's policy directly

Existing files to extend:
- `backend/app/services/orchestration_graph.py` — add handoff routing
- `backend/app/services/scheduler_service.py` — add curator + test gate jobs
- `backend/app/services/unified_llm_client.py` (or equivalent router) — keep, don't replace

---

## Recommended build sequence (4 phases)

**Phase 1 — Substrate (2 weeks).** Langfuse v3 install + OTel instrumentation on every LLM call. Three memory tables + migration. Audit log table with hash chain. AGENTS.md + `.claude/agents/` skeletons. This phase ships zero new agents; it's pure plumbing.

**Phase 2 — First three agents (2 weeks).** Curator (6h cron), Test Gate, Git Committer with T0/T1 ladder. Wire into existing Legion project_id=8 sprint tracking. Shadow mode for first 48h each.

**Phase 3 — Learning loop (2 weeks).** Trace → outcome join job (merge/revert signal). Weekly DSPy MIPROv2 compile on a held-out dataset. A/B gate with feature flag (OpenFeature + Flagsmith).

**Phase 4 — Remaining specialists (ongoing).** Dependency Watcher, Docker Monitor, Research Scout, Code Reviewer. One at a time, each with its own shadow-mode onboarding.

---

## Verification

- **Phase 1:** Every LLM call in `unified_llm_client` produces a Langfuse span with `gen_ai.*` attributes. `SELECT COUNT(*) FROM mem_episodic WHERE created_at > now() - interval '1 day'` > 0. Audit log rows chain-verify via `sha256(prev_hash || row_data) = row_hash` across 100 rows.
- **Phase 2:** Git Committer opens a T0 PR autonomously, Test Gate gates it, merge lands. Human-override rate captured in Langfuse dataset.
- **Phase 3:** First DSPy artifact versioned + A/B'd at 10% traffic. Promotion gate blocks a deliberate regression in the test set.
- **Phase 4:** Dependency Watcher opens a Renovate PR, Socket.dev verdict attached, T0 auto-merge succeeds on a patch bump.

---

## Open questions before executing

1. Do you want Langfuse v3 self-hosted in Docker (adds ClickHouse) or Phoenix (Postgres-only, less powerful)?
2. Is the "third GitHub App / 1-hour token" pattern worth it at solo scale, or start with one App + PAT in `.env`?
3. Is E2B Pro ($150/mo) justified now, or defer until Research Scout exists?
4. Do you want the Curator to also export procedural memory to `.claude/skills/` on disk (portability), or keep it Postgres-only?
