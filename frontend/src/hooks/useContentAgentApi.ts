import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types
export type ContentTopicStatus = 'draft' | 'active' | 'paused' | 'archived'

export interface ContentRule {
    id: string
    text: string
    source: 'llm' | 'user' | 'performance'
    effectiveness_score: number
    times_applied: number
}

export interface ContentTopic {
    id: string
    name: string
    description: string
    niche: string
    platform: string
    tiktok_product_id?: string
    rules: ContentRule[]
    content_style?: string
    target_audience?: string
    tone_guidelines?: string
    hashtag_strategy: string[]
    status: ContentTopicStatus
    examples_count: number
    avg_performance_score: number
    content_generated_count: number
    created_at: string
    updated_at?: string
}

export interface ContentExample {
    id: string
    topic_id: string
    title: string
    caption?: string
    script?: string
    url?: string
    platform?: string
    views: number
    likes: number
    comments: number
    shares: number
    performance_score: number
    source: string
    added_at: string
}

export interface ContentPerformance {
    id: string
    topic_id: string
    platform: string
    content_type?: string
    views: number
    likes: number
    comments: number
    shares: number
    engagement_rate: number
    performance_score: number
    rules_applied: string[]
    posted_at?: string
    synced_at?: string
}

export interface ContentAgentStats {
    total_topics: number
    active_topics: number
    total_examples: number
    total_generated: number
    total_rules: number
    avg_performance_score: number
    by_platform: Record<string, number>
}

// Topic hooks
export function useContentTopics(status?: ContentTopicStatus, platform?: string) {
    return useQuery({
        queryKey: ['content-agent', 'topics', status, platform],
        queryFn: async (): Promise<ContentTopic[]> => {
            const params = new URLSearchParams()
            if (status) params.append('status', status)
            if (platform) params.append('platform', platform)
            const res = await fetch(`${API_URL}/api/content-agent/topics?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch topics')
            return res.json()
        }
    })
}

export function useContentTopic(topicId: string) {
    return useQuery({
        queryKey: ['content-agent', 'topic', topicId],
        queryFn: async (): Promise<ContentTopic> => {
            const res = await fetch(`${API_URL}/api/content-agent/topics/${topicId}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch topic')
            return res.json()
        },
        enabled: !!topicId,
    })
}

export function useCreateTopic() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (data: { name: string; description?: string; niche?: string; platform?: string }) => {
            const res = await fetch(`${API_URL}/api/content-agent/topics`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to create topic')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['content-agent'] })
        }
    })
}

export function useDeleteTopic() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (topicId: string) => {
            const res = await fetch(`${API_URL}/api/content-agent/topics/${topicId}`, {
                method: 'DELETE',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to delete topic')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['content-agent'] })
        }
    })
}

// Example hooks
export function useContentExamples(topicId: string) {
    return useQuery({
        queryKey: ['content-agent', 'examples', topicId],
        queryFn: async (): Promise<ContentExample[]> => {
            const res = await fetch(`${API_URL}/api/content-agent/topics/${topicId}/examples`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch examples')
            return res.json()
        },
        enabled: !!topicId,
    })
}

export function useAddExample() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ topicId, data }: { topicId: string; data: { title: string; caption?: string; script?: string; url?: string; platform?: string } }) => {
            const res = await fetch(`${API_URL}/api/content-agent/topics/${topicId}/examples`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to add example')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['content-agent'] })
        }
    })
}

// Rule hooks
export function useGenerateRules() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ topicId, focus }: { topicId: string; focus?: string }) => {
            const res = await fetch(`${API_URL}/api/content-agent/topics/${topicId}/generate-rules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: focus ? JSON.stringify({ focus }) : '{}',
            })
            if (!res.ok) throw new Error('Failed to generate rules')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['content-agent'] })
        }
    })
}

// Content generation
export function useGenerateContent() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (data: { topic_id: string; content_type?: string; persona_id?: string; additional_prompt?: string }) => {
            const res = await fetch(`${API_URL}/api/content-agent/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to generate content')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['content-agent'] })
        }
    })
}

// Performance
export function useContentPerformance(topicId?: string) {
    return useQuery({
        queryKey: ['content-agent', 'performance', topicId],
        queryFn: async (): Promise<ContentPerformance[]> => {
            const params = new URLSearchParams()
            if (topicId) params.append('topic_id', topicId)
            const res = await fetch(`${API_URL}/api/content-agent/performance?${params.toString()}`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch performance')
            return res.json()
        }
    })
}

// Improvement cycle
export function useRunImprovementCycle() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (topicId?: string) => {
            const params = topicId ? `?topic_id=${topicId}` : ''
            const res = await fetch(`${API_URL}/api/content-agent/improvement-cycle${params}`, {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            if (!res.ok) throw new Error('Failed to run improvement cycle')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['content-agent'] })
        }
    })
}

// Stats
export function useContentAgentStats() {
    return useQuery({
        queryKey: ['content-agent', 'stats'],
        queryFn: async (): Promise<ContentAgentStats> => {
            const res = await fetch(`${API_URL}/api/content-agent/stats`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch stats')
            return res.json()
        }
    })
}
