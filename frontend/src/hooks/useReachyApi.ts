import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { toast } from '@/hooks/use-toast'
import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

/**
 * Follow-up after a motion mutation: invalidate the relevant state caches,
 * fire a short polling burst so the UI reflects the new robot state within
 * a few hundred ms, and surface a toast if the daemon dropped or the
 * state probe started failing right after the motion was dispatched.
 *
 * Pairs with the 2s _STATE_PROBE_STALE_CACHE_S cap on the backend.
 */
async function motionFollowup(qc: QueryClient, label: string): Promise<void> {
  qc.invalidateQueries({ queryKey: ['reachy', 'status'] })
  qc.invalidateQueries({ queryKey: ['reachy', 'motion', 'sources'] })
  qc.invalidateQueries({ queryKey: ['reachy', 'assistant', 'status'] })
  qc.invalidateQueries({ queryKey: ['reachy', 'state'] })
  // Polling burst — refetches at 300 / 900 / 2000ms so the UI sees pose
  // updates without waiting for the next 5–15s scheduled refetch.
  const checkpoints = [300, 600, 1100]
  for (const wait of checkpoints) {
    await new Promise((r) => setTimeout(r, wait))
    try {
      const status = await fetch(`${API_BASE}/reachy/status`, {
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      }).then((r) => (r.ok ? r.json() : null))
      if (!status) continue
      qc.setQueryData(['reachy', 'status'], status)
      if (status.daemon_connected === false) {
        toast({
          title: `${label} dispatched, but daemon is unreachable`,
          description:
            status.robot_detail ||
            'The Reachy daemon stopped responding right after the motion was sent. Check daemon health.',
          variant: 'destructive',
        })
        return
      }
      if (status.robot_ready === false && status.body_control_mode === 'disabled') {
        toast({
          title: `${label} dispatched, but motors are disabled`,
          description:
            status.robot_detail ||
            'Motors are disabled. Click "Wake up" or check the motor mode toggle.',
        })
        return
      }
    } catch {
      // Intermediate errors are non-fatal; the periodic refetch will catch up.
    }
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function findStringField(value: unknown, field: string, depth = 0): string | undefined {
  if (depth > 5) return undefined
  const record = asRecord(value)
  if (!record) return undefined
  const direct = record[field]
  if (typeof direct === 'string' && direct.trim()) return direct
  for (const child of Object.values(record)) {
    const found = findStringField(child, field, depth + 1)
    if (found) return found
  }
  return undefined
}

function formatApiError(status: number, body: string): string {
  let payload: unknown
  try {
    payload = JSON.parse(body)
  } catch {
    return `${status} ${body}`
  }

  const error = findStringField(payload, 'error')
  const reason = findStringField(payload, 'reason')
  const surface = findStringField(payload, 'surface')
  const detail = findStringField(payload, 'detail') ?? findStringField(payload, 'message')
  const label = surface ? surface.replace(/_/g, ' ') : 'request'

  if (error === 'body_motion_locked' || reason?.includes('body_motion')) {
    return `Body motion locked (${label}). ${detail ?? 'Physical movement is disabled for safety.'}`
  }
  if (detail) return `${status} ${detail}`
  if (error) return `${status} ${error}`
  return `${status} ${body}`
}

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(formatApiError(response.status, body))
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
  daemon_connected?: boolean
  robot_ready?: boolean
  robot_detail?: string
  body_control_mode?: string | null
  body_activity?: ReachyBodyActivity
  pose_jitter?: ReachyPoseJitter
  motion_sources?: ReachyMotionSource[]
  active_source_ids?: string[]
  daemon_route?: string
  daemon_direct_reachable?: boolean
  state_probe_reachable?: boolean
  status_stale?: boolean
  recommended_action?: { id: string; label: string; detail: string }
  state_probe?: Record<string, unknown>
  daemon: Record<string, unknown>
  base_url: string
}

export type ReachyAssistantState = 'ready' | 'repair_required' | 'starting' | 'degraded' | 'offline'
export type ReachyBodyActivity = 'still' | 'moving' | 'settling' | 'shaky' | 'unknown'
export type ReachySessionPhase =
  | 'idle'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'moving'
  | 'recovering'
  | 'stalled'

export interface ReachyInputHealth {
  source: string
  ready: boolean
  rms: number
  peak: number
  empty_stt_count: number
  confidence_state: string
  last_signal_at?: number | null
  last_frame_at?: number | null
  suggested_action?: string | null
  last_error?: string | null
}

export interface ReachyOutputHealth {
  sink: string
  ready: boolean
  queued_ms: number
  last_error?: string | null
}

export interface ReachyPoseJitter {
  available: boolean
  samples: number
  shaky: boolean
  head_delta_rad?: number
  body_yaw_delta_rad?: number
  antenna_delta_rad?: number
  deltas?: Record<string, number>
}

export interface ReachyMotionSource {
  id: string
  label: string
  active: boolean
  enabled?: boolean
  detail: string
  raw?: unknown
}

export interface ReachyHardwareIssueStatus {
  available?: boolean
  active?: boolean
  stale?: boolean
  power_issue?: boolean
  last_fault_at?: string | null
  last_fault_age_seconds?: number | null
  active_window_seconds?: number
  faults?: Array<{
    motor?: string
    error?: string
    count?: number
    last_line?: string
    last_at?: string
    last_age_seconds?: number | null
    active?: boolean
    stale?: boolean
  }>
  issues?: Array<{
    id?: string
    severity?: string
    title?: string
    detail?: string
    hint?: string
    missing_motors?: Array<Record<string, unknown>>
  }>
  line_count?: number
}

export interface ReachyAssistantActivity {
  at: number
  event: string
  detail: string
  ok: boolean
  state?: ReachyAssistantState | string | null
  body_activity?: ReachyBodyActivity | string | null
}

export interface ReachyAssistantStep {
  id: 'zero_api' | 'host_agent' | 'reachy_daemon' | 'watchdog' | 'robot' | 'voice_backend' | 'persona'
  label: string
  state: ReachyAssistantState
  detail: string
  action?: string
}

export interface ReachyAssistantStatus {
  state: ReachyAssistantState
  steps: ReachyAssistantStep[]
  actions: Array<{ id: string; ok: boolean; detail: string; command?: string; result?: unknown }>
  repair_command: string
  connected: boolean
  daemon_connected?: boolean
  robot_ready?: boolean
  robot_detail?: string
  body_control_mode?: string | null
  state_probe?: Record<string, unknown>
  daemon_api?: Record<string, unknown>
  daemon: Record<string, unknown>
  watchdog: Record<string, unknown> | null
  host_agent: Record<string, unknown> | null
  realtime: Record<string, unknown>
  persona: string | null
  ambient: Record<string, unknown>
  motion_sources: ReachyMotionSource[]
  active_source_ids: string[]
  body_activity: ReachyBodyActivity
  pose_jitter: ReachyPoseJitter
  session_phase?: ReachySessionPhase
  stalled_reason?: string | null
  input_health?: ReachyInputHealth | null
  output_health?: ReachyOutputHealth | null
  hardware_issues?: ReachyHardwareIssueStatus
  recent_activity: ReachyAssistantActivity[]
  base_url: string
}

export interface ReachyMotionSourcesStatus {
  state: ReachyAssistantState
  sources: ReachyMotionSource[]
  active_source_ids: string[]
  body_activity: ReachyBodyActivity
  pose_jitter: ReachyPoseJitter
}

export interface ReachySettleResult {
  ok: boolean
  reason: string
  actions: Array<{ id: string; ok: boolean; detail: string; result?: unknown }>
  state: ReachyAssistantState
  motion_sources: ReachyMotionSource[]
  active_source_ids: string[]
  body_activity: ReachyBodyActivity
  pose_jitter: ReachyPoseJitter
  robot_ready: boolean
  state_probe?: Record<string, unknown>
  recent_activity?: ReachyAssistantActivity[]
}

const reachyKeys = {
  all: ['reachy'] as const,
  status: () => [...reachyKeys.all, 'status'] as const,
  assistantStatus: () => [...reachyKeys.all, 'assistant', 'status'] as const,
  motionSources: () => [...reachyKeys.all, 'motion', 'sources'] as const,
  motionLibrary: (kind?: MotionKind) => [...reachyKeys.all, 'motion', 'library', kind ?? 'all'] as const,
  daemonStatus: () => [...reachyKeys.all, 'daemon', 'status'] as const,
  daemonLogs: (tail: number) => [...reachyKeys.all, 'daemon', 'logs', tail] as const,
  daemonDiagnostics: () => [...reachyKeys.all, 'daemon', 'diagnostics'] as const,
  daemonWatchdog: () => [...reachyKeys.all, 'daemon', 'watchdog'] as const,
  companionStatus: () => [...reachyKeys.all, 'companion', 'status'] as const,
  companionEvents: (limit: number) => [...reachyKeys.all, 'companion', 'events', limit] as const,
  companionPolicy: () => [...reachyKeys.all, 'companion', 'policy'] as const,
  companionSkills: () => [...reachyKeys.all, 'companion', 'skills'] as const,
  sequences: () => [...reachyKeys.all, 'sequences'] as const,
  sequence: (id: number | string) => [...reachyKeys.all, 'sequences', id] as const,
}

export function useReachyStatus(pollMs = 15_000) {
  return useQuery<ReachyStatus>({
    queryKey: reachyKeys.status(),
    queryFn: () => fetchApi('/reachy/status'),
    refetchInterval: pollMs,
  })
}

export function useReachyAssistantStatus(pollMs = 5_000) {
  return useQuery<ReachyAssistantStatus>({
    queryKey: reachyKeys.assistantStatus(),
    queryFn: () => fetchApi('/reachy/assistant/status'),
    refetchInterval: pollMs,
  })
}

export function useReachyMotionSources(pollMs = 5_000) {
  return useQuery<ReachyMotionSourcesStatus>({
    queryKey: reachyKeys.motionSources(),
    queryFn: () => fetchApi('/reachy/motion/sources'),
    refetchInterval: pollMs,
  })
}

export type CompanionMode = 'ambient' | 'focus' | 'meeting' | 'privacy' | 'sleep'
export type CompanionEventType =
  | 'voice_heard'
  | 'person_seen'
  | 'object_seen'
  | 'phone_seen'
  | 'meeting_started'
  | 'email_arrived'
  | 'ha_state_changed'
  | 'idle_elapsed'
  | 'skill_triggered'
  | 'mode_changed'
  | 'policy_changed'
  | 'privacy_alert'
  | 'notice'

export interface CompanionPolicy {
  mode: CompanionMode
  mic_enabled: boolean
  camera_enabled: boolean
  body_motion_enabled: boolean
  proactive_enabled: boolean
  cloud_realtime_allowed: boolean
  memory_write_allowed: boolean
  deterministic_alerts_enabled: boolean
  max_proactive_events_per_hour: number
  allowed_actions: string[]
  per_persona_tool_grants: Record<string, string[]>
  quiet_hours_start: number
  quiet_hours_end: number
  updated_at: string
}

export interface CompanionEvent {
  id: string
  type: CompanionEventType
  source: string
  summary: string
  payload: Record<string, unknown>
  importance: number
  created_at: string
  mode: CompanionMode
  persona_id?: string | null
}

export interface CompanionSkill {
  id: string
  title: string
  description: string
  mode_bias: CompanionMode
  required_events: CompanionEventType[]
  allowed_actions: string[]
  enabled: boolean
  blocked_reason?: string | null
}

export interface CompanionDiagnostic {
  id: string
  label: string
  state: string
  ok: boolean
  detail: string
  repair?: string | null
}

export interface CompanionStatus {
  mode: CompanionMode
  policy: CompanionPolicy
  persona: Persona | { id: string; name: string; tools?: string[]; [key: string]: unknown }
  presence: Record<string, unknown>
  realtime: Record<string, unknown>
  body: Record<string, unknown>
  senses: Record<string, unknown>
  diagnostics: CompanionDiagnostic[]
  skills: CompanionSkill[]
  timeline: CompanionEvent[]
  next_suggested_action: { id: string; label: string; priority: 'low' | 'medium' | 'high' | string }
  host_agent?: Record<string, unknown> | null
  host_daemon?: Record<string, unknown> | null
}

export function useReachyCompanionStatus(pollMs = 5_000) {
  return useQuery<CompanionStatus>({
    queryKey: reachyKeys.companionStatus(),
    queryFn: () => fetchApi('/reachy/companion/status'),
    refetchInterval: pollMs,
  })
}

export function useReachyCompanionEvents(limit = 30, pollMs = 10_000) {
  return useQuery<CompanionEvent[]>({
    queryKey: reachyKeys.companionEvents(limit),
    queryFn: () => fetchApi(`/reachy/companion/events?limit=${limit}`),
    refetchInterval: pollMs,
  })
}

export function useSetCompanionMode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { mode: CompanionMode; reason?: string; apply_actions?: boolean }) =>
      fetchApi<CompanionPolicy>('/reachy/companion/modes', {
        method: 'POST',
        body: JSON.stringify({ reason: 'user', apply_actions: true, ...req }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.companionStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.companionPolicy() })
      qc.invalidateQueries({ queryKey: reachyKeys.companionEvents(30) })
      qc.invalidateQueries({ queryKey: ['reachy', 'presence'] })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
    },
  })
}

