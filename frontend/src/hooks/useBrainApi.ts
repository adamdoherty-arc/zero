import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types

export interface BenchmarkScore {
  dimension: string
  score: number
  weight: number
  details: Record<string, unknown>
  computed_at: string
}

export interface BenchmarkSnapshot {
  overall_score: number
  dimension_scores: Record<string, number>
  weakest_dimension: string
  improvement_action?: string
  snapshot_at: string
}

export interface BrainStatus {
  overall_score: number
  dimension_scores: Record<string, BenchmarkScore>
  weakest_dimension: string
  total_memories: number
  total_outcomes: number
  total_prompt_variants: number
  active_experiments: number
  last_benchmark_at?: string
  last_learning_cycle_at?: string
}

export interface EpisodicMemory {
  id: string
  namespace: string
  content: string
  source_type: string
  source_id?: string
  importance: number
  tags: string[]
  context: Record<string, unknown>
  expires_at?: string
  created_at: string
}

export interface MemorySearchResult {
  memory: EpisodicMemory
  similarity: number
}

export interface ContentExperiment {
  id: string
  name: string
  hypothesis: string
  experiment_type: string
  control_config: Record<string, unknown>
  variant_config: Record<string, unknown>
  status: string
  sample_size_target: number
  control_results: Record<string, unknown>[]
  variant_results: Record<string, unknown>[]
  conclusion?: string
  winner?: string
  created_at: string
  completed_at?: string
}

export interface LearningCycle {
  id: string
  cycle_type: string
  status: string
  results: Record<string, unknown>
  improvements: Record<string, unknown>[]
  cost_usd: number
  started_at: string
  completed_at?: string
  error?: string
}

export interface CalibrationBucket {
  range_label: string
  count: number
  avg_predicted: number
  avg_actual: number
  mae: number
}

// Query Keys

const brainKeys = {
  all: ['brain'] as const,
  status: () => [...brainKeys.all, 'status'] as const,
  benchmark: () => [...brainKeys.all, 'benchmark'] as const,
  benchmarkHistory: () => [...brainKeys.all, 'benchmark', 'history'] as const,
  learnings: (domain?: string) => [...brainKeys.all, 'learnings', domain] as const,
  calibration: (domain?: string) => [...brainKeys.all, 'calibration', domain] as const,
  outcomes: (domain?: string) => [...brainKeys.all, 'outcomes', domain] as const,
  memory: (query: string) => [...brainKeys.all, 'memory', query] as const,
  memoryRecent: () => [...brainKeys.all, 'memory', 'recent'] as const,
  experiments: (status?: string) => [...brainKeys.all, 'experiments', status] as const,
  prompts: (taskType?: string) => [...brainKeys.all, 'prompts', taskType] as const,
  contentInsights: () => [...brainKeys.all, 'content', 'insights'] as const,
  contentStrategies: () => [...brainKeys.all, 'content', 'strategies'] as const,
  postingTimes: () => [...brainKeys.all, 'content', 'posting-times'] as const,
  cycles: () => [...brainKeys.all, 'cycles'] as const,
}

// Hooks

