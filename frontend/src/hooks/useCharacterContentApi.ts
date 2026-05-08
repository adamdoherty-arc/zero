import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types

export type CharacterUniverse = 'marvel' | 'dc' | 'star_wars' | 'lotr' | 'harry_potter' | 'anime' | 'tv' | 'film' | 'gaming' | 'other'
export type CharacterStatus = 'active' | 'paused' | 'archived' | 'pending'
export type ResearchStatus = 'pending' | 'researching' | 'completed' | 'failed'
export type CarouselStatus = 'draft' | 'ai_reviewed' | 'pending_review' | 'approved' | 'rejected' | 'publishing' | 'published'
export type ContentAngle = 'hidden_truths' | 'power_secrets' | 'underrated_moments' | 'origin_story' | 'character_evolution' | 'controversial_takes' | 'vs_comparison' | 'behind_scenes' | 'fan_theories' | 'dark_facts' | 'actor_secrets' | 'easter_eggs' | 'crossover_connections' | 'what_if' | 'timeline_deep_dive' | 'storyline_recap' | 'power_ranking'

export interface CharacterFact {
    text: string
    category: string
    surprise_score: number
    source?: string
    verified?: boolean
}

export interface Character {
    id: string
    name: string
    universe: string
    franchise?: string
    real_name?: string
    description?: string
    image_url?: string
    image_urls: string[]
    research_data: Record<string, unknown>
    research_status: ResearchStatus
    fact_bank: CharacterFact[]
    tags: string[]
    posts_created: number
    carousels_created: number
    total_views: number
    total_likes: number
    avg_engagement: number
    status: CharacterStatus
    created_at?: string
    updated_at?: string
    last_researched?: string
    research_sources: string[]
    relationship_map: Record<string, unknown>
    research_depth_score: number
    content_themes: string[]
    blocked_image_urls: string[]
    appears_in?: CharacterAppearance[]
}

export interface CharacterAppearance {
    link_id: string
    media_title_id: string
    title: string
    media_type: 'movie' | 'tv_show' | string
    year?: number
    poster_url?: string
    role_name?: string
    role_type?: 'lead' | 'supporting' | 'recurring' | 'guest' | 'cameo' | string
    actor_name?: string
    franchise?: string
    universe?: string
}

export interface CarouselSlide {
    slide_num: number
    text: string
    image_query?: string
    image_url?: string
    font_style?: string
    accent_color?: string
    accent_secondary?: string
}

export interface AIReview {
    hook_strength: number
    fact_quality: number
    engagement_potential: number
    caption_quality: number
    overall_score: number
    suggestions: string[]
    fact_check_flags: string[]
    rewrite_hook?: string
    rewrite_caption?: string
}

export interface CharacterCarousel {
    id: string
    character_id?: string
    character_name?: string
    // Phase 028: media content support
    content_type?: string  // 'character' | 'media'
    media_title_id?: string
    media_title_name?: string
    angle: string
    title?: string
    hook_text?: string
    slides: CarouselSlide[]
    caption?: string
    hashtags: string[]
    music_mood?: string
    ai_review?: AIReview
    human_notes?: string
    status: CarouselStatus
    content_queue_id?: string
    publish_url?: string
    views?: number
    likes?: number
    comments?: number
    shares?: number
    saves?: number
    engagement_rate?: number
    created_at?: string
    published_at?: string
    story_template?: string
    series_id?: string
    series_part?: number
    multi_character_ids: string[]
    music_track?: MusicTrack
    text_overlay_specs: TextOverlaySpec[]
    brain_context_used?: Record<string, unknown>
    generation_metadata: Record<string, unknown>
    hook_style?: string
    content_format?: string
    final_review?: Record<string, unknown>
    final_review_score?: number
    final_review_model?: string
    auto_approved?: boolean
    auto_approved_at?: string
    auto_approve_reason?: string
}

export interface CharacterImage {
    id: string
    character_id: string
    url: string
    source: string
    query_used?: string
    width?: number
    height?: number
    is_valid: boolean
    is_primary: boolean
    usage_count: number
    quality_score: number
    content_type?: string
    file_size?: number
    is_approved?: boolean
    feedback_reason?: string
    validated_at?: string
    created_at?: string
}

export interface CharacterStats {
    total_characters: number
    characters_researched: number
    total_carousels: number
    carousels_by_status: Record<string, number>
    total_published: number
    total_views: number
    total_likes: number
    avg_engagement_rate: number
    top_characters: { name: string; posts: number; likes: number }[]
    top_angles: { angle: string; count: number }[]
}

