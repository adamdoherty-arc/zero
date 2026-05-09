---
owner: company
status: canonical
source_of_truth: finance-procurement-system
last_verified: 2026-05-02
verified_against:
  - C:\code\company\docs\00-company\LLC_AND_COMPLIANCE.md
  - C:\code\company\supabase\migrations\202605020001_company_os.sql
drift_policy: CPA decisions override internal draft categories
---

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

## Monthly Close

1. Import or enter bank and card transactions.
2. Attach receipt evidence to every business purchase.
3. Confirm business purpose and category.
4. Update subscription registry and cancellation candidates.
5. Update hardware asset register with serials, invoices, business-use percent,
   placed-in-service date, and location.
6. Review tax calendar and upcoming filings.
7. Export CPA packet snapshot.

## Procurement Policy

| Risk | Examples | Agent behavior |
|---|---|---|
| Low | Internal task, categorization, renewal reminder | May execute internally |
| Medium | Vendor research, quote comparison, draft purchase request | Draft approval |
| High | Paid subscription, hardware, contract, cancellation | Human approval |
| Critical | Government filing, tax election, legal agreement | Human approval and professional review |

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
