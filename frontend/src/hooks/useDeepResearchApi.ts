import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

export interface DeepResearchRequest {
  query: string
  perspectives?: string[]
  max_cost_usd?: number
}

export interface DeepResearchReport {
  id: string
  query: string
  status: string
  outline?: Record<string, unknown> | null
  perspectives: string[]
  sources: Array<Record<string, unknown>>
  sections: Record<string, unknown>
  report_markdown?: string | null
  executive_summary?: string | null
  cost_usd: number
  error?: string | null
  created_at: string
  completed_at?: string | null
}

const deepResearchKeys = {
  all: ['deep-research'] as const,
  reports: (status?: string, limit?: number) => [...deepResearchKeys.all, 'reports', status, limit] as const,
  report: (id?: string) => [...deepResearchKeys.all, 'report', id] as const,
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `Request failed: ${res.status}`)
  }
  return res.json()
}

export function useDeepResearchReports(status?: string, limit = 30) {
  return useQuery({
    queryKey: deepResearchKeys.reports(status, limit),
    queryFn: () => {
      const params = new URLSearchParams()
      if (status && status !== 'all') params.set('status', status)
      params.set('limit', String(limit))
      return fetchJson<DeepResearchReport[]>(`/api/research/deep?${params.toString()}`)
    },
    refetchInterval: 10000,
  })
}

export function useDeepResearchReport(reportId?: string) {
  return useQuery({
    queryKey: deepResearchKeys.report(reportId),
    queryFn: () => fetchJson<DeepResearchReport>(`/api/research/deep/${reportId}`),
    enabled: !!reportId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && !['completed', 'failed'].includes(status) ? 5000 : false
    },
  })
}

export function useStartDeepResearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: DeepResearchRequest) =>
      fetchJson<DeepResearchReport>('/api/research/deep', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: (report) => {
      qc.invalidateQueries({ queryKey: deepResearchKeys.all })
      qc.setQueryData(deepResearchKeys.report(report.id), report)
    },
  })
}
