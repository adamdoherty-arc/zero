import { useQuery } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

export interface MeetingStewardStatus {
  checked_at: string
  ok: boolean
  issues: Array<{ id: string; detail: string }>
  /** Retired 2026-07-11 — robot/Reachy hardware control moved to Zero Studio. */
  companion?: { retired?: boolean; note?: string }
  /** Retired 2026-07-11 — robot/Reachy hardware control moved to Zero Studio. */
  host_agent?: { retired?: boolean; note?: string }
  approvals?: { pending?: number; error?: string }
  notifications?: {
    recent_count?: number
    by_type?: Record<string, number>
    last_alarm?: Record<string, unknown> | null
    error?: string
  }
  transcript_backlog?: {
    stuck_over_1h?: number
    total_processing?: number
    error?: string
  }
  janitor?: {
    ran_at?: string
    deleted?: number
    kept?: number
    bytes_reclaimed?: number
    retain_days?: number
    never_run?: boolean
    error?: string
  }
  followup_ledger?: { total?: number; last?: Record<string, unknown> | null; error?: string }
  open_meeting_actions?: {
    count?: number
    items?: Array<{ id: string; title: string; status: string; tags?: string[] }>
    error?: string
  }
  concurrency_queue?: { queued?: Array<Record<string, unknown>>; error?: string }
  privacy?: { private_meetings?: string[]; error?: string }
}

export function useMeetingStewardStatus() {
  return useQuery({
    queryKey: ['meeting-steward', 'status'],
    queryFn: async (): Promise<MeetingStewardStatus> => {
      const res = await fetch('/api/meeting-steward/', {
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      return await res.json()
    },
    refetchInterval: 15000,
  })
}
