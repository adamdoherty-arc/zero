import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type {
  SchedulerStatus,
  SchedulerAuditEntry,
  HealthReadyResponse,
  SchedulerJobToggleResult,
  SchedulerJobsToggleResult,
} from '../types'

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
export const schedulerKeys = {
  all: ['scheduler'] as const,
  status: () => [...schedulerKeys.all, 'status'] as const,
  audit: (limit?: number) => [...schedulerKeys.all, 'audit', limit] as const,
}

export const healthKeys = {
  ready: ['health', 'ready'] as const,
}

// ---- Scheduler ----
export function useSchedulerStatus() {
  return useQuery({
    queryKey: schedulerKeys.status(),
    queryFn: () => fetchApi<SchedulerStatus>('/system/scheduler/status'),
    refetchInterval: 30000,
  })
}

export function useSchedulerAudit(limit: number = 50) {
  return useQuery({
    queryKey: schedulerKeys.audit(limit),
    queryFn: () =>
      fetchApi<{ executions: SchedulerAuditEntry[]; total: number }>(
        `/system/scheduler/audit?limit=${limit}`
      ),
    refetchInterval: 30000,
  })
}

export function useTriggerJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobName: string) =>
      fetchApi<{ success: boolean; job: string }>(`/system/scheduler/jobs/${jobName}/trigger`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all })
    },
  })
}

export function useSetSchedulerJobEnabled() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ jobName, enabled }: { jobName: string; enabled: boolean }) =>
      fetchApi<SchedulerJobToggleResult>(`/system/scheduler/jobs/${jobName}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all })
      queryClient.invalidateQueries({ queryKey: ['execution'] })
      queryClient.invalidateQueries({ queryKey: ['reachy-email-session'] })
    },
  })
}

export function useSetSchedulerJobsEnabled() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ jobNames, enabled }: { jobNames: string[]; enabled: boolean }) =>
      fetchApi<SchedulerJobsToggleResult>('/system/scheduler/jobs', {
        method: 'PATCH',
        body: JSON.stringify({ job_names: jobNames, enabled }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all })
      queryClient.invalidateQueries({ queryKey: ['execution'] })
      queryClient.invalidateQueries({ queryKey: ['reachy-email-session'] })
    },
  })
}

// ---- Health ----
export function useHealthReady() {
  return useQuery({
    queryKey: healthKeys.ready,
    queryFn: async () => {
      // /health/ready is NOT under /api and may return 503
      const response = await fetch('/health/ready', {
        headers: { ...getAuthHeaders() },
      })
      return response.json() as Promise<HealthReadyResponse>
    },
    refetchInterval: 30000,
  })
}
