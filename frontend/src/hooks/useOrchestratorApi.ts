import { useQuery } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type {
  PaginatedConversations,
  ConversationDetail,
  ThreadSummary,
  RouteStatEntry,
  OrchestratorActivityEvent,
} from '../types'

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

// Query key factories
export const orchestratorKeys = {
  all: ['orchestrator'] as const,
  conversations: (params?: Record<string, string | number | boolean>) =>
    [...orchestratorKeys.all, 'conversations', params] as const,
  conversation: (id: string) => [...orchestratorKeys.all, 'conversation', id] as const,
  threads: () => [...orchestratorKeys.all, 'threads'] as const,
  thread: (id: string) => [...orchestratorKeys.all, 'thread', id] as const,
  routeStats: (hours: number) => [...orchestratorKeys.all, 'routeStats', hours] as const,
  activityFeed: () => [...orchestratorKeys.all, 'activity'] as const,
  graphStatus: () => [...orchestratorKeys.all, 'graphStatus'] as const,
}

// ---- Conversations ----
export function useConversations(filters?: {
  channel?: string
  route?: string
  errors_only?: boolean
  limit?: number
  offset?: number
}) {
  const params = new URLSearchParams()
  if (filters?.channel) params.set('channel', filters.channel)
  if (filters?.route) params.set('route', filters.route)
  if (filters?.errors_only) params.set('errors_only', 'true')
  if (filters?.limit) params.set('limit', String(filters.limit))
  if (filters?.offset) params.set('offset', String(filters.offset))
  const qs = params.toString()

  return useQuery({
    queryKey: orchestratorKeys.conversations(filters as Record<string, string | number | boolean>),
    queryFn: () => fetchApi<PaginatedConversations>(`/orchestrator/conversations${qs ? `?${qs}` : ''}`),
    refetchInterval: 5000,
  })
}

// ---- Conversation Detail (with traces) ----
export function useConversationDetail(id: string | null) {
  return useQuery({
    queryKey: orchestratorKeys.conversation(id ?? ''),
    queryFn: () => fetchApi<ConversationDetail>(`/orchestrator/conversations/${id}`),
    enabled: !!id,
  })
}

// ---- Threads ----
export function useThreads(limit: number = 20) {
  return useQuery({
    queryKey: orchestratorKeys.threads(),
    queryFn: () => fetchApi<ThreadSummary[]>(`/orchestrator/threads?limit=${limit}`),
    refetchInterval: 10000,
  })
}

// ---- Thread History ----
export function useThreadHistory(threadId: string | null) {
  return useQuery({
    queryKey: orchestratorKeys.thread(threadId ?? ''),
    queryFn: () =>
      fetchApi<import('../types').OrchestratorConversation[]>(
        `/orchestrator/threads/${threadId}?limit=100`
      ),
    enabled: !!threadId,
  })
}

// ---- Route Stats ----
export function useRouteStats(hours: number = 24) {
  return useQuery({
    queryKey: orchestratorKeys.routeStats(hours),
    queryFn: () => fetchApi<RouteStatEntry[]>(`/orchestrator/graph/routes/stats?hours=${hours}`),
    refetchInterval: 30000,
  })
}

// ---- Activity Feed (polling fallback) ----
export function useActivityFeed(limit: number = 50) {
  return useQuery({
    queryKey: orchestratorKeys.activityFeed(),
    queryFn: () => fetchApi<OrchestratorActivityEvent[]>(`/orchestrator/activity/feed?limit=${limit}`),
    refetchInterval: 5000,
  })
}

// ---- Graph Status ----
export function useGraphStatus() {
  return useQuery({
    queryKey: orchestratorKeys.graphStatus(),
    queryFn: () =>
      fetchApi<{
        graph_compiled: boolean
        available_routes: string[]
        checkpointer: string
      }>('/orchestrator/graph/status'),
    refetchInterval: 60000,
  })
}