export interface ContentInspiration {
    id: string
    platform: string
    source_url?: string
    creator_handle?: string
    content_type?: string
    hook_text?: string
    slide_count?: number
    structure_analysis?: Record<string, unknown>
    engagement_metrics: Record<string, unknown>
    tags: string[]
    patterns_extracted: Record<string, unknown>[]
    status: string
    created_at?: string
    analyzed_at?: string
}

export interface MusicTrack {
    id: string
    name: string
    artist?: string
    mood: string
    energy_level?: string
    genre?: string
    tiktok_sound_id?: string
    tiktok_sound_url?: string
    preview_url?: string | null
    is_trending: boolean
    trending_score: number
    use_count: number
    avg_engagement: number
    tags: string[]
    metadata: Record<string, unknown>
    created_at?: string
}

export interface StoryTemplate {
    id: string
    name: string
    template_type: string
    description?: string
    slide_structure: Record<string, unknown>[]
    prompt_template: string
    example_hook?: string
    suitable_angles: string[]
    suitable_universes: string[]
    times_used: number
    avg_score: number
    is_active: boolean
    created_at?: string
}

export interface TextOverlaySpec {
    slide_num: number
    text_position: string
    font_weight: string
    font_style?: string
    max_chars_per_line: number
    background_overlay: number
    text_color: string
    text_shadow: boolean
    emoji_placement?: string
    accent_color?: string
}

export interface WinningPatterns {
    total_analyzed: number
    avg_slide_count: number
    top_hook_types: string[]
    top_storytelling_arcs: string[]
    common_structures: Record<string, unknown>[]
    engagement_insights: string[]
}

export interface SmartBatchResult {
    generated: number
    top_scored: CharacterCarousel[]
    needs_work: CharacterCarousel[]
    errors: string[]
}

export interface SourceAnalytics {
    sources: { source: string; fragment_count: number; avg_relevance: number }[]
    total_fragments: number
}

export interface TemplateAnalytics {
    templates: { name: string; template_type: string; times_used: number; avg_score: number }[]
}

export interface ResearchLink {
    url: string
    title: string
    source: string
}

export interface ResearchJobStep {
    name: string
    status: 'pending' | 'running' | 'completed' | 'failed'
    started_at: string | null
    completed_at: string | null
    result_summary: string | null
    error: string | null
    links_found?: ResearchLink[]
    avg_duration_ms?: number | null
}

export interface ResearchJob {
    id: string
    character_id: string
    character_name: string
    universe: string
    status: 'queued' | 'researching' | 'completed' | 'failed'
    steps: ResearchJobStep[]
    started_at: string | null
    completed_at: string | null
    error: string | null
    facts_found: number
    images_found: number
    sources_used: string[]
    depth_score: number
    eta_seconds?: number | null
}

export interface ResearchQueueStatus {
    total_jobs: number
    queued: number
    researching: number
    completed: number
    failed: number
    current_character: string | null
    current_step: string | null
    jobs: ResearchJob[]
    started_at: string | null
    estimated_completion: string | null
}

export interface ContentIdea {
    id: string
    title: string
    description: string
    angle: string
    source: string
    status: string
    carousel_ids: string[]
    priority: number
    created_at?: string
    used_at?: string
}

// Query keys
const characterKeys = {
    all: ['characters'] as const,
    list: (filters?: Record<string, string>) => [...characterKeys.all, 'list', filters] as const,
    detail: (id: string) => [...characterKeys.all, 'detail', id] as const,
    images: (id: string) => [...characterKeys.all, 'images', id] as const,
    carousels: (filters?: Record<string, string>) => ['carousels', 'list', filters] as const,
    carousel: (id: string) => ['carousels', 'detail', id] as const,
    reviewQueue: ['carousels', 'review-queue'] as const,
    stats: ['characters', 'stats'] as const,
    inspirations: ['characters', 'inspirations'] as const,
    inspirationPatterns: ['characters', 'inspirations', 'patterns'] as const,
    templates: ['characters', 'templates'] as const,
    music: (mood?: string) => ['characters', 'music', mood] as const,
    trendingMusic: ['characters', 'music', 'trending'] as const,
    smartReviewQueue: ['carousels', 'review-queue', 'smart'] as const,
    sourceAnalytics: ['characters', 'analytics', 'sources'] as const,
    templateAnalytics: ['characters', 'analytics', 'templates'] as const,
    researchQueue: ['characters', 'research-queue'] as const,
    ideas: (id: string) => [...characterKeys.all, 'ideas', id] as const,
    employeeReport: (windowHours: number) => ['characters', 'employee-report', windowHours] as const,
}

