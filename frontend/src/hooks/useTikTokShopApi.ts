import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types
export type TikTokProductStatus = 'discovered' | 'pending_approval' | 'approved' | 'researched' | 'content_planned' | 'active' | 'paused' | 'rejected'
export type TikTokProductType = 'affiliate' | 'dropship' | 'own' | 'unknown'

export interface TikTokProduct {
    id: string
    name: string
    category: string
    niche: string
    description: string
    source_url?: string
    marketplace_url?: string
    product_type: TikTokProductType
    trend_score: number
    competition_score: number
    margin_score: number
    opportunity_score: number
    price_range_min?: number
    price_range_max?: number
    estimated_monthly_sales?: number
    competitor_count?: number
    commission_rate?: number
    tags: string[]
    llm_analysis?: string
    content_ideas?: Record<string, unknown>[]
    status: TikTokProductStatus
    linked_content_topic_id?: string
    approved_at?: string
    rejected_at?: string
    rejection_reason?: string
    source_article_title?: string
    source_article_url?: string
    is_extracted: boolean
    why_trending?: string
    estimated_price_range?: string
    discovered_at: string
    last_researched_at?: string
    // Images
    image_url?: string
    image_urls?: string[]
    image_validated?: boolean
    // Success rating
    success_rating?: number
    success_factors?: Record<string, number>
    // Sourcing
    supplier_url?: string
    supplier_name?: string
    sourcing_method?: string
    sourcing_notes?: string
    sourcing_links?: { name: string; url: string; type: string; snippet?: string; link_status?: string; is_valid?: boolean }[]
    listing_steps?: string[]
    // Affiliate & import tracking
    affiliate_link?: string
    tiktok_shop_url?: string
    import_url?: string
    import_source?: string
    // Content performance feedback
    content_performance_score?: number
    best_template_type?: string
    last_performance_update_at?: string
}

export interface CatalogProduct extends TikTokProduct {
    script_count: number
    scripts_generated: number
}

export interface SetupGuide {
    title: string
    steps: {
        step: number
        title: string
        description: string
        link?: string
        options?: string[]
        required: boolean
    }[]
    scheduled_jobs: {
        name: string
        frequency: string
        description: string
    }[]
}

export interface TikTokShopStats {
    total_products: number
    active_products: number
    discovered_products: number
    pending_approval_products: number
    approved_products: number
    avg_opportunity_score: number
    top_niches: string[]
    by_status: Record<string, number>
    by_type: Record<string, number>
}

export interface ResearchCycleResult {
    products_discovered: number
    products_researched: number
    content_topics_created: number
    legion_tasks_created: number
    errors: string[]
}

// Product creation
export interface CreateProductRequest {
    name: string
    category?: string
    niche?: string
    description?: string
    product_type?: TikTokProductType
    estimated_price_range?: string
    marketplace_url?: string
    supplier_url?: string
    why_trending?: string
}

// Product filter params
export interface ProductFilters {
    status?: TikTokProductStatus
    niche?: string
    search?: string
    product_type?: TikTokProductType
    min_score?: number
    sort_by?: string
    sort_order?: string
}

// Hooks
export function useTikTokProducts(filters?: ProductFilters) {
    return useQuery({
        queryKey: ['tiktok-shop', 'products', filters],
        queryFn: async (): Promise<TikTokProduct[]> => {
            const params = new URLSearchParams()
            if (filters?.status) params.append('status', filters.status)
            if (filters?.niche) params.append('niche', filters.niche)
            if (filters?.search) params.append('search', filters.search)
            if (filters?.product_type) params.append('product_type', filters.product_type)
            if (filters?.min_score !== undefined) params.append('min_score', filters.min_score.toString())
            if (filters?.sort_by) params.append('sort_by', filters.sort_by)
            if (filters?.sort_order) params.append('sort_order', filters.sort_order)
            const res = await fetch(`${API_URL}/api/tiktok-shop/products?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch products')
            return res.json()
        },
        staleTime: 5000,
    })
}

export function useTikTokProduct(productId: string) {
    return useQuery({
        queryKey: ['tiktok-shop', 'product', productId],
        queryFn: async (): Promise<TikTokProduct> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch product')
            return res.json()
        },
        enabled: !!productId,
        staleTime: 5000,
    })
}

export function useTikTokShopStats() {
    return useQuery({
        queryKey: ['tiktok-shop', 'stats'],
        queryFn: async (): Promise<TikTokShopStats> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/stats`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch stats')
            return res.json()
        },
        staleTime: 10000,
    })
}

export function useRunResearchCycle() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (): Promise<ResearchCycleResult> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/research/cycle`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to run research cycle')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
        }
    })
}

export function useDeepResearchProduct() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (productId: string): Promise<TikTokProduct> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}/research`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to research product')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
        }
    })
}

