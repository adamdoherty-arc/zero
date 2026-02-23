import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type {
  AgentStatus, AgentQueueItem, AgentHistoryItem,
  AgentSubmitRequest, AgentSettings,
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
export const agentKeys = {
  all: ['agent'] as const,
  status: () => [...agentKeys.all, 'status'] as const,
  queue: () => [...agentKeys.all, 'queue'] as const,
  history: (limit?: number) => [...agentKeys.all, 'history', limit] as const,
  log: (taskId: string) => [...agentKeys.all, 'log', taskId] as const,
  settings: () => [...agentKeys.all, 'settings'] as const,
}

// ---- Status (polls every 5s) ----
export function useAgentStatus() {
  return useQuery({
    queryKey: agentKeys.status(),
    queryFn: () => fetchApi<AgentStatus>('/agent/status'),
    refetchInterval: 5000,
  })
}

// ---- Queue ----
export function useAgentQueue() {
  return useQuery({
    queryKey: agentKeys.queue(),
    queryFn: () => fetchApi<AgentQueueItem[]>('/agent/queue'),
    refetchInterval: 15000,
  })
}

// ---- History ----
export function useAgentHistory(limit: number = 20) {
  return useQuery({
    queryKey: agentKeys.history(limit),
    queryFn: () => fetchApi<AgentHistoryItem[]>(`/agent/history?limit=${limit}`),
  })
}

// ---- Task Log ----
export function useAgentLog(taskId: string) {
  return useQuery({
    queryKey: agentKeys.log(taskId),
    queryFn: () => fetchApi<AgentHistoryItem>(`/agent/log/${taskId}`),
    enabled: !!taskId,
  })
}

// ---- Submit Task ----
export function useSubmitTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: AgentSubmitRequest) =>
      fetchApi<AgentQueueItem>('/agent/submit', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all })
    },
  })
}

// ---- Stop Execution ----
export function useStopExecution() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ status: string; message: string }>('/agent/stop', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.status() })
    },
  })
}

// ---- Pause / Resume ----
export function usePauseAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ status: string; message: string }>('/agent/pause', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.status() })
    },
  })
}

export function useResumeAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ status: string; message: string }>('/agent/resume', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.status() })
    },
  })
}

// ---- Settings ----
export function useAgentSettings() {
  return useQuery({
    queryKey: agentKeys.settings(),
    queryFn: () => fetchApi<AgentSettings>('/agent/settings'),
  })
}

export function useUpdateAgentSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: Partial<AgentSettings>) =>
      fetchApi<AgentSettings>('/agent/settings', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.settings() })
    },
  })
}
