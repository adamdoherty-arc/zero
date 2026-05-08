import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

export interface QuietHours {
  enabled?: boolean
  start?: string
  end?: string
  weekdays_only?: boolean
}

export interface OAuthAccount {
  id: string
  label: string
  email: string
  is_default: boolean
  scopes: string[]
  quiet_hours: QuietHours
  metadata: Record<string, unknown>
  connected_at: string | null
  last_refreshed_at: string | null
}

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const oauthAccountKeys = {
  all: ['oauth-accounts'] as const,
  list: () => [...oauthAccountKeys.all, 'list'] as const,
  detail: (id: string) => [...oauthAccountKeys.all, 'detail', id] as const,
}

export function useOAuthAccounts() {
  return useQuery({
    queryKey: oauthAccountKeys.list(),
    queryFn: () => fetchApi<{ accounts: OAuthAccount[]; total: number }>('/oauth/accounts'),
    refetchInterval: 60_000,
  })
}

export function useDisconnectAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (account_id: string) =>
      fetchApi<unknown>(`/oauth/accounts/${account_id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: oauthAccountKeys.all }),
  })
}

export function useSetDefaultAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (account_id: string) =>
      fetchApi<unknown>(`/oauth/accounts/${account_id}/default`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: oauthAccountKeys.all }),
  })
}

export function useSetAccountLabel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ account_id, label }: { account_id: string; label: string }) =>
      fetchApi<unknown>(`/oauth/accounts/${account_id}/label`, {
        method: 'PATCH',
        body: JSON.stringify({ label }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: oauthAccountKeys.all }),
  })
}

export function useSetQuietHours() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ account_id, quiet_hours }: { account_id: string; quiet_hours: QuietHours }) =>
      fetchApi<unknown>(`/oauth/accounts/${account_id}/quiet-hours`, {
        method: 'PATCH',
        body: JSON.stringify(quiet_hours),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: oauthAccountKeys.all }),
  })
}

/**
 * Build the URL that starts a new OAuth flow for a given label.
 * Caller `window.location.href = startAuthUrl('work')` to redirect.
 */
export function startAuthUrl(label: string): string {
  return `${API_BASE}/google/auth/start?label=${encodeURIComponent(label)}`
}