export function usePatchCompanionPolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<Omit<CompanionPolicy, 'mode' | 'updated_at'>>) =>
      fetchApi<CompanionPolicy>('/reachy/companion/policy', {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.companionStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.companionPolicy() })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.motionSources() })
      qc.invalidateQueries({ queryKey: ['reachy', 'motors'] })
    },
  })
}

export function useTriggerCompanionSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (skillId: string) =>
      fetchApi<{ ok: boolean; skill_id: string; mode: CompanionMode; actions: unknown[]; event: CompanionEvent }>(
        `/reachy/companion/skills/${encodeURIComponent(skillId)}/trigger`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.companionStatus() })
      qc.invalidateQueries({ queryKey: ['reachy', 'presence'] })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
    },
  })
}

export function useCreateCompanionEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (event: {
      type: CompanionEventType
      source?: string
      summary: string
      payload?: Record<string, unknown>
      importance?: number
    }) =>
      fetchApi<CompanionEvent>('/reachy/companion/events', {
        method: 'POST',
        body: JSON.stringify({ source: 'ui', payload: {}, importance: 0.4, ...event }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.companionStatus() })
    },
  })
}

export function useSettleReachyAssistant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req?: { keep_motors_enabled?: boolean; neutral_pose?: 'default' | 'skip'; reason?: string }) =>
      fetchApi<ReachySettleResult>('/reachy/assistant/settle', {
        method: 'POST',
        body: JSON.stringify({
          keep_motors_enabled: false,
          neutral_pose: 'skip',
          reason: 'user',
          ...req,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.motionSources() })
      qc.invalidateQueries({ queryKey: ['reachy', 'motors'] })
      qc.invalidateQueries({ queryKey: ['reachy', 'radio'] })
    },
  })
}

