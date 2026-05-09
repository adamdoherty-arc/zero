---
owner: company
status: canonical
source_of_truth: project-structure
last_verified: 2026-05-02
verified_against:
  - C:\code\company\README.md
  - C:\code\company\docs\10-constitution\MASTER_PLAN.md
  - C:\code\company\plans\README.md
drift_policy: update after docs, app, database, or plan structure changes
---

# Project Structure

`C:\code\company` is the business and architecture source of truth for Doherty
Applied AI LLC. It now contains two merged layers:

1. The **company operating layer**: LLC, finance, procurement, consulting,
   product, robotics, task management, approvals, dashboard, and source registry.
2. The **agentic architecture layer**: Zero, Legion, Ada, Reachy, shared infra,
   model routing, MCP, memory, approval tiers, and 24/7 operations.

These layers should not compete. The company layer explains how the business is
run. The architecture layer explains the technical system the company owns and
operates.

## Current Folder Roles

| Path | Role | Canonical? |
|---|---|---|
| `README.md` | One-page entry point and run instructions | Yes |
| `apps/dashboard/` | Company OS UI and Legion bridge | Yes |
| `supabase/` | Company OS structured state contract and seeds | Yes |
| `docs/00-company/` | LLC, governance, company operating model | Yes |
| `docs/10-constitution/` | Cross-project policy, master plan, architecture | Yes |
| `docs/20-operating-system/` | Agent org, dashboards, task system, finance, second brain | Yes |
| `docs/20-products/` | Ada, Zero, Legion, and platform product portfolio | Yes |
| `docs/30-strategy/` | Long-form imported strategy source material | Context |
| `docs/40-operations/` | Living state, project structure, plan index, validation facts | Yes |
| `docs/50-research/` | Source registry | Yes |
| `plans/active/` | Current execution plan | Yes, until promoted |
| `plans/archive/` | Historical imported plans | Searchable context |
| `.agents/skills/` | Local audit and agent skills | Operational support |
| `scripts/` | Validation and operating scripts | Yes |

## Promotion Rule

Plans and strategy notes become company knowledge only when promoted into a
canonical doc, database seed, dashboard surface, or decision record.

Use this flow:

```text
archive plan or strategy note
  -> summarize into MERGED_PLAN_INDEX.md
  -> decide whether it changes company direction
  -> update the right canonical doc
  -> add or update tasks in Supabase / dashboard seed
  -> mirror summary into Obsidian weekly review
```

## Source-Of-Truth Resolution

| Conflict | Winner |
|---|---|
| Runtime fact vs doc | Runtime fact, then update `LIVING_STATE.md` |
| Safety policy vs plan | `MANDATE.md` |
| System topology vs old plan | `ARCHITECTURE.md` plus live config |
| Business operating choice vs old plan | `COMPANY_OPERATING_MODEL.md` or `LLC_AND_COMPLIANCE.md` |
| Task status vs note checkbox | Company OS database / dashboard |
| Human reflection vs structured task | Obsidian note for reflection, Company OS task for action |

## Current Integration Map

| System | Company role |
|---|---|
| Company OS | Business task source of truth and executive dashboard |
| Legion | Implementation sprint/task execution and cross-project operational engine |
| Obsidian | Second-brain summaries, weekly reviews, decisions, and backlinks |
| Notion | Optional future external/collaborative task mirror, not canonical now |
| Zero | Personal context and chief-of-staff surface |
| Ada | Financial intelligence product path with approval-gated execution |
| Shared infra | Model routing, local/cloud LLM, embeddings, MCP, observability substrate |
