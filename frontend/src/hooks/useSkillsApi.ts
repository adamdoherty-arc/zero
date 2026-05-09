import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// ---------------------------------------------------------------------------
// Types (mirror Legion's skills_registry endpoint shapes)
// ---------------------------------------------------------------------------

export interface Skill {
  id: number
  name: string
  source_path: string
  content_hash: string
  display_name: string
  description: string
  owner_project: 'zero' | 'legion' | 'ada' | 'llmrouter' | 'global' | string
  category: string
  team_id: number | null
  tags: string[]
  enabled: boolean
  deprecated: boolean
  superseded_by: string | null
  cron: string
  judge_tier: 'local' | 'none'
  daily_token_budget: number
  wallclock_budget_s: number
  auto_promote: boolean
  input_args: unknown[]
  output_schema: unknown | null
  zero_loop_id: number | null
  run_count: number
  success_count: number
  avg_score: number | null
  avg_tokens: number | null
  last_run_at: string | null
  last_score: number | null
  last_status: string | null
  last_synced_at: string | null
  body?: string
}

export interface SkillRun {
  id: number
  zero_run_id: number
  loop_name: string
  owner_project: string
  variant_label: string | null
  status: string
  judge_score: number | null
  duration_s: number | null
  vault_path: string | null
  cost_tokens: number | null
  payload: Record<string, unknown>
  received_at: string | null
}

export interface SkillFilters {
  owner_project?: string
  category?: string
  team_id?: number
  deprecated?: boolean
  search?: string
}

export interface SkillPatch {
  cron?: string
  judge_tier?: 'local' | 'none'
  daily_token_budget?: number
  wallclock_budget_s?: number
  auto_promote?: boolean
  enabled?: boolean
  team_id?: number | null
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const skillKeys = {
  all: ['skills'] as const,
  list: (filters?: SkillFilters) => [...skillKeys.all, 'list', filters] as const,
  detail: (name: string) => [...skillKeys.all, 'detail', name] as const,
  runs: (name: string, limit: number) => [...skillKeys.all, 'runs', name, limit] as const,
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useSkills(filters?: SkillFilters) {
  return useQuery({
    queryKey: skillKeys.list(filters),
    queryFn: async (): Promise<Skill[]> => {
      const params = new URLSearchParams()
      if (filters?.owner_project) params.append('owner_project', filters.owner_project)
      if (filters?.category) params.append('category', filters.category)
      if (filters?.team_id !== undefined) params.append('team_id', String(filters.team_id))
      if (filters?.deprecated !== undefined) params.append('deprecated', String(filters.deprecated))
      if (filters?.search) params.append('search', filters.search)
      const qs = params.toString()
      const res = await fetch(`${API_URL}/api/skills${qs ? `?${qs}` : ''}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error(`Failed to fetch skills (${res.status})`)
      return res.json()
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useSkill(name: string | null) {
  return useQuery({
    queryKey: skillKeys.detail(name ?? ''),
    queryFn: async (): Promise<Skill> => {
      const res = await fetch(`${API_URL}/api/skills/${encodeURIComponent(name!)}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch skill')
      return res.json()
    },
    enabled: !!name,
    staleTime: 5_000,
  })
}

export function useSkillRuns(name: string | null, limit = 50) {
  return useQuery({
    queryKey: skillKeys.runs(name ?? '', limit),
    queryFn: async (): Promise<SkillRun[]> => {
      const res = await fetch(`${API_URL}/api/skills/${encodeURIComponent(name!)}/runs?limit=${limit}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch skill runs')
      return res.json()
    },
    enabled: !!name,
    staleTime: 5_000,
    refetchInterval: 15_000,
  })
}

export function usePatchSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, patch }: { name: string; patch: SkillPatch }) => {
      const res = await fetch(`${API_URL}/api/skills/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) throw new Error(`Failed to patch skill (${res.status})`)
      return res.json() as Promise<Skill>
    },
    onSuccess: (_data, { name }) => {
      qc.invalidateQueries({ queryKey: skillKeys.detail(name) })
      qc.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}

export function useSyncSkills() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_URL}/api/skills/sync`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error(`Failed to sync skills (${res.status})`)
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}
