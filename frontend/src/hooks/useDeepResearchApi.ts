import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types

export interface DeepResearchReport {
  id: string
  query: string
  status: string
  perspectives: string[]
  outline: Record<string, unknown>
  sources: { url: string; title: string; snippet: string }[]
  sections: Record<string, string>
  report_markdown?: string
  validation_notes?: string
  cost_usd: number
  created_at: string
  started_at?: string
  completed_at?: string
}

export interface DeepResearchRequest {
  query: string
  max_perspectives?: number
  max_cost_usd?: number
}

export interface ResearchFilters {
  status?: string
  limit?: number
}

// Query key factory

const researchKeys = {
  all: ['deepResearch'] as const,
  reports: () => [...researchKeys.all, 'reports'] as const,
  reportList: (filters?: ResearchFilters) => [...researchKeys.reports(), filters] as const,
  report: (id: string) => [...researchKeys.reports(), id] as const,
}

// Hooks

export function useDeepResearchReports(filters?: ResearchFilters) {
  return useQuery({
    queryKey: researchKeys.reportList(filters),
    queryFn: async (): Promise<DeepResearchReport[]> => {
      const params = new URLSearchParams()
      if (filters?.status) params.append('status', filters.status)
      if (filters?.limit !== undefined) params.append('limit', filters.limit.toString())
      const res = await fetch(`${API_URL}/api/research/deep?${params.toString()}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch research reports')
      return res.json()
    },
    staleTime: 10000,
  })
}

export function useDeepResearchReport(reportId: string) {
  return useQuery({
    queryKey: researchKeys.report(reportId),
    queryFn: async (): Promise<DeepResearchReport> => {
      const res = await fetch(`${API_URL}/api/research/deep/${reportId}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch research report')
      return res.json()
    },
    enabled: !!reportId,
    staleTime: 5000,
  })
}

export function useStartDeepResearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: DeepResearchRequest): Promise<DeepResearchReport> => {
      const res = await fetch(`${API_URL}/api/research/deep`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('Failed to start deep research')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: researchKeys.reports() })
    },
  })
}