export function useActivateReachyAssistant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req?: {
      persona?: string
      voice_mode?: 'live'
      enable_ambient?: boolean
      start_daemon?: boolean
      wake_robot?: boolean
      enable_body_motion?: boolean
    }) =>
      fetchApi<ReachyAssistantStatus>('/reachy/assistant/activate', {
        method: 'POST',
        body: JSON.stringify({
          persona: 'companion',
          voice_mode: 'live',
          enable_ambient: false,
          start_daemon: false,
          wake_robot: false,
          enable_body_motion: false,
          ...req,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonWatchdog() })
      qc.invalidateQueries({ queryKey: reachyKeys.motionSources() })
      qc.invalidateQueries({ queryKey: ['reachy', 'personas'] })
    },
  })
}

type ReachyRealtimeRecoverResult = {
  ok: boolean
  recover: Record<string, unknown>
  assistant: ReachyAssistantStatus
}

export function useRecoverReachyRealtime() {
  const qc = useQueryClient()
  return useMutation<ReachyRealtimeRecoverResult, Error, string | undefined>({
    mutationFn: (reason = 'manual') =>
      fetchApi<ReachyRealtimeRecoverResult>(
        '/reachy/realtime/recover',
        {
          method: 'POST',
          body: JSON.stringify({ reason }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.motionSources() })
    },
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
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { name: string; kind?: MotionKind }) =>
      fetchApi('/reachy/motion/play', {
        method: 'POST',
        body: JSON.stringify(req),
      }),
    onSuccess: (_data, req) => motionFollowup(qc, `Motion ${req.name}`),
  })
}