export function useGenerateContentIdeas() {
    return useMutation({
        mutationFn: async (productId: string) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}/ideas`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to generate ideas')
            return res.json()
        }
    })
}

export function useDeleteProduct() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (productId: string) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}`, {
                method: 'DELETE',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to delete product')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
        }
    })
}

// Approval Queue Hooks

export function usePendingProducts() {
    return useQuery({
        queryKey: ['tiktok-shop', 'pending'],
        queryFn: async (): Promise<TikTokProduct[]> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/pending`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch pending products')
            return res.json()
        },
        refetchInterval: 30000,
        staleTime: 5000,
    })
}

export function useApproveBatch() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (productIds: string[]): Promise<{ status: string; count: number }> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/approve`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: productIds }),
            })
            if (!res.ok) throw new Error('Failed to approve products')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
        }
    })
}

export function useRejectBatch() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ productIds, reason }: { productIds: string[]; reason?: string }): Promise<{ status: string; count: number }> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/reject`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: productIds, rejection_reason: reason }),
            })
            if (!res.ok) throw new Error('Failed to reject products')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
        }
    })
}

// Pipeline hooks

export interface PipelineResult {
    cycle_id: string
    mode: string
    status: 'completed' | 'failed'
    summary: string
    products_discovered: number
    auto_approved: number
    pending_review: number
    scripts_generated: number
    generation_jobs: number
    errors: string[]
}

export function useRunPipeline() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (mode: string = 'full'): Promise<PipelineResult> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/pipeline/run?mode=${mode}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to run pipeline')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-content'] })
        }
    })
}

// Enrichment & Cleanup

export function useEnrichProduct() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (productId: string): Promise<TikTokProduct> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}/enrich`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to enrich product')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        }
    })
}

export function useCleanupProducts() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (): Promise<{ rejected: number; kept: number }> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/cleanup`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to cleanup products')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        }
    })
}

// Setup Guide
export function useSetupGuide() {
    return useQuery({
        queryKey: ['tiktok-shop', 'setup-guide'],
        queryFn: async (): Promise<SetupGuide> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/setup-guide`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch setup guide')
            return res.json()
        },
        staleTime: 60 * 60 * 1000,
    })
}

// Catalog (merged from useTikTokCatalogApi)
export function useCatalog() {
    return useQuery({
        queryKey: ['tiktok-catalog'],
        queryFn: async (): Promise<CatalogProduct[]> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/catalog`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch catalog')
            return res.json()
        },
        refetchInterval: 60000,
    })
}

export interface ProductContent {
    product_id: string
    scripts: {
        id: string
        template_type: string
        hook_text: string
        cta_text?: string
        voiceover_script?: string
        status: string
        duration_seconds: number
        created_at: string
    }[]
    queue_items: {
        id: string
        script_id: string
        status: string
        created_at: string
        completed_at?: string
        error_message?: string
    }[]
}

export function useProductContent(productId: string) {
    return useQuery({
        queryKey: ['tiktok-catalog', 'content', productId],
        queryFn: async (): Promise<ProductContent> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/catalog/${productId}/content`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch product content')
            return res.json()
        },
        enabled: !!productId,
    })
}

// Add & Research (manual product addition with auto-research)
export function useAddAndResearchProduct() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (data: CreateProductRequest): Promise<TikTokProduct> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/add-and-research`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to add and research product')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

// Update product
export function useUpdateProduct() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ productId, updates }: { productId: string; updates: Partial<TikTokProduct> }): Promise<TikTokProduct> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}`, {
                method: 'PATCH',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(updates),
            })
            if (!res.ok) throw new Error('Failed to update product')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

