import { useState } from 'react'
import { Activity, Search, Zap, AlertTriangle, CheckCircle, Clock, FileCode } from 'lucide-react'
import { useActivityFeed, useActivitySummary } from '@/hooks/useEngineApi'

const EVENT_ICONS: Record<string, typeof Activity> = {
  scan: Search,
  analyze: Search,
  queue: Clock,
  execute_start: Zap,
  execute_complete: CheckCircle,
  execute_fail: AlertTriangle,
  sprint_created: FileCode,
  cycle_start: Activity,
  cycle_complete: Activity,
  cycle_error: AlertTriangle,
}

const EVENT_COLORS: Record<string, string> = {
  scan: 'text-blue-400',
  analyze: 'text-blue-400',
  queue: 'text-yellow-400',
  execute_start: 'text-indigo-400',
  execute_complete: 'text-green-400',
  execute_fail: 'text-red-400',
  sprint_created: 'text-purple-400',
  cycle_start: 'text-muted-foreground',
  cycle_complete: 'text-green-400',
  cycle_error: 'text-red-400',
}

const PROJECT_COLORS: Record<string, string> = {
  zero: 'bg-indigo-500/20 text-indigo-300',
  legion: 'bg-purple-500/20 text-purple-300',
  engine: 'bg-gray-500/20 text-gray-300',
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  const now = Date.now()
  const diff = Math.floor((now - d.getTime()) / 1000)

  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return d.toLocaleDateString()
}

export function ActivityFeed() {
  const [projectFilter, setProjectFilter] = useState<string | undefined>()
  const { data: feedData, isLoading } = useActivityFeed(projectFilter, 30)
  const { data: summary } = useActivitySummary(24)

  const events = feedData?.events ?? []
  const filters = ['All', 'zero', 'legion']

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-indigo-400" />
          <h3 className="text-sm font-semibold text-foreground">Activity Feed</h3>
        </div>
      </div>

      {/* Summary row */}
      {summary && (
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="text-center p-2 rounded-lg bg-muted/30">
            <p className="text-base font-bold text-foreground">{summary.improvements_completed}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Improvements</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-muted/30">
            <p className="text-base font-bold text-foreground">{summary.files_changed}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Files</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-muted/30">
            <p className="text-base font-bold text-foreground">{summary.by_type?.cycle_complete ?? 0}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Cycles</p>
          </div>
          <div className="text-center p-2 rounded-lg bg-muted/30">
            <p className="text-base font-bold text-foreground">{summary.total_events}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Events</p>
          </div>
        </div>
      )}

      {/* Project filters */}
      <div className="flex gap-1.5 mb-4">
        {filters.map((f) => {
          const isActive = f === 'All' ? !projectFilter : projectFilter === f
          return (
            <button
              key={f}
              onClick={() => setProjectFilter(f === 'All' ? undefined : f)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                isActive
                  ? 'bg-indigo-500/20 text-indigo-300 font-medium'
                  : 'text-muted-foreground hover:bg-muted/50'
              }`}
            >
              {f}
            </button>
          )
        })}
      </div>

      {/* Event list */}
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading activity...</p>
      ) : events.length === 0 ? (
        <p className="text-sm text-muted-foreground">No activity yet. The engine will start logging events on its next cycle.</p>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
          {events.map((event) => {
            const Icon = EVENT_ICONS[event.event_type] ?? Activity
            const color = EVENT_COLORS[event.event_type] ?? 'text-muted-foreground'
            const projectColor = PROJECT_COLORS[event.project] ?? 'bg-gray-500/20 text-gray-300'

            return (
              <div
                key={event.event_id}
                className="flex items-start gap-2.5 py-2 border-b border-border/50 last:border-0"
              >
                <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${color}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 text-[10px] rounded-full font-medium ${projectColor}`}>
                      {event.project}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{formatTime(event.timestamp)}</span>
                  </div>
                  <p className="text-sm text-foreground mt-0.5 truncate">{event.title}</p>
                  {typeof event.details?.task_id === 'string' && (
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      Task: {event.details.task_id}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
