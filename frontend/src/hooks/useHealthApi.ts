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

export const metricsKeys = {
  all: ['metrics'] as const,
  summary: (hours?: number) => [...metricsKeys.all, 'summary', hours] as const,
  timeseries: (name: string) => [...metricsKeys.all, 'timeseries', name] as const,
  history: () => [...metricsKeys.all, 'history'] as const,
}

export const systemKeys = {
  disk: ['system', 'disk'] as const,
  alerting: ['system', 'alerting'] as const,
}

interface MetricsSummary {
  period_hours: number
  timestamp: string
  metrics: Record<string, {
    count: number
    avg: number
    min: number
    max: number
    p50: number
    p95: number
    p99: number
  }>
  counters: Record<string, number>
  gauges: Record<string, number>
}

interface DiskStatus {
  total_gb: number
  used_gb: number
  free_gb: number
  percent_used: number
  error?: string
}

interface AlertingStatus {
  active_issues: Record<string, boolean>
  recent_alerts: Record<string, string>
}

export function useSystemMetrics(hours: number = 24) {
  return useQuery({
    queryKey: metricsKeys.summary(hours),
    queryFn: () => fetchApi<MetricsSummary>(`/system/metrics?hours=${hours}`),
    refetchInterval: 30000,
  })
}

export function useDiskStatus() {
  return useQuery({
    queryKey: systemKeys.disk,
    queryFn: () => fetchApi<DiskStatus>('/system/disk'),
    refetchInterval: 60000,
  })
}

export function useAlertingStatus() {
  return useQuery({
    queryKey: systemKeys.alerting,
    queryFn: () => fetchApi<AlertingStatus>('/system/alerting/status'),
    refetchInterval: 15000,
  })
}

export function useMetricsHistory(limit: number = 24) {
  return useQuery({
    queryKey: metricsKeys.history(),
    queryFn: () =>
      fetchApi<{
        snapshots: Array<{
          id: number
          timestamp: string
          metrics_data: Record<string, unknown>
          period: string
        }>
        count: number
      }>(`/system/metrics/history?limit=${limit}`),
    refetchInterval: 60000,
  })
}
