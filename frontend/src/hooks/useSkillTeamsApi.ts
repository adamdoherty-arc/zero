import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// ---------------------------------------------------------------------------
// Types (mirror Legion shapes)
// ---------------------------------------------------------------------------

export interface SkillTeam {
  id: number
  name: string
  display_name: string
  description: string | null
  run_strategy: 'parallel' | 'sequential'
  composite_weights: Record<string, number>
  member_count: number
  members: { id: number; name: string; position: number }[]
  last_run_id: number | null
  last_composite_score: number | null
  last_status: string | null
  last_run_at: string | null
}

export interface SkillTeamRun {
  id: number
  team_id: number
  started_at: string
  finished_at: string | null
  status: string
  composite_score: number | null
  child_run_ids: number[]
  trigger_source: string
  trigger_args: Record<string, unknown>
  vault_path: string | null
  error: string | null
}

export interface TeamCreate {
  name: string
  display_name: string
  description?: string
  run_strategy?: 'parallel' | 'sequential'
  composite_weights?: Record<string, number>
}

export interface TeamPatch {
  display_name?: string
  description?: string
  run_strategy?: 'parallel' | 'sequential'
  composite_weights?: Record<string, number>
}

export interface TeamRunRequest {
  trigger_source?: 'manual' | 'cron' | 'webhook'
  trigger_args?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const teamKeys = {
  all: ['skill-teams'] as const,
  list: () => [...teamKeys.all, 'list'] as const,
  detail: (id: number) => [...teamKeys.all, 'detail', id] as const,
  runs: (id: number, limit: number) => [...teamKeys.all, 'runs', id, limit] as const,
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useSkillTeams() {
  return useQuery({
    queryKey: teamKeys.list(),
    queryFn: async (): Promise<SkillTeam[]> => {
      const res = await fetch(`${API_URL}/api/teams`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error(`Failed to fetch teams (${res.status})`)
      return res.json()
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useSkillTeam(id: number | null) {
  return useQuery({
    queryKey: teamKeys.detail(id ?? 0),
    queryFn: async (): Promise<SkillTeam> => {
      const res = await fetch(`${API_URL}/api/teams/${id}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch team')
      return res.json()
    },
    enabled: id != null,
    staleTime: 5_000,
  })
}

export function useTeamRuns(teamId: number | null, limit = 20) {
  return useQuery({
    queryKey: teamKeys.runs(teamId ?? 0, limit),
    queryFn: async (): Promise<SkillTeamRun[]> => {
      const res = await fetch(`${API_URL}/api/teams/${teamId}/runs?limit=${limit}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch team runs')
      return res.json()
    },
    enabled: teamId != null,
    staleTime: 5_000,
    refetchInterval: 15_000,
  })
}

export function useCreateTeam() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (req: TeamCreate) => {
      const res = await fetch(`${API_URL}/api/teams`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      })
      if (!res.ok) throw new Error(`Failed to create team (${res.status})`)
      return res.json() as Promise<SkillTeam>
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: teamKeys.all })
    },
  })
}

export function usePatchTeam() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, patch }: { id: number; patch: TeamPatch }) => {
      const res = await fetch(`${API_URL}/api/teams/${id}`, {
        method: 'PATCH',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) throw new Error(`Failed to patch team (${res.status})`)
      return res.json() as Promise<SkillTeam>
    },
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: teamKeys.detail(id) })
      qc.invalidateQueries({ queryKey: teamKeys.list() })
    },
  })
}

export function useSetTeamMembers() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, skillIds }: { id: number; skillIds: number[] }) => {
      const res = await fetch(`${API_URL}/api/teams/${id}/members`, {
        method: 'PUT',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_ids: skillIds }),
      })
      if (!res.ok) throw new Error(`Failed to set team members (${res.status})`)
      return res.json()
    },
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: teamKeys.detail(id) })
      qc.invalidateQueries({ queryKey: teamKeys.list() })
    },
  })
}

export function useTriggerTeamRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, req }: { id: number; req: TeamRunRequest }) => {
      const res = await fetch(`${API_URL}/api/teams/${id}/run`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      })
      if (!res.ok) throw new Error(`Failed to trigger team run (${res.status})`)
      return res.json() as Promise<SkillTeamRun>
    },
    onSuccess: (_d, { id }) => {
      qc.invalidateQueries({ queryKey: teamKeys.runs(id, 20) })
      qc.invalidateQueries({ queryKey: teamKeys.list() })
    },
  })
}
