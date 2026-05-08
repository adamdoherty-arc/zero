import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders, getToken } from '@/lib/auth'

const API_URL = ''
const BASE = '/api/character-content/reference-videos'

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

export type RefVideoIntent = 'inbox' | 'inspiration' | 'facts' | 'discovery'
export type RefVideoStatus =
    | 'pending'
    | 'downloading'
    | 'downloaded'
    | 'transcribing'
    | 'analyzing'
    | 'ready'
    | 'failed'

export interface StyleAnalysis {
    hook?: string | null
    structure?: string | null
    pacing?: string | null
    visual_style?: string | null
    transitions?: string | null
    estimated_engagement?: string | null
}

export interface ExtractedFact {
    text: string
    category?: string | null
    surprise_score?: number | null
    source_timecode?: string | null
}

export interface ProposedCharacter {
    name?: string | null
    universe?: string | null
    franchise?: string | null
    description?: string | null
    seed_facts?: ExtractedFact[]
}

export interface CharacterReferenceVideo {
    id: string
    tiktok_url: string
    tiktok_video_id?: string | null
    character_id?: string | null
    intent: RefVideoIntent
    status: RefVideoStatus
    error_message?: string | null
    retry_count: number

    title?: string | null
    author_name?: string | null
    author_url?: string | null
    caption?: string | null
    hashtags: string[]
    duration_seconds?: number | null
    thumbnail_url?: string | null
    views?: number | null
    likes?: number | null

    video_path?: string | null
    thumbnail_path?: string | null
    audio_path?: string | null
    file_size_bytes?: number | null

    transcript?: string | null
    transcript_language?: string | null
    transcribed_at?: string | null

    style_analysis?: StyleAnalysis | null
    extracted_facts?: ExtractedFact[] | null
    proposed_character?: ProposedCharacter | null
    analyzed_at?: string | null

    notes?: string | null
    promoted_character_id?: string | null
    applied_fact_count: number

    created_at: string
    updated_at?: string | null
}

export interface RefVideoFilters {
    character_id?: string
    intent?: RefVideoIntent
    status?: RefVideoStatus
    limit?: number
    offset?: number
}

export interface IngestResponse {
    id: string
    status: RefVideoStatus
    tiktok_url: string
}

export interface ApplyFactsResponse {
    reference_video_id: string
    character_id: string
    applied_count: number
    total_fact_bank_size: number
}

export interface PromoteResponse {
    reference_video_id: string
    character_id: string
    status: string
}

// ----------------------------------------------------------------------------
// Query key factory
// ----------------------------------------------------------------------------

export const referenceVideoKeys = {
    all: ['reference-videos'] as const,
    list: (filters?: RefVideoFilters) => ['reference-videos', 'list', filters ?? {}] as const,
    detail: (id: string) => ['reference-videos', 'detail', id] as const,
}

// ----------------------------------------------------------------------------
// Fetch helper
// ----------------------------------------------------------------------------

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
    // DELETE endpoints may return minimal JSON; keep uniform
    return res.json() as Promise<T>
}

function buildQueryString(filters?: RefVideoFilters): string {
    if (!filters) return ''
    const params = new URLSearchParams()
    if (filters.character_id) params.set('character_id', filters.character_id)
    if (filters.intent) params.set('intent', filters.intent)
    if (filters.status) params.set('status', filters.status)
    if (filters.limit != null) params.set('limit', String(filters.limit))
    if (filters.offset != null) params.set('offset', String(filters.offset))
    const qs = params.toString()
    return qs ? `?${qs}` : ''
}

const INCOMPLETE: RefVideoStatus[] = [
    'pending',
    'downloading',
    'downloaded',
    'transcribing',
    'analyzing',
]

// ----------------------------------------------------------------------------
// Queries
// ----------------------------------------------------------------------------

export function useReferenceVideos(filters?: RefVideoFilters) {
    return useQuery({
        queryKey: referenceVideoKeys.list(filters),
        queryFn: () => fetchApi<CharacterReferenceVideo[]>(`${BASE}/${buildQueryString(filters)}`),
        refetchInterval: (query) => {
            const rows = query.state.data as CharacterReferenceVideo[] | undefined
            if (!rows || rows.length === 0) return false
            return rows.some((r) => INCOMPLETE.includes(r.status)) ? 10_000 : false
        },
    })
}

