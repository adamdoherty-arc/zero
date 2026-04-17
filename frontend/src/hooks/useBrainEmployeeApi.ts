import { useQuery } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

export interface EmployeeOverview {
  carousels_last_24h: number
  trending_signals_active: number
  swarm_predictions_7d: number
  competitor_samples_active: number
  active_prompt_variants: number
  benchmark_overall: number | null
  weakest_dimension: string | null
  last_benchmark_at: string | null
}

export interface AgentStat {
  role_name: string
  total_predictions_30d: number
  avg_confidence: number
  avg_calibration_error: number | null
  accept_count: number
  reject_count: number
  accept_rate: number
}

export interface TrendingFeedItem {
  id: string
  source: string
  title: string
  franchise: string | null
  media_type: string | null
  release_date: string | null
  signal_strength: number
  linked_character_count: number
  linked_media_title_count: number
}

export interface EmployeeCost {
  total_llm_cost_usd_7d: number
  carousels_7d: number
  cost_per_carousel_usd: number | null
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

export function useEmployeeOverview() {
  return useQuery<EmployeeOverview>({
    queryKey: ['brain', 'employee', 'overview'],
    queryFn: () => fetchJson<EmployeeOverview>('/api/brain/employee/overview'),
    refetchInterval: 60_000,
  })
}

export function useAgentStats() {
  return useQuery<AgentStat[]>({
    queryKey: ['brain', 'employee', 'agent-stats'],
    queryFn: () => fetchJson<AgentStat[]>('/api/brain/employee/agent-stats'),
    refetchInterval: 120_000,
  })
}

export function useTrendingFeed(limit = 10) {
  return useQuery<TrendingFeedItem[]>({
    queryKey: ['brain', 'employee', 'trending', limit],
    queryFn: () => fetchJson<TrendingFeedItem[]>(`/api/brain/employee/trending?limit=${limit}`),
    refetchInterval: 60_000,
  })
}

export function useEmployeeCost() {
  return useQuery<EmployeeCost>({
    queryKey: ['brain', 'employee', 'cost'],
    queryFn: () => fetchJson<EmployeeCost>('/api/brain/employee/cost'),
    refetchInterval: 300_000,
  })
}
