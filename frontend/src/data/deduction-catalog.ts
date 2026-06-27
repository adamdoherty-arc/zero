/**
 * "Everything else you can claim" — a guided catalog of Schedule C deduction
 * categories for ADA AI LLC (single-member LLC, disregarded entity). Each item
 * maps to how it's tracked in Zero so the Tax & Deductions page can flag whether
 * it's been set up yet. Nothing here is tax advice — the CPA confirms at filing.
 *
 * Groups intentionally scoped to what the operator selected:
 *   - Software, cloud & fees
 *   - Vehicle, travel & meals
 *   - Education & professional services
 * (Retirement / self-employed health / QBI deliberately excluded — CPA-gated.)
 */

export type DeductionGroup =
  | 'Software, cloud & fees'
  | 'Vehicle, travel & meals'
  | 'Education & professional services'

export type DeductionAction = 'recurring' | 'asset' | 'worksheet' | 'manual'

export interface DeductionCatalogItem {
  key: string
  label: string
  group: DeductionGroup
  irs: string
  howTo: string
  action: DeductionAction
  /** Beancount accounts that, if seen in the ledger/recurring registry, mark this "set up". */
  accounts?: string[]
  /** Tax-summary line_item key that, if > 0, marks this "set up". */
  summaryKey?: string
}

export const deductionCatalog: DeductionCatalogItem[] = [
  // --- Software, cloud & fees ------------------------------------------------
  {
    key: 'software_non_ai',
    label: 'Software / SaaS (non-AI)',
    group: 'Software, cloud & fees',
    irs: 'Sch C L27a — other expenses',
    howTo: 'Add as a recurring expense with category "Software / SaaS".',
    action: 'recurring',
    accounts: ['Expenses:Software'],
  },
  {
    key: 'cloud_hosting',
    label: 'Cloud / hosting / domains',
    group: 'Software, cloud & fees',
    irs: 'Sch C L27a',
    howTo: 'Add cloud/hosting/domain bills as recurring (category "Cloud / hosting").',
    action: 'recurring',
    accounts: ['Expenses:Cloud'],
  },
  {
    key: 'insurance',
    label: 'Business insurance',
    group: 'Software, cloud & fees',
    irs: 'Sch C L15',
    howTo: 'Add the policy as a recurring expense (category "Business insurance").',
    action: 'recurring',
    accounts: ['Expenses:Insurance'],
  },
  {
    key: 'bank_fees',
    label: 'Bank / merchant / processing fees',
    group: 'Software, cloud & fees',
    irs: 'Sch C L10 / L27a',
    howTo: 'Categorize bank & Stripe/processor fees as "Bank / merchant fees" when reconciling.',
    action: 'manual',
    accounts: ['Expenses:Fees:Bank'],
  },
  // --- Vehicle, travel & meals ----------------------------------------------
  {
    key: 'vehicle',
    label: 'Business mileage / vehicle',
    group: 'Vehicle, travel & meals',
    irs: 'Sch C L9 — car & truck',
    howTo: 'Log business miles in the Vehicle worksheet (standard mileage rate).',
    action: 'worksheet',
    summaryKey: 'vehicle',
  },
  {
    key: 'travel',
    label: 'Business travel',
    group: 'Vehicle, travel & meals',
    irs: 'Sch C L24a',
    howTo: 'Categorize trips (airfare, lodging) as "Travel" when reconciling.',
    action: 'manual',
    accounts: ['Expenses:Travel'],
  },
  {
    key: 'meals',
    label: 'Business meals (50%)',
    group: 'Vehicle, travel & meals',
    irs: 'Sch C L24b — 50% limit',
    howTo: 'Categorize qualifying meals as "Meals". Counted at 50% in the summary.',
    action: 'manual',
    accounts: ['Expenses:Meals'],
  },
  // --- Education & professional services ------------------------------------
  {
    key: 'education',
    label: 'Education / courses / training',
    group: 'Education & professional services',
    irs: 'Sch C L27a',
    howTo: 'Add courses/books/training as recurring or one-off (category "Education / training").',
    action: 'recurring',
    accounts: ['Expenses:Education'],
  },
  {
    key: 'professional',
    label: 'Legal & accounting (CPA / attorney)',
    group: 'Education & professional services',
    irs: 'Sch C L17',
    howTo: 'Categorize CPA / attorney / registered-agent fees as "Professional services".',
    action: 'manual',
    accounts: ['Expenses:Professional', 'Expenses:Legal'],
  },
  {
    key: 'startup_costs',
    label: 'Startup / organizational costs (§195)',
    group: 'Education & professional services',
    irs: 'IRC §195 — up to $5k year one',
    howTo: 'Track formation/legal/registration costs incurred before go-live; CPA elects amortization.',
    action: 'manual',
    accounts: ['Expenses:Legal', 'Expenses:Professional'],
  },
]
