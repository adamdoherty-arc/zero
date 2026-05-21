import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@/hooks/use-toast'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

export type ApprovalTier = 'read' | 'write_local' | 'write_external' | 'financial'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired'

export interface AgentApproval {
  id: string
  tool_name: string
  tier: ApprovalTier
  summary: string
  arguments: Record<string, unknown>
  status: ApprovalStatus
  requested_by: string
  requested_at: string
  decided_at?: string | null
  decided_by?: string | null
  reason?: string | null
  expires_at?: string | null
}

export const approvalsKeys = {
  all: ['approvals'] as const,
  pending: () => ['approvals', 'pending'] as const,
  list: (status: ApprovalStatus | 'all') => ['approvals', 'list', status] as const,
  detail: (id: string) => ['approvals', 'detail', id] as const,
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 240)}`)
  }
  return (await res.json()) as T
}

export function usePendingApprovals() {
  return useQuery({
    queryKey: approvalsKeys.pending(),
    queryFn: () => jsonFetch<AgentApproval[]>('/agent-approvals?status=pending'),
    refetchInterval: 15000,
  })
}

export function useAllApprovals(status: ApprovalStatus | 'all' = 'all') {
  return useQuery({
    queryKey: approvalsKeys.list(status),
    queryFn: () =>
      jsonFetch<AgentApproval[]>(
        status === 'all' ? '/agent-approvals' : `/agent-approvals?status=${status}`,
      ),
    refetchInterval: 30000,
  })
}

export function useDecideApproval() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars: {
      id: string
      status: 'approved' | 'rejected'
      reason?: string
    }) =>
      jsonFetch<AgentApproval>(`/agent-approvals/${vars.id}/decide`, {
        method: 'POST',
        body: JSON.stringify({
          status: vars.status,
          reason: vars.reason,
          decided_by: 'user',
        }),
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: approvalsKeys.all })
      toast({
        title: data.status === 'approved' ? 'Approved' : 'Rejected',
        description: data.summary?.slice(0, 120) || data.tool_name,
      })
    },
    onError: (err: Error) => {
      toast({ title: 'Decision failed', description: err.message, variant: 'destructive' })
    },
  })
}

export function useExpireStale() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      jsonFetch<{ expired: number }>('/agent-approvals/expire-stale', {
        method: 'POST',
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: approvalsKeys.all })
      toast({
        title: 'Stale approvals expired',
        description: `${data.expired ?? 0} request(s) moved to expired.`,
      })
    },
  })
}
