---
owner: company
status: canonical
source_of_truth: finance-procurement-system
last_verified: 2026-05-05
verified_against:
  - C:\code\zero\docs\company\00-company\LLC_AND_COMPLIANCE.md
  - C:\code\zero\backend\app\db\migrations\202605020001_company_os.sql
  - C:\code\zero\docs\company\finance-setup-kit.md
drift_policy: CPA decisions override internal draft categories
---


> Active Zero context: migrated into `C:\code\zero\docs\company` on 2026-05-02. Zero is now the active app, database, UI, and reporting layer for ADA AI LLC Company OS. `C:\code\company` is retained as a legacy migration/archive folder.

# Finance And Procurement System

Finance starts manual/import-first. Live bank and card APIs are deferred until
there is a clear need, security model, and approval workflow.

## Records To Keep

| Record | Why it matters |
|---|---|
| Vendors | Vendor risk, renewals, contracts, W-9s |
| Subscriptions | Monthly burn, renewal dates, business purpose |
| Assets | Depreciation, bonus depreciation evidence, warranties |
| Receipts | Deduction support and CPA packet |
| Licenses | Software compliance and renewal control |
| Tax events | Filing deadlines and planning decisions |
| Decisions | Why major business/tax/compliance choices were made |
| FMV evidence | Comparable value support for personal assets entering ADA |
| IP schedules | Software ownership, license scope, and CPA/attorney review |

## ADA Finance Setup Rails

| Rail | Control |
|---|---|
| EIN | Confirm no existing EIN, apply through IRS only, save CP 575 |
| Banking | Open checking after EIN; classify first deposit as owner contribution |
| Card | Document personal guarantee, hard-pull likelihood, reporting policy, and autopay before applying |
| Books | Track AI/API, SaaS, cloud, software, hardware, robot, home-office, owner contributions, and reimbursements |
| Receipts | Attach receipt, business purpose, category, and paid-from account to every purchase |
| Home office | Measure exclusive business space and collect actual expense evidence for CPA |
| Assets | Track serials, photos, receipts, upgrades, business-use percent, placed-in-service date, and FMV evidence |
| Robot | ADA buys directly when possible; otherwise transfer at documented FMV |
| Software/IP | Use assignment or license schedule; attorney and CPA decide final treatment |
| CPA packet | Export P&L, receipts, subscriptions, assets, home office, transfer memos, and decisions needed |

## Monthly Close

1. Import or enter bank and card transactions.
2. Attach receipt evidence to every business purchase.
3. Confirm business purpose and category.
4. Update subscription registry and cancellation candidates.
5. Update hardware asset register with serials, invoices, business-use percent,
   placed-in-service date, and location.
6. Reconcile owner contributions and reimbursements.
7. Update home-office evidence and business-use percentages.
8. Review tax calendar and upcoming filings.
9. Export CPA packet snapshot.

## Procurement Policy

| Risk | Examples | Agent behavior |
|---|---|---|
| Low | Internal task, categorization, renewal reminder | May execute internally |
| Medium | Vendor research, quote comparison, draft purchase request | Draft approval |
| High | Paid subscription, hardware, contract, cancellation | Human approval |
| Critical | Government filing, tax election, legal agreement | Human approval and professional review |

## Existing Asset Transfer Policy

Existing computers, components, monitors, peripherals, robot hardware, and other
personal equipment may enter ADA only through an owner contribution memo, bill
of sale, or CPA-approved reimbursement. The value recorded must be documented
fair market value, supported by comparable listings, receipts, photos, serials,
and business-use percent.

Upgrades and configuration can support value only when the market evidence
supports it. Do not add unsupported markup for Adam's unpaid labor.

Templates:

- `templates/owner-equipment-transfer-memo.md`
- `templates/ip-assignment-schedule.md`
- `templates/bank-card-decision-log.md`
- `templates/cpa-setup-agenda.md`

## CPA Packet Standard

Each CPA packet should include:

- profit/loss summary;
- categorized transaction export;
- receipts and invoices;
- subscription register;
- hardware and equipment register;
- home-office evidence;
- mileage or travel records if any;
- business purpose notes for unusual purchases;
- decisions requiring CPA review.


