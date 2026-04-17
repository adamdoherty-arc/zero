import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AutopilotStats {
  autopilot_enabled: boolean
  characters_discovered_24h: number
  carousels_auto_approved_24h: number
  gaps_filled_24h: number
  minimax_spend_today_usd: number
  minimax_daily_cap_usd: number
  minimax_pct_of_cap: number
  approved_queued_count: number
  human_review_queue_count: number
  priority_characters: number
  probation_characters: number
}

export interface AutopilotAction {
  id: number
  job_name: string
  started_at?: string | null
  completed_at?: string | null
  status: string
  duration_seconds?: number | null
  error?: string | null
}

export interface HumanReviewQueueItem {
  carousel_id: string
  character_id: string
  character_name?: string | null
  priority_tier?: string | null
  final_review_score?: number | null
  hook_text?: string | null
  angle?: string | null
  created_at?: string | null
}

export interface AutopilotBudget {
  date: string
  providers: Record<string, number>
  minimax: {
    spend_usd: number
    cap_usd: number
    pct_of_cap: number
    exceeded: boolean
  }
}

export interface DiscoveredCharacter {
  id: string
  name: string
  universe?: string | null
  discovery_source?: string | null
  discovery_hits: number
  research_status?: string | null
  priority_tier?: string | null
  created_at?: string | null
  evidence_summary?: string | null
}

export interface ResearchingCharacter {
  id: string
  name: string
  universe?: string | null
  research_status: string
  research_depth_score: number
  fact_count: number
  image_count: number
  last_researched?: string | null
}

export interface RecentCarousel {
  id: string
  character_id: string
  character_name?: string | null
  angle?: string | null
  hook_text?: string | null
  status: string
  final_review_score?: number | null
  auto_approved?: boolean | null
  created_at?: string | null
}

export interface AutopilotActivity {
  recently_discovered: DiscoveredCharacter[]
  currently_researching: ResearchingCharacter[]
  recent_carousels: RecentCarousel[]
  counts: {
    total_discovered: number
    total_researching: number
    total_pending_research: number
    total_in_progress_carousels: number
  }
}

export type AutopilotJob =
  | 'character_auto_approval'
  | 'character_publish_backlog'
  | 'character_gap_audit'
  | 'character_discovery'
  | 'character_discovery_refvideos'
  | 'character_hook_audit'

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${url}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return (await res.json()) as T
}

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

export const autopilotKeys = {
  all: ['character-autopilot'] as const,
  stats: () => [...autopilotKeys.all, 'stats'] as const,
  actions: (limit: number) => [...autopilotKeys.all, 'actions', limit] as const,
  humanQueue: (limit: number) => [...autopilotKeys.all, 'human-queue', limit] as const,
  budget: () => [...autopilotKeys.all, 'budget'] as const,
  activity: (limit: number) => [...autopilotKeys.all, 'activity', limit] as const,
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useAutopilotStats() {
  return useQuery({
    queryKey: autopilotKeys.stats(),
    queryFn: () => fetchJson<AutopilotStats>('/api/characters/autopilot/stats'),
    refetchInterval: 30_000,
  })
}

export function useAutopilotActions(limit = 20) {
  return useQuery({
    queryKey: autopilotKeys.actions(limit),
    queryFn: () => fetchJson<AutopilotAction[]>(`/api/characters/autopilot/actions?limit=${limit}`),
    refetchInterval: 60_000,
  })
}

export function useAutopilotHumanQueue(limit = 20) {
  return useQuery({
    queryKey: autopilotKeys.humanQueue(limit),
    queryFn: () => fetchJson<HumanReviewQueueItem[]>(`/api/characters/autopilot/human-queue?limit=${limit}`),
    refetchInterval: 60_000,
  })
}

export function useAutopilotBudget() {
  return useQuery({
    queryKey: autopilotKeys.budget(),
    queryFn: () => fetchJson<AutopilotBudget>('/api/characters/autopilot/budget'),
    refetchInterval: 60_000,
  })
}

export function useAutopilotActivity(limit = 10) {
  return useQuery({
    queryKey: autopilotKeys.activity(limit),
    queryFn: () => fetchJson<AutopilotActivity>(`/api/characters/autopilot/activity?limit=${limit}`),
    refetchInterval: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useAutopilotToggle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      fetchJson<{ autopilot_enabled: boolean }>('/api/characters/autopilot/toggle', {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: autopilotKeys.stats() }),
  })
}

export function useAutopilotTrigger() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (job: AutopilotJob) =>
      fetchJson<{ job: string; status: string; result: Record<string, unknown> }>(
        `/api/characters/autopilot/trigger/${job}`,
        { method: 'POST' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: autopilotKeys.all }),
  })
}

export function useAutonomousToggle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (characterId: string) =>
      fetchJson<{ character_id: string; autonomous_disabled: boolean }>(
        `/api/characters/${characterId}/autonomous/toggle`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: autopilotKeys.all })
      qc.invalidateQueries({ queryKey: ['characters'] })
    },
  })
}
