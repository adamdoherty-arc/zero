import { Zap, Power, Play, Loader2 } from 'lucide-react'
import { useEngineStatus, useToggleEngine, useTriggerCycle } from '@/hooks/useEngineApi'

function timeAgo(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = Math.floor((now - then) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function EngineStatusCard() {
  const { data: status, isLoading } = useEngineStatus()
  const toggleEngine = useToggleEngine()
  const triggerCycle = useTriggerCycle()

  if (isLoading) {
    return (
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading engine status...</span>
        </div>
      </div>
    )
  }

  if (!status) return null

  const isActive = status.enabled && !status.cooldown_until

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Zap className={`w-5 h-5 ${isActive ? 'text-indigo-400' : 'text-muted-foreground'}`} />
          <h3 className="text-sm font-semibold text-foreground">Enhancement Engine</h3>
          {status.running ? (
            <span className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              Running
            </span>
          ) : status.enabled ? (
            <span className="flex items-center gap-1.5 text-xs text-indigo-400">
              <span className="w-2 h-2 rounded-full bg-indigo-400" />
              Active
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="w-2 h-2 rounded-full bg-gray-500" />
              Disabled
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => triggerCycle.mutate()}
            disabled={status.running || !status.enabled}
            className="btn-icon text-indigo-400 hover:text-indigo-300 disabled:opacity-30"
            title="Run cycle now"
          >
            <Play className="w-4 h-4" />
          </button>
          <button
            onClick={() => toggleEngine.mutate(!status.enabled)}
            className={`btn-icon ${status.enabled ? 'text-green-400 hover:text-red-400' : 'text-muted-foreground hover:text-green-400'}`}
            title={status.enabled ? 'Disable engine' : 'Enable engine'}
          >
            <Power className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <div className="text-center">
          <p className="text-lg font-bold text-foreground">{status.improvements_today}</p>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Today</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-foreground">{status.completed_total}</p>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Total</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-foreground">{status.cycle_count}</p>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Cycles</p>
        </div>
      </div>

      {/* Projects */}
      <div className="flex gap-1.5 mb-3">
        {status.target_projects.map((project) => (
          <span
            key={project}
            className="px-2 py-0.5 text-[10px] rounded-full bg-indigo-500/20 text-indigo-300 font-medium"
          >
            {project}
          </span>
        ))}
      </div>

      {/* Footer info */}
      <div className="text-xs text-muted-foreground space-y-0.5">
        {status.last_cycle_at && (
          <p>Last cycle: {timeAgo(status.last_cycle_at)}</p>
        )}
        {status.cooldown_until && (
          <p className="text-yellow-400">Cooldown until: {new Date(status.cooldown_until).toLocaleTimeString()}</p>
        )}
        {status.failed_total > 0 && (
          <p className="text-red-400">{status.failed_total} failure(s)</p>
        )}
      </div>
    </div>
  )
}