// Fetch helpers
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
// CHARACTER QUERIES
// ============================================

export function useCharacters(filters?: { universe?: string; status?: string; research_status?: string; limit?: number }) {
    const params = new URLSearchParams()
    if (filters?.universe) params.set('universe', filters.universe)
    if (filters?.status) params.set('status', filters.status)
    if (filters?.research_status) params.set('research_status', filters.research_status)
    // Default to a high cap so the Characters list shows every character, not
    // just the backend's pagination default. The backend caps at 2000.
    params.set('limit', String(filters?.limit ?? 1000))
    const qs = `?${params}`

    return useQuery({
        queryKey: characterKeys.list({ ...(filters as Record<string, string>), limit: String(filters?.limit ?? 1000) }),
        queryFn: () => fetchApi<Character[]>(`/api/characters/${qs}`),
    })
}

export function useCharacter(id: string) {
    return useQuery({
        queryKey: characterKeys.detail(id),
        queryFn: () => fetchApi<Character>(`/api/characters/${id}`),
        enabled: !!id,
    })
}

export function useCharacterImages(characterId: string) {
    return useQuery({
        queryKey: characterKeys.images(characterId),
        queryFn: () => fetchApi<CharacterImage[]>(`/api/characters/${characterId}/images`),
        enabled: !!characterId,
    })
}

export function useCharacterStats() {
    return useQuery({
        queryKey: characterKeys.stats,
        queryFn: () => fetchApi<CharacterStats>('/api/characters/stats'),
    })
}

export interface CarouselEmployeeReport {
    generated_at: string
    window_hours: number
    period: { from: string; to: string }
    carousels: {
        generated?: number
        by_status?: Record<string, number>
        approved?: number
        rejected?: number
        reviewed?: number
        stage2_avg_score?: number | null
        stage2_min_score?: number | null
        stage2_max_score?: number | null
    }
    learning: {
        variant_sample_size?: number
        top_variants?: Array<{ hook_style: string; story_template: string; uses: number; avg_score: number }>
        bottom_variants?: Array<{ hook_style: string; story_template: string; uses: number; avg_score: number }>
    }
    queue: { pending?: number; in_progress?: number; completed?: number; error?: string }
    issues: string[]
    wins: string[]
    summary: string
}

export function useCarouselEmployeeReport(windowHours: number = 12) {
    return useQuery({
        queryKey: characterKeys.employeeReport(windowHours),
        queryFn: () => fetchApi<CarouselEmployeeReport>(`/api/characters/employee-report?window_hours=${windowHours}`),
        refetchInterval: 5 * 60 * 1000,
    })
}

// ============================================
// CAROUSEL QUERIES
// ============================================

export function useCarousels(filters?: { character_id?: string; status?: string }) {
    const params = new URLSearchParams()
    if (filters?.character_id) params.set('character_id', filters.character_id)
    if (filters?.status) params.set('status', filters.status)
    const qs = params.toString() ? `?${params}` : ''

    return useQuery({
        queryKey: characterKeys.carousels(filters as Record<string, string>),
        queryFn: () => fetchApi<CharacterCarousel[]>(`/api/characters/carousels${qs}`),
    })
}

export function useCarousel(id: string) {
    return useQuery({
        queryKey: characterKeys.carousel(id),
        queryFn: () => fetchApi<CharacterCarousel>(`/api/characters/carousels/${id}`),
        enabled: !!id,
    })
}

export function useReviewQueue() {
    return useQuery({
        queryKey: characterKeys.reviewQueue,
        queryFn: () => fetchApi<CharacterCarousel[]>('/api/characters/review-queue'),
    })
}

export function useSmartReviewQueue() {
    return useQuery({
        queryKey: characterKeys.smartReviewQueue,
        queryFn: () => fetchApi<CharacterCarousel[]>('/api/characters/review-queue/smart'),
    })
}

export function useInspirations() {
    return useQuery({
        queryKey: characterKeys.inspirations,
        queryFn: () => fetchApi<ContentInspiration[]>('/api/characters/inspirations'),
    })
}

export function useInspirationPatterns() {
    return useQuery({
        queryKey: characterKeys.inspirationPatterns,
        queryFn: () => fetchApi<WinningPatterns>('/api/characters/inspirations/patterns'),
    })
}

