import { useQuery } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'

export interface TaxSummaryLineItem {
  key: string
  label: string
  amount: number
  source: string
  detail?: Record<string, number>
  note?: string | null
  missing_fields?: string[]
}

export interface TaxSummary {
  year: number
  entity: string
  line_items: TaxSummaryLineItem[]
  total_deductible: number
  marginal_federal_pct: number
  include_se: boolean
  est_income_tax_saved: number
  est_se_tax_saved: number
  est_total_tax_saved: number
  se_note: string
  disclaimer: string
}

export interface DeductionsSummary {
  cell_phone: { monthly: number | null; business_pct: number | null; annual_deductible: number | null }
  vehicle: {
    business_miles_ytd: number | null
    mileage_rate: number
    annual_deductible: number | null
    rate_note: string
  }
  total_annual_deductible: number
}

export interface ExpenseCategoryPreset {
  account: string
  label: string
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(detail.detail || response.statusText || `HTTP ${response.status}`))
  }
  return response.json()
}

export const taxSummaryKeys = {
  all: ['taxSummary'] as const,
  summary: (year?: number) => [...taxSummaryKeys.all, year] as const,
  deductions: () => ['deductionsSummary'] as const,
  categories: () => ['expenseCategories'] as const,
}

export function useTaxSummary(year?: number) {
  return useQuery({
    queryKey: taxSummaryKeys.summary(year),
    queryFn: () => fetchJson<TaxSummary>(`/api/company/tax-summary${year ? `?year=${year}` : ''}`),
    refetchInterval: 60000,
  })
}

export function useDeductionsSummary() {
  return useQuery({
    queryKey: taxSummaryKeys.deductions(),
    queryFn: () => fetchJson<DeductionsSummary>('/api/company/facts/deductions/summary'),
    refetchInterval: 60000,
  })
}

export function useExpenseCategories() {
  return useQuery({
    queryKey: taxSummaryKeys.categories(),
    queryFn: () => fetchJson<{ categories: ExpenseCategoryPreset[] }>('/api/bookkeeper/categories'),
    staleTime: 5 * 60 * 1000,
  })
}
