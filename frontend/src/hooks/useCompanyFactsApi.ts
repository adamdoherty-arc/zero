import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'
import type { CompanyFact, CompanyFactCreate, CompanyFactUpdate } from '@/types'

const API_URL = ''

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
    ...options,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(detail.detail || response.statusText || `HTTP ${response.status}`))
  }
  return response.json()
}

export interface CompanyFactsFilters {
  domain?: string
  search?: string
}

export const companyFactsKeys = {
  all: ['companyFacts'] as const,
  list: (filters?: CompanyFactsFilters) => [...companyFactsKeys.all, 'list', filters] as const,
}

function qs(filters?: CompanyFactsFilters): string {
  const params = new URLSearchParams()
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function useCompanyFacts(filters?: CompanyFactsFilters) {
  return useQuery({
    queryKey: companyFactsKeys.list(filters),
    queryFn: () => fetchJson<CompanyFact[]>(`/api/company/facts${qs(filters)}`),
    refetchInterval: 60000,
  })
}

export function useUpsertCompanyFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CompanyFactCreate & { actor?: string }) =>
      fetchJson<CompanyFact>('/api/company/facts', {
        method: 'POST',
        body: JSON.stringify({ actor: data.actor ?? 'dashboard', ...data }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: companyFactsKeys.all })
      qc.invalidateQueries({ queryKey: ['companyWorkItems'] })
    },
  })
}

export function usePatchCompanyFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: CompanyFactUpdate }) =>
      fetchJson<CompanyFact>(`/api/company/facts/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: companyFactsKeys.all }),
  })
}

export function useDeleteCompanyFact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<{ status: string; id: string }>(`/api/company/facts/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: companyFactsKeys.all }),
  })
}
