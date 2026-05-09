---
owner: company
status: canonical
source_of_truth: company-operating-model
last_verified: 2026-05-02
verified_against:
  - C:\code\zero\README.md
  - C:\code\zero\docs\company\20-operating-system\AGENT_COMPANY_STRUCTURE.md
  - C:\code\zero\docs\company\20-operating-system\DASHBOARD_SPEC.md
drift_policy: human-owned; Legion may propose updates, not auto-apply
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Company Operating Model

**ADA AI LLC** is the formed company identity. Public positioning remains
Adam Doherty Applied AI, with ADA also standing for Automated Decision Agent.
The existing `adamdoherty.com` domain remains Adam's personal authority and
consulting site while `adappliedai.com` becomes the company/product domain.

The company combines three lines of work:

1. AI adoption consulting for small businesses, founders, and operators.
2. Software products that turn internal AI operating patterns into sellable
   tools.
3. A future robotics and 3D-printing lab for prototypes, internal hardware
   workflows, and carefully reviewed physical products.

## 2026 Entity Stance

The best starting structure is a Florida single-member LLC taxed by default as a
disregarded entity. It is simple, gives a state-law liability shield, and lets
valid operating losses flow to Adam's personal return subject to federal limits.

S-Corp status is deferred. With a high W-2 income already covering the Social
Security wage base, the marginal S-Corp benefit is likely too small in a loss or
low-profit year to justify payroll, 1120-S filing, reasonable compensation
documentation, and administrative overhead.

Options trading stays outside this operating LLC. If trader tax status and a
Section 475(f) election become serious, that belongs in a separate specialist
CPA decision path.

## Source-of-Truth Model

| Layer | Canonical role |
|---|---|
| Repo | Operating manual, migrations, app code, task seeds, decisions |
| Zero Postgres | Structured state for tasks, agents, approvals, vendors, assets, CRM, products, robotics |
| Dashboard | Daily operating surface, task cockpit, and approval queue |
| Legion | Implementation project/sprint/task execution status |
| Obsidian | Mirrored summaries, weekly reviews, backlinks, durable thinking |

The repo and database are canonical. Obsidian receives summaries and source
links; it does not replace the structured operating record. Notion is deferred
until the company needs a shared external task board for clients or contractors.

## Company Departments

| Department | Primary agents | Dashboard surface |
|---|---|---|
| Executive operations | CEO / Chief-of-Staff | Command center, daily/weekly reports |
| Finance and CPA readiness | Finance / CPA Ops, Procurement | Subscriptions, receipts, assets, tax calendar |
| Legal and compliance | Legal / Compliance, Security / Risk | LLC checklist, contract inventory, approval gates |
| Consulting revenue | Consulting Revenue, Delivery, Marketing | CRM pipeline, offers, proposals, client projects |
| Product studio | Product, Engineering, LLM Ops | Product ideas, roadmaps, releases, evals |
| Robotics lab | Robotics / 3D Lab, Procurement, Security | Printers, materials, print jobs, safety reviews |
| Knowledge operations | Knowledge / Second-Brain | Vault sync, decisions, backlinks, weekly reviews |

## Task Management Decision

Zero Company OS tasks in the Zero database, surfaced in the Company dashboard, are the canonical task
system. Legion owns engineering execution tasks. Obsidian owns context and
weekly review. Notion is an optional future export.

## Approval Policy

Agents can automate low-risk internal work:

- categorize expenses and receipts;
- draft tasks, reports, proposals, and checklists;
- update internal run logs;
- summarize docs into Obsidian;
- reconcile read-only dashboard state;
- create approval records.

Agents must stop for approval before:

- spending money or changing paid subscriptions;
- filing LLC, tax, BOI, license, bank, or government paperwork;
- making tax elections or depreciation claims;
- sending client-facing messages, proposals, contracts, invoices, or website
  updates;
- making legal, compliance, investment, or financial advice claims;
- changing production infrastructure, credentials, or security posture;
- selling or delivering physical products where liability could attach.

## Operating Cadence

| Cadence | Output |
|---|---|
| Daily | Review command center, blocked tasks, approvals, next deadlines |
| Weekly | Close task board, update Obsidian effort note, refresh decision log |
| Monthly | Reconcile vendors, receipts, assets, subscription renewals, CPA evidence |
| Quarterly | Review tax estimates, product bets, consulting pipeline, risk controls |
| Annual | Florida annual report, LBTR renewal, entity/S-Corp review, insurance review |

## First Milestone

Acceptance for the first milestone: Adam can open one dashboard and see the next
tasks, agent status, subscriptions/assets, tax/legal deadlines, Legion project
status, and links back to the sourced operating manual.