export function usePlayEmotion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (emotion: string) =>
      fetchApi('/reachy/emotion', {
        method: 'POST',
        body: JSON.stringify({ emotion }),
      }),
    onSuccess: (_data, emotion) => motionFollowup(qc, `Emotion ${emotion}`),
  })
}

export function usePlayDance() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (dance: string) =>
      fetchApi('/reachy/dance', {
        method: 'POST',
        body: JSON.stringify({ dance }),
      }),
    onSuccess: (_data, dance) => motionFollowup(qc, `Dance ${dance}`),
  })
}

export function useWakeUp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/wake-up', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: ['reachy', 'motors'] })
    },
  })
}

export function useGoToSleep() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/sleep', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: ['reachy', 'motors'] })
    },
  })
}

export function useStopMove() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/move/stop', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.motionSources() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
    },
  })
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
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: MoveRequest) =>
      fetchApi('/reachy/move', { method: 'POST', body: JSON.stringify(req) }),
    onSuccess: () => motionFollowup(qc, 'Head move'),
  })
}

export function useSetAntennas() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: AntennasRequest) =>
      fetchApi('/reachy/antennas', { method: 'POST', body: JSON.stringify(req) }),
    onSuccess: () => motionFollowup(qc, 'Antennas'),
  })
}

export function useLookAt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: LookAtRequest) =>
      fetchApi('/reachy/look', { method: 'POST', body: JSON.stringify(req) }),
    onSuccess: () => motionFollowup(qc, 'Look at'),
  })
}

