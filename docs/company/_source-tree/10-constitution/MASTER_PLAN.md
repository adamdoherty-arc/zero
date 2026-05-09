---
owner: company
status: canonical
source_of_truth: master-plan
last_verified: 2026-05-02
verified_against:
  - C:\code\company\docs\10-constitution\MANDATE.md
  - C:\code\company\docs\10-constitution\ARCHITECTURE.md
  - C:\code\shared-infra\litellm\config.yaml
  - C:\code\shared-infra\docker-compose.vllm.yml
drift_policy: human-edited, Legion-audited
---

# Company Living Master Plan

`C:\code\company` is the operating home for the company Adam is building. It
absorbs the ArchitectureMaster constitution and keeps Zero, Legion, Ada, the
Obsidian vault, shared infra, and company formation work aligned as one effort.

## North Star

Build a durable personal operating system where:

- **Zero** is Adam's chief-of-staff, second brain, voice surface, and Reachy Mini
  companion.
- **Legion** is the 24/7 software and ecosystem operator that keeps every
  project under `C:\code\` healthy, updated, measured, and improving.
- **Ada** is the financial intelligence product: first Adam's trusted advisor,
  later the seed of a company if the product, safety, and compliance bar is met.
- **Shared infra** is the common model, routing, memory, observability, and
  approval substrate that prevents three projects from becoming three separate
  worlds.

The ecosystem is successful when Adam can ask "what should I focus on right
now?" and get one answer that safely accounts for personal commitments, project
health, financial signals, energy, risk, and long-term goals.

## Source Of Truth

The documents have different jobs. Do not let them compete.

| Layer | Source | Job |
|---|---|---|
| Policy | `docs/10-constitution/MANDATE.md` | Agent identity, approval tiers, privacy partitions, non-negotiable safety rules |
| Topology | `docs/10-constitution/ARCHITECTURE.md` | Target system shape, routing, memory, MCP fabric, model map |
| Living state | `docs/40-operations/LIVING_STATE.md` | Current runtime facts, open drift, verification status |
| Strategy | `docs/30-strategy/SecondBrain.md`, `docs/30-strategy/AgenticOs.md` | Long-form design rationale and research context |
| Execution history | `plans/active/review-the-two-lively-cascade.md` | The staged rollout and prior implementation decisions |
| Runtime truth | `C:\code\shared-infra\litellm\config.yaml`, compose files, project configs | What is actually running |

When these disagree, runtime truth wins for current facts, `MANDATE.md` wins for
safety, and `MASTER_PLAN.md` decides where the ecosystem is trying to go.

## Pillars

### Zero

Zero owns Adam's personal loop: voice, Reachy Mini, daily routine, vault writes,
journal, calendar/email, habits, goals, and high-salience surfacing. Zero is the
only default human-facing assistant. It delegates code work to Legion and
financial research to Ada, then writes the durable outcome back into the vault.

Zero's trust contract is vault discipline. It never writes to `.obsidian/`,
`.git/`, `.trash/`, or work-partition material, and it only writes outside
`00_Meta/_agent/` through the approved whitelist and mtime/audit footer path.

### Legion

Legion owns continuous improvement. Its loop is:

```text
discover -> plan -> execute -> review -> learn -> repeat
```

Legion should increasingly behave like a measured research organization, not a
bag of scripts. It keeps projects fresh, creates and executes bounded sprints,
observes every LLM call, promotes better prompts only through canaries, and
turns failures into learning data.

Karpathy's `autoresearch` pattern is the design model for high-trust autonomy:
small scope, fixed budget, one metric, keep winners, roll back losers, and wake
the human with a readable experiment log. Legion should apply that pattern to
software health, prompt evolution, dependency updates, model routing, and later
Ada strategy research. Reference: https://github.com/karpathy/autoresearch.
The underlying `nanochat` context matters because it keeps the experiment
harness small, hackable, measurable, and end-to-end:
https://github.com/karpathy/nanochat.

### Ada

Ada's personal role is to research, monitor, explain, and surface financial
signals. It is paper-default. Any live brokerage action is `financial` tier:
explicit approval, explicit confirmation, audit trail, and no autonomous live
execution.

Ada's company path is real but gated. Public/product documentation must describe
Ada as decision support until legal and compliance review clears stronger
claims. The product ambition is to become the best agentic financial advisor in
the world by combining portfolio context, options-native workflows, market
regime awareness, learning from outcomes, and transparent risk controls.

### Shared Infra

Shared infra exists so Zero, Legion, and Ada do not each maintain separate model
stacks. Current routing runs through LiteLLM on host `:4444`; local chat is
served on host `:18800`; embeddings are served on host `:8001`; Reachy owns host
`:8000` and must never be displaced.

Model swaps are not doc edits. They are Legion `llm_ops` proposals backed by
benchmarks, A/B tests, rollback paths, and updated `LIVING_STATE.md` entries.

## Living Documentation Loop

Documentation should evolve the same way the system does:

1. Humans update intent in `MASTER_PLAN.md`, `MANDATE.md`, or strategy docs.
2. Runtime changes land in code/config first.
3. Legion audits docs against runtime truth, project docs, MCP files, compose
   files, vault rules, and model registry state.
4. Low-risk doc drift becomes an agent proposal or local patch. External,
   financial, service restart, plugin install, push, or model-swap actions go
   to the queue.
5. `LIVING_STATE.md` records current facts and known gaps after each audit.

Graphify and codebase graph tools are optional structural memory for large
repositories. Use them first as generated state, not committed truth. They are
valuable when they reduce repeated file reads and expose cross-file design
relationships; they do not replace source code or project docs. Reference:
https://graphify.net/.

Graphiti is deferred until temporal relationship memory becomes load-bearing
beyond Postgres, pgvector, and LangMem. Reference:
https://blog.getzep.com/graphiti-hits-20k-stars-mcp-server-1-0/.

## Current Priorities

1. Make the docs trustworthy: reconcile model, port, plan-path, mandate, and MCP
   drift.
2. Finish the 24/7 substrate: service autostart, daemon heartbeat surface,
   audit queue, and morning system health summaries.
3. Give Legion a durable architecture-master audit subgraph with MCP/API
   surfaces for audit, drift, queue, and graph queries.
4. Harden Ada's financial safety story before any product/company expansion.
5. Pilot Graphify/codebase-memory on one repo, measure whether it improves
   architecture Q&A, then decide whether it belongs in Legion.
