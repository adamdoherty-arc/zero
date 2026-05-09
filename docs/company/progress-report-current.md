---
owner: company
status: current
source_of_truth: company-progress-report
last_verified: 2026-05-03
verified_against:
  - Zero Company OS docs in C:\code\zero\docs\company
  - Zero live task database project_id=company
  - C:\code\zero\backend\app\routers\company_work_items.py
  - C:\code\zero\frontend\src\pages\CompanyOsPage.tsx
  - zero-company MCP daily brief
drift_policy: update after each weekly company review or major operating-system change
---

# Company Progress Report And Next Steps

This is the current operating report for ADA AI LLC Company OS. It
answers three questions:

1. What exists now?
2. What does the company still need?
3. How should AI help get the work done without crossing approval lines?

## Current State

As of the 2026-05-03 tightening pass, Zero is the active company operating
system and the Company OS is backed by live editable task records rather than
read-only seed examples.

| Area | State |
|---|---|
| Company home | `C:\code\zero` |
| Company docs | `C:\code\zero\docs\company` |
| Dashboard | Zero UI routes under `/company` |
| 24/7 operator | `/company/operator` plus Zero scheduler jobs |
| Task source of truth | Zero task database, `project_id=company` |
| Company tasks | 53 live tasks |
| Task status | 36 backlog, 17 blocked, 0 ready, 0 in progress, 0 done |
| High-priority tasks | 10, including 9 formation tasks and backlog triage |
| Open approvals | 11 operator approval gates surfaced in the Company Operator report |
| Company subagent packets | 5 completed: legal, finance, procurement, consulting, knowledge |
| Latest live smoke test | create/edit/complete/delete safe company task passed |
| AI connector | `zero-company` MCP for Claude Co-Work and safe task execution |
| Reachy check-ins | Company status, today, blockers, approvals, and overnight report |
| Obsidian | Mirror and review layer, not canonical task state |
| Notion | Deferred unless external collaboration requires it |

The most important operational gap is no longer basic task editability. The
remaining gap is operating discipline: the backlog is live and editable, but it
still needs to be triaged into a small active sprint with clear due dates,
owners, task dependencies, and approval resolutions.

Zero Company Operator now owns that execution-control loop. It can run
scheduled monitor ticks, overnight internal work, morning briefs, evening
reports, weekly reviews, and prompt-evaluation bridge runs while keeping
external/legal/financial/client/public actions behind approval gates.

## What The Company Still Needs

### 1. Formation And Compliance Completion

The company still needs the Florida LLC formation path executed in order:

- verify name on Sunbiz;
- choose registered agent;
- file Florida LLC;
- get EIN;
- sign operating agreement;
- sign IP assignment;
- open bank account and business credit card;
- get Duval Local Business Tax Receipt;
- schedule CPA and attorney consults.

These are high-priority tasks. Many are external, legal, government, financial,
or paid actions, so AI can prepare and checklist them but must not execute them
without approval.

### 2. Financial Operating Rails

The company needs CPA-ready records before spending grows:

- vendor and subscription registry;
- hardware asset register;
- receipt inbox;
- bookkeeping category map;
- home-office evidence log;
- monthly close checklist;
- CPA export format.

AI can draft category maps, receipt checklists, vendor summaries, and monthly
close reports. Purchases, cancellations, tax claims, and CPA-facing filings
require approval.

### 3. Task And Reporting Discipline

The Company OS needs a weekly rhythm:

- Monday: choose the active sprint and top 3 outcomes;
- daily: review next tasks, blockers, deadlines, and approvals;
- Friday: close completed work, update decisions, and write weekly review;
- monthly: reconcile vendors, subscriptions, assets, receipts, and tax evidence.

The dashboard and MCP support this, but the task board must be actively moved
from backlog into ready, in-progress, blocked, and done.

### 4. Consulting Revenue System

The company needs the first sellable consulting motion:

- ideal customer profile;
- service packages;
- discovery questionnaire;
- proposal and SOW templates;
- CRM pipeline;
- website update plan for `adamdoherty.com`;
- outreach and follow-up drafts.

AI can draft ICPs, packages, proposals, discovery questions, and follow-up
emails. Client-facing messages, published website changes, prices, and
contractual language require approval.

### 5. Product Studio Focus

The product side needs one thesis, not a pile of possible apps:

- choose first product thesis;
- write MVP spec;
- define pricing assumptions;
- define Stripe and tax requirements;
- build roadmap.

AI can compare product theses, draft specs, generate user stories, create
engineering tasks, and summarize tradeoffs. It should not make public product
claims or launch payment flows without approval.

### 6. Robotics And 3D Printing Controls

The robotics/3D-printing work needs safety and liability scaffolding before it
becomes commercial:

- printer and hardware inventory;
- consumables ledger;
- maintenance checklist;
- product-liability review task;
- insurance and warning-label review once physical products are sold.

AI can track materials, draft maintenance logs, prepare safety checklists, and
flag liability questions. Selling or delivering physical products requires
human review and, when appropriate, attorney/insurance input.

## How AI Should Help

AI should behave like an operations team, not an unchecked executive.

| Agent capability | Allowed by default | Requires approval |
|---|---|---|
| Read docs and summarize state | Yes | No |
| Create internal tasks | Yes | No |
| Update safe task status | Yes | No |
| Draft reports and checklists | Yes | No |
| Draft CPA/attorney packets | Yes | Before sending |
| Draft client emails/proposals | Yes | Before sending |
| Compare vendors/tools | Yes | Before purchase |
| Prepare filing steps | Yes | Before filing |
| Complete paid/legal/financial/public actions | No | Always |

