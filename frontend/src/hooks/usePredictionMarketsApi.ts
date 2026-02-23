import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types
export interface PredictionMarket {
  id: string
  platform: string
  ticker: string
  title: string
  category: string
  yes_price: number
  no_price: number
  volume: number
  open_interest: number
  status: string
  close_time: string | null
  result: string | null
  last_synced_at: string | null
  created_at: string
}

export interface PredictionBettor {
  id: string
  platform: string
  bettor_address: string
  display_name: string | null
  total_trades: number
  win_count: number
  loss_count: number
  win_rate: number
  total_volume: number
  pnl_total: number
  avg_bet_size: number
  best_streak: number
  current_streak: number
  categories: string[]
  composite_score: number
  last_active_at: string | null
  tracked_since: string | null
}

export interface PredictionStats {
  total_markets: number
  open_markets: number
  kalshi_markets: number
  polymarket_markets: number
  total_bettors: number
  avg_composite_score: number
  total_volume: number
  last_sync: string | null
}

export interface QualityReport {
  data_health: Record<string, unknown>
  sync_status: Record<string, unknown>
  bettor_quality: Record<string, unknown>
  ada_push_status: Record<string, unknown>
}

export interface LegionStatus {
  zero_sprint: Record<string, unknown>
  ada_sprints: Record<string, unknown>[]
  overall_progress: number
  error?: string
  status?: string
}

// Hooks
export function usePredictionStats() {
  return useQuery({
    queryKey: ['prediction-markets', 'stats'],
    queryFn: async (): Promise<PredictionStats> => {
      const res = await fetch(`${API_URL}/api/prediction-markets/stats`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch stats')
      return res.json()
    },
    refetchInterval: 60_000,
  })
}

export function usePredictionMarkets(params?: {
  platform?: string
  category?: string
  status?: string
  limit?: number
}) {
  return useQuery({
    queryKey: ['prediction-markets', 'list', params],
    queryFn: async (): Promise<{ markets: PredictionMarket[]; count: number }> => {
      const qp = new URLSearchParams()
      if (params?.platform) qp.set('platform', params.platform)
      if (params?.category) qp.set('category', params.category)
      if (params?.status) qp.set('status', params.status)
      if (params?.limit) qp.set('limit', String(params.limit))
      const res = await fetch(`${API_URL}/api/prediction-markets/markets?${qp}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch markets')
      return res.json()
    },
  })
}

export function usePredictionBettors(params?: {
  platform?: string
  min_win_rate?: number
  limit?: number
}) {
  return useQuery({
    queryKey: ['prediction-markets', 'bettors', params],
    queryFn: async (): Promise<{ bettors: PredictionBettor[]; count: number }> => {
      const qp = new URLSearchParams()
      if (params?.platform) qp.set('platform', params.platform)
      if (params?.min_win_rate) qp.set('min_win_rate', String(params.min_win_rate))
      if (params?.limit) qp.set('limit', String(params.limit))
      const res = await fetch(`${API_URL}/api/prediction-markets/bettors?${qp}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch bettors')
      return res.json()
    },
  })
}

export function usePredictionQualityReport() {
  return useQuery({
    queryKey: ['prediction-markets', 'quality'],
    queryFn: async (): Promise<QualityReport> => {
      const res = await fetch(`${API_URL}/api/prediction-markets/quality-report`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch quality report')
      return res.json()
    },
  })
}

export function usePredictionLegionStatus() {
  return useQuery({
    queryKey: ['prediction-markets', 'legion'],
    queryFn: async (): Promise<LegionStatus> => {
      const res = await fetch(`${API_URL}/api/prediction-markets/legion-status`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch legion status')
      return res.json()
    },
  })
}

export function useSyncKalshi() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_URL}/api/prediction-markets/sync/kalshi`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to sync Kalshi')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prediction-markets'] })
    },
  })
}

export function useSyncPolymarket() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_URL}/api/prediction-markets/sync/polymarket`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to sync Polymarket')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prediction-markets'] })
    },
  })
}

export function useSyncBettors() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_URL}/api/prediction-markets/sync/bettors`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to sync bettors')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prediction-markets'] })
    },
  })
}

export function useRunFullCycle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_URL}/api/prediction-markets/cycle/run`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to run cycle')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prediction-markets'] })
    },
  })
}

export function usePushToAda() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_URL}/api/prediction-markets/push`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to push to ADA')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prediction-markets'] })
    },
  })
}
