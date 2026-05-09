import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

export interface BriefSection {
  title: string
  body: string
  bullets: string[]
  error?: string | null
}

export interface BriefPayload {
  date: string
  sections: BriefSection[]
  markdown: string
  spoken_summary: string
  generated_at: number
}

const API_URL = ''

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { headers: { ...getAuthHeaders() } })
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json()
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json()
}

export function useDailyBriefToday() {
  return useQuery<BriefPayload>({
    queryKey: ['daily-brief', 'today'],
    queryFn: () => getJson<BriefPayload>('/api/daily-brief/today'),
    staleTime: 60_000,
  })
}

export function useDailyBriefHistory(limit = 14) {
  return useQuery<{ briefs: BriefPayload[] }>({
    queryKey: ['daily-brief', 'history', limit],
    queryFn: () => getJson(`/api/daily-brief/history?limit=${limit}`),
    staleTime: 5 * 60_000,
  })
}

export function useRegenerateBrief() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => postJson<BriefPayload>('/api/daily-brief/regenerate'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['daily-brief'] }),
  })
}

export function useSendBriefNow() {
  return useMutation({
    mutationFn: (params?: { to?: string; from_account?: string; regenerate?: boolean }) =>
      postJson<{ brief_date: string; sent: boolean; error?: string }>(
        '/api/daily-brief/send-now',
        params ?? {},
      ),
  })
}

export function useSpeakBrief() {
  return useMutation({
    mutationFn: async (text: string) => {
      const r = await fetch('/api/tts/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ text }),
      })
      if (!r.ok) throw new Error(`tts ${r.status}`)
      const buf = await r.arrayBuffer()
      const blob = new Blob([buf], { type: 'audio/wav' })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      await audio.play()
      return true
    },
  })
}
