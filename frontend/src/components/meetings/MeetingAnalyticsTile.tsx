import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, CheckCircle2, Clock, DollarSign, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { getAuthHeaders } from '@/lib/auth'

interface CostSummary {
  meetings: number
  total_audio_seconds: number
  total_transcription_seconds: number
  total_summary_tokens: number
  estimated_cost_usd: number
  by_model: Record<string, number>
}

interface WeeklyAnalytics {
  checked_at: string
  this_week: {
    count: number
    minutes: number
    top_attendees: { name: string; meetings: number }[]
  }
  previous_week: {
    count: number
    minutes: number
    top_attendees: { name: string; meetings: number }[]
  }
  delta_count: number
  delta_minutes: number
  action_item_completion: {
    total: number
    done: number
    ratio: number
    error?: string
  }
}

function deltaIcon(delta: number) {
  if (delta > 0) return <ArrowUpRight className="w-3.5 h-3.5 text-emerald-300" />
  if (delta < 0) return <ArrowDownRight className="w-3.5 h-3.5 text-rose-300" />
  return <ArrowRight className="w-3.5 h-3.5 text-gray-400" />
}

/**
 * F-73 — dashboard tile showing this week's meeting count + minutes,
 * top 3 attendees, and action-item completion ratio. Reuses the same
 * /api/meeting-steward/weekly-analytics endpoint the steward page can
 * later expand on.
 */
export function MeetingAnalyticsTile() {
  const query = useQuery({
    queryKey: ['meeting-steward', 'weekly-analytics'],
    queryFn: async (): Promise<WeeklyAnalytics> => {
      const res = await fetch('/api/meeting-steward/weekly-analytics', {
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      return (await res.json()) as WeeklyAnalytics
    },
    refetchInterval: 60000,
  })

  const costQuery = useQuery({
    queryKey: ['meeting-steward', 'cost', 'weekly'],
    queryFn: async (): Promise<CostSummary> => {
      const res = await fetch('/api/meeting-steward/cost/weekly', {
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      return (await res.json()) as CostSummary
    },
    refetchInterval: 60000,
  })

  if (query.isLoading) {
    return (
      <div className="glass-card p-4">
        <div className="text-xs uppercase tracking-wide text-gray-500">Meetings this week</div>
        <div className="mt-2 text-sm text-gray-400">Loading…</div>
      </div>
    )
  }
  if (query.isError || !query.data) {
    return (
      <div className="glass-card p-4 border border-rose-500/40 bg-rose-500/5">
        <div className="text-xs uppercase tracking-wide text-rose-300">Meetings this week</div>
        <div className="mt-2 text-sm text-rose-300">
          {String(query.error) || 'analytics unavailable'}
        </div>
      </div>
    )
  }
  const a = query.data
  const ratio = Math.round(a.action_item_completion.ratio * 100)

  return (
    <div className="glass-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
        <Activity className="w-4 h-4 text-indigo-300" />
        Meetings this week
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <div className="text-2xl font-bold text-white flex items-center gap-1">
            {a.this_week.count}
            {deltaIcon(a.delta_count)}
          </div>
          <div className="text-[11px] text-gray-500">
            meetings ({a.delta_count >= 0 ? '+' : ''}
            {a.delta_count} vs last week)
          </div>
        </div>
        <div>
          <div className="text-2xl font-bold text-white flex items-center gap-1">
            <Clock className="w-4 h-4 text-gray-400" />
            {a.this_week.minutes}
          </div>
          <div className="text-[11px] text-gray-500">
            minutes ({a.delta_minutes >= 0 ? '+' : ''}
            {a.delta_minutes})
          </div>
        </div>
        <div>
          <div className="text-2xl font-bold text-white flex items-center gap-1">
            <CheckCircle2 className="w-4 h-4 text-gray-400" />
            {ratio}%
          </div>
          <div className="text-[11px] text-gray-500">
            actions done ({a.action_item_completion.done}/
            {a.action_item_completion.total})
          </div>
        </div>
      </div>
      {a.this_week.top_attendees.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-gray-500 mb-1.5 flex items-center gap-1">
            <Users className="w-3 h-3" /> Top attendees
          </div>
          <div className="flex flex-wrap gap-1.5">
            {a.this_week.top_attendees.slice(0, 5).map((p) => (
              <span
                key={p.name}
                className="text-xs rounded-full border border-gray-700 bg-gray-900/50 px-2 py-0.5 text-gray-300"
                title={`${p.meetings} meeting${p.meetings === 1 ? '' : 's'} this week`}
              >
                {p.name.split('@')[0]} · {p.meetings}
              </span>
            ))}
          </div>
        </div>
      )}
      {costQuery.data && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400 border-t border-gray-800 pt-2">
          <DollarSign className="w-3.5 h-3.5" />
          <span>
            <span className="font-mono text-gray-200">
              ${(costQuery.data.estimated_cost_usd ?? 0).toFixed(4)}
            </span>{' '}
            est. cost
          </span>
          <span>·</span>
          <span>
            <span className="font-mono text-gray-200">
              {costQuery.data.total_summary_tokens}
            </span>{' '}
            tokens
          </span>
          <span>·</span>
          <span>
            <span className="font-mono text-gray-200">
              {Math.round((costQuery.data.total_transcription_seconds ?? 0) / 60)}
            </span>{' '}
            min Whisper
          </span>
        </div>
      )}
      <Link
        to="/meeting-steward"
        className="text-xs text-indigo-300 hover:text-indigo-200"
      >
        Full meeting steward →
      </Link>
    </div>
  )
}