export function useBrainStatus() {
  return useQuery({
    queryKey: brainKeys.status(),
    queryFn: async (): Promise<BrainStatus> => {
      const res = await fetch(`${API_URL}/api/brain/status`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch brain status')
      return res.json()
    },
    staleTime: 30000,
  })
}

export function useBenchmark() {
  return useQuery({
    queryKey: brainKeys.benchmark(),
    queryFn: async (): Promise<BenchmarkSnapshot | null> => {
      const res = await fetch(`${API_URL}/api/brain/benchmark`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch benchmark')
      return res.json()
    },
    staleTime: 60000,
  })
}

export function useBenchmarkHistory() {
  return useQuery({
    queryKey: brainKeys.benchmarkHistory(),
    queryFn: async (): Promise<BenchmarkSnapshot[]> => {
      const res = await fetch(`${API_URL}/api/brain/benchmark/history?limit=20`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch benchmark history')
      return res.json()
    },
    staleTime: 60000,
  })
}

export function useBrainLearnings(domain?: string) {
  return useQuery({
    queryKey: brainKeys.learnings(domain),
    queryFn: async (): Promise<string[]> => {
      const params = new URLSearchParams()
      if (domain) params.append('domain', domain)
      const res = await fetch(`${API_URL}/api/brain/learnings?${params}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch learnings')
      return res.json()
    },
    staleTime: 30000,
  })
}

export function useCalibrationReport(domain?: string) {
  return useQuery({
    queryKey: brainKeys.calibration(domain),
    queryFn: async (): Promise<{ buckets: CalibrationBucket[]; domain: string }> => {
      const params = new URLSearchParams()
      if (domain) params.append('domain', domain)
      const res = await fetch(`${API_URL}/api/brain/calibration?${params}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch calibration')
      return res.json()
    },
    staleTime: 60000,
  })
}

export function useBrainOutcomes(domain?: string) {
  return useQuery({
    queryKey: brainKeys.outcomes(domain),
    queryFn: async () => {
      const params = new URLSearchParams()
      if (domain) params.append('domain', domain)
      const res = await fetch(`${API_URL}/api/brain/outcomes?${params}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch outcomes')
      return res.json()
    },
    staleTime: 15000,
  })
}

export function useMemorySearch(query: string) {
  return useQuery({
    queryKey: brainKeys.memory(query),
    queryFn: async (): Promise<MemorySearchResult[]> => {
      const res = await fetch(`${API_URL}/api/brain/memory?q=${encodeURIComponent(query)}&limit=10`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to search memory')
      return res.json()
    },
    enabled: query.length >= 2,
    staleTime: 10000,
  })
}

export function useRecentMemories() {
  return useQuery({
    queryKey: brainKeys.memoryRecent(),
    queryFn: async (): Promise<EpisodicMemory[]> => {
      const res = await fetch(`${API_URL}/api/brain/memory/recent?limit=20`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch recent memories')
      return res.json()
    },
    staleTime: 15000,
  })
}

export function useBrainExperiments(status?: string) {
  return useQuery({
    queryKey: brainKeys.experiments(status),
    queryFn: async (): Promise<ContentExperiment[]> => {
      const params = new URLSearchParams()
      if (status) params.append('status', status)
      const res = await fetch(`${API_URL}/api/brain/experiments?${params}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch experiments')
      return res.json()
    },
    staleTime: 15000,
  })
}

export function useContentInsights() {
  return useQuery({
    queryKey: brainKeys.contentInsights(),
    queryFn: async () => {
      const res = await fetch(`${API_URL}/api/brain/content/insights`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch content insights')
      return res.json()
    },
    staleTime: 60000,
  })
}

export function useLearningCycles() {
  return useQuery({
    queryKey: brainKeys.cycles(),
    queryFn: async (): Promise<LearningCycle[]> => {
      const res = await fetch(`${API_URL}/api/brain/cycles?limit=10`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch learning cycles')
      return res.json()
    },
    staleTime: 15000,
  })
}

// Mutations

export function useTriggerBenchmark() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (): Promise<BenchmarkSnapshot> => {
      const res = await fetch(`${API_URL}/api/brain/benchmark/run`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to run benchmark')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: brainKeys.all })
    },
  })
}

export function useTriggerLearningCycle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (): Promise<LearningCycle> => {
      const res = await fetch(`${API_URL}/api/brain/cycles/run`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to run learning cycle')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: brainKeys.all })
    },
  })
}

export function useTriggerImprovement() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (dimension?: string) => {
      const params = new URLSearchParams()
      if (dimension) params.append('dimension', dimension)
      const res = await fetch(`${API_URL}/api/brain/improve?${params}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to trigger improvement')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: brainKeys.all })
    },
  })
}

// --- Prompt Runs ---

export interface PromptRun {
  id: string
  variant_id?: string | null
  task_type: string
  source: string
  source_id?: string | null
  provider: string
  model: string
  system_prompt?: string | null
  user_prompt: string
  rendered_variables: Record<string, unknown>
  response_text?: string | null
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  cost_usd: number
  success: boolean
  error_type?: string | null
  error_message?: string | null
  quality_score?: number | null
  quality_flags: string[]
  quality_summary?: string | null
  grader_model?: string | null
  graded_at?: string | null
  outcome_score?: number | null
  outcome_recorded_at?: string | null
  context: Record<string, unknown>
  created_at: string
}

export interface PromptRunStats {
  totals: {
    total: number
    graded: number
    ungraded: number
    total_cost_usd: number
  }
  by_task_type: Array<{
    task_type: string
    total: number
    graded: number
    ungraded: number
    avg_quality: number | null
    avg_outcome: number | null
    avg_latency_ms: number | null
    total_cost_usd: number
  }>
}

const promptRunKeys = {
  all: ['brain', 'prompt-runs'] as const,
  list: (taskType?: string, source?: string, variantId?: string) =>
    [...promptRunKeys.all, 'list', taskType, source, variantId] as const,
  detail: (runId: string) => [...promptRunKeys.all, 'detail', runId] as const,
  stats: () => [...promptRunKeys.all, 'stats'] as const,
}

export function usePromptRuns(opts?: {
  taskType?: string
  source?: string
  variantId?: string
  limit?: number
}) {
  return useQuery({
    queryKey: promptRunKeys.list(opts?.taskType, opts?.source, opts?.variantId),
    queryFn: async (): Promise<PromptRun[]> => {
      const params = new URLSearchParams()
      if (opts?.taskType) params.append('task_type', opts.taskType)
      if (opts?.source) params.append('source', opts.source)
      if (opts?.variantId) params.append('variant_id', opts.variantId)
      params.append('limit', String(opts?.limit ?? 50))
      const res = await fetch(`${API_URL}/api/brain/prompt-runs?${params}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch prompt runs')
      return res.json()
    },
    staleTime: 15000,
  })
}

export function usePromptRun(runId: string | null) {
  return useQuery({
    queryKey: promptRunKeys.detail(runId ?? ''),
    queryFn: async (): Promise<PromptRun | null> => {
      if (!runId) return null
      const res = await fetch(`${API_URL}/api/brain/prompt-runs/${runId}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch prompt run')
      return res.json()
    },
    enabled: !!runId,
    staleTime: 30000,
  })
}

export function usePromptRunStats() {
  return useQuery({
    queryKey: promptRunKeys.stats(),
    queryFn: async (): Promise<PromptRunStats> => {
      const res = await fetch(`${API_URL}/api/brain/prompt-runs/stats`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to fetch prompt run stats')
      return res.json()
    },
    staleTime: 30000,
  })
}

export function useTriggerPromptGrading() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (limit: number = 20): Promise<{ graded: number; failed: number }> => {
      const res = await fetch(`${API_URL}/api/brain/prompt-runs/grade?limit=${limit}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to trigger grading')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: promptRunKeys.all })
      queryClient.invalidateQueries({ queryKey: brainKeys.prompts() })
    },
  })
}
