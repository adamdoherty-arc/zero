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

export interface ReachyState {
  head_pose?: { x: number; y: number; z: number; roll: number; pitch: number; yaw: number }
  body_yaw?: number
  antenna_positions?: [number, number]
  doa?: { angle: number; speech_detected: boolean }
}

export function useReachyState(pollMs = 500) {
  return useQuery<ReachyState>({
    queryKey: ['reachy', 'state'],
    queryFn: () => fetchApi('/reachy/state'),
    refetchInterval: pollMs,
    refetchIntervalInBackground: false,
  })
}

// ---- Move recorder (Wave 10) ----

export interface RecordStatus {
  recording: boolean
  library: string
  name: string
  description: string
  started_at: string | null
  elapsed_s: number | null
  frame_count: number
  replaying: boolean
}

export interface UserMove {
  library: string
  name: string
  description: string
  duration_s: number
  frame_count: number
  recorded_at: string | null
}

export function useRecordStatus(pollMs = 1000) {
  return useQuery<RecordStatus>({
    queryKey: ['reachy', 'moves', 'record', 'status'],
    queryFn: () => fetchApi('/reachy/moves/record/status'),
    refetchInterval: pollMs,
  })
}

export function useStartRecording() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { library: string; name: string; description?: string }) =>
      fetchApi('/reachy/moves/record/start', { method: 'POST', body: JSON.stringify(req) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'moves'] }),
  })
}

export function useStopRecording() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/moves/record/stop', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'moves'] }),
  })
}

export function useUserMoves() {
  return useQuery<{ moves: UserMove[] }>({
    queryKey: ['reachy', 'moves', 'user'],
    queryFn: () => fetchApi('/reachy/moves/user'),
    staleTime: 30_000,
  })
}

export function usePlayUserMove() {
  return useMutation({
    mutationFn: (req: { library: string; name: string }) =>
      fetchApi(`/reachy/moves/user/${encodeURIComponent(req.library)}/${encodeURIComponent(req.name)}/play`, {
        method: 'POST',
      }),
  })
}

export function useDeleteUserMove() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { library: string; name: string }) =>
      fetchApi(`/reachy/moves/user/${encodeURIComponent(req.library)}/${encodeURIComponent(req.name)}`, {
        method: 'DELETE',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'moves'] }),
  })
}

// ---- Wake word (Wave 11) ----

export interface WakeWordStatus {
  available: boolean
  model: string
  threshold: number
  cooldown_s: number
  last_score: number
  import_error: string | null
}

export function useWakeWordStatus(pollMs = 5000) {
  return useQuery<WakeWordStatus>({
    queryKey: ['reachy', 'wake-word', 'status'],
    queryFn: () => fetchApi('/reachy/wake-word/status'),
    refetchInterval: pollMs,
  })
}

// ---- Vision (Wave 12) ----

export interface VisionBackends {
  hands: { available: boolean; library?: string; version?: string; reason?: string }
  face: { available: boolean; library?: string; version?: string; reason?: string }
}

export interface VisionDetection {
  kind: string
  x: number
  y: number
  width: number
  height: number
  confidence: number
}

export interface VisionResult {
  available: boolean
  backend?: string
  image_size?: { width: number; height: number }
  detections: VisionDetection[]
  reason?: string
}

export function useVisionBackends() {
  return useQuery<VisionBackends>({
    queryKey: ['reachy', 'vision', 'backends'],
    queryFn: () => fetchApi('/reachy/vision/backends'),
    staleTime: 30_000,
  })
}

// ---- Radio (Wave 13) ----

export interface RadioStatus {
  active: boolean
  bpm: number
  beats_per_dance: number
  dances: string[]
  current_dance: string | null
  dances_played: number
  started_at: string | null
  elapsed_s: number | null
}

export function useRadioStatus(pollMs = 2000) {
  return useQuery<RadioStatus>({
    queryKey: ['reachy', 'radio', 'status'],
    queryFn: () => fetchApi('/reachy/radio/status'),
    refetchInterval: pollMs,
  })
}

export function useStartRadio() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { bpm: number; beats_per_dance?: number; dances?: string[] }) =>
      fetchApi('/reachy/radio/start', { method: 'POST', body: JSON.stringify(req) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'radio'] }),
  })
}

export function useStopRadio() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/radio/stop', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'radio'] }),
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