export function useTemplates() {
    return useQuery({
        queryKey: characterKeys.templates,
        queryFn: () => fetchApi<StoryTemplate[]>('/api/characters/templates'),
    })
}

export function useMusicTracks(mood?: string) {
    const params = mood ? `?mood=${mood}` : ''
    return useQuery({
        queryKey: characterKeys.music(mood),
        queryFn: () => fetchApi<MusicTrack[]>(`/api/characters/music${params}`),
    })
}

export function useTrendingMusic() {
    return useQuery({
        queryKey: characterKeys.trendingMusic,
        queryFn: () => fetchApi<MusicTrack[]>('/api/characters/music/trending'),
    })
}

export function useSourceAnalytics() {
    return useQuery({
        queryKey: characterKeys.sourceAnalytics,
        queryFn: () => fetchApi<SourceAnalytics>('/api/characters/analytics/sources'),
    })
}

export function useTemplateAnalytics() {
    return useQuery({
        queryKey: characterKeys.templateAnalytics,
        queryFn: () => fetchApi<TemplateAnalytics>('/api/characters/analytics/templates'),
    })
}

// ============================================
// CHARACTER MUTATIONS
// ============================================

export function useCreateCharacter() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: { name: string; universe: CharacterUniverse; franchise?: string; real_name?: string; description?: string; tags?: string[] }) =>
            fetchApi<Character>('/api/characters/', { method: 'POST', body: JSON.stringify(data) }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.all }),
    })
}

export function useResearchCharacter() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (characterId: string) =>
            fetchApi<Character>(`/api/characters/${characterId}/research`, { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.all }),
    })
}

export interface EnhanceCharacterRequest {
    refresh_research?: boolean
    add_images?: number
    regenerate_weak_carousels?: boolean
    weak_threshold?: number
}

export interface EnhanceCharacterResult {
    character_id: string
    facts_before: number
    facts_after: number
    facts_added: number
    images_before: number
    images_after: number
    images_added: number
    carousels_regenerated: number
    carousels_archived: number
    research_depth_before: number
    research_depth_after: number
    research_depth_delta: number
    errors: string[]
}

export function useEnhanceCharacter() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, ...body }: { characterId: string } & EnhanceCharacterRequest) =>
            fetchApi<EnhanceCharacterResult>(`/api/characters/${characterId}/enhance`, {
                method: 'POST',
                body: JSON.stringify(body),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: characterKeys.all })
            qc.invalidateQueries({ queryKey: ['carousels'] })
        },
    })
}

export function useSeedCharacters() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: () => fetchApi<Character[]>('/api/characters/seed', { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.all }),
    })
}

// ============================================
// CONTENT REQUESTS
// ============================================

export interface ContentRequestResult {
    characters_created: Array<{ id: string; name: string }>
    movies_created: Array<{ id: string; title: string }>
    tv_shows_created: Array<{ id: string; title: string }>
    already_existed: string[]
    research_queued: number
}

export function useSubmitContentRequest() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: { text: string; auto_research?: boolean }) =>
            fetchApi<ContentRequestResult>('/api/characters/content-requests', {
                method: 'POST',
                body: JSON.stringify(data),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: characterKeys.all })
            qc.invalidateQueries({ queryKey: ['media-content'] })
        },
    })
}

// ============================================
// CAROUSEL MUTATIONS
// ============================================

export function useGenerateCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: { character_id: string; angle?: ContentAngle; story_template?: string; multi_character_ids?: string[]; slide_count?: number; hook_style?: string; content_format?: string }) =>
            fetchApi<CharacterCarousel>(`/api/characters/${data.character_id}/carousel`, {
                method: 'POST',
                body: JSON.stringify({ angle: data.angle || 'hidden_truths', story_template: data.story_template, multi_character_ids: data.multi_character_ids, slide_count: data.slide_count || 6, hook_style: data.hook_style, content_format: data.content_format }),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useGenerateRankingCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: { theme?: string; universe?: string; character_ids?: string[] }) =>
            fetchApi<CharacterCarousel>('/api/characters/generate-ranking', {
                method: 'POST',
                body: JSON.stringify(data),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useUpdateCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, ...data }: { id: string; hook_text?: string; slides?: CarouselSlide[]; caption?: string; hashtags?: string[]; human_notes?: string }) =>
            fetchApi<CharacterCarousel>(`/api/characters/carousels/${id}`, {
                method: 'PATCH',
                body: JSON.stringify(data),
            }),
        onSuccess: (_d, vars) => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: ['carousels', 'detail', vars.id] })
            qc.invalidateQueries({ queryKey: ['carousels', vars.id, 'versions'] })
        },
    })
}

