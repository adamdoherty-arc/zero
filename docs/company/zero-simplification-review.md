---
owner: zero
status: canonical
source_of_truth: zero-simplification-review
last_verified: 2026-05-02
---

> Active Zero context: created in `C:\code\zero\docs\company` on 2026-05-02.
> This review is about simplifying Zero after merging ADA AI LLC Company OS.

# Zero Simplification Review

Zero is now both personal assistant and Company OS. That is the right direction,
but the repo has accumulated overlapping surfaces. The simplification goal is
not to make Zero smaller at the expense of capability; it is to keep one clear
home for each workflow.

## Current Size Snapshot

As of 2026-05-02:

| Area | Count | Note |
|---|---:|---|
| Frontend pages | 63 | Several are specialized workbenches that should remain reachable until explicitly retired |
| Backend routers | 76 | Many are active domains; some overlap by lifecycle stage |
| Backend service modules | 183 | Content, Reachy, meetings, memory, and company systems dominate |
| Alembic migrations | 43 | Normal for the current pace; avoid squashing until schema stabilizes |
| MCP servers | 3 local Zero-owned | `zero-mcp`, `zero-company`, `kimi-llm` |

## Keep

These are core operating surfaces and should remain first-class:

- Zero dashboard and top-level mode navigation.
- Company OS: `/company`, tasks, agents, approvals, finance, legal, docs.
- Tasks and approvals as the canonical execution system.
- Vault/brain services as the second-brain and retrieval layer.
- Reachy and voice surfaces, because they are part of Zero's personal assistant identity.
- Meetings and calendar/email surfaces, because they feed memory and tasks.
- Character/content automation, if the content business remains active.
- Legion/Ada bridges, but accessed through narrow task-specific surfaces.

## Merge Candidates

These may be folded into fewer conceptual homes, but only after a review pass
with Adam. Until then, keep the existing surfaces reachable.

| Current surface | Target home | Why |
|---|---|---|
| AI Company page | `/company/agents` | Company agents are now part of Company OS, but the original dashboard remains useful as a workbench |
| LLC Guidance page | `/company/legal` | Florida SMLLC decision is documented, but the original guidance page remains useful as a workbench |
| Money Maker / CRM / Product planning | `/company/revenue` and `/company/product` | Revenue work should share one company pipeline |
| Research / Knowledge / Brain | Personal/Company docs and vault search | Three search surfaces are confusing unless they have clear jobs |
| Operations / Ecosystem / System Health / Architecture / QA | `Systems` mode | These are operator tools, not daily company work |
| Broad `zero-mcp` | Developer-only MCP | Keep, but use `zero-company` for Claude Co-Work |

## Retire Or Archive Candidates

No candidate in this table should be deleted, redirected, or hidden without
explicit approval. The default action is to keep the old page reachable and add
cross-links to the newer Company OS surface.

| Candidate | Decision | Timing |
|---|---|---|
| `frontend/src/pages/AiCompanyPage.tsx` | Keep as standalone workbench; cross-link with Company OS agents | Review with Adam |
| `frontend/src/pages/LlcGuidancePage.tsx` | Keep as standalone workbench; cross-link with Company OS legal | Review with Adam |
| `frontend/src/hooks/useLlcGuidanceApi.ts` | Keep while LLC Guidance page exists | Review with Adam |
| `/deep-research` page | Keep as standalone workbench backed by `/api/research/deep` | Review with Adam |
| `/api/llc-guidance` router/service/models | Keep while LLC Guidance page exists | Review with Adam |
| Notion integration | Keep dormant; do not make primary task system | Revisit when external collaboration requires it |
| Standalone `C:\code\company` app | Archive only | Done |
| Old dashboard references to Next/Supabase Company app | Keep as historical docs only | Done |

## Simplification Rules

1. New daily work gets a Company route only if it belongs in the operating loop.
2. Specialized workbenches can exist, but they should be linked under `Build`,
   `Systems`, or `Content`, not sprinkled through the primary nav.
3. Any old page that overlaps with Company OS should remain reachable until
   Adam explicitly approves redirecting, hiding, archiving, or deleting it.
4. Any MCP exposed to Claude Co-Work should be narrow and approval-aware.
5. Broad tools remain available for developer use but should not be the default
   agent surface.

## Next Simplification Sprint

- Replace static Company OS seed arrays with live Zero task/approval/vendor data.
- Seed company backlog records into Zero DB once, then stop relying on frontend
  constants for operating truth.
- Add a small `/company/docs/:slug` reader instead of only the index cards.
- Review each overlapping workbench one by one: AI Company Dashboard, LLC
  Guidance, Deep Research, Research, Knowledge, CRM, Money Maker, and Product
  planning.
- Collapse duplicate health pages into one Systems command center.
- Add a "show hidden/legacy pages" toggle only for developer/admin mode.
