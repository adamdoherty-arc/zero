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
export function useRecordingCapabilities() {
  return useQuery({
    queryKey: [...meetingKeys.all, 'capabilities'] as const,
    queryFn: () => fetchApi<{
      can_record: boolean
      has_system_audio: boolean
      has_mic: boolean
      message: string | null
    }>('/meeting-recordings/capabilities'),
    staleTime: 60_000,
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
    mutationFn: (data: { meeting_id?: string; title?: string }) =>
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
