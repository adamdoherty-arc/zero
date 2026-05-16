import { Activity, AlertTriangle, Bug, ChevronDown, ChevronUp } from 'lucide-react'
import { useDaemonStatus, useHostAgentStatus, useReachyStatus } from '@/hooks/useReachyApi'

interface Props {
  isOpen: boolean
  onToggle: () => void
}

function formatUptime(s: number | null | undefined): string {
  if (s == null || s < 0) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${Math.floor(s)}s`
}

/**
 * One-line daemon status row with a [Debug ▸] toggle.
 *
 * Replaces the standalone DaemonPanel header that used to live in the
 * primary page flow. The detailed daemon controls + logs + diagnostics
 * are now inside AssistantDebugPanel and surface only when the user
 * opens this bar.
 */
export function DaemonStatusBar({ isOpen, onToggle }: Props) {
  const hostAgent = useHostAgentStatus(4_000)
  const daemon = useDaemonStatus(8_000)
  const reachy = useReachyStatus(8_000)

  const hostReachable = hostAgent.data?.reachable ?? true
  const daemonRunning = daemon.data?.running ?? false
  const robotReady = reachy.data?.robot_ready ?? false
  const uptime = daemon.data?.uptime_seconds

  const { tone, dot, label } = (() => {
    if (!hostReachable) {
      return { tone: 'bg-red-500/10 border-red-500/30 text-red-100', dot: 'bg-red-400', label: 'host_agent offline' }
    }
    if (!daemonRunning) {
      return { tone: 'bg-amber-500/10 border-amber-500/30 text-amber-100', dot: 'bg-amber-400', label: 'daemon stopped' }
    }
    if (!robotReady) {
      return { tone: 'bg-amber-500/10 border-amber-500/30 text-amber-100', dot: 'bg-amber-400', label: 'daemon running · body not ready' }
    }
    return { tone: 'bg-green-500/10 border-green-500/30 text-green-100', dot: 'bg-green-400', label: 'running' }
  })()

  return (
    <button
      type="button"
      onClick={onToggle}
      className={`w-full flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border ${tone} hover:bg-white/5 transition-colors`}
    >
      <div className="flex items-center gap-3 min-w-0">
        <Activity className="h-4 w-4 shrink-0 opacity-70" />
        <span className={`h-2 w-2 rounded-full shrink-0 ${dot}`} />
        <span className="text-sm font-semibold truncate">Daemon · {label}</span>
        {daemonRunning && (
          <span className="text-xs opacity-70 truncate">uptime {formatUptime(uptime)}</span>
        )}
        {!hostReachable && (
          <span className="inline-flex items-center gap-1 text-xs opacity-80">
            <AlertTriangle className="h-3 w-3" /> click to expand
          </span>
        )}
      </div>
      <span className="inline-flex items-center gap-1.5 text-xs font-medium shrink-0">
        <Bug className="h-3.5 w-3.5" />
        {isOpen ? 'Hide debug' : 'Debug'}
        {isOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </span>
    </button>
  )
}