// ============================================
// CAROUSEL ENHANCE / COUNCIL / VERSIONS
// ============================================

export type CarouselEnhanceTarget = 'hook' | 'slide' | 'caption' | 'hashtags' | 'all'
export type CarouselVersionSource = 'manual_edit' | 'enhance' | 'council_vote' | 'restore' | 'backfill'

export interface EnhanceCarouselVariant {
    target: CarouselEnhanceTarget
    slide_num: number | null
    text: string
    provider: string
    model: string
    cost_usd?: number | null
}

export interface EnhanceCarouselResponse {
    carousel_id: string
    variants: EnhanceCarouselVariant[]
}

export interface CouncilVoteResponse {
    carousel_id: string
    decision_id: string
    target: CarouselEnhanceTarget
    slide_num: number | null
    winning_variant: EnhanceCarouselVariant
    winning_rank: number
    variants: EnhanceCarouselVariant[]
    votes: Record<string, unknown>
    reasoning: string[]
}

export interface CarouselVersion {
    id: string
    carousel_id: string
    version_number: number
    parent_version_id?: string | null
    title?: string | null
    hook_text?: string | null
    slides: Record<string, unknown>[]
    caption?: string | null
    hashtags: string[]
    human_notes?: string | null
    music_track?: Record<string, unknown> | null
    text_overlay_specs: Record<string, unknown>[]
    source: CarouselVersionSource
    source_metadata: Record<string, unknown>
    created_by?: string | null
    created_at?: string | null
}

export interface RestoreVersionResponse {
    carousel: CharacterCarousel
    restored_from: string
}

export function useEnhanceCarouselPiece() {
    return useMutation({
        mutationFn: ({
            carouselId,
            target,
            slide_num,
            provider,
            model,
            instruction,
            n_variants,
        }: {
            carouselId: string
            target: CarouselEnhanceTarget
            slide_num?: number | null
            provider?: string
            model?: string
            instruction?: string
            n_variants?: number
        }) =>
            fetchApi<EnhanceCarouselResponse>(
                `/api/characters/carousels/${carouselId}/enhance`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        target,
                        slide_num: slide_num ?? null,
                        provider: provider ?? null,
                        model: model ?? null,
                        instruction: instruction ?? null,
                        n_variants: n_variants ?? 3,
                    }),
                },
            ),
    })
}

export function useApplyEnhanceVariant() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            carouselId,
            target,
            slide_num,
            text,
            provider,
            model,
        }: {
            carouselId: string
            target: CarouselEnhanceTarget
            slide_num?: number | null
            text: string
            provider?: string
            model?: string
        }) =>
            fetchApi<CharacterCarousel>(
                `/api/characters/carousels/${carouselId}/enhance/apply`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        target,
                        slide_num: slide_num ?? null,
                        text,
                        provider: provider ?? 'manual',
                        model: model ?? 'manual',
                    }),
                },
            ),
        onSuccess: (_d, vars) => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: ['carousels', 'detail', vars.carouselId] })
            qc.invalidateQueries({ queryKey: ['carousels', vars.carouselId, 'versions'] })
        },
    })
}

export function useCarouselCouncilVote() {
    return useMutation({
        mutationFn: ({
            carouselId,
            target,
            slide_num,
            n_variants,
            providers,
        }: {
            carouselId: string
            target: CarouselEnhanceTarget
            slide_num?: number | null
            n_variants?: number
            providers?: string[]
        }) =>
            fetchApi<CouncilVoteResponse>(
                `/api/characters/carousels/${carouselId}/council-vote`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        target,
                        slide_num: slide_num ?? null,
                        n_variants: n_variants ?? 3,
                        providers: providers ?? null,
                    }),
                },
            ),
    })
}

export function useApplyCouncilWinner() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            carouselId,
            target,
            slide_num,
            text,
            decision_id,
        }: {
            carouselId: string
            target: CarouselEnhanceTarget
            slide_num?: number | null
            text: string
            decision_id?: string
        }) =>
            fetchApi<CharacterCarousel>(
                `/api/characters/carousels/${carouselId}/council-vote/apply`,
                {
                    method: 'POST',
                    body: JSON.stringify({
                        target,
                        slide_num: slide_num ?? null,
                        text,
                        decision_id: decision_id ?? null,
                    }),
                },
            ),
        onSuccess: (_d, vars) => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: ['carousels', 'detail', vars.carouselId] })
            qc.invalidateQueries({ queryKey: ['carousels', vars.carouselId, 'versions'] })
        },
    })
}

