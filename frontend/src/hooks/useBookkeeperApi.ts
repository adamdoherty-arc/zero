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

export const bookkeeperKeys = {
  all: ['bookkeeper'] as const,
  snapshot: (period: string) => [...bookkeeperKeys.all, 'snapshot', period] as const,
  recurring: () => [...bookkeeperKeys.all, 'recurring'] as const,
  drafts: (status?: string) => [...bookkeeperKeys.all, 'drafts', status] as const,
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
