import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types

export interface Experiment {
  id: string
  title: string
  hypothesis: string
  methodology?: string
  experiment_type: string
  status: string
  parameters: Record<string, unknown>
  metrics: Record<string, unknown>
  results?: Record<string, unknown>
  conclusion?: string
  linked_idea_id?: string
  linked_research_id?: string
  created_by_role?: string
  cost_usd: number
  created_at: string
  started_at?: string
  completed_at?: string
}

export interface ExperimentCreate {
  hypothesis: string
  experiment_type?: string
  title?: string
  parameters?: Record<string, unknown>
}

export interface ExperimentFilters {
  status?: string
  exp_type?: string
  limit?: number
}

// Query key factory

const experimentKeys = {
  all: ['experiments'] as const,
  list: () => [...experimentKeys.all, 'list'] as const,
  filteredList: (filters?: ExperimentFilters) => [...experimentKeys.list(), filters] as const,
  detail: (id: string) => [...experimentKeys.all, 'detail', id] as const,
}

// Hooks

export function useExperiments(filters?: ExperimentFilters) {
  return useQuery({
    queryKey: experimentKeys.filteredList(filters),
    queryFn: async (): Promise<Experiment[]> => {
      const params = new URLSearchParams()
      if (filters?.status) params.append('status', filters.status)
      if (filters?.exp_type) params.append('exp_type', filters.exp_type)
      if (filters?.limit !== undefined) params.append('limit', filters.limit.toString())
      const res = await fetch(`${API_URL}/api/experiments?${params.toString()}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch experiments')
      return res.json()
    },
    staleTime: 10000,
  })
}

export function useExperiment(expId: string) {
  return useQuery({
    queryKey: experimentKeys.detail(expId),
    queryFn: async (): Promise<Experiment> => {
      const res = await fetch(`${API_URL}/api/experiments/${expId}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch experiment')
      return res.json()
    },
    enabled: !!expId,
    staleTime: 5000,
  })
}

export function useDesignExperiment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ExperimentCreate): Promise<Experiment> => {
      const res = await fetch(`${API_URL}/api/experiments`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('Failed to design experiment')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: experimentKeys.list() })
    },
  })
}

export function useRunExperiment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (expId: string): Promise<Experiment> => {
      const res = await fetch(`${API_URL}/api/experiments/${expId}/run`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to run experiment')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: experimentKeys.list() })
    },
  })
}
