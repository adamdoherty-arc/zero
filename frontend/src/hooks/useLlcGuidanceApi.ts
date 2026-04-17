import { useQuery, useMutation } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

export type BusinessType =
    | 'tiktok_shop'
    | 'consulting'
    | 'ecommerce'
    | 'content_creation'
    | 'software'
    | 'dropshipping'
    | 'affiliate_marketing'
    | 'agency'
    | 'other'

export type LLCType = 'single_member' | 'multi_member' | 'series_llc'

export interface StateInfo {
    state_code: string
    state_name: string
    filing_fee: string
    annual_fee: string
    processing_time: string
    online_filing: boolean
    notes: string
}

export interface FormationStep {
    step_number: number
    title: string
    description: string
    estimated_cost?: string
    estimated_time?: string
    links: { text: string; url: string }[]
    tips: string[]
    required: boolean
}

export interface GuidanceRequest {
    business_types: BusinessType[]
    state: string
    llc_name_ideas: string[]
    llc_type: LLCType
    num_members: number
    annual_revenue_estimate?: string
    has_existing_llc: boolean
    specific_questions?: string
}

export interface GuidanceResponse {
    llc_name_suggestions: string[]
    recommended_state: string
    recommended_type: LLCType
    why_this_structure: string
    formation_steps: FormationStep[]
    estimated_total_cost: string
    estimated_timeline: string
    tax_considerations: string[]
    business_specific_tips: Record<string, string[]>
    operating_agreement_points: string[]
    next_steps_after_formation: string[]
    warnings: string[]
}

export function useStates() {
    return useQuery({
        queryKey: ['llc-guidance', 'states'],
        queryFn: async (): Promise<StateInfo[]> => {
            const res = await fetch(`${API_URL}/api/llc-guidance/states`, { headers: getAuthHeaders() })
            if (!res.ok) throw new Error('Failed to fetch states')
            return res.json()
        },
        staleTime: 24 * 60 * 60 * 1000,
    })
}

export function useGenerateGuidance() {
    return useMutation({
        mutationFn: async (request: GuidanceRequest): Promise<GuidanceResponse> => {
            const res = await fetch(`${API_URL}/api/llc-guidance/guidance`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(request),
            })
            if (!res.ok) throw new Error('Failed to generate guidance')
            return res.json()
        },
    })
}

export function useAskLlcQuestion() {
    return useMutation({
        mutationFn: async ({ question, context }: { question: string; context?: Record<string, unknown> }): Promise<{ question: string; answer: string }> => {
            const params = new URLSearchParams({ question })
            const res = await fetch(`${API_URL}/api/llc-guidance/ask?${params.toString()}`, {
                method: 'POST',
                headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
                body: context ? JSON.stringify(context) : undefined,
            })
            if (!res.ok) throw new Error('Failed to ask question')
            return res.json()
        },
    })
}
