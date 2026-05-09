---
owner: company
status: canonical
source_of_truth: zero-company-operator
last_verified: 2026-05-03
verified_against:
  - C:\code\zero\backend\app\services\company_operator_service.py
  - C:\code\zero\backend\app\routers\company_operator.py
  - C:\code\zero\frontend\src\pages\CompanyOsPage.tsx
drift_policy: engineering-owned for implementation; human approval required for autonomy expansion
---

# Zero Company Operator

Zero Company Operator is the supervised 24/7 manager for ADA AI LLC.
It lives inside Zero, not as a separate app. The operator reads company docs,
Zero tasks, agent assignments, approval gates, scheduler audit logs, Legion
health, and prompt-run outcomes, then turns that state into reports, safe work
packets, task updates, and approval requests.

## Cadence

| Loop | Schedule | Purpose |
|---|---:|---|
| Live monitor | Every 15 minutes | Heartbeat, blockers, approvals, next-step snapshot |
| Overnight work | 1:00 a.m. daily | Internal work packets, formation triage, approval queueing |
| Morning brief | 6:45 a.m. daily | What Adam should do today |
| Evening report | 8:30 p.m. daily | Progress, stuck work, next approvals |
| Weekly review | Friday 4:30 p.m. | Company review and next sprint |
| Prompt eval bridge | 2:15 a.m. daily | Grade company prompt runs and maintain experiments |

## Autonomy Boundary

Allowed without approval:

- summarize company state;
- create or edit internal Zero tasks;
- prepare docs, checklists, reports, and packets;
- delegate internal planning work to subagents;
- record prompt runs and queue prompt evaluations;
- update internal status logs.

Requires approval:

- purchases, subscriptions, or cancellations;
- Sunbiz, EIN, LBTR, tax, legal, or government filings;
- bank, credit-card, Stripe, account, or credential changes;
- CPA, attorney, insurance, vendor, or client commitments;
- public website, LinkedIn, email, proposal, or client communications.

## First Goal

The first measurable success is the Formation Sprint:

1. triage LLC formation tasks into ready, blocked, and done;
2. queue approval gates for legal, tax, financial, and account actions;
3. assign packet-prep work to Legal, Finance, Procurement, Consulting, and
   Knowledge subagents;
4. produce an overnight report and a morning brief with clear next steps.

## Interfaces

The dashboard entry point is `/company/operator`. Reachy can answer short voice
queries about company status, overnight work, today, blockers, approvals, and
LLC formation state. Voice task edits require confirmation before writing.

The operator API lives at `/api/company/operator/*` and exposes status,
reports, runs, overnight state, today state, manual tick, report generation,
pause/resume, task edits, approval queueing, and subagent assignment.

Task safety is enforced in the API. Newly created high-risk company tasks are
blocked immediately, and attempts to mark high-risk tasks done create approval
requests instead of completing the task.

## 2026-05-03 Operations Upgrade

Zero Company Operator now delegates company task mutations through the Company
Work Items service, not the generic task API. That gives the operator the same
approval behavior as the dashboard, Reachy, and Claude Co-Work:

- company tasks are created under `project_id=company`;
- domain, owner agent, due date, risk, approval state, tags, links, sort order,
  and estimates are first-class task fields;
- every create/edit/block/approval/complete action can write a
  `company_task_events` audit entry;
- high-risk completion attempts queue `company_work_item_completion_gate`
  approvals;
- scheduled ticks can execute a bounded number of safe internal `agent_tasks`
  when their context allows `autonomy=internal_work`;
- scheduled ticks retry failed safe internal company `agent_tasks` before
  treating them as stale failures;
- safe internal company `agent_tasks` have a deterministic checklist/report
  fallback if the LLM router, provider, or structured JSON parsing path fails;
- skipped agent work records an idle reason such as approval required,
  dependency blocked, budget paused, failed last run, or no eligible task.

Live verification on 2026-05-03 completed all 5 current Formation Sprint
subagent packets: Legal/Compliance, Finance/CPA, Procurement/Asset,
Consulting Revenue, and Knowledge/Second-Brain. The next operator milestone is
an agent detail drawer and richer report charts so Adam can see not just that an
agent is idle, but exactly what it last tried, what it cost, which prompt
variant ran, and what task it should take next.
