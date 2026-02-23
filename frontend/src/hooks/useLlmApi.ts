import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type { LlmRouterStatus, LlmProvider, LlmUsageToday } from '../types'

const API_BASE = '/api'

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }
  return response.json()
}

const llmKeys = {
  all: ['llm'] as const,
  config: () => [...llmKeys.all, 'config'] as const,
  resolve: (taskType: string) => [...llmKeys.all, 'resolve', taskType] as const,
  providers: () => [...llmKeys.all, 'providers'] as const,
  usageToday: () => [...llmKeys.all, 'usage', 'today'] as const,
  availableModels: () => [...llmKeys.all, 'available-models'] as const,
}

export function useLlmConfig() {
  return useQuery<LlmRouterStatus>({
    queryKey: llmKeys.config(),
    queryFn: () => fetchApi('/llm/config'),
    refetchInterval: 60_000,
  })
}

export function useSetDefaultModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { model: string; update_all_tasks: boolean }) =>
      fetchApi('/llm/default-model', {
        method: 'PUT',
        body: JSON.stringify(req),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: llmKeys.all }),
  })
}

export function useSetTaskModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: {
      task_type: string
      model: string
      fallbacks?: string[] | null
      temperature?: number | null
      num_predict?: number | null
      keep_alive?: string | null
    }) =>
      fetchApi(`/llm/task/${req.task_type}`, {
        method: 'PUT',
        body: JSON.stringify(req),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: llmKeys.all }),
  })
}

export function useRemoveTaskOverride() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskType: string) =>
      fetchApi(`/llm/task/${taskType}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: llmKeys.all }),
  })
}

export function useLlmProviders() {
  return useQuery<{ providers: LlmProvider[] }>({
    queryKey: llmKeys.providers(),
    queryFn: () => fetchApi('/llm/providers'),
    refetchInterval: 30_000,
  })
}

export function useLlmUsageToday() {
  return useQuery<LlmUsageToday>({
    queryKey: llmKeys.usageToday(),
    queryFn: () => fetchApi('/llm/usage/today'),
    refetchInterval: 30_000,
  })
}

export function useLlmAvailableModels() {
  return useQuery<{ models_by_provider: Record<string, string[]> }>({
    queryKey: llmKeys.availableModels(),
    queryFn: () => fetchApi('/llm/available-models'),
    staleTime: 5 * 60_000,
  })
}
