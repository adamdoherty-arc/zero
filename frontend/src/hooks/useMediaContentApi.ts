import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MediaType = 'tv_show' | 'movie'
export type MediaContentAngle =
  | 'plot_holes' | 'best_episodes' | 'showrunner_secrets' | 'casting_stories'
  | 'deleted_scenes' | 'fan_theories' | 'sequel_predictions' | 'box_office_analysis'
  | 'cinematography' | 'soundtrack_breakdown' | 'season_ranking' | 'hidden_details'
  | 'production_disasters' | 'cultural_impact' | 'adaptation_changes' | 'controversial_decisions'

export type MediaStoryTemplate =
  | 'episode_breakdown' | 'season_arc_analysis' | 'directors_vision' | 'behind_the_scenes'
  | 'cast_chemistry' | 'franchise_timeline' | 'remake_comparison' | 'box_office_battle'
  | 'genre_evolution' | 'cliffhanger_ranking' | 'iconic_scenes' | 'writers_room'

export interface MediaTitle {
  id: string
  media_type: MediaType
  title: string
  year?: number
  end_year?: number
  genre: string[]
  franchise?: string
  universe?: string
  poster_url?: string
  backdrop_url?: string
  synopsis?: string
  tagline?: string
  // TV-specific
  season_count?: number
  episode_count?: number
  network?: string
  show_status?: string
  // Movie-specific
  runtime_minutes?: number
  budget_usd?: number
  box_office_usd?: number
  mpaa_rating?: string
  // Research
  research_data: Record<string, unknown>
  research_status: string
  fact_bank: Array<{ fact: string; category: string; surprise_score: number; source?: string }>
  research_sources: string[]
  research_depth_score: number
  content_themes: string[]
  // External IDs
  tmdb_id?: number
  imdb_id?: string
  // Stats
  carousels_created: number
  total_views: number
  total_likes: number
  avg_engagement: number
  // Meta
  status: string
  tags: string[]
  created_at?: string
  updated_at?: string
  last_researched?: string
  character_count: number
}

export interface CharacterMediaLink {
  id: string
  character_id: string
  media_title_id: string
  character_name?: string
  media_title_name?: string
  role_name?: string
  role_type: string
  actor_name?: string
  seasons_appeared: number[]
  notes?: string
  created_at?: string
  // Deep-link fields populated by the joined endpoint.
  character_image_url?: string
  character_status?: string
  media_type?: string
  media_year?: number
  media_poster_url?: string
  media_franchise?: string
  media_universe?: string
}

export interface MediaImage {
  id: string
  media_title_id: string
  url: string
  source: string
  query_used?: string
  width?: number
  height?: number
  is_valid: boolean
  is_primary: boolean
  usage_count: number
  quality_score: number
  is_approved?: boolean
  created_at?: string
}

export interface MediaStats {
  total_titles: number
  tv_shows: number
  movies: number
  titles_researched: number
  total_carousels: number
  carousels_by_status: Record<string, number>
  total_published: number
  total_views: number
  total_likes: number
  avg_engagement_rate: number
  top_titles: Array<Record<string, unknown>>
  top_angles: Array<Record<string, unknown>>
}

export interface TMDBSearchResult {
  tmdb_id: number
  title: string
  media_type: string
  year?: number
  overview?: string
  poster_url?: string
  vote_average?: number
  already_imported: boolean
}

export interface AngleOption {
  value: string
  label: string
}

export interface TemplateOption {
  value: string
  label: string
}

// ---------------------------------------------------------------------------
// Query key factory
// ---------------------------------------------------------------------------

