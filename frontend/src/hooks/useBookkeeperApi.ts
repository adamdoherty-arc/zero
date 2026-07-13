import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

export interface RecurringExpense {
  id: string
  vendor: string
  amount_monthly: number
  category: string
  billing_day: number
  paid_from: string
  active: boolean
  notes: string
  created_at: number
}

export interface RecurringSummary {
  period: string
  total_monthly: number
  active_count: number
  by_category: Record<string, number>
  generated_for_period: string[]
  all_generated: boolean
  metered?: { period_cost: number; ytd_cost: number } | null
}

export interface RecurringListResponse {
  recurring: RecurringExpense[]
  summary: RecurringSummary
}

export interface BookkeeperDraft {
  id: string
  date: string
  description: string
  amount: number
  currency: string
  suggested_category: string
  source: string
  raw: Record<string, unknown>
  status: string
  paid_from?: string
  created_at: number
}

export interface BookkeeperSnapshot {
  entity: string
  period: string
  revenue: number
  expenses: number
  net: number
  by_category: Record<string, number>
  estimated_tax: number
  last_entry_at: string | null
  pending_drafts: number
  backend: string
}

export interface RecurringCreateInput {
  vendor: string
  amount_monthly: number
  category?: string
  billing_day?: number
  paid_from?: string
  notes?: string
}

export interface RecurringUpdateInput {
  vendor?: string
  amount_monthly?: number
  category?: string
  billing_day?: number
  paid_from?: string
  active?: boolean
  notes?: string
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
    ...options,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(detail.detail || response.statusText || `HTTP ${response.status}`))
  }
  return response.json()
}

async function fetchFormData<T>(url: string, form: FormData): Promise<T> {
  // No explicit Content-Type: the browser sets the multipart boundary itself.
  const response = await fetch(`${API_URL}${url}`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: form,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(detail.detail || response.statusText || `HTTP ${response.status}`))
  }
  return response.json()
}

export interface CategorizationRule {
  id: string
  match_type: 'payee' | 'contains' | 'regex'
  pattern: string
  category: string
  priority: number
  active: boolean
  hits: number
  learned: boolean
  created_at: number
}

export const bookkeeperKeys = {
  all: ['bookkeeper'] as const,
  snapshot: (period: string) => [...bookkeeperKeys.all, 'snapshot', period] as const,
  recurring: () => [...bookkeeperKeys.all, 'recurring'] as const,
  drafts: (status?: string) => [...bookkeeperKeys.all, 'drafts', status] as const,
  rules: () => [...bookkeeperKeys.all, 'rules'] as const,
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: bookkeeperKeys.all })
  // Recurring/draft changes feed the consolidated tax-savings summary.
  qc.invalidateQueries({ queryKey: ['taxSummary'] })
}

export function useBookkeeperSnapshot(period: 'YTD' | 'MTD' | 'QTD' = 'YTD') {
  return useQuery({
    queryKey: bookkeeperKeys.snapshot(period),
    queryFn: () => fetchJson<BookkeeperSnapshot>(`/api/bookkeeper/snapshot?period=${period}`),
    refetchInterval: 60000,
  })
}

export function useRecurringExpenses() {
  return useQuery({
    queryKey: bookkeeperKeys.recurring(),
    queryFn: () => fetchJson<RecurringListResponse>('/api/bookkeeper/recurring'),
    refetchInterval: 60000,
  })
}

export function useAddRecurring() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: RecurringCreateInput) =>
      fetchJson<RecurringExpense>('/api/bookkeeper/recurring', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useUpdateRecurring() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: RecurringUpdateInput }) =>
      fetchJson<RecurringExpense>(`/api/bookkeeper/recurring/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useDeleteRecurring() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<{ status: string; id: string }>(`/api/bookkeeper/recurring/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidate(qc),
  })
}

export function useRunRecurring() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (period?: string) =>
      fetchJson<{ period: string; created: BookkeeperDraft[]; created_count: number }>(
        `/api/bookkeeper/recurring/run${period ? `?period=${period}` : ''}`,
        { method: 'POST' },
      ),
    onSuccess: () => invalidate(qc),
  })
}

export function useImportStatement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ file, paidFrom }: { file: File; paidFrom: string }) => {
      const ext = (file.name.split('.').pop() ?? '').toLowerCase()
      if (ext === 'ofx' || ext === 'qfx') {
        const form = new FormData()
        form.append('file', file)
        form.append('paid_from', paidFrom)
        return fetchFormData<{ drafts: BookkeeperDraft[]; count: number }>(
          '/api/bookkeeper/ingest-ofx',
          form,
        )
      }
      const csvText = await file.text()
      const result = await fetchJson<{ drafts: BookkeeperDraft[]; count: number }>(
        '/api/bookkeeper/ingest',
        {
          method: 'POST',
          body: JSON.stringify({ source: 'bank_csv', csv: csvText, paid_from: paidFrom }),
        },
      )
      return result
    },
    onSuccess: () => invalidate(qc),
  })
}

export function useIngestReceipt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, paidFrom }: { file: File; paidFrom: string }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('paid_from', paidFrom)
      return fetchFormData<BookkeeperDraft>('/api/bookkeeper/receipts', form)
    },
    onSuccess: () => invalidate(qc),
  })
}

export interface RecurringSuggestion {
  vendor: string
  amount_monthly: number
  category: string
  billing_day: number
  occurrences: number
  months: string[]
}

export function useRecurringSuggestions() {
  return useQuery({
    queryKey: [...bookkeeperKeys.all, 'recurringSuggestions'] as const,
    queryFn: () => fetchJson<{ suggestions: RecurringSuggestion[] }>('/api/bookkeeper/recurring/suggestions'),
    refetchInterval: 120000,
  })
}

export function useAcceptRecurringSuggestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (s: RecurringSuggestion) =>
      fetchJson<RecurringExpense>('/api/bookkeeper/recurring/suggestions/accept', {
        method: 'POST',
        body: JSON.stringify({
          vendor: s.vendor,
          amount_monthly: s.amount_monthly,
          category: s.category,
          billing_day: s.billing_day,
        }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useCategorizationRules() {
  return useQuery({
    queryKey: bookkeeperKeys.rules(),
    queryFn: () => fetchJson<{ rules: CategorizationRule[] }>('/api/bookkeeper/rules'),
    refetchInterval: 120000,
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<{ status: string; id: string }>(`/api/bookkeeper/rules/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidate(qc),
  })
}

export function useRunMetered() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (period?: string) =>
      fetchJson<{ period: string; created: BookkeeperDraft | null; reason: string }>(
        `/api/bookkeeper/metered/run${period ? `?period=${period}` : ''}`,
        { method: 'POST' },
      ),
    onSuccess: () => invalidate(qc),
  })
}

export function useBookkeeperDrafts(status?: string) {
  return useQuery({
    queryKey: bookkeeperKeys.drafts(status),
    queryFn: () =>
      fetchJson<{ drafts: BookkeeperDraft[] }>(`/api/bookkeeper/drafts${status ? `?status=${status}` : ''}`),
    refetchInterval: 60000,
  })
}

export function useAcceptDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, category }: { id: string; category?: string }) =>
      fetchJson<BookkeeperDraft>(`/api/bookkeeper/drafts/${id}/accept`, {
        method: 'POST',
        body: JSON.stringify({ category: category ?? null }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useRejectDraft() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<BookkeeperDraft>(`/api/bookkeeper/drafts/${id}/reject`, { method: 'POST' }),
    onSuccess: () => invalidate(qc),
  })
}
