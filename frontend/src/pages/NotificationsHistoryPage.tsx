import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, Clock } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'

interface HistoryEvent {
  type: string
  source?: string | null
  ts: string | null
  [key: string]: unknown
}

interface HistoryResponse {
  events: HistoryEvent[]
  since_hours: number
  type_filter: string | null
  by_type: Record<string, number>
  count: number
}

const PRESETS: { label: string; hours: number }[] = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: '30d', hours: 720 },
]

function eventTone(type: string): string {
  if (type.includes('alarm') || type.includes('lost') || type.includes('failed')) {
    return 'border-rose-500/40 bg-rose-500/10 text-rose-200'
  }
  if (type.startsWith('meeting.starting') || type === 'meeting.prep') {
    return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
  }
  if (type.startsWith('meeting.conflict')) {
    return 'border-amber-500/40 bg-amber-500/10 text-amber-200'
  }
  return 'border-gray-800 bg-gray-900/50 text-gray-300'
}

export function NotificationsHistoryPage() {
  const [hours, setHours] = useState<number>(24)
  const [typeFilter, setTypeFilter] = useState<string>('')

  const query = useQuery({
    queryKey: ['notifications', 'history', hours, typeFilter || null],
    queryFn: async (): Promise<HistoryResponse> => {
      const params = new URLSearchParams({
        since_hours: String(hours),
        limit: '300',
      })
      if (typeFilter) params.set('type', typeFilter)
      const res = await fetch(`/api/notifications/history?${params.toString()}`, {
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      return (await res.json()) as HistoryResponse
    },
    refetchInterval: 30000,
  })

  const allTypes = useMemo(() => {
    const s = new Set<string>()
    for (const t of Object.keys(query.data?.by_type ?? {})) s.add(t)
    return Array.from(s).sort()
  }, [query.data?.by_type])

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
            <Activity className="w-4 h-4 text-indigo-300" /> Notifications history
          </div>
          <h1 className="text-2xl font-bold text-white">
            {query.data?.count ?? 0} event{(query.data?.count ?? 0) === 1 ? '' : 's'}
            <span className="ml-2 text-sm text-gray-400 font-normal">
              over the last {hours}h{typeFilter ? ` · type=${typeFilter}` : ''}
            </span>
          </h1>
          <p className="text-sm text-gray-400">
            DB-backed (Enhancement-11). Pruned daily at 4 AM keeping the last 30 days.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {PRESETS.map((p) => (
            <button
              key={p.hours}
              type="button"
              onClick={() => setHours(p.hours)}
              className={`rounded-md border px-3 py-1.5 text-sm ${
                hours === p.hours
                  ? 'border-indigo-500 bg-indigo-500/15 text-white'
                  : 'border-gray-800 bg-gray-900/50 text-gray-400 hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {allTypes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setTypeFilter('')}
            className={`rounded-md border px-2.5 py-1 text-xs ${
              !typeFilter
                ? 'border-indigo-500 bg-indigo-500/15 text-white'
                : 'border-gray-800 bg-gray-900/50 text-gray-400 hover:text-white'
            }`}
          >
            all
          </button>
          {allTypes.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTypeFilter(t === typeFilter ? '' : t)}
              className={`rounded-md border px-2.5 py-1 text-xs ${
                t === typeFilter
                  ? 'border-indigo-500 bg-indigo-500/15 text-white'
                  : 'border-gray-800 bg-gray-900/50 text-gray-400 hover:text-white'
              }`}
            >
              {t} ({query.data?.by_type[t] ?? 0})
            </button>
          ))}
        </div>
      )}

      {query.isLoading && (
        <div className="glass-card p-6 text-center text-gray-400">
          <Clock className="w-5 h-5 inline mr-2" /> Loading history…
        </div>
      )}
      {query.isError && (
        <div className="glass-card p-6 text-rose-400">
          <AlertTriangle className="w-4 h-4 inline mr-2" />
          {String(query.error)}
        </div>
      )}
      {!query.isLoading && (query.data?.events.length ?? 0) === 0 && (
        <div className="glass-card p-6 text-center text-gray-400">
          No events in this window.
        </div>
      )}

      <div className="space-y-1">
        {(query.data?.events ?? []).map((ev, i) => (
          <div
            key={`${ev.ts}-${i}`}
            className={`rounded-md border px-3 py-2 text-sm flex items-start gap-3 ${eventTone(ev.type)}`}
          >
            <span className="font-mono text-xs shrink-0 text-gray-400 w-32 truncate">
              {ev.ts ? new Date(ev.ts).toLocaleString() : '—'}
            </span>
            <span className="font-semibold shrink-0 w-44 truncate">{ev.type}</span>
            <span className="text-gray-300 truncate flex-1">
              {String(ev.title ?? ev.summary ?? ev.detail ?? '')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
