import { AlertTriangle, RefreshCw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useHostAgentStatus } from '@/hooks/useReachyApi'

export function HostAgentOfflineBanner() {
  const qc = useQueryClient()
  const status = useHostAgentStatus(4_000)
  const reachable = status.data?.reachable ?? true

  if (status.isLoading && status.data === undefined) {
    return null
  }
  if (reachable) {
    return null
  }

  const lastError = status.data?.last_error
  const url = status.data?.url

  return (
    <div
      role="alert"
      className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-amber-200">
            Reachy stack is not running
          </div>
          <p className="mt-1 text-sm text-amber-100/90">
            Run <code className="rounded bg-amber-950/40 px-1">host_agent\start-zero.bat</code> from the Zero
            directory to start the Reachy supervisor. Then use the{' '}
            <strong>Reachy</strong> panel to start the robot daemon.
            This banner clears automatically once{' '}
            <code className="rounded bg-amber-950/40 px-1">{url ?? 'host_agent :18796'}</code>{' '}
            comes online.
          </p>
          {lastError ? (
            <p className="mt-1 text-xs text-amber-100/70 opacity-70">({lastError})</p>
          ) : null}
        </div>
        <button
          onClick={() =>
            qc.invalidateQueries({ queryKey: ['reachy', 'host-agent', 'status'] })
          }
          className="shrink-0 inline-flex items-center gap-1.5 rounded border border-amber-500/40 bg-amber-500/20 px-2.5 py-1 text-xs font-medium text-amber-100 hover:bg-amber-500/30"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${status.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>
    </div>
  )
}
