import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API = '/api/reachy'

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export interface VoiceConfig {
  stt_model: string
  llm: { provider: string; model: string; spec: string; task_type: string }
  tts_voice: string
}

export interface VoiceConfigPatch {
  stt_model?: string
  llm_model?: string
  tts_voice?: string
}

export interface LlmChoice {
  provider: string
  model: string
  spec: string
}

export interface SttChoice {
  id: string
  name: string
  description: string
  size_mb: number
}

export interface TtsChoice {
  id: string
  engine: string
  label: string
}

export interface VoiceModelsCatalog {
  stt: SttChoice[]
  llm: LlmChoice[]
  tts: TtsChoice[]
}

const voiceKeys = {
  all: ['reachy', 'voice'] as const,
  config: () => [...voiceKeys.all, 'config'] as const,
  models: () => [...voiceKeys.all, 'models'] as const,
}

export function useVoiceConfig() {
  return useQuery<VoiceConfig>({
    queryKey: voiceKeys.config(),
    queryFn: () => apiGet<VoiceConfig>('/voice/config'),
    staleTime: 30_000,
  })
}

export function useVoiceModels() {
  return useQuery<VoiceModelsCatalog>({
    queryKey: voiceKeys.models(),
    queryFn: () => apiGet<VoiceModelsCatalog>('/voice/models'),
    staleTime: 60_000,
  })
}

export function useUpdateVoiceConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: VoiceConfigPatch) =>
      apiPut<{ ok: boolean; applied: VoiceConfigPatch }>('/voice/config', patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: voiceKeys.config() })
    },
  })
}
