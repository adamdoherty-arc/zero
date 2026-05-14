import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Cpu, RefreshCw } from 'lucide-react'
import { useReachyStatus, useRelink } from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

/**
 * Compact TopBar badge showing the live daemon + host_agent health.
 *
 * - Green: daemon connected, robot ready, host_agent reachable.
 * - Amber: daemon reachable but body not ready, motors disabled,
 *   state probe stale, OR host_agent supervisor returned a stale cache.
 * - Red: daemon unreachable OR host_agent unreachable AND no recent cache.
 * - Grey: still loading (first poll has not landed).
 *
 * Click navigates to /zero where DaemonPanel exposes restart, watchdog,
 * audio reset, logs, and diagnostics. When the dot is amber/red, a
 * companion Smart Re-link button appears so recovery is one click away
 * without navigating into the page. Pairs with LLMStatusBadge in TopBar so
 * the user always knows brain health AND body health at a glance.
 */
export function DaemonHealthBadge() {
  const { data: status, isLoading } = useReachyStatus(5_000)
  const relink = useRelink()
  const { toast } = useToast()

  const { dotClass, label, tooltip, healthy } = useMemo(() => {
    if (isLoading || !status) {
      return {
        dotClass: 'bg-zinc-500',
        label: 'Zero ...',
        tooltip: 'Probing Zero robot daemon and host_agent...',
        healthy: true, // suppress the recovery button while we don't know
      }
    }
    const stale = Boolean(status.status_stale)
    const daemonOk = status.daemon_connected ?? false
    const robotReady = status.robot_ready ?? false
    const motorsDisabled = status.body_control_mode === 'disabled'
    const hostAgentUnreachable =
      (status as { supervisor?: { status?: string } }).supervisor?.status ===
      'host_agent_unreachable'

    if (!daemonOk) {
      return {
        dotClass: 'bg-red-500',
        label: 'Zero down',
        tooltip:
          status.robot_detail ||
          'Zero robot daemon is not reachable. Click Re-link to recover or open the panel.',
        healthy: false,
      }
    }
    if (hostAgentUnreachable) {
      return {
        dotClass: 'bg-red-500',
        label: 'host_agent down',
        tooltip:
          'host_agent (Windows-side supervisor) is not responding. Daemon control, camera and recording will be unavailable until it comes back.',
        healthy: false,
      }
    }
    if (!robotReady || motorsDisabled || stale) {
      const reason = motorsDisabled
        ? 'motors disabled'
        : stale
          ? 'state stale'
          : status.robot_detail || 'robot not ready'
      return {
        dotClass: 'bg-amber-400',
        label: `Zero - ${reason}`,
        tooltip: status.robot_detail || `Zero is degraded: ${reason}.`,
        healthy: false,
      }
    }
    return {
      dotClass: 'bg-emerald-500',
      label: 'Zero ready',
      tooltip: 'Daemon connected, host_agent reachable, motors ready.',
      healthy: true,
    }
  }, [isLoading, status])

  const handleRelink = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    try {
      const res = await relink.mutateAsync()
      toast({
        title: res.action === 'restarted' ? 'Re-linked Zero' : 'Waiting for Docker',
        description: res.detail,
      })
    } catch (err) {
      toast({
        title: 'Smart Re-link failed',
        description: err instanceof Error ? err.message : String(err),
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <Link
        to="/zero"
        title={tooltip}
        className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs bg-zinc-900 hover:bg-zinc-800 border-zinc-700 text-zinc-100 transition-colors"
      >
        <span className={`w-2 h-2 rounded-full ${dotClass}`} aria-hidden />
        <Cpu className="w-3 h-3 text-zinc-400" aria-hidden />
        <span className="font-medium hidden md:inline">{label}</span>
      </Link>
      {!healthy && (
        <button
          type="button"
          onClick={handleRelink}
          disabled={relink.isPending}
          title="Smart Re-link: re-probe Docker and refresh the Zero robot daemon link"
          className="flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs bg-amber-500/10 border-amber-500/40 text-amber-100 hover:bg-amber-500/20 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${relink.isPending ? 'animate-spin' : ''}`} aria-hidden />
          <span className="font-medium hidden lg:inline">Re-link</span>
        </button>
      )}
    </div>
  )
}
