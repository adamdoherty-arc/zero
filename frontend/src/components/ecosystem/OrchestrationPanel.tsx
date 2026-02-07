import {
  useOrchestrationStatus,
  useTriggerOrchestration,
  type OrchestrationLogEntry,
} from '@/hooks/useSprintApi'
import {
  Bot,
  Play,
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock,
  Zap,
  Search,
  Sparkles,
} from 'lucide-react'

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function RunCard({
  label,
  icon: Icon,
  entry,
  color,
}: {
  label: string
  icon: React.ElementType
  entry: OrchestrationLogEntry | null
  color: string
}) {
  if (!entry) {
    return (
      <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/30 border border-border/40">
        <Icon className="w-4 h-4 text-muted-foreground" />
        <div className="flex-1">
          <div className="text-xs font-medium text-muted-foreground">{label}</div>
          <div className="text-[11px] text-muted-foreground/70">Never run</div>
        </div>
      </div>
    )
  }

  const isSuccess = entry.result === 'completed' || entry.result === 'issues_found'
  const isFailed = entry.result === 'failed' || entry.result === 'aborted'
  const details = entry.details || {}

  return (
    <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/30 border border-border/40">
      <Icon className={`w-4 h-4 ${color}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground">{label}</span>
          {isSuccess && <CheckCircle className="w-3 h-3 text-green-400" />}
          {isFailed && <XCircle className="w-3 h-3 text-red-400" />}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <Clock className="w-3 h-3 text-muted-foreground" />
          <span className="text-[11px] text-muted-foreground">
            {timeAgo(entry.timestamp)}
          </span>
          {details.actions_taken != null && (
            <span className="text-[10px] text-muted-foreground/70">
              {String(details.actions_taken)} action(s)
            </span>
          )}
          {details.errors != null && Number(details.errors) > 0 && (
            <span className="text-[10px] text-red-400">
              {String(details.errors)} error(s)
            </span>
          )}
          {details.issue_count != null && Number(details.issue_count) > 0 && (
            <span className="text-[10px] text-yellow-400">
              {String(details.issue_count)} issue(s)
            </span>
          )}
          {details.signals_found != null && (
            <span className="text-[10px] text-muted-foreground/70">
              {String(details.signals_found)} signal(s)
            </span>
          )}
          {details.tasks_created != null && Number(details.tasks_created) > 0 && (
            <span className="text-[10px] text-blue-400">
              {String(details.tasks_created)} task(s) created
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function RecentActionRow({ entry }: { entry: OrchestrationLogEntry }) {
  const isFailed = entry.result === 'failed' || entry.result === 'aborted'
  const isIssues = entry.result === 'issues_found'

  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-border/20 last:border-0">
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
          isFailed ? 'bg-red-400' : isIssues ? 'bg-yellow-400' : 'bg-green-400'
        }`}
      />
      <span className="text-[11px] text-foreground/80 flex-1 truncate">{entry.action}</span>
      <span className="text-[10px] text-muted-foreground flex-shrink-0">{entry.result}</span>
      <span className="text-[10px] text-muted-foreground/60 flex-shrink-0 w-14 text-right">
        {timeAgo(entry.timestamp)}
      </span>
    </div>
  )
}

export function OrchestrationPanel() {
  const { data: status, isLoading } = useOrchestrationStatus()
  const triggerOrch = useTriggerOrchestration()

  if (isLoading) {
    return (
      <div className="glass-card p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Bot className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Autopilot</h2>
        </div>
        <div className="flex items-center justify-center py-6">
          <RefreshCw className="w-5 h-5 text-muted-foreground animate-spin" />
        </div>
      </div>
    )
  }

  const recentActions = status?.recent_actions ?? []

  return (
    <div className="glass-card p-5 mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Autopilot</h2>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 font-medium">
            Active
          </span>
          {status?.total_actions != null && (
            <span className="text-[10px] text-muted-foreground">
              {status.total_actions} total actions
            </span>
          )}
        </div>
        <button
          onClick={() => triggerOrch.mutate()}
          disabled={triggerOrch.isPending}
          className="btn-secondary text-xs flex items-center gap-1.5"
        >
          {triggerOrch.isPending ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Play className="w-3.5 h-3.5" />
          )}
          Run Now
        </button>
      </div>

      {/* Trigger result feedback */}
      {triggerOrch.isSuccess && (
        <div className="mb-3 p-2.5 rounded-lg border border-green-500/30 bg-green-500/5">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-3.5 h-3.5 text-green-400" />
            <span className="text-xs text-green-400">
              Orchestration complete: {triggerOrch.data.actions?.length ?? 0} action(s),{' '}
              {triggerOrch.data.errors?.length ?? 0} error(s)
            </span>
          </div>
        </div>
      )}
      {triggerOrch.isError && (
        <div className="mb-3 p-2.5 rounded-lg border border-red-500/30 bg-red-500/5">
          <div className="flex items-center gap-2">
            <XCircle className="w-3.5 h-3.5 text-red-400" />
            <span className="text-xs text-red-400">
              {(triggerOrch.error as Error).message}
            </span>
          </div>
        </div>
      )}

      {/* Three run cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <RunCard
          label="Daily Orchestration"
          icon={Zap}
          entry={status?.last_daily_orchestration ?? null}
          color="text-yellow-400"
        />
        <RunCard
          label="Continuous Monitor"
          icon={Search}
          entry={status?.last_continuous_monitor ?? null}
          color="text-blue-400"
        />
        <RunCard
          label="Enhancement Cycle"
          icon={Sparkles}
          entry={status?.last_enhancement_cycle ?? null}
          color="text-purple-400"
        />
      </div>

      {/* Recent actions */}
      {recentActions.length > 0 && (
        <div>
          <h3 className="text-[11px] font-medium text-muted-foreground mb-2">Recent Actions</h3>
          <div className="max-h-40 overflow-y-auto">
            {recentActions
              .slice()
              .reverse()
              .map((entry, i) => (
                <RecentActionRow key={i} entry={entry} />
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
