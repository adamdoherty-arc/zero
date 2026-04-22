import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`${response.status} ${body}`)
  }
  return response.json()
}

export type MotionKind = 'emotion' | 'dance'

export interface MotionClip {
  name: string
  kind: MotionKind
  dataset: string
  description: string
  category: string
  aliases: string[]
}

export interface MotionLibrary {
  total: number
  emotions: number
  dances: number
  clips: MotionClip[]
  by_category: Record<string, MotionClip[]>
}

export interface ReachyStatus {
  connected: boolean
  daemon: Record<string, unknown>
  base_url: string
}

const reachyKeys = {
  all: ['reachy'] as const,
  status: () => [...reachyKeys.all, 'status'] as const,
  motionLibrary: (kind?: MotionKind) => [...reachyKeys.all, 'motion', 'library', kind ?? 'all'] as const,
}

export function useReachyStatus(pollMs = 15_000) {
  return useQuery<ReachyStatus>({
    queryKey: reachyKeys.status(),
    queryFn: () => fetchApi('/reachy/status'),
    refetchInterval: pollMs,
  })
}

export function useMotionLibrary(kind?: MotionKind) {
  return useQuery<MotionLibrary>({
    queryKey: reachyKeys.motionLibrary(kind),
    queryFn: () => {
      const q = kind ? `?kind=${kind}` : ''
      return fetchApi(`/reachy/motion/library${q}`)
    },
    staleTime: 5 * 60_000,
  })
}

export function usePlayMotion() {
  return useMutation({
    mutationFn: (req: { name: string; kind?: MotionKind }) =>
      fetchApi('/reachy/motion/play', {
        method: 'POST',
        body: JSON.stringify(req),
      }),
  })
}

export function usePlayEmotion() {
  return useMutation({
    mutationFn: (emotion: string) =>
      fetchApi('/reachy/emotion', {
        method: 'POST',
        body: JSON.stringify({ emotion }),
      }),
  })
}

export function usePlayDance() {
  return useMutation({
    mutationFn: (dance: string) =>
      fetchApi('/reachy/dance', {
        method: 'POST',
        body: JSON.stringify({ dance }),
      }),
  })
}

export function useWakeUp() {
  return useMutation({ mutationFn: () => fetchApi('/reachy/wake-up', { method: 'POST' }) })
}

export function useGoToSleep() {
  return useMutation({ mutationFn: () => fetchApi('/reachy/sleep', { method: 'POST' }) })
}

export function useStopMove() {
  return useMutation({ mutationFn: () => fetchApi('/reachy/move/stop', { method: 'POST' }) })
}

// ---- Teleop (Wave 7) ----

export interface MoveRequest {
  roll?: number
  pitch?: number
  yaw?: number
  duration?: number
}

export interface AntennasRequest {
  left_angle?: number
  right_angle?: number
  duration?: number
}

export interface LookAtRequest {
  x: number
  y: number
  z: number
  duration?: number
}

export function useMoveHead() {
  return useMutation({
    mutationFn: (req: MoveRequest) =>
      fetchApi('/reachy/move', { method: 'POST', body: JSON.stringify(req) }),
  })
}

export function useSetAntennas() {
  return useMutation({
    mutationFn: (req: AntennasRequest) =>
      fetchApi('/reachy/antennas', { method: 'POST', body: JSON.stringify(req) }),
  })
}

export function useLookAt() {
  return useMutation({
    mutationFn: (req: LookAtRequest) =>
      fetchApi('/reachy/look', { method: 'POST', body: JSON.stringify(req) }),
  })
}

export function useCameraStream() {
  return useQuery<{ url: string; format: string }>({
    queryKey: ['reachy', 'camera', 'stream'],
    queryFn: () => fetchApi('/reachy/camera/stream?fmt=webrtc'),
    staleTime: 5 * 60_000,
  })
}

// ---- Personas (Wave 2) ----

export interface Persona {
  id: string
  name: string
  tagline: string
  tools: string[]
  system_prompt?: string
}

export interface PersonaList {
  active_id: string
  personas: Persona[]
}

const personaKeys = {
  all: ['reachy', 'personas'] as const,
  list: () => [...personaKeys.all, 'list'] as const,
  detail: (id: string) => [...personaKeys.all, 'detail', id] as const,
}

export function usePersonas() {
  return useQuery<PersonaList>({
    queryKey: personaKeys.list(),
    queryFn: () => fetchApi('/reachy/personas'),
    staleTime: 60_000,
  })
}

export function useSelectPersona() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (persona_id: string) =>
      fetchApi<{ active_id: string }>('/reachy/personas/select', {
        method: 'POST',
        body: JSON.stringify({ persona_id }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: personaKeys.list() }),
  })
}

export interface GestureParseResult {
  clean_text: string
  actions: { kind: string; payload: string; offset: number }[]
}

export function useGestureParse() {
  return useMutation({
    mutationFn: (text: string) =>
      fetchApi<GestureParseResult>('/reachy/gesture/parse', {
        method: 'POST',
        body: JSON.stringify({ text }),
      }),
  })
}
