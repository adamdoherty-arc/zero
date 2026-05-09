---
owner: company
status: canonical
source_of_truth: agent-company-structure
last_verified: 2026-05-02
verified_against:
  - C:\code\company\docs\00-company\COMPANY_OPERATING_MODEL.md
  - C:\code\company\apps\dashboard\src\lib\company-data.ts
drift_policy: agents may propose role changes; human approves permission changes
---

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
- whether any action was blocked.

## Guardrail Test

Any high-risk or critical action must create an approval record and must not be
marked auto-executed. This is enforced in the Supabase approval schema and shown
as a first-class dashboard queue.
