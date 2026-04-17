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

const approvalKeys = {
  pending: ['approvals', 'pending'] as const,
  all: (status?: string) => ['approvals', 'all', status] as const,
  stats: ['approvals', 'stats'] as const,
  detail: (id: string) => ['approvals', 'detail', id] as const,
}

export function usePendingApprovals() {
  return useQuery({
    queryKey: approvalKeys.pending,
    queryFn: () => fetchApi('/approvals/pending'),
    refetchInterval: 10000,
  })
}

export function useAllApprovals(status?: string) {
  return useQuery({
    queryKey: approvalKeys.all(status),
    queryFn: () => fetchApi(`/approvals/all${status ? `?status=${status}` : ''}`),
    refetchInterval: 15000,
  })
}

export function useApprovalStats() {
  return useQuery({
    queryKey: approvalKeys.stats,
    queryFn: () => fetchApi('/approvals/stats'),
    refetchInterval: 30000,
  })
}

export function useApproveRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      fetchApi(`/approvals/${id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ decision_by: 'user', reason }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: approvalKeys.pending })
      qc.invalidateQueries({ queryKey: approvalKeys.stats })
    },
  })
}

export function useRejectRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      fetchApi(`/approvals/${id}/reject`, {
        method: 'POST',
        body: JSON.stringify({ decision_by: 'user', reason }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: approvalKeys.pending })
      qc.invalidateQueries({ queryKey: approvalKeys.stats })
    },
  })
}
