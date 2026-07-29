import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

// Same-origin API base. Mirrors useCharacterContentApi.ts — the frontend is
// served behind the same nginx that proxies /api/* to zero-api, so relative
// paths resolve correctly. Exposed so <video src> can be built explicitly.
export const API_URL = ''
export const apiBase = API_URL

// ============================================
// TYPES
// ============================================

export type ReelSubNiche =
    | 'stoicism'
    | 'discipline'
    | 'wealth_mindset'
    | 'self_improvement'
    | 'faith'
    | 'grindset'
    | 'mental_health'
    | 'entrepreneurship'
    | 'affirmations'

export type ReelMood =
    | 'epic'
    | 'calm'
    | 'hopeful'
    | 'dark'
    | 'intense'
    | 'reflective'
    | 'uplifting'

export type ReelStatus =
    | 'pending'
    | 'sourcing'
    | 'planning'
    | 'rendering'
    | 'assembling'
    | 'awaiting_review'
    | 'publishing'
    | 'published'
    | 'abandoned'
    | 'failed'

export type ReelQuoteAttribution = 'verified' | 'unverified' | 'anonymous' | string

export interface ReelQuote {
    text: string
    author?: string
    attribution?: ReelQuoteAttribution
    source_work?: string
}

export interface ReelScene {
    scene_num: number
    role: string
    text: string
    duration_s: number
}

export interface ReelMusic {
    title: string
    mood?: string
    bpm?: number
}

export interface ReelPlatformPublish {
    platform: string
    status: string
    post_id?: string | null
    dry_run?: boolean
}

export interface ReelRow {
    id: string
    reel_id: string
    sub_niche: ReelSubNiche | string
    theme?: string
    mood?: ReelMood | string
    quote: ReelQuote
    scenes: ReelScene[]
    music?: ReelMusic | null
    voiceover: boolean
    video_url?: string | null
    duration_s?: number | null
    caption?: string
    hashtags: string[]
    cta_text?: string
    composite_score?: number | null
    status: ReelStatus
    created_at?: string
    platform_publishes: ReelPlatformPublish[]
}

export interface MusicTrack {
    id: string
    title: string
    mood?: string
    bpm?: number
    duration_s?: number | null
    source?: string
    is_bakeable?: boolean
    [key: string]: unknown
}

export interface GenerateReelRequest {
    sub_niche?: ReelSubNiche
    theme?: string
    quote_text?: string
    quote_author?: string
    scene_count?: number
    target_duration_s?: number
    voiceover?: boolean
    mood?: ReelMood
    music_track_id?: string
    auto_publish?: boolean
    platforms?: string[]
}

export interface GenerateReelStartedResponse {
    generation_id: string
    status: 'started'
}

export interface ReelPublishResponse {
    ok: boolean
    status?: string
    platform_publishes?: ReelPlatformPublish[]
}

export interface ReelMusicResponse {
    tracks: MusicTrack[]
}

export interface SeedMusicResponse {
    ok: boolean
    bakeable_tracks: number
}

interface ReelListResponse {
    reels: ReelRow[]
}

export interface ReelFilters {
    limit?: number
    status?: ReelStatus
    sub_niche?: ReelSubNiche
}

// In-progress statuses used to drive polling on the list page.
export const REEL_IN_PROGRESS_STATUSES: ReelStatus[] = [
    'pending',
    'sourcing',
    'planning',
    'rendering',
    'assembling',
    'publishing',
]

// ============================================
// QUERY KEYS
// ============================================

export const reelKeys = {
    all: ['reels'] as const,
    list: (filters?: ReelFilters) => ['reels', 'list', filters ?? {}] as const,
    detail: (id: string) => ['reels', 'detail', id] as const,
    music: ['reels', 'music'] as const,
}

// ============================================
// FETCH HELPER
// ============================================

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${API_URL}${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
            ...options?.headers,
        },
    })
    if (!res.ok) {
        const error = await res.text()
        throw new Error(`API error ${res.status}: ${error}`)
    }
    return res.json()
}

// ============================================
// QUERIES
// ============================================

export function useReels(filters?: ReelFilters, refetchInterval?: number | false) {
    const params = new URLSearchParams()
    if (filters?.limit != null) params.set('limit', String(filters.limit))
    if (filters?.status) params.set('status', filters.status)
    if (filters?.sub_niche) params.set('sub_niche', filters.sub_niche)
    const qs = params.toString() ? `?${params}` : ''

    return useQuery({
        queryKey: reelKeys.list(filters),
        queryFn: async () => {
            const data = await fetchApi<ReelListResponse>(`/api/reels${qs}`)
            return data.reels
        },
        // Poll while any reel is mid-pipeline so freshly generated reels appear
        // and advance through statuses without a manual refresh. Settles to no
        // polling once everything has reached a terminal/review state.
        refetchInterval:
            refetchInterval !== undefined
                ? refetchInterval
                : (query) => {
                      const rows = query.state.data
                      if (Array.isArray(rows) && rows.some((r) => REEL_IN_PROGRESS_STATUSES.includes(r.status))) {
                          return 5000
                      }
                      return false
                  },
    })
}

export function useReel(id: string) {
    return useQuery({
        queryKey: reelKeys.detail(id),
        queryFn: () => fetchApi<ReelRow>(`/api/reels/${id}`),
        enabled: !!id,
    })
}

export function useReelMusic() {
    return useQuery({
        queryKey: reelKeys.music,
        queryFn: async () => {
            const data = await fetchApi<ReelMusicResponse>('/api/reels/music')
            return data.tracks
        },
    })
}

// ============================================
// MUTATIONS
// ============================================

export function useGenerateReel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: GenerateReelRequest) =>
            fetchApi<GenerateReelStartedResponse>('/api/reels/generate?wait=false', {
                method: 'POST',
                body: JSON.stringify(data),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: reelKeys.all }),
    })
}

export function useApproveReel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: string) =>
            fetchApi<ReelPublishResponse>(`/api/reels/${id}/approve`, { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: reelKeys.all }),
    })
}

export function useRejectReel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: string) =>
            fetchApi<{ ok: boolean; status: string }>(`/api/reels/${id}/reject`, { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: reelKeys.all }),
    })
}

export function usePublishReel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, platforms }: { id: string; platforms?: string[] }) => {
            const qs = platforms && platforms.length > 0 ? `?platforms=${platforms.join(',')}` : ''
            return fetchApi<ReelPublishResponse>(`/api/reels/${id}/publish${qs}`, { method: 'POST' })
        },
        onSuccess: () => qc.invalidateQueries({ queryKey: reelKeys.all }),
    })
}

export function useSeedReelMusic() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: () => fetchApi<SeedMusicResponse>('/api/reels/music/seed', { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: reelKeys.music }),
    })
}