export function useCameraStream() {
  return useQuery<{ url: string; format: string }>({
    queryKey: ['reachy', 'camera', 'stream'],
    queryFn: () => fetchApi('/reachy/camera/stream?fmt=mjpeg'),
    staleTime: 5 * 60_000,
  })
}

export interface CameraStatus {
  active: boolean
  backend?: string
  device_index?: number
  width?: number
  height?: number
  fps?: number
  age_seconds?: number | null
  consumers?: number
  last_error?: string | null
  reason?: string
}

export function useCameraStatus(pollMs = 2000) {
  return useQuery<CameraStatus>({
    queryKey: ['reachy', 'camera', 'status'],
    queryFn: () => fetchApi('/reachy/camera/status'),
    refetchInterval: pollMs,
    refetchIntervalInBackground: false,
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

// ---- Presence: Pomodoro + Meeting mode ----

export interface PomodoroState {
  active: boolean
  phase: string
  started_at: string | null
  elapsed_s: number | null
  focus_minutes: number
  break_minutes: number
  cycle_index: number
}

export interface MeetingState {
  active: boolean
  meeting_id: string | null
  started_at: string | null
  elapsed_s: number | null
  doa_available?: boolean
}

export function usePomodoroState(pollMs = 2000) {
  return useQuery<PomodoroState>({
    queryKey: ['reachy', 'presence', 'pomodoro'],
    queryFn: () => fetchApi('/reachy/presence/pomodoro'),
    refetchInterval: pollMs,
  })
}

export function useStartPomodoro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: { focus_minutes?: number; break_minutes?: number }) =>
      fetchApi('/reachy/presence/pomodoro/start', {
        method: 'POST',
        body: JSON.stringify({ focus_minutes: 25, break_minutes: 5, ...req }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'presence'] }),
  })
}

export function useStopPomodoro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/presence/pomodoro/stop', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'presence'] }),
  })
}

export function useMeetingState(pollMs = 2000) {
  return useQuery<MeetingState>({
    queryKey: ['reachy', 'presence', 'meeting'],
    queryFn: () => fetchApi('/reachy/presence/meeting'),
    refetchInterval: pollMs,
  })
}

export function useStartMeetingMode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (meeting_id?: string) =>
      fetchApi('/reachy/presence/meeting/start', {
        method: 'POST',
        body: JSON.stringify({ meeting_id: meeting_id ?? null }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'presence'] }),
  })
}

export function useStopMeetingMode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi('/reachy/presence/meeting/stop', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'presence'] }),
  })
}

// ---- Volume, motors, sounds, test ----

export function useVolume(kind: 'speaker' | 'mic' = 'speaker') {
  const path = kind === 'mic' ? '/reachy/volume/microphone' : '/reachy/volume'
  return useQuery<{ volume: number }>({
    queryKey: ['reachy', 'volume', kind],
    queryFn: () => fetchApi(path),
    staleTime: 10_000,
  })
}

export function useSetVolume(kind: 'speaker' | 'mic' = 'speaker') {
  const qc = useQueryClient()
  const path = kind === 'mic' ? '/reachy/volume/microphone' : '/reachy/volume'
  return useMutation({
    mutationFn: (volume: number) =>
      fetchApi(path, { method: 'POST', body: JSON.stringify({ volume }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'volume', kind] }),
  })
}

export function useTestSound() {
  return useMutation({ mutationFn: () => fetchApi('/reachy/test-sound', { method: 'POST' }) })
}

export interface MotorStatus {
  mode?: string
  ready?: boolean
  [k: string]: unknown
}

export function useMotorStatus(pollMs = 5000) {
  return useQuery<MotorStatus>({
    queryKey: ['reachy', 'motors'],
    queryFn: () => fetchApi('/reachy/motors'),
    refetchInterval: pollMs,
  })
}

export function useSetMotorMode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (mode: 'enabled' | 'disabled' | 'compliant') =>
      fetchApi('/reachy/motors/mode', {
        method: 'POST',
        body: JSON.stringify({ mode }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['reachy', 'motors'] })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
    },
  })
}

export function useSounds() {
  return useQuery<{ sounds?: string[]; files?: string[]; [k: string]: unknown }>({
    queryKey: ['reachy', 'sounds'],
    queryFn: () => fetchApi('/reachy/sounds'),
    staleTime: 30_000,
  })
}

export function usePlayDaemonSound() {
  return useMutation({
    mutationFn: (file: string) =>
      fetchApi('/reachy/sounds/play', { method: 'POST', body: JSON.stringify({ file }) }),
  })
}

