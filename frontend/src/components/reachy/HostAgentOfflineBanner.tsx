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
            Double-click <strong>Start Zero Robot</strong> on your desktop. This banner
            will clear automatically once <code className="rounded bg-amber-950/40 px-1">{url ?? 'host_agent'}</code>{' '}
            comes online.
          </p>
          <p className="mt-1 text-xs text-amber-100/70">
            No shortcut? Run{' '}
            <code className="rounded bg-amber-950/40 px-1">
              powershell -ExecutionPolicy Bypass -File host_agent\install-shortcut.ps1
            </code>{' '}
            once.
            {lastError ? <span className="ml-2 opacity-70">({lastError})</span> : null}
          </p>
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
