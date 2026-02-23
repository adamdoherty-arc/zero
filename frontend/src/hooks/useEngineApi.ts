import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type { EngineStatus, EngineConfig, ActivityEvent, ActivitySummary } from '../types'

const API_BASE = '/api'

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

// Query key factories
export const engineKeys = {
  all: ['engine'] as const,
  status: () => [...engineKeys.all, 'status'] as const,
  activity: (project?: string) => [...engineKeys.all, 'activity', project] as const,
  summary: (hours?: number) => [...engineKeys.all, 'summary', hours] as const,
}

// ---- Engine Status (polls every 10s) ----
export function useEngineStatus() {
  return useQuery({
    queryKey: engineKeys.status(),
    queryFn: () => fetchApi<EngineStatus>('/engine/status'),
    refetchInterval: 10000,
  })
}

// ---- Activity Feed (polls every 15s) ----
export function useActivityFeed(project?: string, limit: number = 50) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (project) params.set('project', project)

  return useQuery({
    queryKey: engineKeys.activity(project),
    queryFn: () =>
      fetchApi<{ events: ActivityEvent[]; total: number }>(
        `/engine/activity?${params.toString()}`
      ),
    refetchInterval: 15000,
  })
}

// ---- Activity Summary ----
export function useActivitySummary(hours: number = 24) {
  return useQuery({
    queryKey: engineKeys.summary(hours),
    queryFn: () => fetchApi<ActivitySummary>(`/engine/activity/summary?hours=${hours}`),
    refetchInterval: 30000,
  })
}

// ---- Toggle Engine ----
export function useToggleEngine() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      fetchApi<{ enabled: boolean }>('/engine/toggle', {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: engineKeys.status() })
    },
  })
}

// ---- Update Config ----
export function useUpdateEngineConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (updates: Partial<EngineConfig>) =>
      fetchApi<EngineConfig>('/engine/config', {
        method: 'PATCH',
        body: JSON.stringify(updates),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: engineKeys.status() })
    },
  })
}

// ---- Trigger Cycle ----
export function useTriggerCycle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ triggered: boolean; message: string }>('/engine/trigger', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: engineKeys.all })
    },
  })
}
