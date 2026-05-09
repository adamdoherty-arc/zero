---
owner: company
status: canonical
source_of_truth: task-management-system
last_verified: 2026-05-02
verified_against:
  - C:\code\company\supabase\migrations\202605020001_company_os.sql
  - C:\code\company\apps\dashboard\src\app\page.tsx
  - C:\code\company\docs\40-operations\PROJECT_STRUCTURE.md
drift_policy: human-owned for source-of-truth changes; agents may propose workflow refinements
---

# Task Management System

## Decision

Make **Company OS tasks in Supabase, surfaced through the dashboard, the
canonical task-management system**.

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
| Supabase Postgres | Structured task, event, approval, and link records | Yes |
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

## Notion Trigger

Add Notion only after one of these is true:

- a client needs a shared task board;
- a contractor needs a workspace without access to repo/Supabase;
- public-facing project tracking becomes part of a consulting offer;
- Notion becomes an acquisition or delivery channel.

Until then, Notion should be an export target, not the operating core.