// Bulk operations
export function useBulkEnrich() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (productIds: string[]): Promise<{ status: string; count: number }> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/bulk-enrich`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: productIds }),
            })
            if (!res.ok) throw new Error('Failed to bulk enrich')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

// ============================================
// Content Review & Publishing
// ============================================

export interface ReviewItem {
    queue_id: string
    product: {
        id: string
        name: string
        niche: string
        category: string
        image_url?: string
        opportunity_score: number
        why_trending?: string
        estimated_price_range?: string
    }
    script: {
        id: string
        template_type: string
        hook_text: string
        body_sections: Record<string, string>[]
        cta_text: string
        text_overlays: string[]
        voiceover_script: string
        duration_seconds: number
        status: string
    }
    queue: {
        id: string
        status: string
        generation_type: string
        act_job_id?: string
        act_generation_id?: string
        created_at?: string
        completed_at?: string
    }
    publish: {
        status: string | null
        platform: string | null
        url: string | null
        published_at: string | null
        error: string | null
        caption: string | null
        hashtags: string[]
    }
}

export interface PublishReadiness {
    platforms: {
        tiktok: {
            configured: boolean
            authorized: boolean
            open_id?: string
            setup_instructions?: { step: string; title: string; description: string; link?: string }[]
        }
    }
    queue_counts: {
        pending_review: number
        approved: number
        publishing: number
        published: number
        publish_failed: number
        rejected: number
    }
}

export interface E2ESeedResult {
    success: boolean
    products_found: number
    products_approved: number
    scripts_generated: number
    items_queued_for_review: number
    errors: string[]
    error?: string
}

export function useContentReview(status?: string) {
    return useQuery({
        queryKey: ['tiktok-shop', 'review', status],
        queryFn: async (): Promise<ReviewItem[]> => {
            const params = new URLSearchParams()
            if (status) params.append('status', status)
            const res = await fetch(`${API_URL}/api/tiktok-shop/review?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch review items')
            return res.json()
        },
        refetchInterval: 15000,
        staleTime: 5000,
    })
}

export function usePublishStatus() {
    return useQuery({
        queryKey: ['tiktok-shop', 'publish-status'],
        queryFn: async (): Promise<PublishReadiness> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/publish/status`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch publish status')
            return res.json()
        },
        refetchInterval: 30000,
    })
}

export function useSeedE2ETest() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (count: number = 5): Promise<E2ESeedResult> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/e2e-test/seed?count=${count}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to seed E2E test')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-content'] })
        },
    })
}

export function useApproveContent() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ queueId, caption, hashtags }: { queueId: string; caption?: string; hashtags?: string[] }) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/review/${queueId}/approve`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ caption, hashtags }),
            })
            if (!res.ok) throw new Error('Failed to approve content')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'review'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'publish-status'] })
        },
    })
}

export function useRejectContent() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ queueId, reason }: { queueId: string; reason?: string }) => {
            const params = reason ? `?reason=${encodeURIComponent(reason)}` : ''
            const res = await fetch(`${API_URL}/api/tiktok-shop/review/${queueId}/reject${params}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to reject content')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'review'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'publish-status'] })
        },
    })
}

export function usePublishContent() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ queueId, platform }: { queueId: string; platform?: string }) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/review/${queueId}/publish`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ platform: platform || 'tiktok' }),
            })
            if (!res.ok) {
                const data = await res.json().catch(() => ({}))
                throw new Error(data.detail || 'Failed to publish')
            }
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'review'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'publish-status'] })
        },
    })
}

export function usePublishAllApproved() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (platform: string = 'tiktok') => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/review/publish-all?platform=${platform}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to publish all')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'review'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'publish-status'] })
        },
    })
}

export function useTikTokAuthStatus() {
    return useQuery({
        queryKey: ['tiktok-shop', 'auth-status'],
        queryFn: async () => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/auth/status`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch auth status')
            return res.json()
        },
    })
}

export function useBulkDelete() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (productIds: string[]): Promise<{ status: string; count: number }> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/bulk-delete`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_ids: productIds }),
            })
            if (!res.ok) throw new Error('Failed to bulk delete')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

// ============================================
// URL Import
// ============================================

export function useImportProductFromUrl() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ url, research = true }: { url: string; research?: boolean }): Promise<TikTokProduct> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/import-url?url=${encodeURIComponent(url)}&research=${research}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) {
                const detail = await res.text().catch(() => '')
                throw new Error(detail || 'Failed to import product from URL')
            }
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

