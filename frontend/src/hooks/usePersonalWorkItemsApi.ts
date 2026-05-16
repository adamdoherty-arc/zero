import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'
import type { Task, TaskCreate, TaskUpdate } from '@/types'

const API_URL = ''

export interface PersonalWorkItemFilters {
  status?: string
  topic?: string
  priority?: string
  search?: string
  filter_name?: string
  include_archived?: boolean
  limit?: number
}

export interface PersonalTopic {
  topic: string
  total: number
  open: number
  done: number
}

export interface PersonalTaskEvent {
  id: string
  task_id: string
  event_type: string
  actor: string
  summary?: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  created_at: string
}

export interface PersonalSeedVAResult {
  created: number
  skipped: number
  tasks: Task[]
}

export interface PersonalSeedVAStatus {
  has_va_tasks: boolean
  topic: string
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

function qs(filters?: PersonalWorkItemFilters) {
  const params = new URLSearchParams()
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const personalWorkItemKeys = {
  all: ['personalWorkItems'] as const,
  list: (filters?: PersonalWorkItemFilters) => [...personalWorkItemKeys.all, 'list', filters] as const,
  topics: () => [...personalWorkItemKeys.all, 'topics'] as const,
  events: (taskId?: string) => [...personalWorkItemKeys.all, 'events', taskId] as const,
  seedStatus: () => [...personalWorkItemKeys.all, 'seedStatus'] as const,
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: personalWorkItemKeys.all })
  qc.invalidateQueries({ queryKey: ['tasks'] })
}

export function usePersonalWorkItems(filters?: PersonalWorkItemFilters) {
  return useQuery({
    queryKey: personalWorkItemKeys.list(filters),
    queryFn: () => fetchJson<Task[]>(`/api/personal/work-items${qs(filters)}`),
    refetchInterval: 30000,
  })
}

export function usePersonalTopics() {
  return useQuery({
    queryKey: personalWorkItemKeys.topics(),
    queryFn: () => fetchJson<PersonalTopic[]>('/api/personal/work-items/topics'),
    refetchInterval: 30000,
  })
}

export function usePersonalTaskEvents(taskId?: string) {
  return useQuery({
    queryKey: personalWorkItemKeys.events(taskId),
    queryFn: () => fetchJson<PersonalTaskEvent[]>(`/api/personal/work-items/${taskId}/events`),
    enabled: Boolean(taskId),
  })
}

export function useCreatePersonalWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskCreate) =>
      fetchJson<Task>('/api/personal/work-items', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useUpdatePersonalWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: TaskUpdate }) =>
      fetchJson<Task>(`/api/personal/work-items/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useCompletePersonalWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, completion_note }: { id: string; completion_note?: string }) =>
      fetchJson<Task>(`/api/personal/work-items/${id}/complete`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'self', completion_note: completion_note ?? null }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useReopenPersonalWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<Task>(`/api/personal/work-items/${id}/reopen`, {
        method: 'POST',
        body: JSON.stringify({ actor: 'self' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useDeletePersonalWorkItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<{ status: string; task_id: string }>(`/api/personal/work-items/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidate(qc),
  })
}

export function usePersonalSeedVAStatus() {
  return useQuery({
    queryKey: personalWorkItemKeys.seedStatus(),
    queryFn: () => fetchJson<PersonalSeedVAStatus>('/api/personal/work-items/seed-va/status'),
    refetchInterval: 60000,
  })
}

export function useSeedVAClaim() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchJson<PersonalSeedVAResult>('/api/personal/work-items/seed-va', {
        method: 'POST',
        body: JSON.stringify({ actor: 'self' }),
      }),
    onSuccess: () => invalidate(qc),
  })
}
