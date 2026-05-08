import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type {
  Meeting, MeetingListResponse, MeetingCreate,
  TranscriptResponse, MeetingSummary,
  RecordingStatus, MeetingSearchResponse,
  SpeakerMapping,
} from '../types/meeting'

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
  if (response.status === 204) return undefined as T
  return response.json()
}

// Query key factories
export const meetingKeys = {
  all: ['meetings'] as const,
  lists: () => [...meetingKeys.all, 'list'] as const,
  list: (filters?: MeetingListFilters) => [...meetingKeys.lists(), filters] as const,
  details: () => [...meetingKeys.all, 'detail'] as const,
  detail: (id: string) => [...meetingKeys.details(), id] as const,
  transcript: (id: string) => [...meetingKeys.all, 'transcript', id] as const,
  summary: (id: string) => [...meetingKeys.all, 'summary', id] as const,
  speakers: (id: string) => [...meetingKeys.all, 'speakers', id] as const,
  search: (query: string, type?: string) => [...meetingKeys.all, 'search', query, type] as const,
  recording: () => [...meetingKeys.all, 'recording'] as const,
}

export interface MeetingListFilters {
  status?: string
  limit?: number
  offset?: number
}

// ---- Recording Capabilities ----
export interface RecordingCapabilities {
  can_record: boolean
  via?: 'host_agent' | 'local'
  host_agent_url?: string
  has_system_audio?: boolean
  has_mic?: boolean
  message: string | null
}

export function useRecordingCapabilities(pollMs = 30_000) {
  return useQuery<RecordingCapabilities>({
    queryKey: [...meetingKeys.all, 'capabilities'] as const,
    queryFn: () => fetchApi<RecordingCapabilities>('/meeting-recordings/capabilities'),
    staleTime: 30_000,
    refetchInterval: pollMs,
  })
}

// ---- List Meetings ----
export function useMeetings(filters?: MeetingListFilters) {
  const params = new URLSearchParams()
  if (filters?.status) params.set('status', filters.status)
  if (filters?.limit) params.set('limit', String(filters.limit))
  if (filters?.offset) params.set('offset', String(filters.offset))
  const qs = params.toString()

  return useQuery({
    queryKey: meetingKeys.list(filters),
    queryFn: () => fetchApi<MeetingListResponse>(`/meetings/${qs ? `?${qs}` : ''}`),
  })
}

// ---- Get Single Meeting ----
export function useMeeting(id: string) {
  return useQuery({
    queryKey: meetingKeys.detail(id),
    queryFn: () => fetchApi<Meeting>(`/meetings/${id}`),
    enabled: !!id,
  })
}

// ---- Create Meeting ----
export function useCreateMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: MeetingCreate) =>
      fetchApi<Meeting>('/meetings/', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.lists() })
    },
  })
}