export function useStopDaemonSound() {
  return useMutation({ mutationFn: () => fetchApi('/reachy/sounds/stop', { method: 'POST' }) })
}

// ---- Context hint + persona stats ----

export interface ContextHintResult { persona: string; hint: string }

export function useContextHint(pollMs = 10000) {
  return useQuery<ContextHintResult>({
    queryKey: ['reachy', 'context', 'hint'],
    queryFn: () => fetchApi('/reachy/context/hint'),
    refetchInterval: pollMs,
  })
}

export interface ContextDebug {
  local_time: string | null
  time_of_day: string | null
  pomodoro: { phase: string; cycle_index: number; elapsed_s: number } | null
  meeting: { elapsed_s: number; doa_available: boolean | null } | null
  upcoming: { label: string; minutes: number | null; imminent: boolean } | null
  sight: string | null
  attention: string | null
}

export interface MemoryNote {
  id: string
  category: 'preference' | 'fact' | 'correction' | 'topic'
  text: string
  confidence: number
  learned_at: number
  last_used_at: number | null
  uses: number
}

export interface MemoryStats {
  total_turns: number
  turns_retained: number
  notes_count: number
  per_persona: Record<string, number>
  notes_by_category: Record<string, number>
}

export interface MemoryPayload { notes: MemoryNote[]; stats: MemoryStats }

const memoryKeys = {
  all: ['reachy', 'memory'] as const,
}

export function useUserMemory(pollMs = 30_000) {
  return useQuery<MemoryPayload>({
    queryKey: memoryKeys.all,
    queryFn: () => fetchApi('/reachy/memory'),
    refetchInterval: pollMs,
    staleTime: pollMs / 2,
  })
}

export function useAddMemoryNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      category: 'preference' | 'fact' | 'correction' | 'topic'
      text: string
      confidence?: number
    }) =>
      fetchApi<MemoryNote>('/reachy/memory/notes', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: memoryKeys.all }),
  })
}

