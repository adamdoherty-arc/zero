import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    ...options,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

const workflowKeys = {
  list: ['visual-workflows'] as const,
  detail: (id: string) => ['visual-workflows', id] as const,
  nodeTypes: ['visual-workflows', 'node-types'] as const,
  executions: (id: string) => ['visual-workflows', id, 'executions'] as const,
  outcomes: (days: number) => ['outcomes', days] as const,
}

export function useVisualWorkflows(status?: string) {
  return useQuery({
    queryKey: workflowKeys.list,
    queryFn: () => fetchApi(`/visual-workflows${status ? `?status=${status}` : ''}`),
  })
}

export function useVisualWorkflow(id: string) {
  return useQuery({
    queryKey: workflowKeys.detail(id),
    queryFn: () => fetchApi(`/visual-workflows/${id}`),
    enabled: !!id,
  })
}

export function useNodeTypes() {
  return useQuery({
    queryKey: workflowKeys.nodeTypes,
    queryFn: () => fetchApi('/visual-workflows/node-types'),
    staleTime: Infinity,
  })
}

export function useWorkflowExecutions(workflowId: string) {
  return useQuery({
    queryKey: workflowKeys.executions(workflowId),
    queryFn: () => fetchApi(`/visual-workflows/${workflowId}/executions`),
    enabled: !!workflowId,
  })
}

export function useCreateWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      fetchApi('/visual-workflows', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: workflowKeys.list }),
  })
}

export function useUpdateWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      fetchApi(`/visual-workflows/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: workflowKeys.list })
      qc.invalidateQueries({ queryKey: workflowKeys.detail(id) })
    },
  })
}

export function useDeleteWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi(`/visual-workflows/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: workflowKeys.list }),
  })
}

export function useExecuteWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi(`/visual-workflows/${id}/execute`, { method: 'POST' }),
    onSuccess: (_, id) => qc.invalidateQueries({ queryKey: workflowKeys.executions(id) }),
  })
}

export function useOutcomeDashboard(days: number = 30) {
  return useQuery({
    queryKey: workflowKeys.outcomes(days),
    queryFn: () => fetchApi(`/visual-workflows/outcomes/dashboard?days=${days}`),
    refetchInterval: 60000,
  })
}
