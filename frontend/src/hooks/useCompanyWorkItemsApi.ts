import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'
import type { CompanyDashboardReviewSummary, CompanyTaskEvent, CompanyWorkItemReview, Task, TaskCreate, TaskUpdate } from '@/types'

const API_URL = ''

export interface CompanyWorkItemFilters {
  status?: string
  domain?: string
  owner_agent?: string
  risk_level?: string
  approval_state?: string
  filter_name?: string
  search?: string
  limit?: number
}

export interface CompanySeedStatus {
  has_live_tasks: boolean
  seed_source: string
  message: string
}

export interface CompanySeedImportResult {
  created: number
  skipped: number
  tasks: Task[]
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

function qs(filters?: CompanyWorkItemFilters) {
  const params = new URLSearchParams()
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const companyWorkItemKeys = {
  all: ['companyWorkItems'] as const,
  list: (filters?: CompanyWorkItemFilters) => [...companyWorkItemKeys.all, 'list', filters] as const,
  seedStatus: () => [...companyWorkItemKeys.all, 'seedStatus'] as const,
  events: (taskId?: string) => [...companyWorkItemKeys.all, 'events', taskId] as const,
  review: (taskId?: string) => [...companyWorkItemKeys.all, 'review', taskId] as const,
  reviewSummary: () => [...companyWorkItemKeys.all, 'reviewSummary'] as const,
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: companyWorkItemKeys.all })
  qc.invalidateQueries({ queryKey: ['companyOperator'] })
  qc.invalidateQueries({ queryKey: ['tasks'] })
  qc.invalidateQueries({ queryKey: ['agentApprovals'] })
}

export function useCompanyWorkItems(filters?: CompanyWorkItemFilters) {
  return useQuery({
    queryKey: companyWorkItemKeys.list(filters),
    queryFn: () => fetchJson<Task[]>(`/api/company/work-items${qs(filters)}`),
    refetchInterval: 30000,
  })
}

export function useCompanySeedStatus() {
  return useQuery({
    queryKey: companyWorkItemKeys.seedStatus(),
    queryFn: () => fetchJson<CompanySeedStatus>('/api/company/work-items/seed-status'),
    refetchInterval: 60000,
  })
}

export function useCompanyTaskEvents(taskId?: string) {
  return useQuery({
    queryKey: companyWorkItemKeys.events(taskId),
    queryFn: () => fetchJson<CompanyTaskEvent[]>(`/api/company/work-items/${taskId}/events`),
    enabled: Boolean(taskId),
  })
}

export function useCompanyTaskReview(taskId?: string) {
  return useQuery({
    queryKey: companyWorkItemKeys.review(taskId),
    queryFn: () => fetchJson<CompanyWorkItemReview>(`/api/company/work-items/${taskId}/review`),
    enabled: Boolean(taskId),
    retry: false,
  })
}

export function useCompanyReviewSummary() {
  return useQuery({
    queryKey: companyWorkItemKeys.reviewSummary(),
    queryFn: () => fetchJson<CompanyDashboardReviewSummary>('/api/company/work-items/reviews/summary'),
    refetchInterval: 30000,
  })
}

export function useRunCompanyDashboardReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchJson<Record<string, unknown>>('/api/company/work-items/reviews/run', {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useCreateCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskCreate) =>
      fetchJson<Task>('/api/company/work-items', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useUpdateCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: TaskUpdate }) =>
      fetchJson<Task>(`/api/company/work-items/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useCompleteCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<Task>(`/api/company/work-items/${id}/complete`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useReopenCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<Task>(`/api/company/work-items/${id}/reopen`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useDuplicateCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<Task>(`/api/company/work-items/${id}/duplicate`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useDeleteCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<{ status: string; task_id: string }>(`/api/company/work-items/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidate(qc),
  })
}

export function useImportCompanySeedBacklog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchJson<CompanySeedImportResult>('/api/company/work-items/import-seed', {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}