export function useCarouselVersions(carouselId: string, limit = 50) {
    return useQuery({
        queryKey: ['carousels', carouselId, 'versions', limit],
        queryFn: () =>
            fetchApi<CarouselVersion[]>(
                `/api/characters/carousels/${carouselId}/versions?limit=${limit}`,
            ),
        enabled: !!carouselId,
        staleTime: 10_000,
    })
}

export function useRestoreCarouselVersion() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            carouselId,
            versionId,
            force,
        }: {
            carouselId: string
            versionId: string
            force?: boolean
        }) =>
            fetchApi<RestoreVersionResponse>(
                `/api/characters/carousels/${carouselId}/versions/${versionId}/restore${force ? '?force=true' : ''}`,
                { method: 'POST' },
            ),
        onSuccess: (_d, vars) => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: ['carousels', 'detail', vars.carouselId] })
            qc.invalidateQueries({ queryKey: ['carousels', vars.carouselId, 'versions'] })
        },
    })
}

export function useAiReviewCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (carouselId: string) =>
            fetchApi<CharacterCarousel>(`/api/characters/carousels/${carouselId}/review`, { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['carousels'] }),
    })
}

export function useReimageCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (carouselId: string) =>
            fetchApi<CharacterCarousel>(`/api/characters/carousels/${carouselId}/reimage`, { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['carousels'] }),
    })
}

export interface SlideImageCandidate {
    id: string
    url: string
    source: string
    width?: number | null
    height?: number | null
    quality_score: number
    phash?: string | null
    is_used_in_carousel: boolean
}

export function useSlideImageCandidates(carouselId: string, slideIndex: number, limit = 24) {
    return useQuery({
        queryKey: ['carousels', carouselId, 'slide-image-candidates', slideIndex, limit],
        queryFn: () =>
            fetchApi<SlideImageCandidate[]>(
                `/api/characters/carousels/${carouselId}/slides/${slideIndex}/image-candidates?limit=${limit}`,
            ),
        enabled: !!carouselId && slideIndex >= 0,
        staleTime: 15_000,
    })
}

export function useSwapSlideImage() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({
            carouselId, slideIndex, imageUrl, imageId,
        }: { carouselId: string; slideIndex: number; imageUrl: string; imageId?: string }) =>
            fetchApi<CharacterCarousel>(
                `/api/characters/carousels/${carouselId}/slides/${slideIndex}/image`,
                {
                    method: 'PATCH',
                    body: JSON.stringify({ image_url: imageUrl, image_id: imageId ?? null }),
                },
            ),
        onSuccess: (_d, vars) => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: ['carousels', 'detail', vars.carouselId] })
            qc.invalidateQueries({ queryKey: ['carousels', vars.carouselId, 'slide-image-candidates'] })
        },
    })
}

export function useUploadSlideImage() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: async ({
            carouselId, slideIndex, file,
        }: { carouselId: string; slideIndex: number; file: File }) => {
            const form = new FormData()
            form.append('file', file)
            const res = await fetch(
                `/api/characters/carousels/${carouselId}/slides/${slideIndex}/image/upload`,
                {
                    method: 'POST',
                    headers: { ...getAuthHeaders() },
                    body: form,
                },
            )
            if (!res.ok) {
                throw new Error(`Upload failed: ${await res.text()}`)
            }
            return res.json() as Promise<CharacterCarousel>
        },
        onSuccess: (_d, vars) => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: ['carousels', 'detail', vars.carouselId] })
            qc.invalidateQueries({ queryKey: ['carousels', vars.carouselId, 'slide-image-candidates'] })
        },
    })
}

export function useReimageSlide() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ carouselId, slideIndex, query }: { carouselId: string; slideIndex: number; query?: string }) =>
            fetchApi<CharacterCarousel>(
                `/api/characters/carousels/${carouselId}/slides/${slideIndex}/reimage`,
                {
                    method: 'POST',
                    body: JSON.stringify({ query: query ?? null }),
                },
            ),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['carousels'] }),
    })
}

export function useReimageWithFreshSources() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (carouselId: string) =>
            fetchApi<CharacterCarousel>(
                `/api/characters/carousels/${carouselId}/reimage-with-fresh-sources`,
                { method: 'POST' },
            ),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useApproveCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, ...data }: { id: string; caption?: string; hashtags?: string[]; human_notes?: string }) =>
            fetchApi<CharacterCarousel>(`/api/characters/carousels/${id}/approve`, {
                method: 'POST',
                body: JSON.stringify(data),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['carousels'] }),
    })
}

