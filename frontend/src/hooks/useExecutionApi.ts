import { useQuery } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

async function fetchApi<T>(url: string): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

const executionKeys = {
  dashboard: ['execution', 'dashboard'] as const,
  timeline: (hours: number) => ['execution', 'timeline', hours] as const,
  jobHistory: (name: string) => ['execution', 'job', name] as const,
}

export function useSchedulerDashboard() {
  return useQuery({
    queryKey: executionKeys.dashboard,
    queryFn: () => fetchApi('/system/scheduler/dashboard'),
    refetchInterval: 10000,
  })
}

export function useJobTimeline(hours: number = 24) {
  return useQuery({
    queryKey: executionKeys.timeline(hours),
    queryFn: () => fetchApi(`/system/scheduler/timeline?hours=${hours}`),
    refetchInterval: 30000,
  })
}

export function useJobHistory(jobName: string) {
  return useQuery({
    queryKey: executionKeys.jobHistory(jobName),
    queryFn: () => fetchApi(`/system/scheduler/jobs/${jobName}/history`),
    enabled: !!jobName,
  })
}
