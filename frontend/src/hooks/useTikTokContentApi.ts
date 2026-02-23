import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types
export type VideoTemplateType = 'voiceover_broll' | 'text_overlay_showcase' | 'before_after' | 'listicle_topn' | 'problem_solution'
export type VideoScriptStatus = 'draft' | 'approved' | 'queued' | 'generated' | 'failed'
export type ContentQueueStatus = 'queued' | 'generating' | 'completed' | 'failed'

export interface VideoTemplateInfo {
    type: VideoTemplateType
    name: string
    description: string
    duration: number
    sections: string[]
}

export interface VideoScript {
    id: string
    product_id: string
    topic_id?: string
    template_type: VideoTemplateType
    hook_text: string
    body_sections: Record<string, string>[]
    cta_text: string
    text_overlays: string[]
    voiceover_script: string
    duration_seconds: number
    status: VideoScriptStatus
    created_at: string
    generated_at?: string
}

export interface ContentQueueItem {
    id: string
    script_id: string
    product_id: string
    generation_type: string
    act_job_id?: string
    act_generation_id?: string
    status: ContentQueueStatus
    error_message?: string
    created_at: string
    completed_at?: string
}

export interface ContentQueueStats {
    total_queued: number
    generating: number
    completed: number
    failed: number
    total_scripts: number
    scripts_by_template: Record<string, number>
}

// Template hooks
export function useVideoTemplates() {
    return useQuery({
        queryKey: ['tiktok-content', 'templates'],
        queryFn: async (): Promise<VideoTemplateInfo[]> => {
            const res = await fetch(`${API_URL}/api/tiktok-content/templates`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch templates')
            return res.json()
        },
        staleTime: 60 * 60 * 1000, // Templates rarely change
    })
}

// Script hooks
export function useVideoScripts(productId?: string, status?: string) {
    return useQuery({
        queryKey: ['tiktok-content', 'scripts', productId, status],
        queryFn: async (): Promise<VideoScript[]> => {
            const params = new URLSearchParams()
            if (productId) params.append('product_id', productId)
            if (status) params.append('status', status)
            const res = await fetch(`${API_URL}/api/tiktok-content/scripts?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch scripts')
            return res.json()
        },
    })
}

export function useVideoScript(scriptId: string) {
    return useQuery({
        queryKey: ['tiktok-content', 'script', scriptId],
        queryFn: async (): Promise<VideoScript> => {
            const res = await fetch(`${API_URL}/api/tiktok-content/scripts/${scriptId}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch script')
            return res.json()
        },
        enabled: !!scriptId,
    })
}

export function useGenerateScript() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ productId, templateType }: { productId: string; templateType: VideoTemplateType }): Promise<VideoScript> => {
            const res = await fetch(`${API_URL}/api/tiktok-content/scripts/generate`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ product_id: productId, template_type: templateType }),
            })
            if (!res.ok) throw new Error('Failed to generate script')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-content'] })
        },
    })
}

export function useUpdateScript() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ scriptId, updates }: { scriptId: string; updates: Partial<VideoScript> }): Promise<VideoScript> => {
            const res = await fetch(`${API_URL}/api/tiktok-content/scripts/${scriptId}`, {
                method: 'PATCH',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(updates),
            })
            if (!res.ok) throw new Error('Failed to update script')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-content'] })
        },
    })
}

// Queue hooks
export function useQueueForGeneration() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (scriptId: string): Promise<ContentQueueItem> => {
            const res = await fetch(`${API_URL}/api/tiktok-content/scripts/${scriptId}/queue`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to queue for generation')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tiktok-content'] })
        },
    })
}

export function useContentQueue(status?: string) {
    return useQuery({
        queryKey: ['tiktok-content', 'queue', status],
        queryFn: async (): Promise<ContentQueueItem[]> => {
            const params = new URLSearchParams()
            if (status) params.append('status', status)
            const res = await fetch(`${API_URL}/api/tiktok-content/queue?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch queue')
            return res.json()
        },
        refetchInterval: 15000, // Poll every 15s
    })
}

export function useContentQueueStats() {
    return useQuery({
        queryKey: ['tiktok-content', 'queue-stats'],
        queryFn: async (): Promise<ContentQueueStats> => {
            const res = await fetch(`${API_URL}/api/tiktok-content/queue/stats`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch queue stats')
            return res.json()
        },
        refetchInterval: 30000,
    })
}
