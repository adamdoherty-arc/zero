---
owner: company
status: canonical
source_of_truth: task-management-system
last_verified: 2026-05-03
verified_against:
  - C:\code\zero\backend\app\migrations\versions\044_company_work_items.py
  - C:\code\zero\backend\app\routers\company_work_items.py
  - C:\code\zero\backend\app\services\company_work_item_service.py
  - C:\code\zero\frontend\src\pages\CompanyOsPage.tsx
drift_policy: human-owned for source-of-truth changes; agents may propose workflow refinements
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Task Management System

## Decision

Make **Zero Company OS tasks in the Zero database, surfaced through the Company
dashboard, the canonical task-management system**.

Use Obsidian for thinking, weekly reviews, source notes, and backlinks. Use
Legion for implementation sprint execution. Defer Notion until there is a real
external collaboration need.

## Why

The company needs task records that agents can safely read and update with:

- typed status, priority, risk, owner, due date, and source fields;
- approval gates for high-risk actions;
- links to Legion, Obsidian, Notion, docs, and receipts;
- audit events;
- dashboard views for Adam's daily operating loop.

Markdown checkboxes alone are too flexible for compliance and agent operations.
Notion is excellent for collaboration, but its API and permissions model add a
cloud dependency before the company needs one.

## System Roles

| System | Role | Source of truth? |
|---|---|---|
| Company OS dashboard | Daily task cockpit, Kanban, approvals, next actions | Yes |
| Zero Postgres | Structured task, event, approval, and link records | Yes |
| Legion | Engineering implementation sprints and execution telemetry | For engineering execution only |
| Obsidian | Weekly review, decisions, meeting notes, source-backed context | No, mirror and context |
| Notion | Optional future client/shared workspace mirror | No |

## Workflow

1. Capture ideas in Obsidian, dashboard quick-add, or Legion.
2. Promote real work into Company OS tasks.
3. Assign domain, sprint, owner agent, risk, approval requirement, and due date.
4. Execute engineering work in Legion when code is involved.
5. Mirror weekly summaries back to Obsidian.
6. Export a Notion database only when collaboration with clients or contractors
   requires it.

## Zero Operator Task Loop

Zero Company Operator uses the same Zero task records as the canonical company
board. It may:

- create internal company tasks from reports, docs, or Reachy-confirmed voice
  commands;
- move low-risk internal tasks from backlog to ready;
- mark legal, financial, account, client, public, or filing-related work as
  blocked until Adam approves;
- assign internal planning packets to company subagents;
- include task progress in morning, evening, overnight, and weekly reports.

The operator must not mark a high-risk external task done merely because it
prepared a checklist. Completion of filings, purchases, account setup, client
messages, and public changes remains human-owned or approval-owned.

Implementation guardrail: Company Operator task APIs block high-risk task
creation into `blocked` status and convert high-risk "mark done" attempts into
approval requests. The dashboard also labels `Done` as approval-gated for those
tasks so the interface matches the backend rule.

## Task Record Minimum

Each task should have:

- title;
- domain;
- sprint;
- status;
- owner agent;
- priority;
- risk level;
- due date when relevant;
- source system;
- external links;
- approval requirement;
- latest event.

## UI Priority

The dashboard should open to task management first. The task view should show:

- next actions;
- overdue and blocked tasks;
- approval-gated tasks;
- formation and compliance tasks;
- Legion-linked engineering tasks;
- source links into docs, Obsidian, or Notion.

`/company/operator` provides the daily command layer around the task board:
heartbeat, overnight accomplishments, active subagents, blocked work,
approvals, prompt evaluations, and the current "what should I work on today?"
answer.

## Current Implementation State

As of 2026-05-03, the active company task surface is the Company Work Items API:

- `/api/company/work-items` lists, creates, and edits live company tasks;
- `/api/company/work-items/import-seed` imports `docs/company/task-backlog.md`
  once into editable Zero tasks;
- `/api/company/work-items/{task_id}/complete` completes safe tasks and queues
  approvals for high-risk completion;
- `/api/company/work-items/{task_id}/events` exposes the audit trail.

The UI no longer treats seed tasks as the working board. If the Zero database
has no live `project_id=company` tasks, `/company/tasks` shows an import action
and the seed cards only as read-only examples.

Claude Co-Work should use `company_list_tasks`, `company_create_task`,
`company_update_task`, and `company_complete_task`; those MCP tools now route
through the Company Work Items API instead of the generic `/api/tasks` endpoint.

## Feature Scorecard

| Feature | 2026-05-03 score | Path to 100 |
|---|---:|---|
| Task create/edit/complete | 82 | Add archive/bulk actions, stronger inline validation, and richer conflict handling. |
| Task data model | 75 | Add subtasks UI, saved views, richer link records, dependencies, and event diffs in the drawer. |
| Task views | 72 | Add calendar/due-date view, saved filters, and Formation Sprint dedicated board. |
| Reporting | 65 | Persist more report types and add charts for WIP, blocked age, throughput, readiness. |
| Agent execution | 65 | Expand safe executor adapters, add budgets per agent, and show task outputs inline. |
| Agent observability | 68 | Add agent detail drawer, cost/latency history, prompt variant, and next eligible task. |
| Approval guardrails | 88 | Add approve/reject resolution controls linked back to task state. |
| Prompt/Legion eval | 52 | Start Legion locally, complete nightly grading, variant comparison, and approval-gated prompt promotion. |
| Docs/context | 85 | Add stale-doc warnings from live task/report changes. |
| Reachy/Claude Co-Work | 76 | Add richer confirmation flows and clearer spoken failure responses. |
| Finance/legal/domain modules | 35 | Convert static registries into editable tables linked to tasks and approvals. |
| UX polish/reliability | 70 | Add optimistic drag/drop, mobile task drawer refinements, and auth diagnostics. |

## Notion Trigger

Add Notion only after one of these is true:

- a client needs a shared task board;
- a contractor needs a workspace without access to repo or Zero;
- public-facing project tracking becomes part of a consulting offer;
- Notion becomes an acquisition or delivery channel.

Until then, Notion should be an export target, not the operating core.


