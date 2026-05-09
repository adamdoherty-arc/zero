---
owner: company
status: canonical
source_of_truth: agent-company-structure
last_verified: 2026-05-02
verified_against:
  - C:\code\zero\docs\company\00-company\COMPANY_OPERATING_MODEL.md
  - C:\code\zero\frontend\src\lib\company-data.ts
drift_policy: agents may propose role changes; human approves permission changes
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Agent Company Structure

The Company OS treats agents as internal departments with explicit permissions,
run logs, approvals, and measurable operating surfaces. The goal is not to let
agents run the company unsupervised. The goal is to make every repeatable
company function visible, delegated, and gated.

## Permission Tiers

| Tier | Agent may do |
|---|---|
| Observe | Read approved sources, summarize, report drift |
| Draft | Create drafts, checklists, task records, and approval requests |
| Recommend | Rank options, prepare decision memos, suggest next actions |
| Execute low-risk | Update internal records, categorize, create reminders, sync summaries |
| Human approval | Purchases, filings, legal/tax/client/public/security/financial actions |

## Org Chart

| Agent | Mission | Default tier | Human approvals required for |
|---|---|---|---|
| CEO / Chief-of-Staff | Route work, produce reports, maintain operating cadence | Recommend | Company priorities, external actions |
| Finance / CPA Ops | Prepare books, receipt reviews, tax calendar, CPA packet | Draft | Tax positions, filings, bank/card actions |
| Legal / Compliance Ops | LLC checklist, contracts, privacy/ToS queue, attorney packet | Draft | Filings, public legal claims, contracts |
| Procurement / Asset | Subscriptions, hardware, licenses, renewals, warranties | Execute low-risk | Purchases, cancellations, vendor commitments |
| Consulting Revenue | ICP, offers, outreach lists, proposal drafts, CRM follow-up | Draft | Client messages, proposals, pricing commitments |
| Delivery | Client onboarding, notes, deliverables, implementation checklists | Draft | Client deliverables and scope changes |
| Product | Product strategy, specs, roadmap, feedback loops | Recommend | Public roadmap, pricing, regulated positioning |
| Engineering | Architecture, implementation sprints, tests, deployment readiness | Execute low-risk | Production deploys, secrets, paid services |
| LLM Ops | Model/provider monitoring, costs, routing, evals | Recommend | Paid model changes, data policy changes |
| Knowledge / Second-Brain | Vault summaries, decisions, backlinks, weekly review | Execute low-risk | Deleting or rewriting human-authored notes |
| Marketing / Content | Website plan, case studies, LinkedIn/blog drafts | Draft | Public publishing |
| Robotics / 3D Lab | Printer inventory, materials, print jobs, maintenance, safety | Draft | Selling/delivering physical products |
| Security / Risk | Secrets, access reviews, OWASP/NIST controls, incident log | Recommend | Credential rotation, access changes, disclosures |

## Run Log Standard

Each agent run should record:

- agent key and version;
- trigger source;
- input sources;
- output summary;
- tasks created or updated;
- approvals created;
- risk level;
- whether any action was blocked;
- prompt run ID or variant ID when a prompt was used;
- cost and runtime when available.

## Zero Company Operator

Zero Company Operator is the CEO / Chief-of-Staff control loop. It checks in on
all company subagents, creates internal work packets, records run logs, and
publishes morning, evening, overnight, and weekly reports.

Default scheduled behavior:

- every 15 minutes: heartbeat monitor;
- nightly: safe internal work and Formation Sprint triage;
- morning: "what should Adam do today?";
- evening: progress and blockers;
- weekly: company review and next sprint;
- nightly prompt bridge: grade company prompt runs and maintain experiments.

The operator can delegate low-risk internal planning to the subagents listed
above. It cannot make purchases, file documents, create accounts, contact
clients, publish content, change credentials, or make legal/tax decisions
without an approval gate.

## Ruflo Evaluation Boundary

Ruflo may be studied as an optional planning, memory, and run-observability
pattern source for company subagents. It is not an agent department, permission
tier, or source of truth. During evaluation it must run only in
`C:\code\sandbox\ruflo-eval`, must not register broad MCP tools, and must not
write Zero, Legion, Ada, vault, broker, credential, or production project files.

If a future adapter is approved, it starts disabled behind
`ZERO_COMPANY_RUFLO_ENABLED=false` and only records coordination data unless a
human explicitly authorizes a narrower capability.

## Guardrail Test

Any high-risk or critical action must create an approval record and must not be
marked auto-executed. This is enforced in the Supabase approval schema and shown
as a first-class dashboard queue.