Claude Co-Work should use the `zero-company` MCP connector with this loop:

1. Call `company_daily_brief`.
2. Call `company_list_tasks`.
3. Pick no more than three recommended next actions.
4. Create or update internal tasks as needed.
5. Queue approvals for high-risk work.
6. Produce a short end-of-session report.

## Reports That Exist Now

| Report or surface | Where | Use |
|---|---|---|
| Company dashboard | `/company` | Daily command center |
| Company operator | `/company/operator` | 24/7 heartbeat, overnight report, subagents, prompt lab, next steps |
| Company tasks | `/company/tasks` | Live task board |
| Company approvals | `/company/approvals` | Human approval queue |
| Company docs | `/company/docs` and `docs/company/INDEX.md` | Operating manual and retrieval index |
| Living state | `docs/company/living-state.md` | Runtime facts and drift |
| Master plan | `docs/company/master-plan.md` | North star and current priorities |
| MCP daily brief | `company_daily_brief` tool | AI-readable operating snapshot |
| This report | `docs/company/progress-report-current.md` | Current progress, gaps, and next steps |

## Latest Tightening Pass

- `/company/tasks` is now backed by the dedicated Company Work Items API,
  including create, edit, complete, reopen, duplicate, delete, seed import,
  filters, task detail drawer, and audit events.
- Task records now include domain, owner agent, due date, scheduled date, risk,
  approval state, approval id, tags, links, sort order, estimate points, and
  parent task id.
- The company MCP connector now uses `/api/company/work-items`, so Claude
  Co-Work sees the same approval-safe task behavior as the UI.
- Zero Company Operator now routes task writes through the same service and can
  execute a bounded number of safe internal subagent work packets per tick.
- Failed-but-safe internal company subagent work is now retried by the operator,
  and completed subagent tasks clear stale error text so agents do not look dead
  after successful retry.
- Safe internal subagent execution has a deterministic fallback packet path, so
  legal, finance, procurement, consulting, and knowledge agents can still
  produce useful checklists/reports if the LLM router or JSON parsing stumbles.
- Agent cards now report idle reason and last output when available, rather
  than merely looking inactive.
- Command Center approvals now prefer live operator approval gates before
  falling back to seed examples, so `/company` matches `/company/operator` and
  `/company/approvals`.
- High-risk company tasks are covered at both entry points: creation starts
  them blocked, and attempts to mark them done queue an approval gate instead
  of silently completing legal, financial, account, client, public, or tax work.
- Focused backend regression coverage now checks high-risk creation blocking,
  high-risk completion blocking, and normal low-risk completion.
- Live verification passed for `/api/company/work-items`,
  `/api/company/operator/status`, `/api/company/operator/today`, and manual
  operator ticks. The latest manual ticks completed all 5 current company
  subagent packets with no operator errors.
- Current external dependency warning: Legion at `http://localhost:8005` is
  unreachable from Zero right now, so prompt evaluation is queued/reported but
  not fully active until Legion is running.

## Feature Grades After 2026-05-03 Pass

| Feature | Grade | Current gap to 100 |
|---|---:|---|
| Task create/edit/complete | 82 | Add archive/bulk actions, stronger inline validation, and richer conflict handling. |
| Task data model | 75 | Expose parent/subtasks, richer links, dependencies, and event diffs in the UI. |
| Task views | 72 | Add due/calendar view, saved filters, and Formation Sprint board. |
| Reporting | 65 | Add charts and persisted readiness reports beyond the current cards. |
| Agent execution | 65 | Expand safe execution beyond formation packets and expose executor budgets. |
| Agent observability | 68 | Add agent drawer with run history, cost/latency, prompt variant, and next task. |
| Approval guardrails | 88 | Add approve/reject task-state resolution controls in the company UI. |
| Prompt/Legion eval | 52 | Start Legion locally, finish nightly grading, experiments, and promotion approvals. |
| Docs/context | 85 | Add stale-doc warnings when docs disagree with live tasks/reports. |
| Reachy/Claude Co-Work | 76 | Improve confirmed edits and spoken/report failure messages. |
| Finance/legal/domain modules | 35 | Convert static cards into editable registries linked to tasks. |
| UX polish/reliability | 70 | Add optimistic updates, mobile refinements, and auth diagnostics. |

## Clear Next Steps

### Next 24 Hours

1. Triage the 53 live company tasks.
2. Move the 9 formation tasks from backlog into ready or blocked.
3. Add due dates and approval requirements to the formation tasks.
4. Choose the registered-agent path.
5. Prepare a human approval packet for LLC filing.

### Next 7 Days

1. Complete or block every formation task.
2. Set up receipt inbox, vendor registry, and asset register.
3. Draft the operating agreement and IP assignment packet.
4. Draft the CPA and attorney consult agendas.
5. Define the first consulting offer and discovery workflow.

### Next 30 Days

1. Finish baseline legal/finance operating rails.
2. Launch the first version of the consulting pipeline.
3. Pick the first product thesis and write the MVP spec.
4. Decide which robotics/3D-printing assets are business assets.
5. Produce the first monthly CPA-readiness packet.

## Default Daily Question

Every day, Zero should be able to answer:

> What are the three company tasks Adam should handle today, what is blocked,
> and what can AI do before asking for approval?

If that answer is unclear, the task board needs triage before new work is added.
