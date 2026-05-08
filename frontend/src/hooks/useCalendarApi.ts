import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EventDateTime {
  date_time?: string
  date?: string
  timezone?: string
}

export interface CalendarEventSummary {
  id: string
  summary: string
  start: EventDateTime
  end: EventDateTime
  location?: string
  is_all_day?: boolean
  status?: string
  has_attendees?: boolean
  html_link?: string
}

export interface AutoRecordEntry {
  calendar_event_id: string
  meeting_id: string
  start_time: string
  end_time?: string | null
  title?: string | null
  started?: boolean
  stopped?: boolean
  started_at?: string
  stopped_at?: string
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const calendarKeys = {
  all: ['calendar'] as const,
  events: (params?: Record<string, string>) =>
    [...calendarKeys.all, 'events', params ?? {}] as const,
  today: () => [...calendarKeys.all, 'today'] as const,
  autoRecord: () => [...calendarKeys.all, 'auto-record'] as const,
  status: () => [...calendarKeys.all, 'status'] as const,
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export interface CalendarStatus {
  connected: boolean
  email_address: string | null
  last_sync: string | null
  calendars_count: number
  upcoming_events_count: number
  sync_errors: string[]
}

export function useCalendarStatus() {
  return useQuery({
    queryKey: calendarKeys.status(),
    queryFn: () => fetchApi<CalendarStatus>('/calendar/status'),
    refetchInterval: 30_000,
  })
}

export async function fetchCalendarAuthUrl(): Promise<string> {
  // Use the unified Google OAuth flow (/api/google/auth/...). The
  // /api/calendar/auth/... callback URL isn't registered in the Google
  // Cloud Console OAuth client, so it fails with redirect_uri_mismatch.
  // The unified flow grants both Gmail + Calendar scopes in one consent
  // and stores the account in oauth_accounts, which is what
  // calendar_service.sync_events() reads from.
  const data = await fetchApi<{ auth_url: string; state: string }>('/google/auth/url')
  return data.auth_url
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useCalendarEvents(params?: {
  start_date?: string
  end_date?: string
  limit?: number
  account_id?: string | null
}) {
  const qs = new URLSearchParams()
  if (params?.start_date) qs.set('start_date', params.start_date)
  if (params?.end_date) qs.set('end_date', params.end_date)
  if (params?.limit) qs.set('limit', String(params.limit))
  if (params?.account_id) qs.set('account_id', params.account_id)
  const search = qs.toString()
  return useQuery({
    queryKey: calendarKeys.events(params as Record<string, string> | undefined),
    // Backend returns List[EventSummary] directly (not wrapped in {events,total}).
    queryFn: () => fetchApi<CalendarEventSummary[]>(`/calendar/events${search ? `?${search}` : ''}`),
    refetchInterval: 60_000,
  })
}

export function useTodaySchedule() {
  return useQuery({
    queryKey: calendarKeys.today(),
    queryFn: () => fetchApi<unknown>('/calendar/today'),
    refetchInterval: 60_000,
  })
}

export function useAutoRecordList() {
  return useQuery({
    queryKey: calendarKeys.autoRecord(),
    queryFn: () => fetchApi<{ entries: AutoRecordEntry[] }>('/meetings/auto-record/list'),
    refetchInterval: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export interface CreateEventInput {
  summary: string
  description?: string
  location?: string
  start: EventDateTime
  end: EventDateTime
  attendees?: { email: string; name?: string }[]
}

export function useCreateCalendarEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CreateEventInput) =>
      fetchApi<unknown>('/calendar/events', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useSyncCalendar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<unknown>('/calendar/sync', { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useMeetingFromEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (calendar_event_id: string) =>
      fetchApi<{ id: string; title: string }>('/meetings/from-event', {
        method: 'POST',
        body: JSON.stringify({ calendar_event_id }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.autoRecord() })
      qc.invalidateQueries({ queryKey: ['meetings'] })
    },
  })
}

export function useRecordNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (meeting_id: string) =>
      fetchApi<unknown>(`/meetings/${meeting_id}/record-now`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meetings'] })
    },
  })
}

export function useToggleAutoRecord() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ meeting_id, enabled }: { meeting_id: string; enabled: boolean }) =>
      fetchApi<{ meeting_id: string; auto_record: boolean }>(`/meetings/${meeting_id}/auto-record`, {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.autoRecord() })
    },
  })
}
