---
owner: company
status: canonical
source_of_truth: project-structure
last_verified: 2026-05-02
verified_against:
  - C:\code\zero\README.md
  - C:\code\zero\docs\company\master-plan.md
  - C:\code\zero\docs\company\plans\README.md
drift_policy: update after docs, app, database, or plan structure changes
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Project Structure

`C:\code\zero` is the business, architecture, UI, and task source of truth for
ADA AI LLC. The former `C:\code\company` project is now a legacy
archive and provenance source. Zero contains two merged layers:

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
| `README.md` | One-page Zero entry point and run instructions | Yes |
| `frontend/` | Zero UI, including `/company` Company OS surfaces | Yes |
| `backend/` | Zero API, database models, approvals, and company context endpoints | Yes |
| `docs/company/` | Company operating manual, LLC docs, architecture, task system, sources | Yes |
| `docs/company/plans/` | Historical imported plans and active rollout archive | Searchable context |
| `.agents/skills/ecosystem-audit/` | Local audit skill now reading Zero company docs | Operational support |
| `workspace/` | Runtime workspace, generated reports, and local operating state | Generated |

## Promotion Rule

Plans and strategy notes become company knowledge only when promoted into a
canonical doc, database seed, dashboard surface, or decision record.

Use this flow:

```text
archive plan or strategy note
  -> summarize into MERGED_PLAN_INDEX.md
  -> decide whether it changes company direction
  -> update the right canonical doc
  -> add or update tasks in Zero database / dashboard seed
  -> mirror summary into Obsidian weekly review
```

## Source-Of-Truth Resolution

| Conflict | Winner |
|---|---|
| Runtime fact vs doc | Runtime fact, then update `LIVING_STATE.md` |
| Safety policy vs plan | `MANDATE.md` |
| System topology vs old plan | `ARCHITECTURE.md` plus live config |
| Business operating choice vs old plan | `COMPANY_OPERATING_MODEL.md` or `LLC_AND_COMPLIANCE.md` |
| Task status vs note checkbox | Zero Company OS database / dashboard |
| Human reflection vs structured task | Obsidian note for reflection, Company OS task for action |

## Current Integration Map

| System | Company role |
|---|---|
| Zero Company OS | Business task source of truth and executive dashboard |
| Legion | Implementation sprint/task execution and cross-project operational engine |
| Obsidian | Second-brain summaries, weekly reviews, decisions, and backlinks |
| Notion | Optional future external/collaborative task mirror, not canonical now |
| Zero | Personal context, chief-of-staff surface, and company operating UI |
| Ada | Financial intelligence product path with approval-gated execution |
| Shared infra | Model routing, local/cloud LLM, embeddings, MCP, observability substrate |


