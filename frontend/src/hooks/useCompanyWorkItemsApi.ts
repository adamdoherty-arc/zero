import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'
import type { CompanyDashboardReviewSummary, CompanyTaskEvent, CompanyWorkItemReview, CompletionOutput, Task, TaskCreate, TaskUpdate, WalkthroughCompletionField } from '@/types'

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
  setupProgress: () => [...companyWorkItemKeys.all, 'setupProgress'] as const,
  progressCheckin: () => [...companyWorkItemKeys.all, 'progressCheckin'] as const,
  walkthrough: (taskId?: string) => [...companyWorkItemKeys.all, 'walkthrough', taskId] as const,
}

export interface CompanySetupDomainBreakdown {
  total: number
  done: number
  blocked: number
  in_progress: number
  percent: number
}

export interface CompanySetupTaskSummary {
  id: string
  title: string
  domain: string
  status: string
  priority: string
  blocked_reason?: string | null
  due_at?: string | null
}

export interface CompanySetupProgress {
  percent: number
  total: number
  done: number
  blocked: number
  in_progress: number
  ready: number
  by_domain: Record<string, CompanySetupDomainBreakdown>
  next_unblocked: CompanySetupTaskSummary[]
  critical_blocked: CompanySetupTaskSummary[]
  computed_at: string
}

export interface CompanyProgressCheckin {
  summary: string
  computed_at: string
  requested_by: string
  setup_percent: number
  setup_done: number
  setup_total: number
  stalled_count: number
  overdue_count: number
  moved_recently_count: number
  stalled: Array<{ id: string; title: string; domain: string; priority: string; stalled_days: number; last_event?: string; blocked_reason?: string | null }>
  overdue: Array<{ id: string; title: string; domain: string; priority: string; due_at: string; overdue_hours: number }>
  moved_recently: Array<{ id: string; title: string; domain: string; status: string; event: string }>
  ready_to_close: Array<{ id: string; title: string; domain: string; priority: string }>
  next_unblocked: CompanySetupTaskSummary[]
  critical_blocked: CompanySetupTaskSummary[]
}

export interface CompanyCompletionVerdict {
  quality_score: number
  summary: string
  looks_complete: boolean
  concerns: string[]
  missing_followups: Array<{ title: string; why: string; domain: string; priority: string }>
  infrastructure_suggestions: Array<{ surface: string; name: string; rationale: string }>
  created_followups?: Array<{ id: string; title: string; domain: string }>
  reviewed_at?: string
  reviewed_by?: string
  fallback?: boolean
}

export interface CompanyWalkthroughStep {
  title: string
  instruction: string
  url?: string
  button?: string
  fields?: Array<{ label: string; value?: string }>
  gotcha?: string
  completion_check?: string
}

export interface CompanyWalkthrough {
  title: string
  time_required?: string
  cost?: string
  best_time?: string
  prerequisites?: string[]
  steps: CompanyWalkthroughStep[]
  evidence_to_archive?: string[]
  what_this_unlocks?: string[]
  common_mistakes?: string[]
  if_something_goes_wrong?: string[]
  completion_fields?: WalkthroughCompletionField[]
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

export interface CompleteCompanyWorkItemInput {
  id: string
  completion_note?: string
  outputs?: CompletionOutput[]
  actor?: string
}

export function useCompleteCompanyWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: string | CompleteCompanyWorkItemInput) => {
      const payload =
        typeof input === 'string'
          ? { id: input, actor: 'dashboard', completion_note: undefined, outputs: [] as CompletionOutput[] }
          : { actor: 'dashboard', completion_note: undefined, outputs: [] as CompletionOutput[], ...input }
      return fetchJson<Task>(`/api/company/work-items/${payload.id}/complete`, {
        method: 'POST',
        body: JSON.stringify({
          actor: payload.actor ?? 'dashboard',
          completion_note: payload.completion_note ?? null,
          outputs: payload.outputs ?? [],
        }),
      })
    },
    onSuccess: () => {
      invalidate(qc)
      qc.invalidateQueries({ queryKey: ['companyFacts'] })
    },
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

export function useCompanySetupProgress() {
  return useQuery({
    queryKey: companyWorkItemKeys.setupProgress(),
    queryFn: () => fetchJson<CompanySetupProgress>('/api/company/work-items/setup-progress'),
    refetchInterval: 30000,
  })
}

export function useCompanyProgressCheckin() {
  return useQuery({
    queryKey: companyWorkItemKeys.progressCheckin(),
    queryFn: () => fetchJson<CompanyProgressCheckin>('/api/company/work-items/progress-checkin'),
    refetchInterval: 60000,
  })
}

export function useRunCompanyProgressCheckin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchJson<CompanyProgressCheckin>('/api/company/work-items/progress-checkin/run', {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useCompanyTaskWalkthrough(taskId?: string) {
  return useQuery({
    queryKey: companyWorkItemKeys.walkthrough(taskId),
    queryFn: () => fetchJson<CompanyWalkthrough>(`/api/company/work-items/${taskId}/walkthrough`),
    enabled: Boolean(taskId),
    retry: false,
  })
}

export function useRunCompanyCompletionReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, auto_create_followups = true }: { id: string; auto_create_followups?: boolean }) =>
      fetchJson<CompanyCompletionVerdict>(`/api/company/work-items/${id}/completion-review`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'dashboard', auto_create_followups }),
      }),
    onSuccess: () => invalidate(qc),
  })
}
