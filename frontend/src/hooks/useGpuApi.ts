import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type {
  GpuStatus,
  GpuManagerConfig,
  LoadedModel,
  OllamaModelInfo,
  VramBudget,
  ProjectUsage,
} from '../types'

const API_BASE = '/api'

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

// Query key factory
export const gpuKeys = {
  all: ['gpu'] as const,
  status: () => [...gpuKeys.all, 'status'] as const,
  loaded: () => [...gpuKeys.all, 'loaded'] as const,
  available: () => [...gpuKeys.all, 'available'] as const,
  budget: (model: string) => [...gpuKeys.all, 'budget', model] as const,
  usage: () => [...gpuKeys.all, 'usage'] as const,
  config: () => [...gpuKeys.all, 'config'] as const,
}

// ---- GPU Status (polls every 30s) ----
export function useGpuStatus() {
  return useQuery({
    queryKey: gpuKeys.status(),
    queryFn: () => fetchApi<GpuStatus>('/gpu/status'),
    refetchInterval: 30000,
  })
}

// ---- Loaded Models ----
export function useLoadedModels() {
  return useQuery({
    queryKey: gpuKeys.loaded(),
    queryFn: () =>
      fetchApi<{ models: LoadedModel[]; count: number; total_vram_used_mb: number }>(
        '/gpu/models/loaded'
      ),
    refetchInterval: 30000,
  })
}

// ---- Available Models ----
export function useAvailableModels() {
  return useQuery({
    queryKey: gpuKeys.available(),
    queryFn: () =>
      fetchApi<{ models: OllamaModelInfo[]; count: number }>('/gpu/models/available'),
    staleTime: 60000,
  })
}

// ---- VRAM Budget ----
export function useVramBudget(model: string) {
  return useQuery({
    queryKey: gpuKeys.budget(model),
    queryFn: () => fetchApi<VramBudget>(`/gpu/budget/${encodeURIComponent(model)}`),
    enabled: !!model,
  })
}

// ---- Project Usage ----
export function useProjectUsage() {
  return useQuery({
    queryKey: gpuKeys.usage(),
    queryFn: () =>
      fetchApi<{ usage: ProjectUsage[]; count: number }>('/gpu/usage'),
    refetchInterval: 30000,
  })
}

// ---- Load Model ----
export function useLoadModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      model: string
      project?: string
      keep_alive?: string
      force?: boolean
    }) =>
      fetchApi<{ status: string; model: string }>('/gpu/models/load', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gpuKeys.all })
    },
  })
}

// ---- Unload Model ----
export function useUnloadModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: { model: string; project?: string }) =>
      fetchApi<{ status: string; model: string }>('/gpu/models/unload', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gpuKeys.all })
    },
  })
}

// ---- Force Refresh ----
export function useForceGpuRefresh() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ status: string }>('/gpu/refresh', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gpuKeys.all })
    },
  })
}

// ---- Config ----
export function useGpuConfig() {
  return useQuery({
    queryKey: gpuKeys.config(),
    queryFn: () => fetchApi<GpuManagerConfig>('/gpu/config'),
  })
}

export function useUpdateGpuConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: Partial<GpuManagerConfig>) =>
      fetchApi<GpuManagerConfig>('/gpu/config', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gpuKeys.config() })
    },
  })
}
