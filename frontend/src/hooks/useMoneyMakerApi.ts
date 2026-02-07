import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:18792'

// Types
export type IdeaStatus = 'new' | 'researching' | 'validated' | 'pursuing' | 'parked' | 'rejected'
export type IdeaCategory = 'saas' | 'content' | 'freelance' | 'consulting' | 'affiliate' | 'product' | 'automation' | 'other'

export interface MoneyIdea {
    id: string
    title: string
    description: string
    category: IdeaCategory
    status: IdeaStatus
    revenue_potential: number
    effort_score: number
    viability_score: number
    research_notes?: string
    market_validation: number
    competition_score: number
    first_steps: string[]
    resources_needed: string[]
    created_at: string
}

export interface MoneyMakerStats {
    totalIdeas: number
    byStatus: Record<string, number>
    byCategory: Record<string, number>
    topViabilityScore: number
    ideasThisWeek: number
}

// Hooks
export function useMoneyMakerIdeas(status?: IdeaStatus) {
    return useQuery({
        queryKey: ['money-maker', 'ideas', status],
        queryFn: async (): Promise<MoneyIdea[]> => {
            const params = new URLSearchParams()
            if (status) params.append('status', status)

            const res = await fetch(`${API_URL}/api/money-maker/ideas?${params.toString()}`)
            if (!res.ok) throw new Error('Failed to fetch ideas')
            return res.json()
        }
    })
}

export function useMoneyMakerStats() {
    return useQuery({
        queryKey: ['money-maker', 'stats'],
        queryFn: async (): Promise<MoneyMakerStats> => {
            const res = await fetch(`${API_URL}/api/money-maker/stats`)
            if (!res.ok) throw new Error('Failed to fetch stats')
            return res.json()
        }
    })
}

export function useGenerateIdeas() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (params: { count?: number; category?: string }) => {
            const res = await fetch(`${API_URL}/api/money-maker/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            })
            if (!res.ok) throw new Error('Failed to generate ideas')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['money-maker'] })
        }
    })
}

export function useResearchIdea() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async (ideaId: string) => {
            const res = await fetch(`${API_URL}/api/money-maker/ideas/${ideaId}/research`, {
                method: 'POST'
            })
            if (!res.ok) throw new Error('Failed to research idea')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['money-maker'] })
        }
    })
}

export function useUpdateIdeaStatus() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: async ({ id, status }: { id: string; status: IdeaStatus }) => {
            const res = await fetch(`${API_URL}/api/money-maker/ideas/${id}/status`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status })
            })
            if (!res.ok) throw new Error('Failed to update idea status')
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['money-maker'] })
        }
    })
}
