import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types

export interface CouncilVote {
  role: string
  position: string
  reasoning: string
  confidence: number
}

export interface CouncilRound {
  round: number
  positions: CouncilVote[]
}

export interface CouncilDecision {
  id: string
  topic: string
  context: Record<string, unknown>
  proposer_role: string
  rounds: CouncilRound[]
  votes: Record<string, CouncilVote>
  decision?: string
  confidence_score: number
  created_at: string
  decided_at?: string
}

export interface CouncilProposal {
  topic: string
  context?: Record<string, unknown>
}

export interface CouncilFilters {
  status?: string
  limit?: number
}

// Query key factory

const councilKeys = {
  all: ['council'] as const,
  decisions: () => [...councilKeys.all, 'decisions'] as const,
  decisionList: (filters?: CouncilFilters) => [...councilKeys.decisions(), filters] as const,
  decision: (id: string) => [...councilKeys.decisions(), id] as const,
}

// Hooks

export function useCouncilDecisions(filters?: CouncilFilters) {
  return useQuery({
    queryKey: councilKeys.decisionList(filters),
    queryFn: async (): Promise<CouncilDecision[]> => {
      const params = new URLSearchParams()
      if (filters?.status) params.append('status', filters.status)
      if (filters?.limit !== undefined) params.append('limit', filters.limit.toString())
      const res = await fetch(`${API_URL}/api/council/decisions?${params.toString()}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch council decisions')
      return res.json()
    },
    staleTime: 10000,
  })
}

export function useCouncilDecision(decisionId: string) {
  return useQuery({
    queryKey: councilKeys.decision(decisionId),
    queryFn: async (): Promise<CouncilDecision> => {
      const res = await fetch(`${API_URL}/api/council/decisions/${decisionId}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch council decision')
      return res.json()
    },
    enabled: !!decisionId,
    staleTime: 5000,
  })
}

export function useProposeDecision() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: CouncilProposal): Promise<CouncilDecision> => {
      const res = await fetch(`${API_URL}/api/council/decisions`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('Failed to propose decision')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: councilKeys.decisions() })
    },
  })
}

export function useConductVote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (decisionId: string): Promise<CouncilDecision> => {
      const res = await fetch(`${API_URL}/api/council/decisions/${decisionId}/vote`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to conduct vote')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: councilKeys.decisions() })
    },
  })
}
