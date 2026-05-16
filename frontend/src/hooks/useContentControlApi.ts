import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { schedulerKeys } from '@/hooks/useSystemApi'

const API_BASE = '/api/content-control'

export interface ContentProductionJob {
  id: string
  name: string
  display_name: string
  category: string
  schedule: string
  next_run: string | null
  enabled: boolean
  default_enabled: boolean
}

export interface ContentProductionStatus {
  paused: boolean
  reason: string
  updated_at: string
  updated_by: string
  affected_job_ids: string[]
  previous_job_states: Record<string, boolean>
  last_scheduler_sync_at?: string | null
  affected_jobs: ContentProductionJob[]
  scheduler_result?: Record<string, unknown>
}

export interface ContentProductionStatusUpdate {
  paused: boolean
  reason?: string
  restore_previous_jobs?: boolean
}

async function fetchContentControl<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      detail?: string
      error?: { message?: string }
    } | null
    throw new Error(payload?.error?.message || payload?.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

export const contentControlKeys = {
  all: ['content-control'] as const,
  status: () => [...contentControlKeys.all, 'status'] as const,
}

export const CONTENT_PRODUCTION_PAUSED_TOOLTIP =
  'Content production is paused. Resume it from Settings > Content Production.'

export function useContentProductionStatus() {
  return useQuery({
    queryKey: contentControlKeys.status(),
    queryFn: () => fetchContentControl<ContentProductionStatus>('/status'),
    refetchInterval: 30000,
  })
}

export function useSetContentProductionStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ContentProductionStatusUpdate) =>
      fetchContentControl<ContentProductionStatus>('/status', {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentControlKeys.all })
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all })
    },
  })
}

export function useSyncContentProductionScheduler() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchContentControl<ContentProductionStatus>('/sync-scheduler', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentControlKeys.all })
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all })
    },
  })
}
