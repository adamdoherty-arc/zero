import { useState } from 'react'
import {
  useOrchestrationLog,
  type OrchestrationLogEntry,
} from '@/hooks/useSprintApi'
import {
  ScrollText,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from 'lucide-react'

function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function resultBadge(result: string) {
  if (result === 'completed' || result === 'triggered') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-green-500/20 text-green-400">
        <CheckCircle className="w-2.5 h-2.5" /> {result}
      </span>
    )
  }
  if (result === 'failed' || result === 'aborted') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">
        <XCircle className="w-2.5 h-2.5" /> {result}
      </span>
    )
  }
  if (result === 'issues_found') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">
        <AlertTriangle className="w-2.5 h-2.5" /> issues
      </span>
    )
  }
  return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
      {result}
    </span>
  )
}

function LogEntryRow({ entry }: { entry: OrchestrationLogEntry }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetails = entry.details && Object.keys(entry.details).length > 0

  return (
    <div className="border-b border-border/20 last:border-0">
      <div
        className={`flex items-center gap-2 py-2 px-2 ${hasDetails ? 'cursor-pointer hover:bg-muted/20' : ''}`}
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        {hasDetails ? (
          expanded ? (
            <ChevronDown className="w-3 h-3 text-muted-foreground flex-shrink-0" />
          ) : (
            <ChevronRight className="w-3 h-3 text-muted-foreground flex-shrink-0" />
          )
        ) : (
          <span className="w-3 flex-shrink-0" />
        )}
        <span className="text-[11px] text-muted-foreground flex-shrink-0 w-28">
          {formatTimestamp(entry.timestamp)}
        </span>
        <span className="text-xs text-foreground/90 flex-1 truncate font-mono">
          {entry.action}
        </span>
        {resultBadge(entry.result)}
      </div>
      {expanded && hasDetails && (
        <div className="pl-8 pr-3 pb-2">
          <pre className="text-[10px] text-muted-foreground/80 bg-muted/20 p-2 rounded overflow-x-auto max-h-48">
            {JSON.stringify(entry.details, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

export function OrchestrationLog() {
  const { data, isLoading } = useOrchestrationLog(100)
  const entries = data?.entries ?? []

  if (isLoading) {
    return (
      <div className="glass-card p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <ScrollText className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Orchestration Log</h2>
        </div>
        <div className="flex items-center justify-center py-6">
          <RefreshCw className="w-5 h-5 text-muted-foreground animate-spin" />
        </div>
      </div>
    )
  }

  if (entries.length === 0) {
    return (
      <div className="glass-card p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <ScrollText className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Orchestration Log</h2>
        </div>
        <p className="text-xs text-muted-foreground text-center py-4">
          No orchestration activity yet. The autopilot runs daily at 8:00 AM.
        </p>
      </div>
    )
  }

  // Show newest first
  const reversed = entries.slice().reverse()

  // Summary counts
  const completed = entries.filter(e => e.result === 'completed' || e.result === 'triggered').length
  const failed = entries.filter(e => e.result === 'failed' || e.result === 'aborted').length
  const issues = entries.filter(e => e.result === 'issues_found').length

  return (
    <div className="glass-card p-5 mb-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ScrollText className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Orchestration Log</h2>
          <span className="text-[10px] text-muted-foreground">({entries.length} entries)</span>
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="text-green-400">{completed} ok</span>
          {issues > 0 && <span className="text-yellow-400">{issues} issues</span>}
          {failed > 0 && <span className="text-red-400">{failed} failed</span>}
        </div>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {reversed.map((entry, i) => (
          <LogEntryRow key={i} entry={entry} />
        ))}
      </div>
    </div>
  )
}
