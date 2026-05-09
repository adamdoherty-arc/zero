---
owner: company
status: canonical
source_of_truth: dashboard-spec
last_verified: 2026-05-02
verified_against:
  - C:\code\company\apps\dashboard
  - C:\code\company\supabase\migrations\202605020001_company_os.sql
drift_policy: engineering-owned; product and approval changes require review
---

# Dashboard Spec

The dashboard is the daily control surface for the company. It should open
directly to operating state, not a marketing page.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js App Router, TypeScript |
| Styling | Tailwind CSS with restrained operational UI |
| Components | Local components with Radix/shadcn-compatible patterns |
| Data | Seeded TypeScript data now; Supabase query layer next |
| Charts | Recharts |
| Server integration | Next route handler for Legion read-only status |
| Future auth | Supabase auth-ready records |

## Views

| View | Purpose |
|---|---|
| Task cockpit | Next actions, task filters, Kanban, approvals, blocked work |
| Executive command center | Cash/runway placeholder, open approvals, active sprints, next deadlines, Legion status |
| Agent activity | Agent org chart, recent runs, blocked work, autonomy level, approval queue |
| Tasks | Kanban by status with domain, sprint, owner, risk, due date |
| Finance / CPA readiness | Receipts, subscriptions, assets, tax calendar, deduction evidence |
| Growth lab | Consulting pipeline, product roadmap, robotics/3D-printing jobs |

## Legion Integration

The dashboard calls `GET /api/legion`, which reads:

- `GET http://localhost:8005/livez`;
- `GET http://localhost:8005/managed-projects`;
- `GET http://localhost:8005/sprints/?project_id={companyProjectId}` when the
  company project exists.

The dashboard treats Legion as read-only. Sprint creation and project
registration happen through scripts or explicit human-run commands.

## Data Model

Supabase tables:

`tasks`, `sprints`, `agents`, `agent_runs`, `approvals`, `decisions`,
`documents`, `vendors`, `subscriptions`, `assets`, `receipts`, `licenses`,
`tax_events`, `crm_contacts`, `opportunities`, `client_projects`,
`product_ideas`, `robotics_assets`, `print_jobs`, `inventory_items`.

## Acceptance Criteria

- dashboard renders on desktop and mobile;
- high-risk approvals are visible without scrolling through docs;
- task cockpit is the primary view and exposes formation, finance, consulting,
  product, robotics, and Legion work;
- Finance view shows subscriptions, assets, tax events, and evidence status;
- Legion panel shows online/offline state without breaking the dashboard;
- sourced operating manual is present in `docs/`.