export function useReferenceVideo(id: string | undefined) {
    return useQuery({
        queryKey: referenceVideoKeys.detail(id ?? ''),
        queryFn: () => fetchApi<CharacterReferenceVideo>(`${BASE}/${id}`),
        enabled: !!id,
        refetchInterval: (query) => {
            const row = query.state.data as CharacterReferenceVideo | undefined
            if (!row) return false
            return INCOMPLETE.includes(row.status) ? 5_000 : false
        },
    })
}

// ----------------------------------------------------------------------------
// Mutations
// ----------------------------------------------------------------------------

export function useIngestReferenceVideo() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (payload: { url: string; character_id?: string; intent?: RefVideoIntent; notes?: string }) =>
            fetchApi<CharacterReferenceVideo>(`${BASE}/`, {
                method: 'POST',
                body: JSON.stringify({
                    tiktok_url: payload.url,
                    character_id: payload.character_id,
                    intent: payload.intent ?? 'inbox',
                    notes: payload.notes,
                }),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
        },
    })
}

export function useUpdateReferenceVideo() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            id,
            ...body
        }: {
            id: string
            intent?: RefVideoIntent
            character_id?: string | null
            notes?: string
        }) =>
            fetchApi<CharacterReferenceVideo>(`${BASE}/${id}`, {
                method: 'PATCH',
                body: JSON.stringify(body),
            }),
        onSuccess: (data) => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
            qc.setQueryData(referenceVideoKeys.detail(data.id), data)
        },
    })
}

export function useAssignReferenceVideoCharacter() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, character_id }: { id: string; character_id: string }) =>
            fetchApi<CharacterReferenceVideo>(`${BASE}/${id}/assign-character`, {
                method: 'POST',
                body: JSON.stringify({ character_id }),
            }),
        onSuccess: (data) => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
            qc.setQueryData(referenceVideoKeys.detail(data.id), data)
        },
    })
}

export function useApplyReferenceVideoFacts() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, fact_indexes }: { id: string; fact_indexes?: number[] }) =>
            fetchApi<ApplyFactsResponse>(`${BASE}/${id}/apply-facts`, {
                method: 'POST',
                body: JSON.stringify({ fact_indexes: fact_indexes ?? null }),
            }),
        onSuccess: (_data, vars) => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
            qc.invalidateQueries({ queryKey: referenceVideoKeys.detail(vars.id) })
            // Character fact bank changed
            qc.invalidateQueries({ queryKey: ['characters'] })
        },
    })
}

export function usePromoteReferenceVideoToCharacter() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            id,
            ...overrides
        }: {
            id: string
            name?: string
            universe?: string
            franchise?: string
            description?: string
        }) =>
            fetchApi<PromoteResponse>(`${BASE}/${id}/promote-to-character`, {
                method: 'POST',
                body: JSON.stringify(overrides),
            }),
        onSuccess: (_data, vars) => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
            qc.invalidateQueries({ queryKey: referenceVideoKeys.detail(vars.id) })
            qc.invalidateQueries({ queryKey: ['characters'] })
        },
    })
}

export function useReanalyzeReferenceVideo() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: string) =>
            fetchApi<CharacterReferenceVideo>(`${BASE}/${id}/analyze`, { method: 'POST' }),
        onSuccess: (data) => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
            qc.setQueryData(referenceVideoKeys.detail(data.id), data)
        },
    })
}

export function useRetryReferenceVideo() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: string) =>
            fetchApi<CharacterReferenceVideo>(`${BASE}/${id}/retry`, { method: 'POST' }),
        onSuccess: (data) => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
            qc.setQueryData(referenceVideoKeys.detail(data.id), data)
        },
    })
}

export function useDeleteReferenceVideo() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (id: string) =>
            fetchApi<{ status: string; id: string }>(`${BASE}/${id}`, { method: 'DELETE' }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: referenceVideoKeys.all })
        },
    })
}

// ----------------------------------------------------------------------------
// File URL builder (thumbnail/video/audio)
// ----------------------------------------------------------------------------

export function getReferenceVideoFileUrl(id: string, kind: 'video' | 'thumbnail' | 'audio'): string {
    const token = getToken()
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${BASE}/${id}/file/${kind}${qs}`
}
