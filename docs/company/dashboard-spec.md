---
owner: company
status: canonical
source_of_truth: dashboard-spec
last_verified: 2026-05-02
verified_against:
  - C:\code\zero\frontend
  - C:\code\zero\backend\app\db\migrations\202605020001_company_os.sql
drift_policy: engineering-owned; product and approval changes require review
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Dashboard Spec

The dashboard is the daily control surface for the company. It should open
directly to operating state, not a marketing page.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Zero React/Vite UI, TypeScript |
| Styling | Tailwind CSS with restrained operational UI |
| Components | Local components with Radix/shadcn-compatible patterns |
| Data | Zero Postgres plus seeded TypeScript fallback during migration |
| Charts | Existing Zero chart/components stack |
| Server integration | Zero API reads company docs/context and Legion read-only status |
| Future auth | Existing Zero auth and approval contracts |

## Views

| View | Purpose |
|---|---|
| Operator | 24/7 Zero heartbeat, overnight report, active subagents, prompt experiments, approvals, and today plan |
| Task cockpit | Next actions, task filters, Kanban, approvals, blocked work |
| Executive command center | Cash/runway placeholder, open approvals, active sprints, next deadlines, Legion status |
| Agent activity | Agent org chart, recent runs, blocked work, autonomy level, approval queue |
| Tasks | Kanban by status with domain, sprint, owner, risk, due date |
| Finance / CPA readiness | Receipts, subscriptions, assets, tax calendar, deduction evidence |
| Growth lab | Consulting pipeline, product roadmap, robotics/3D-printing jobs |

## Legion Integration

The dashboard should call Zero API endpoints that read:

- `GET http://localhost:8005/livez`;
- `GET http://localhost:8005/managed-projects`;
- `GET http://localhost:8005/sprints/?project_id={companyProjectId}` when the
  company project exists.

The dashboard treats Legion as read-only. Sprint creation and project
registration happen through scripts or explicit human-run commands.

## Operator Dashboard

`/company/operator` is the live command center for the always-on company loop.
It shows:

- Zero heartbeat and pause/resume state;
- overnight accomplishments and recent operator runs;
- active subagents, assignments, blocked reasons, and cost;
- editable company tasks and approval-gated blockers;
- Formation Sprint progress;
- prompt-run grading status and Legion evaluation health;
- the answer to "what should Adam work on today?"

The operator may create reports, edit internal tasks, delegate internal
planning work, and queue approvals. It must not execute external, legal,
financial, client, account, or public actions.

## Data Model

Zero company data model:

`tasks`, `sprints`, `agents`, `agent_runs`, `approvals`, `decisions`,
`documents`, `vendors`, `subscriptions`, `assets`, `receipts`, `licenses`,
`tax_events`, `crm_contacts`, `opportunities`, `client_projects`,
`product_ideas`, `robotics_assets`, `print_jobs`, `inventory_items`.

## Acceptance Criteria

- dashboard renders on desktop and mobile;
- `/company/operator` renders heartbeat, overnight report, subagents, prompt
  lab status, blockers, approvals, and next steps;
- high-risk approvals are visible without scrolling through docs;
- task cockpit is the primary view and exposes formation, finance, consulting,
  product, robotics, and Legion work;
- Finance view shows subscriptions, assets, tax events, and evidence status;
- Legion panel shows online/offline state without breaking the dashboard;
- sourced operating manual is present in `docs/company/`.


