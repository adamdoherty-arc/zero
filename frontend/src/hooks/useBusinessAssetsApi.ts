import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'

export type AssetMethod = 'section_179' | 'de_minimis' | 'macrs_5yr' | 'none'

export interface BusinessAsset {
  id: string
  name: string
  asset_type: string | null
  cost: number
  business_use_pct: number
  placed_in_service: string | null
  method: AssetMethod
  disposed_at: string | null
  evidence_url: string | null
  notes: string | null
  created_by: string | null
  created_at: string | null
  updated_at: string | null
  current_year_deduction: number | null
}

export interface BusinessAssetCreateInput {
  name: string
  asset_type?: string | null
  cost?: number
  business_use_pct?: number
  placed_in_service?: string | null
  method?: AssetMethod
  evidence_url?: string | null
  notes?: string | null
}

export interface BusinessAssetUpdateInput {
  name?: string
  asset_type?: string | null
  cost?: number
  business_use_pct?: number
  placed_in_service?: string | null
  method?: AssetMethod
  disposed_at?: string | null
  evidence_url?: string | null
  notes?: string | null
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
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

export const businessAssetKeys = {
  all: ['businessAssets'] as const,
  list: (year?: number) => [...businessAssetKeys.all, 'list', year] as const,
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: businessAssetKeys.all })
  // The asset deduction feeds the consolidated tax summary.
  qc.invalidateQueries({ queryKey: ['taxSummary'] })
}

export function useBusinessAssets(year?: number) {
  return useQuery({
    queryKey: businessAssetKeys.list(year),
    queryFn: () => fetchJson<BusinessAsset[]>(`/api/company/assets${year ? `?year=${year}` : ''}`),
    refetchInterval: 60000,
  })
}

export function useCreateBusinessAsset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: BusinessAssetCreateInput) =>
      fetchJson<BusinessAsset>('/api/company/assets', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useUpdateBusinessAsset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: BusinessAssetUpdateInput }) =>
      fetchJson<BusinessAsset>(`/api/company/assets/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidate(qc),
  })
}

export function useDeleteBusinessAsset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchJson<{ status: string; id: string }>(`/api/company/assets/${id}`, { method: 'DELETE' }),
    onSuccess: () => invalidate(qc),
  })
}