export function useSetProductLinks() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ productId, affiliate_link, tiktok_shop_url }: { productId: string; affiliate_link?: string; tiktok_shop_url?: string }) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/products/${productId}/links`, {
                method: 'PATCH',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ affiliate_link, tiktok_shop_url }),
            })
            if (!res.ok) throw new Error('Failed to update links')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

// ============================================
// Reference Videos (Video Inspiration)
// ============================================

export interface ReferenceVideo {
    id: string
    tiktok_url: string
    product_id?: string
    title?: string
    author_name?: string
    author_url?: string
    thumbnail_url?: string
    caption?: string
    hashtags: string[]
    views?: number
    likes?: number
    comments?: number
    shares?: number
    hook_analysis?: string
    structure_analysis?: string
    style_notes?: string
    content_type?: string
    estimated_duration?: number
    generated_script_id?: string
    status: string
    created_at: string
    analyzed_at?: string
}

export function useReferenceVideos(productId?: string) {
    return useQuery({
        queryKey: ['tiktok-shop', 'references', productId],
        queryFn: async (): Promise<ReferenceVideo[]> => {
            const params = new URLSearchParams()
            if (productId) params.append('product_id', productId)
            const res = await fetch(`${API_URL}/api/tiktok-shop/references?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch references')
            return res.json()
        },
        refetchInterval: 30000,
        staleTime: 5000,
    })
}

export function useCreateReference() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ tiktok_url, product_id }: { tiktok_url: string; product_id?: string }): Promise<ReferenceVideo> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/references`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ tiktok_url, product_id }),
            })
            if (!res.ok) throw new Error('Failed to create reference')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'references'] })
        },
    })
}

export function useAnalyzeReference() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (refId: string): Promise<ReferenceVideo> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/references/${refId}/analyze`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to analyze reference')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'references'] })
        },
    })
}

export function useCopyScript() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ refId, productId, templateType = 'voiceover_broll' }: { refId: string; productId: string; templateType?: string }) => {
            const res = await fetch(
                `${API_URL}/api/tiktok-shop/references/${refId}/copy-script?product_id=${productId}&template_type=${templateType}`,
                { method: 'POST', headers: getAuthHeaders() },
            )
            if (!res.ok) throw new Error('Failed to copy script')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'references'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-content'] })
            queryClient.invalidateQueries({ queryKey: ['tiktok-catalog'] })
        },
    })
}

export function useDeleteReference() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (refId: string) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/references/${refId}`, {
                method: 'DELETE',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to delete reference')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'references'] })
        },
    })
}

// ============================================
// Automation Config & Pipeline Status
// ============================================

export interface TikTokConfig {
    auto_approve_threshold: number
    auto_enrichment_enabled: boolean
    pipeline_default_mode: string
}

export interface PipelineJobStatus {
    job_name: string
    last_run: string | null
    status: string
    duration_seconds: number | null
    error: string | null
}

export function useTikTokConfig() {
    return useQuery({
        queryKey: ['tiktok-shop', 'config'],
        queryFn: async (): Promise<TikTokConfig> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/config`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch config')
            return res.json()
        },
        staleTime: 60000,
    })
}

export function useUpdateTikTokConfig() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (updates: Partial<TikTokConfig>) => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/config`, {
                method: 'PATCH',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(updates),
            })
            if (!res.ok) throw new Error('Failed to update config')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-shop', 'config'] })
        },
    })
}

export function usePipelineStatus() {
    return useQuery({
        queryKey: ['tiktok-shop', 'pipeline-status'],
        queryFn: async (): Promise<{ jobs: PipelineJobStatus[] }> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/pipeline/status`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch pipeline status')
            return res.json()
        },
        refetchInterval: 60000,
    })
}

export interface TemplateAnalytics {
    template_type: string
    script_count: number
    product_count: number
    avg_performance_score: number
}

export function useTemplateAnalytics() {
    return useQuery({
        queryKey: ['tiktok-shop', 'template-analytics'],
        queryFn: async (): Promise<TemplateAnalytics[]> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/analytics/templates`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch template analytics')
            return res.json()
        },
        refetchInterval: 120000,
    })
}
