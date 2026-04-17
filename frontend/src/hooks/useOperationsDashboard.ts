import { useQuery } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

async function fetchApi<T>(url: string): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

export const operationsDashboardKeys = {
  all: ['operations-dashboard'] as const,
  snapshot: () => [...operationsDashboardKeys.all, 'snapshot'] as const,
}

export interface OperationsKpis {
  daily_grade: number | null
  success_rate_24h: number | null
  total_runs_24h: number
  active_alerts: number
  llm_spend_usd: number
  llm_budget_usd: number
  conversations_today: number
}

export interface ActiveIssue {
  type: string
  name: string
  message: string
  severity: 'info' | 'warning' | 'error'
  since: string | null
}

export interface RecentFailure {
  job_name: string
  failed_at: string | null
  error: string
  duration_s: number
}

export interface LiveActivityEvent {
  timestamp: string | null
  type: 'job' | 'conversation'
  summary: string
  status: string
}

export interface LlmProviderStatus {
  name: string
  healthy: boolean
  circuit_state: string
  spend_today_usd: number
  error?: string
}

export interface OperationsSnapshot {
  snapshot_time: string
  kpis: OperationsKpis
  service_health: Record<string, string>
  active_issues: ActiveIssue[]
  recent_failures: RecentFailure[]
  live_activity: LiveActivityEvent[]
  llm_providers: LlmProviderStatus[]
  errors: string[]
}

export function useOperationsDashboard() {
  return useQuery<OperationsSnapshot>({
    queryKey: operationsDashboardKeys.snapshot(),
    queryFn: () => fetchApi('/system/operations-dashboard'),
    refetchInterval: 15000,
    staleTime: 10000,
  })
}
