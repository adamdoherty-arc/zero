import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Loop {
  id: number
  name: string
  owner_project: 'zero' | 'legion' | 'ada'
  runner_kind: 'claude_skill' | 'opencode' | 'http' | 'prompt_variant'
  runner_target: string
  cron: string
  enabled: boolean
  sandbox_required: boolean
  judge_tier: 'local' | 'none'
  auto_promote_enabled: boolean
  current_variant_id: number | null
  baseline_score: number | null
  consecutive_regressions: number
  daily_token_budget: number
  daily_run_cap: number
  wall_clock_budget_s: number
  last_run_id: number | null
  last_run_at: string | null
  next_due_at: string | null
  description: string | null
  created_at: string | null
  updated_at: string | null
}

export interface LoopRun {
  id: number
  loop_id: number
  variant_id: number | null
  runner_kind: string
  runner_id: string | null
  started_at: string | null
  ended_at: string | null
  duration_s: number | null
  status: 'running' | 'success' | 'failure' | 'timeout' | 'budget_paused'
  judge_score: number | null
  judge_notes: string | null
  vault_path: string | null
  legion_run_id: number | null
  cost_tokens: number | null
  error: string | null
  output: string | null
  metadata: Record<string, unknown>
}

export interface LoopVariant {
  id: number
  loop_id: number
  parent_id: number | null
  variant_label: string
  payload_kind: string
  payload: string
  is_active: boolean
  is_canary: boolean
  canary_traffic_pct: number
  runs_count: number
  successes: number
  total_score: number
  avg_score: number | null
  success_rate: number | null
  retired_at: string | null
  created_at: string | null
}

export interface LoopFilters {
  owner_project?: string
  enabled_only?: boolean
}

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

export const loopKeys = {
  all: ['loops'] as const,
  list: () => [...loopKeys.all, 'list'] as const,
  filteredList: (filters?: LoopFilters) => [...loopKeys.list(), filters] as const,
  detail: (id: number) => [...loopKeys.all, 'detail', id] as const,
  runs: (id: number) => [...loopKeys.all, 'runs', id] as const,
  variants: (id: number) => [...loopKeys.all, 'variants', id] as const,
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useLoops(filters?: LoopFilters) {
  return useQuery({
    queryKey: loopKeys.filteredList(filters),
    queryFn: async (): Promise<Loop[]> => {
      const params = new URLSearchParams()
      if (filters?.owner_project) params.append('owner_project', filters.owner_project)
      if (filters?.enabled_only) params.append('enabled_only', 'true')
      const qs = params.toString()
      const res = await fetch(`${API_URL}/api/loops${qs ? `?${qs}` : ''}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch loops')
      return res.json()
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

export function useLoop(loopId: number | null) {
  return useQuery({
    queryKey: loopKeys.detail(loopId ?? 0),
    queryFn: async (): Promise<Loop> => {
      const res = await fetch(`${API_URL}/api/loops/${loopId}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch loop')
      return res.json()
    },
    enabled: !!loopId,
    staleTime: 5_000,
  })
}

export function useLoopRuns(loopId: number | null, limit = 50) {
  return useQuery({
    queryKey: [...loopKeys.runs(loopId ?? 0), limit],
    queryFn: async (): Promise<LoopRun[]> => {
      const res = await fetch(`${API_URL}/api/loops/${loopId}/runs?limit=${limit}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch loop runs')
      return res.json()
    },
    enabled: !!loopId,
    staleTime: 5_000,
    refetchInterval: 10_000,
  })
}

export function useLoopVariants(loopId: number | null) {
  return useQuery({
    queryKey: loopKeys.variants(loopId ?? 0),
    queryFn: async (): Promise<LoopVariant[]> => {
      const res = await fetch(`${API_URL}/api/loops/${loopId}/variants`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch loop variants')
      return res.json()
    },
    enabled: !!loopId,
    staleTime: 10_000,
  })
}

export function useEnableLoop() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ loopId, enabled }: { loopId: number; enabled: boolean }) => {
      const action = enabled ? 'enable' : 'disable'
      const res = await fetch(`${API_URL}/api/loops/${loopId}/${action}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error(`Failed to ${action} loop`)
      return res.json() as Promise<Loop>
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: loopKeys.all })
    },
  })
}

export function useTriggerLoop() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (loopId: number) => {
      const res = await fetch(`${API_URL}/api/loops/${loopId}/trigger`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to trigger loop')
      return res.json()
    },
    onSuccess: (_data, loopId) => {
      qc.invalidateQueries({ queryKey: loopKeys.runs(loopId) })
      qc.invalidateQueries({ queryKey: loopKeys.detail(loopId) })
      qc.invalidateQueries({ queryKey: loopKeys.list() })
    },
  })
}