// ---- Delete Meeting ----
export function useDeleteMeeting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<void>(`/meetings/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.lists() })
    },
  })
}

// ---- Start Recording ----
export function useStartRecording() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      meeting_id?: string
      title?: string
      source?: string
      mic_device_index?: number
      system_device_index?: number
    }) =>
      fetchApi<RecordingStatus>('/meeting-recordings/start', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.recording() })
      queryClient.invalidateQueries({ queryKey: meetingKeys.lists() })
    },
  })
}

// ---- Audio devices (mic + system loopback) ----
export interface AudioDeviceInfo {
  index: number
  name: string
  host_api: string
  max_input_channels: number
  default_samplerate: number
  is_reachy: boolean
}

export interface AudioDevicesResponse {
  mic: AudioDeviceInfo[]
  system_loopback: AudioDeviceInfo[]
}

export function useAudioDevices() {
  return useQuery({
    queryKey: [...meetingKeys.all, 'devices'] as const,
    queryFn: () => fetchApi<AudioDevicesResponse>('/meeting-recordings/devices'),
    staleTime: 30_000,
  })
}

// ---- Reachy status ----
export interface ReachyStatus {
  connected: boolean
  daemon?: Record<string, unknown>
  base_url?: string
}

export function useReachyStatus() {
  return useQuery({
    queryKey: ['reachy', 'status'] as const,
    queryFn: () => fetchApi<ReachyStatus>('/reachy/status'),
    refetchInterval: 10_000,
    retry: false,
  })
}

// ---- Stop Recording ----
export function useStopRecording() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<RecordingStatus>('/meeting-recordings/stop', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.recording() })
      queryClient.invalidateQueries({ queryKey: meetingKeys.lists() })
    },
  })
}

// ---- Transcript ----
export function useMeetingTranscript(id: string) {
  return useQuery({
    queryKey: meetingKeys.transcript(id),
    queryFn: () => fetchApi<TranscriptResponse>(`/meeting-transcriptions/${id}`),
    enabled: !!id,
  })
}

// ---- Summary ----
export function useMeetingSummary(id: string) {
  return useQuery({
    queryKey: meetingKeys.summary(id),
    queryFn: () => fetchApi<MeetingSummary>(`/meeting-summaries/${id}`),
    enabled: !!id,
  })
}

// ---- Generate Summary ----
export function useGenerateSummary() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<MeetingSummary>(`/meeting-summaries/${id}/generate`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.summary(id) })
      queryClient.invalidateQueries({ queryKey: meetingKeys.detail(id) })
    },
  })
}

// ---- Retranscribe ----
export function useRetranscribe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<unknown>(`/meeting-transcriptions/${id}/retranscribe`, { method: 'POST' }),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.transcript(id) })
    },
  })
}

// ---- Search ----
export function useMeetingSearch(query: string, type?: string) {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  if (type) params.set('search_type', type)
  const qs = params.toString()

  return useQuery({
    queryKey: meetingKeys.search(query, type),
    queryFn: () => fetchApi<MeetingSearchResponse>(`/meeting-search/?${qs}`),
    enabled: query.length > 0,
  })
}

// ---- Speakers ----
export function useMeetingSpeakers(id: string) {
  return useQuery({
    queryKey: meetingKeys.speakers(id),
    queryFn: () => fetchApi<SpeakerMapping[]>(`/meetings/${id}/speakers`),
    enabled: !!id,
  })
}

// ---- Artifact stats (badge data) ----
export interface MeetingArtifactStats {
  meeting_id: string
  transcript_segments: number
  has_summary: boolean
  action_items_count: number
  speaker_count: number
}

export function useMeetingArtifactStats(meetingIds: string[]) {
  const ids = meetingIds.slice().sort().join(',')
  return useQuery({
    queryKey: ['meetings', 'artifact-stats', ids],
    queryFn: () =>
      fetchApi<MeetingArtifactStats[]>(
        `/meetings/artifacts/stats?meeting_ids=${encodeURIComponent(ids)}`,
      ),
    enabled: ids.length > 0,
    staleTime: 30_000,
  })
}

// ---- Meeting preferences ----
export interface MeetingPreferences {
  auto_record_all: boolean
  auto_create_tasks_from_meetings: boolean
}

export const meetingPrefKeys = {
  all: ['meeting-preferences'] as const,
}

export function useMeetingPreferences() {
  return useQuery({
    queryKey: meetingPrefKeys.all,
    queryFn: () => fetchApi<MeetingPreferences>('/meeting-preferences'),
    staleTime: 30_000,
  })
}

export function useUpdateMeetingPreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (update: Partial<MeetingPreferences>) =>
      fetchApi<MeetingPreferences>('/meeting-preferences', {
        method: 'PATCH',
        body: JSON.stringify(update),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: meetingPrefKeys.all })
    },
  })
}

// ---- Live tick (running notes during recording) ----
export interface LiveTickResponse {
  running_notes_delta: string[]
  new_action_items: { owner: string; description: string; due: string | null }[]
}

export function useLiveTick() {
  return useMutation({
    mutationFn: (input: {
      chunk_text: string
      running_notes: string[]
      meeting_title: string
    }) =>
      fetchApi<LiveTickResponse>('/meeting-summaries/live-tick', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
  })
}

// ---- Action Items → Tasks ----
export interface ActionItemTaskLink {
  index: number
  owner: string
  description: string
  due: string | null
  task_id: string | null
  skipped_reason: string | null
}

export interface CreateTasksResponse {
  meeting_id: string
  created: ActionItemTaskLink[]
  skipped: ActionItemTaskLink[]
}

export function useCreateTasksFromActionItems() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      meeting_id,
      owner_filter = 'all',
    }: {
      meeting_id: string
      owner_filter?: 'all' | 'me'
    }) =>
      fetchApi<CreateTasksResponse>(
        `/meetings/${meeting_id}/action-items/create-tasks`,
        {
          method: 'POST',
          body: JSON.stringify({ owner_filter, auto_assign: true }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

// ---- Voiceprints ----
export interface Voiceprint {
  id: number
  display_name: string
  samples_seconds: number
  is_primary: boolean
  source_meeting_id: string | null
  created_at: string
  updated_at: string
}

export const voiceprintKeys = {
  all: ['voiceprints'] as const,
}

export function useVoiceprints() {
  return useQuery({
    queryKey: voiceprintKeys.all,
    queryFn: () => fetchApi<Voiceprint[]>('/voiceprints'),
    staleTime: 30_000,
  })
}

export function useDeleteVoiceprint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      fetchApi<{ deleted: boolean; id: number }>(`/voiceprints/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: voiceprintKeys.all })
    },
  })
}

/** Drives the host_agent's mic-only enrollment recording. */
export function useEnrollVoiceprint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      display_name: string
      duration_seconds?: number
      is_primary?: boolean
    }) => {
      // host_agent runs on the Windows host. Hit it directly — same convention
      // the live transcript WebSocket uses.
      const url = '/host-agent/voice/enroll'
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          display_name: input.display_name,
          duration_seconds: input.duration_seconds ?? 30,
          is_primary: input.is_primary ?? true,
        }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(err.detail || `HTTP ${response.status}`)
      }
      return response.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: voiceprintKeys.all })
    },
  })
}

// ---- Update Speakers ----
export function useUpdateSpeakers() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, speakers }: { id: string; speakers: SpeakerMapping[] }) =>
      fetchApi<SpeakerMapping[]>(`/meetings/${id}/speakers`, {
        method: 'PUT',
        body: JSON.stringify(speakers),
      }),
    onSuccess: (_data, { id }) => {
      queryClient.invalidateQueries({ queryKey: meetingKeys.speakers(id) })
      queryClient.invalidateQueries({ queryKey: meetingKeys.transcript(id) })
    },
  })
}
