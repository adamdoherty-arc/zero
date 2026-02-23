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
    // Success rating
    success_rating?: number
    success_factors?: Record<string, number>
    // Sourcing
    supplier_url?: string
    supplier_name?: string
    sourcing_method?: string
    sourcing_notes?: string
    sourcing_links?: { name: string; url: string; type: string; snippet?: string }[]
    listing_steps?: string[]
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

// Hooks
export function useTikTokProducts(status?: TikTokProductStatus, niche?: string) {
    return useQuery({
        queryKey: ['tiktok-shop', 'products', status, niche],
        queryFn: async (): Promise<TikTokProduct[]> => {
            const params = new URLSearchParams()
            if (status) params.append('status', status)
            if (niche) params.append('niche', niche)
            const res = await fetch(`${API_URL}/api/tiktok-shop/products?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch products')
            return res.json()
        }
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
    })
}

export function useTikTokShopStats() {
    return useQuery({
        queryKey: ['tiktok-shop', 'stats'],
        queryFn: async (): Promise<TikTokShopStats> => {
            const res = await fetch(`${API_URL}/api/tiktok-shop/stats`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch stats')
            return res.json()
        }
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