const mediaKeys = {
  all: ['media-content'] as const,
  stats: () => [...mediaKeys.all, 'stats'] as const,
  titles: (filters?: Record<string, unknown>) => [...mediaKeys.all, 'titles', filters] as const,
  title: (id: string) => [...mediaKeys.all, 'title', id] as const,
  carousels: (filters?: Record<string, unknown>) => [...mediaKeys.all, 'carousels', filters] as const,
  linkedCharacters: (mediaId: string) => [...mediaKeys.all, 'linked-characters', mediaId] as const,
  characterMedia: (charId: string) => [...mediaKeys.all, 'character-media', charId] as const,
  images: (mediaId: string) => [...mediaKeys.all, 'images', mediaId] as const,
  tmdbSearch: (query: string) => [...mediaKeys.all, 'tmdb-search', query] as const,
  angles: () => [...mediaKeys.all, 'angles'] as const,
  templates: () => [...mediaKeys.all, 'templates'] as const,
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function fetchMedia<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}/api/media-content${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// ---------------------------------------------------------------------------
// Query Hooks
// ---------------------------------------------------------------------------

export function useMediaStats() {
  return useQuery({
    queryKey: mediaKeys.stats(),
    queryFn: () => fetchMedia<MediaStats>('/stats'),
  })
}

export function useMediaTitles(filters?: {
  media_type?: string
  universe?: string
  status?: string
  research_status?: string
  limit?: number
  offset?: number
}) {
  const params = new URLSearchParams()
  if (filters?.media_type) params.set('media_type', filters.media_type)
  if (filters?.universe) params.set('universe', filters.universe)
  if (filters?.status) params.set('status', filters.status)
  if (filters?.research_status) params.set('research_status', filters.research_status)
  if (filters?.limit) params.set('limit', String(filters.limit))
  if (filters?.offset) params.set('offset', String(filters.offset))

  const qs = params.toString()
  return useQuery({
    queryKey: mediaKeys.titles(filters),
    queryFn: () => fetchMedia<MediaTitle[]>(`/titles${qs ? `?${qs}` : ''}`),
  })
}

export function useMediaTitle(id: string) {
  return useQuery({
    queryKey: mediaKeys.title(id),
    queryFn: () => fetchMedia<MediaTitle>(`/titles/${id}`),
    enabled: !!id,
  })
}

export function useMediaCarousels(filters?: {
  media_title_id?: string
  status?: string
  angle?: string
  limit?: number
}) {
  const params = new URLSearchParams()
  if (filters?.media_title_id) params.set('media_title_id', filters.media_title_id)
  if (filters?.status) params.set('status', filters.status)
  if (filters?.angle) params.set('angle', filters.angle)
  if (filters?.limit) params.set('limit', String(filters.limit))

  const qs = params.toString()
  return useQuery({
    queryKey: mediaKeys.carousels(filters),
    queryFn: () => fetchMedia<unknown[]>(`/carousels${qs ? `?${qs}` : ''}`),
  })
}

export function useLinkedCharacters(mediaId: string) {
  return useQuery({
    queryKey: mediaKeys.linkedCharacters(mediaId),
    queryFn: () => fetchMedia<CharacterMediaLink[]>(`/titles/${mediaId}/characters`),
    enabled: !!mediaId,
  })
}

export function useCharacterMedia(characterId: string) {
  return useQuery({
    queryKey: mediaKeys.characterMedia(characterId),
    queryFn: () => fetchMedia<CharacterMediaLink[]>(`/characters/${characterId}/media`),
    enabled: !!characterId,
  })
}

export function useMediaImages(mediaId: string) {
  return useQuery({
    queryKey: mediaKeys.images(mediaId),
    queryFn: () => fetchMedia<MediaImage[]>(`/titles/${mediaId}/images`),
    enabled: !!mediaId,
  })
}

export function useTMDBSearch(query: string, mediaType?: string) {
  const params = new URLSearchParams({ q: query })
  if (mediaType) params.set('media_type', mediaType)
  return useQuery({
    queryKey: mediaKeys.tmdbSearch(query + (mediaType || '')),
    queryFn: () => fetchMedia<TMDBSearchResult[]>(`/search-tmdb?${params}`),
    enabled: query.length >= 2,
  })
}

export function useMediaAngles() {
  return useQuery({
    queryKey: mediaKeys.angles(),
    queryFn: () => fetchMedia<AngleOption[]>('/angles'),
    staleTime: Infinity,
  })
}

export function useMediaTemplates() {
  return useQuery({
    queryKey: mediaKeys.templates(),
    queryFn: () => fetchMedia<TemplateOption[]>('/templates'),
    staleTime: Infinity,
  })
}

// ---------------------------------------------------------------------------
// Mutation Hooks
// ---------------------------------------------------------------------------

export function useCreateMediaTitle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      title: string
      media_type: MediaType
      year?: number
      synopsis?: string
      tmdb_id?: number
      franchise?: string
      universe?: string
      genre?: string[]
      tags?: string[]
    }) => fetchMedia<MediaTitle>('/titles', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKeys.titles() })
      qc.invalidateQueries({ queryKey: mediaKeys.stats() })
    },
  })
}

