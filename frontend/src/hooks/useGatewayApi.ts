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

const gatewayKeys = {
  health: ['gateway', 'health'] as const,
  status: ['gateway', 'status'] as const,
  channels: ['gateway', 'channels'] as const,
  agents: ['gateway', 'agents'] as const,
  agent: (id: string) => ['gateway', 'agent', id] as const,
}

export function useGatewayHealth() {
  return useQuery({
    queryKey: gatewayKeys.health,
    queryFn: () => fetchApi('/gateway/health'),
    refetchInterval: 30000,
  })
}

export function useGatewayStatus() {
  return useQuery({
    queryKey: gatewayKeys.status,
    queryFn: () => fetchApi('/gateway/status'),
    refetchInterval: 30000,
  })
}

export function useGatewayChannels() {
  return useQuery({
    queryKey: gatewayKeys.channels,
    queryFn: () => fetchApi('/gateway/channels'),
    refetchInterval: 30000,
  })
}

export function useGatewayAgents() {
  return useQuery({
    queryKey: gatewayKeys.agents,
    queryFn: () => fetchApi('/gateway/agents'),
    refetchInterval: 60000,
  })
}

export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      fetchApi('/gateway/agents', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: gatewayKeys.agents }),
  })
}

export function useUpdateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      fetchApi(`/gateway/agents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: gatewayKeys.agents }),
  })
}

export function useDeleteAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi(`/gateway/agents/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: gatewayKeys.agents }),
  })
}