export function useRejectCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, reason, human_notes }: { id: string; reason: string; human_notes?: string }) =>
            fetchApi<CharacterCarousel>(`/api/characters/carousels/${id}/reject`, {
                method: 'POST',
                body: JSON.stringify({ reason, human_notes }),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['carousels'] }),
    })
}

export function useBatchGenerate() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: { universe?: CharacterUniverse; character_ids?: string[]; angle?: ContentAngle; count?: number }) =>
            fetchApi<CharacterCarousel[]>('/api/characters/batch-generate', {
                method: 'POST',
                body: JSON.stringify(data),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useSmartBatchGenerate() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data?: { count?: number; universe?: CharacterUniverse }) =>
            fetchApi<SmartBatchResult>('/api/characters/batch-smart', {
                method: 'POST',
                body: JSON.stringify(data || {}),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useDiscoverInspirations() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (niche?: string) =>
            fetchApi<ContentInspiration[]>('/api/characters/inspirations/discover', {
                method: 'POST',
                body: JSON.stringify({ niche: niche || 'character facts carousel' }),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.inspirations }),
    })
}

export function useAnalyzeInspiration() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (url: string) =>
            fetchApi<ContentInspiration>('/api/characters/inspirations/analyze', {
                method: 'POST',
                body: JSON.stringify({ url }),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.inspirations }),
    })
}

export function useSeedTemplates() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: () => fetchApi<StoryTemplate[]>('/api/characters/templates/seed', { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.templates }),
    })
}

export function useSeedMusic() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: () => fetchApi<MusicTrack[]>('/api/characters/music/seed', { method: 'POST' }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.music() }),
    })
}

export function useGenerateSeries() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data: { character_id: string; story_template?: string; parts?: number; angle?: ContentAngle }) =>
            fetchApi<CharacterCarousel[]>(`/api/characters/${data.character_id}/carousel/series`, {
                method: 'POST',
                body: JSON.stringify({ story_template: data.story_template, parts: data.parts || 3, angle: data.angle }),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useAssignMusic() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ carouselId, trackId }: { carouselId: string; trackId: string }) =>
            fetchApi<CharacterCarousel>(`/api/characters/carousels/${carouselId}/music`, {
                method: 'POST',
                body: JSON.stringify({ track_id: trackId }),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['carousels'] }),
    })
}

// ============================================
// IMAGE & FACT MUTATIONS
// ============================================

export function useSourceImages() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (characterId: string) =>
            fetchApi<CharacterImage[]>(`/api/characters/${characterId}/source-images`, { method: 'POST' }),
        onSuccess: (_data, characterId) => {
            qc.invalidateQueries({ queryKey: characterKeys.images(characterId) })
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useValidateAllImages() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (limit: number = 100) =>
            fetchApi<{ total_checked: number; validated: number; invalidated: number }>(
                `/api/characters/images/validate-all?limit=${limit}`, { method: 'POST' }
            ),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['characters'] }),
    })
}

export function useApproveImage() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, imageId }: { characterId: string; imageId: string }) =>
            fetchApi<CharacterImage>(
                `/api/characters/${characterId}/images/${imageId}/approve`, { method: 'POST' }
            ),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.images(characterId) })
        },
    })
}

export function useRejectImage() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, imageId, reason }: { characterId: string; imageId: string; reason?: string }) =>
            fetchApi<CharacterImage>(
                `/api/characters/${characterId}/images/${imageId}/reject?reason=${encodeURIComponent(reason || '')}`,
                { method: 'POST' }
            ),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.images(characterId) })
        },
    })
}

export function useDeleteCharacter() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (characterId: string) =>
            fetchApi<{ status: string; id: string }>(`/api/characters/${characterId}`, { method: 'DELETE' }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: characterKeys.all })
            qc.invalidateQueries({ queryKey: ['carousels'] })
        },
    })
}

export function useDeleteCarousel() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (carouselId: string) =>
            fetchApi<{ status: string; id: string }>(`/api/characters/carousels/${carouselId}`, { method: 'DELETE' }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['carousels'] })
            qc.invalidateQueries({ queryKey: characterKeys.all })
        },
    })
}