export function useDeleteMemoryNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<{ deleted: string }>(`/reachy/memory/notes/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: memoryKeys.all }),
  })
}

export interface ContextDebugResult { persona: string; context: ContextDebug }

export function useContextDebug(pollMs = 30_000) {
  return useQuery<ContextDebugResult>({
    queryKey: ['reachy', 'context', 'debug'],
    queryFn: () => fetchApi('/reachy/context/debug?include_sight=false'),
    refetchInterval: pollMs,
    staleTime: pollMs / 2,
  })
}

export interface PersonaStats {
  last_switched_at: string | null
  rotation: Record<string, unknown>
  personas: Record<string, {
    interactions: number
    emotions_fired: number
    dances_fired: number
    last_used_at: string | null
  }>
}

export function usePersonaStats(pollMs = 5000) {
  return useQuery<PersonaStats>({
    queryKey: ['reachy', 'personas', 'stats'],
    queryFn: () => fetchApi('/reachy/personas/stats'),
    refetchInterval: pollMs,
  })
}

export function useResetPersonaStats() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (persona_id?: string) => {
      const qs = persona_id ? `?persona_id=${encodeURIComponent(persona_id)}` : ''
      return fetchApi(`/reachy/personas/stats/reset${qs}`, { method: 'POST' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reachy', 'personas', 'stats'] }),
  })
}

// ---- Home Assistant ----

export interface HaStatus {
  configured: boolean
  base?: string
  message?: string
  version?: string
  [k: string]: unknown
}

export interface HaState {
  entity_id: string
  state: string
  attributes?: Record<string, unknown>
  last_changed?: string
  [k: string]: unknown
}

export function useHaStatus(pollMs = 30000) {
  return useQuery<HaStatus>({
    queryKey: ['reachy', 'ha', 'status'],
    queryFn: () => fetchApi('/home-assistant/status'),
    refetchInterval: pollMs,
  })
}

export function useHaStates() {
  return useQuery<HaState[]>({
    queryKey: ['reachy', 'ha', 'states'],
    queryFn: () => fetchApi('/home-assistant/states'),
    staleTime: 20_000,
  })
}

export function useHaCallService() {
  return useMutation({
    mutationFn: (req: { domain: string; service: string; data?: Record<string, unknown> }) =>
      fetchApi('/home-assistant/service', { method: 'POST', body: JSON.stringify(req) }),
  })
}

export interface HaGestureMap {
  started: boolean
  map: Record<string, { state?: string; emotion?: string; dance?: string; cooldown_s?: number }>
}

export function useHaGestureMap() {
  return useQuery<HaGestureMap>({
    queryKey: ['reachy', 'ha', 'gesture-map'],
    queryFn: () => fetchApi('/home-assistant/gesture-map'),
    staleTime: 30_000,
  })
}

// ---- Personas (Wave 2) ----

export interface Persona {
  id: string
  name: string
  tagline: string
  tools: string[]
  system_prompt?: string
  voice?: string | null
  preview_line?: string | null
  signature_gesture?: string | null
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

export interface RecentMotion {
  name: string
  kind: string
  source: string
  ts: number
}

export function useRecentMotions(limit = 10, pollMs = 6_000) {
  return useQuery<{ motions: RecentMotion[] }>({
    queryKey: ['reachy', 'motion', 'recent', limit],
    queryFn: () => fetchApi(`/reachy/motion/recent?limit=${limit}`),
    refetchInterval: pollMs,
    staleTime: pollMs / 2,
  })
}

export interface PersonaPreviewResult {
  persona_id: string
  line: string
  voice: string | null
  gesture: string | null
  played_on_robot: boolean
  audio_b64: string
}

export function usePreviewPersona() {
  return useMutation({
    mutationFn: (persona_id: string) =>
      fetchApi<PersonaPreviewResult>(
        `/reachy/personas/${encodeURIComponent(persona_id)}/preview`,
        { method: 'POST' },
      ),
  })
}

export interface PersonaIntrosMap {
  map: Record<string, number>
}

const personaIntrosKeys = {
  all: ['reachy', 'personas', 'intros'] as const,
}

export function usePersonaIntros() {
  return useQuery<PersonaIntrosMap>({
    queryKey: personaIntrosKeys.all,
    queryFn: () => fetchApi('/reachy/personas/intros'),
    staleTime: 30_000,
  })
}

export function useSetPersonaIntro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: { persona_id: string; sequence_id: number }) =>
      fetchApi<{ persona_id: string; sequence_id: number }>(
        `/reachy/personas/${encodeURIComponent(params.persona_id)}/intro`,
        { method: 'POST', body: JSON.stringify({ sequence_id: params.sequence_id }) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: personaIntrosKeys.all }),
  })
}

export function useClearPersonaIntro() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (persona_id: string) =>
      fetchApi<{ cleared: string }>(
        `/reachy/personas/${encodeURIComponent(persona_id)}/intro`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: personaIntrosKeys.all }),
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

// ---- Daemon supervisor (proxied through zero-api to host_agent) ----

export interface DaemonStatus {
  running: boolean
  pid: number | null
  started_at: string | null
  uptime_seconds: number | null
  last_exit_code: number | null
  log_path: string | null
  daemon_url?: string
}

export interface DaemonLogs {
  lines: string[]
  count: number
  total_buffered: number
  log_path: string | null
}

export interface DaemonRestartEvent {
  at: string
  reason: string
  was_running_before: boolean
  new_pid: number | null
}

export interface DaemonWatchdog {
  enabled: boolean
  consecutive_failures: number
  failure_threshold: number
  poll_interval_s: number
  last_check: string | null
  last_daemon_up: string | null
  restart_history: DaemonRestartEvent[]
}

export interface DaemonKnownIssue {
  id: string
  severity: 'error' | 'warning' | 'info'
  title: string
  hint: string
}

export interface DaemonDiagnostics {
  daemon: Record<string, unknown>
  audio_devices: Array<{
    index: number
    name: string
    is_input: boolean
    is_output: boolean
    sample_rate: number
    host_api: number | string
    is_reachy: boolean
  }>
  usb_devices: {
    ports: Array<{
      device: string
      description: string
      vid: number | null
      pid: number | null
      manufacturer: string | null
      serial_number: string | null
    }>
    likely_reachy: Array<{ device: string; description: string }>
    error?: string
  }
  host: {
    cpu_percent?: number
    mem_used_mb?: number
    mem_total_mb?: number
    mem_percent?: number
    timestamp?: string
    psutil_error?: string
  }
  supervisor: DaemonStatus
  watchdog: DaemonWatchdog
  known_issues?: {
    count: number
    items: DaemonKnownIssue[]
  }
}

export interface DaemonRetryScanResult {
  ok: boolean
  action: 'start' | 'restart' | string
  detail: string
  daemon: Record<string, unknown>
  wait: Record<string, unknown>
  assistant: ReachyAssistantStatus
  hardware_issues?: ReachyHardwareIssueStatus
}

export function useDaemonStatus(pollMs = 5_000) {
  return useQuery<DaemonStatus>({
    queryKey: reachyKeys.daemonStatus(),
    queryFn: () => fetchApi('/reachy/daemon/status'),
    refetchInterval: pollMs,
    retry: false,
  })
}

export function useDaemonLogs(tail = 100, enabled = false, pollMs = 3_000) {
  return useQuery<DaemonLogs>({
    queryKey: reachyKeys.daemonLogs(tail),
    queryFn: () => fetchApi(`/reachy/daemon/logs?tail=${tail}`),
    refetchInterval: enabled ? pollMs : false,
    enabled,
    retry: false,
  })
}

export function useDaemonDiagnostics(enabled = false) {
  return useQuery<DaemonDiagnostics>({
    queryKey: reachyKeys.daemonDiagnostics(),
    queryFn: () => fetchApi('/reachy/daemon/diagnostics'),
    enabled,
    retry: false,
    staleTime: 10_000,
  })
}

export function useDaemonWatchdog(pollMs = 10_000) {
  return useQuery<DaemonWatchdog>({
    queryKey: reachyKeys.daemonWatchdog(),
    queryFn: () => fetchApi('/reachy/daemon/watchdog'),
    refetchInterval: pollMs,
    retry: false,
  })
}

function useDaemonMutation(path: string, body?: unknown) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi(path, {
        method: 'POST',
        body: body !== undefined ? JSON.stringify(body) : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.daemonStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonWatchdog() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonDiagnostics() })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
    },
  })
}

export function useStartDaemon() {
  return useDaemonMutation('/reachy/daemon/start')
}

export function useStopDaemon() {
  return useDaemonMutation('/reachy/daemon/stop')
}

export function useRestartDaemon() {
  return useDaemonMutation('/reachy/daemon/restart')
}

export function useRetryHardwareScan() {
  const qc = useQueryClient()
  return useMutation<DaemonRetryScanResult, Error, string | undefined>({
    mutationFn: (reason = 'manual') =>
      fetchApi<DaemonRetryScanResult>('/reachy/daemon/retry-scan', {
        method: 'POST',
        body: JSON.stringify({ reason }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.daemonStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonWatchdog() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonDiagnostics() })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.motionSources() })
    },
  })
}

export function useResetAudio() {
  return useDaemonMutation('/reachy/daemon/audio/reset')
}

export function useSetWatchdog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      fetchApi('/reachy/daemon/watchdog', {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.daemonWatchdog() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonStatus() })
      qc.invalidateQueries({ queryKey: reachyKeys.daemonDiagnostics() })
      qc.invalidateQueries({ queryKey: reachyKeys.status() })
      qc.invalidateQueries({ queryKey: reachyKeys.assistantStatus() })
    },
  })
}

// ---- User-defined motion sequences ----

export interface SequenceStep {
  clip: string
  kind?: 'emotion' | 'dance' | null
  gap_ms: number
}

export interface MotionSequence {
  id: number
  name: string
  description: string | null
  steps: SequenceStep[]
  aliases: string[]
  created_at: string | null
  updated_at: string | null
}

export interface SequenceCreate {
  name: string
  description?: string | null
  steps: SequenceStep[]
  aliases?: string[]
}

export interface SequenceUpdate {
  name?: string
  description?: string | null
  steps?: SequenceStep[]
  aliases?: string[]
}

export function useSequences() {
  return useQuery<{ sequences: MotionSequence[] }>({
    queryKey: reachyKeys.sequences(),
    queryFn: () => fetchApi('/reachy/sequences'),
    staleTime: 30_000,
  })
}

export function useSequence(idOrName: number | string | null) {
  return useQuery<MotionSequence>({
    queryKey: reachyKeys.sequence(idOrName ?? 'none'),
    queryFn: () => fetchApi(`/reachy/sequences/${idOrName}`),
    enabled: idOrName !== null && idOrName !== undefined && idOrName !== '',
  })
}

export function useCreateSequence() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SequenceCreate) =>
      fetchApi<MotionSequence>('/reachy/sequences', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.sequences() })
    },
  })
}

export function useUpdateSequence() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: SequenceUpdate }) =>
      fetchApi<MotionSequence>(`/reachy/sequences/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: reachyKeys.sequences() })
      qc.invalidateQueries({ queryKey: reachyKeys.sequence(vars.id) })
    },
  })
}

export function useDeleteSequence() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      fetchApi(`/reachy/sequences/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: reachyKeys.sequences() })
    },
  })
}

export function usePlaySequence() {
  return useMutation({
    mutationFn: (idOrName: number | string) =>
      fetchApi(`/reachy/sequences/${idOrName}/play`, { method: 'POST' }),
  })
}
