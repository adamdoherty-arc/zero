# Audit evolution

Append new checks the user has asked the skill to take on permanently. Each
entry is dated. The skill loads this file at boot (Phase A step 4) and
incorporates the additions on subsequent runs.

---

## 2026-04-28 â€” Run 1 baseline

No new checks added beyond the skill default. Future-state pointers:

### Future: migrate audit into Legion (target ~2 weeks out)

After Q1, Q7, and the new `architecture_master` Legion subgraph ship:

1. Move auto-heal logic from this skill into Legion's `architecture_master`
   subgraph (`c:\code\Legion\backend\app\subgraphs\architecture_master.py`,
   doesn't exist yet).
2. Persist findings/queue/insights in Postgres `legion` DB (new tables:
   `audit_findings`, `audit_queue`, `audit_insights`). Schema migrated by
   Legion's existing alembic.
3. Skill becomes a thin entry point that calls `legion-mcp` `audit.run()`.
4. Vault output stays in `00_Meta/_agent/architecture/<date>.md`.

When this happens, this skill's `state/` directory is read-only-archived
(rename to `state.archive-pre-legion/`) and the new authoritative source is
`/api/architecture-master/...` on Legion.

### Future: enable Phase G (parallel research)

Phase G (model/PKM/desktop-control/supply-chain web research via 4 parallel
sub-agents) is part of the skill spec but was deliberately scoped out of Run
1's plan to keep first-run focused on framework setup. Enable on Run 2 once
the state framework exists to receive the findings.

<!-- agent-run-id: 1895a7c5-6ade-4f85-a1cd-7ef8860fc0cf source: ecosystem-audit at: 2026-04-28T-run-1 -->