export function useDeleteImage() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, imageId }: { characterId: string; imageId: string }) =>
            fetchApi<{ deleted: boolean; blocked_url: string }>(
                `/api/characters/${characterId}/images/${imageId}`, { method: 'DELETE' }
            ),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.images(characterId) })
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useAddFact() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, fact }: { characterId: string; fact: { text: string; category: string; surprise_score: number; source?: string; verified?: boolean } }) =>
            fetchApi<Character>(`/api/characters/${characterId}/facts`, {
                method: 'POST',
                body: JSON.stringify(fact),
            }),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useUpdateFact() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, factIndex, fact }: { characterId: string; factIndex: number; fact: { text: string; category: string; surprise_score: number; source?: string; verified?: boolean } }) =>
            fetchApi<Character>(`/api/characters/${characterId}/facts/${factIndex}`, {
                method: 'PATCH',
                body: JSON.stringify(fact),
            }),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useBatchResearch() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (data?: { universe?: CharacterUniverse; limit?: number }) =>
            fetchApi<{ researched: number; skipped: number; errors: { character: string; error: string }[]; total_candidates: number }>('/api/characters/batch-research', {
                method: 'POST',
                body: JSON.stringify(data || {}),
            }),
        onSuccess: () => qc.invalidateQueries({ queryKey: characterKeys.all }),
    })
}

export function useCharacterCarousels(characterId: string) {
    return useQuery({
        queryKey: characterKeys.carousels({ character_id: characterId }),
        queryFn: () => fetchApi<CharacterCarousel[]>(`/api/characters/carousels?character_id=${characterId}`),
        enabled: !!characterId,
    })
}

// ============================================
// RESEARCH QUEUE
// ============================================

export function useResearchQueue(enabled = false) {
    return useQuery({
        queryKey: characterKeys.researchQueue,
        queryFn: () => fetchApi<ResearchQueueStatus>('/api/characters/research-queue'),
        refetchInterval: enabled ? 5000 : false,
        enabled,
    })
}

export function useStartResearchQueue() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (params?: { universe?: string; limit?: number }) =>
            fetchApi<ResearchQueueStatus>('/api/characters/research-queue/start', {
                method: 'POST',
                body: JSON.stringify(params || {}),
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: characterKeys.researchQueue })
        },
    })
}

export function useCancelResearchQueue() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: () =>
            fetchApi<Record<string, unknown>>('/api/characters/research-queue/cancel', {
                method: 'POST',
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: characterKeys.researchQueue })
        },
    })
}

export function useRetryResearch() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (characterId: string) =>
            fetchApi<ResearchQueueStatus>(`/api/characters/research-queue/retry/${characterId}`, {
                method: 'POST',
            }),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: characterKeys.researchQueue })
        },
    })
}

// ============================================
// CONTENT IDEAS
// ============================================

export function useCharacterIdeas(characterId: string) {
    return useQuery({
        queryKey: characterKeys.ideas(characterId),
        queryFn: () => fetchApi<ContentIdea[]>(`/api/characters/${characterId}/ideas`),
        enabled: !!characterId,
    })
}

export function useSeedIdeas() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (characterId: string) =>
            fetchApi<ContentIdea[]>(`/api/characters/${characterId}/ideas/seed`, { method: 'POST' }),
        onSuccess: (_data, characterId) => {
            qc.invalidateQueries({ queryKey: characterKeys.ideas(characterId) })
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useGenerateIdeas() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, count, avoid_used }: { characterId: string; count?: number; avoid_used?: boolean }) =>
            fetchApi<ContentIdea[]>(`/api/characters/${characterId}/ideas/generate`, {
                method: 'POST',
                body: JSON.stringify({ count: count || 5, avoid_used: avoid_used ?? true }),
            }),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.ideas(characterId) })
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useUpdateIdea() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, ideaId, ...data }: { characterId: string; ideaId: string; status?: string; carousel_ids?: string[]; title?: string; description?: string; priority?: number }) =>
            fetchApi<ContentIdea>(`/api/characters/${characterId}/ideas/${ideaId}`, {
                method: 'PATCH',
                body: JSON.stringify(data),
            }),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.ideas(characterId) })
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}

export function useDeleteIdea() {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ characterId, ideaId }: { characterId: string; ideaId: string }) =>
            fetchApi<{ status: string; id: string }>(`/api/characters/${characterId}/ideas/${ideaId}`, {
                method: 'DELETE',
            }),
        onSuccess: (_data, { characterId }) => {
            qc.invalidateQueries({ queryKey: characterKeys.ideas(characterId) })
            qc.invalidateQueries({ queryKey: characterKeys.detail(characterId) })
        },
    })
}
