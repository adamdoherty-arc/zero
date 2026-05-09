# Ecosystem audit â€” recurring insights

This file accumulates patterns that appear in **two or more consecutive runs**.
First-run observations land in `runs/<date>.md` only. They get promoted here on
the second confirmation. This is the index of what has *durably* gone wrong,
not the firehose.

---

## Run 1 â€” 2026-04-28 â€” baseline established

First formal run. Skill state did not previously exist (was scaffolded this
run). Lib files (`canonical-mandates.md`, `port-map.md`, `managed-projects.md`,
`models-baseline.md`, `plugin-baseline.md`) were already populated by the
human installer / prior partial work; treated as authoritative.

### Observations to watch (candidate insights, not yet confirmed)

These will be promoted to permanent insights only if Run 2 sees them again.

1. **Pattern: schedulers shipped, schedulers don't fire.** Three independent
   confirmations this run â€” Ada daily-briefing, Ada enhanced post-market
   report, Legion `llm_ops` â€” all defined cron jobs but `register_*_jobs()` is
   never called from the FastAPI lifespan. Watch Run 2 for whether this
   recurs after Q1/Q2 land.

2. **Pattern: no daemon heartbeat surface.** No supervised daemon writes a
   "last-run-ok" timestamp anywhere readable (vault, dashboard table, Discord).
   When a job silently dies, nothing notices. Q7 is the structural fix; flag
   re-occurrence until heartbeat table exists.

3. **Pattern: gate-by-env-var instead of `interrupt()`.** Ada
   `broker_orders.py` gates live orders on `ROBINHOOD_PAPER_TRADING` env var
   only â€” no LangGraph `interrupt()`. This is a `financial`-tier MANDATE
   violation. Q4 is the fix.

4. **Pattern: lib registry drift caught only manually.** Lib `port-map.md` says
   `:3001` is "Legion UI"; `docker ps` shows `:3001` is `ada-grafana`. Legion
   UI lives at `:3005` only. Suggests lib was authored from docs-as-truth, not
   docker-as-truth. Watch for similar drift in `managed-projects.md`.

### What worked

- All five canonical models reachable: `qwen3-chat`, `qwen3-coder`,
  `Qwen/Qwen3-Embedding-0.6B` resolved on `:18800` and `:8001`.
- LiteLLM image pinned to `1.83.7-stable` â€” satisfies MANDATE invariant #7
  (â‰¥1.81.14, not in compromised 1.82.7/1.82.8 window).
- Vault git is live (last commit â‰¤24h ago).
- All three project mandates verbatim against canonical.
- Reachy daemon owns `:8000` correctly (banner confirms â€” "Reachy Mini
  dashboard").
- All 7 Tier-1 + 2 of 3 Tier-2 plugins present in vault (only `bases` missing,
  proposal already filed `plugin-bases-builtin-note.md`).
- All projects have commits within the past week.

<!-- agent-run-id: 1895a7c5-6ade-4f85-a1cd-7ef8860fc0cf source: ecosystem-audit at: 2026-04-28T-run-1 -->

## Run 2 - 2026-05-02 - living master plan introduced

Second formal run focused on converting the ecosystem vision into canonical docs
and repeatable validation.

### Confirmed patterns

1. **Pattern: runtime truth drifts faster than docs.** Shared infra had already
   moved `qwen3-chat` to llama.cpp on `:18800` with a Qwen3.6 GGUF backend,
   while several docs and baselines still described Qwen3-32B-AWQ/vLLM-chat or
   `qwen3-coder` as current. `LIVING_STATE.md` and the validator are now the
   containment strategy.

2. **Pattern: MCP references get ahead of implementation.** Zero and Legion
   reference `ada-mcp`, but `C:\code\ADA\mcp_servers\ada_mcp.py` does not yet
   exist. Q11 tracks the compatibility server; Q12 tracks Ada MCP alignment
   after that server exists.

3. **Pattern: no daemon heartbeat surface.** Q7 remains open and is still the
   right structural fix for making daily state trustworthy.

### What worked

- ArchitectureMaster now has `MASTER_PLAN.md` and `LIVING_STATE.md`.
- Canonical docs carry frontmatter for owner, status, source-of-truth class,
  verification date, verification targets, and drift policy.
- Validation passes against the current shared-infra model route and active plan
  path, with only the expected Ada MCP warning.
- Ada now has a top-level `MANDATE.md` with paper-default, financial-tier, and
  public decision-support constraints.

<!-- agent-run-id: 817be7f3-2366-4cb3-9545-c299ef281940 source: ecosystem-audit at: 2026-05-02T-run-1 -->

## Run 2b - 2026-05-02 - company becomes canonical

The operating root moved from `C:\code\ArchitectureMaster` to
`C:\code\zero`.

### Confirmed patterns

1. **Pattern: company context and architecture context must not split.** The
   architecture is the company substrate, so docs and plans now live beside
   company formation/product docs in one folder.

2. **Pattern: legacy paths need compatibility pointers.** ArchitectureMaster
   remains as a pointer so old tools do not fail suddenly, but new work starts
   from `C:\code\zero`.

### What worked

- Company docs validate from the new root.
- The active plan and full historical plan archive were imported.
- Zero, Legion, and Ada mandates now reference company canonical docs.

<!-- agent-run-id: 67b5b32a-89e4-4aee-a58e-0381c0d8e8c0 source: ecosystem-audit at: 2026-05-02T-run-2 -->

