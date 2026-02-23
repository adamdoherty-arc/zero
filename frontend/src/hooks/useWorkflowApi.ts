import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api/workflows'

async function fetchJson(url: string, options?: RequestInit) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    ...options,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export interface WorkflowSummary {
  name: string
  version: string
  description: string
  steps: number
  triggers: string[]
  source: string
}

export interface StepResult {
  output: unknown
  status: string
  error?: string
}

export interface WorkflowExecution {
  workflow_id: string
  execution_id: string
  status: string
  steps: Record<string, StepResult>
  started_at?: string
  completed_at?: string
  error?: string
}

export function useWorkflows() {
  return useQuery({
    queryKey: ['workflows'],
    queryFn: () => fetchJson(API_BASE + '/'),
    refetchInterval: 30000,
  })
}

export function useWorkflowDetail(name: string) {
  return useQuery({
    queryKey: ['workflow', name],
    queryFn: () => fetchJson(`${API_BASE}/${name}`),
    enabled: !!name,
  })
}

export function useActiveExecutions() {
  return useQuery({
    queryKey: ['workflow-executions-active'],
    queryFn: () => fetchJson(`${API_BASE}/executions/active`),
    refetchInterval: 5000,
  })
}

export function useExecutionHistory(limit = 20) {
  return useQuery({
    queryKey: ['workflow-executions-history', limit],
    queryFn: () => fetchJson(`${API_BASE}/executions/history?limit=${limit}`),
    refetchInterval: 15000,
  })
}

export function useTriggerWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, trigger, variables }: { name: string; trigger?: Record<string, unknown>; variables?: Record<string, unknown> }) =>
      fetchJson(`${API_BASE}/${name}/trigger`, {
        method: 'POST',
        body: JSON.stringify({ trigger, variables }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflow-executions-active'] })
      qc.invalidateQueries({ queryKey: ['workflow-executions-history'] })
    },
  })
}

export function useCancelExecution() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (executionId: string) =>
      fetchJson(`${API_BASE}/executions/${executionId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflow-executions-active'] })
      qc.invalidateQueries({ queryKey: ['workflow-executions-history'] })
    },
  })
}