export function useUpdateMediaTitle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Record<string, unknown>) =>
      fetchMedia<MediaTitle>(`/titles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: mediaKeys.title(vars.id) })
      qc.invalidateQueries({ queryKey: mediaKeys.titles() })
    },
  })
}

export function useDeleteMediaTitle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => fetchMedia<void>(`/titles/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKeys.titles() })
      qc.invalidateQueries({ queryKey: mediaKeys.stats() })
    },
  })
}

export function useResearchMediaTitle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => fetchMedia<MediaTitle>(`/titles/${id}/research`, { method: 'POST' }),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: mediaKeys.title(id) })
      qc.invalidateQueries({ queryKey: mediaKeys.titles() })
    },
  })
}

export function useGenerateMediaCarousel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      media_title_id: string
      angle?: string
      story_template?: string
      character_id?: string
      slide_count?: number
      hook_style?: string
      content_format?: string
    }) =>
      fetchMedia<unknown>(`/titles/${data.media_title_id}/generate`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKeys.carousels() })
      qc.invalidateQueries({ queryKey: mediaKeys.stats() })
    },
  })
}

export function useLinkCharacter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      media_title_id: string
      character_id: string
      role_name?: string
      role_type?: string
      actor_name?: string
    }) =>
      fetchMedia<CharacterMediaLink>(`/titles/${data.media_title_id}/characters`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: mediaKeys.linkedCharacters(vars.media_title_id) })
      qc.invalidateQueries({ queryKey: mediaKeys.characterMedia(vars.character_id) })
      qc.invalidateQueries({ queryKey: mediaKeys.title(vars.media_title_id) })
    },
  })
}

export function useUnlinkCharacter() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ mediaId, characterId }: { mediaId: string; characterId: string }) =>
      fetchMedia<void>(`/titles/${mediaId}/characters/${characterId}`, { method: 'DELETE' }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: mediaKeys.linkedCharacters(vars.mediaId) })
      qc.invalidateQueries({ queryKey: mediaKeys.characterMedia(vars.characterId) })
    },
  })
}

export function useSeedMediaTitles() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params?: { count?: number; media_type?: string }) => {
      const qs = new URLSearchParams()
      if (params?.count) qs.set('count', String(params.count))
      if (params?.media_type) qs.set('media_type', params.media_type)
      return fetchMedia<MediaTitle[]>(`/seed?${qs}`, { method: 'POST' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: mediaKeys.titles() })
      qc.invalidateQueries({ queryKey: mediaKeys.stats() })
    },
  })
}

export function useAddMediaImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { media_title_id: string; url: string; source?: string }) =>
      fetchMedia<MediaImage>(`/titles/${data.media_title_id}/images`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: mediaKeys.images(vars.media_title_id) })
    },
  })
}

export function useDeleteMediaImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ mediaId, imageId }: { mediaId: string; imageId: string }) =>
      fetchMedia<void>(`/titles/${mediaId}/images/${imageId}`, { method: 'DELETE' }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: mediaKeys.images(vars.mediaId) })
    },
  })
}
