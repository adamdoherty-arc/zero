import { Activity, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { useHealthReady } from '@/hooks/useSystemApi'

export function HealthTab() {
  const { data: health, isLoading } = useHealthReady()

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        Checking service health...
      </div>
    )
  }

  if (!health) {
    return <div className="text-sm text-muted-foreground">Could not reach health endpoint.</div>
  }

  const services = health.checks ?? {}

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-2">
        <Activity className="w-5 h-5 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium text-foreground">
            System Health: {health.ready ? 'All Systems Go' : 'Degraded'}
          </p>
          {health.timestamp && (
            <p className="text-xs text-muted-foreground">
              Checked at {new Date(health.timestamp).toLocaleTimeString()}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {Object.entries(services).map(([name, info]) => {
          const isUp = typeof info === 'object' && info !== null
            ? (info as Record<string, unknown>).status === 'ok' || (info as Record<string, unknown>).status === 'ready'
            : info === 'ok'

          const detail = typeof info === 'object' && info !== null
            ? (info as Record<string, string>).detail || (info as Record<string, string>).status || ''
            : String(info)

          return (
            <div key={name} className="glass-card p-4 flex items-center gap-3">
              {isUp ? (
                <CheckCircle className="w-5 h-5 text-green-400 shrink-0" />
              ) : (
                <XCircle className="w-5 h-5 text-red-400 shrink-0" />
              )}
              <div>
                <p className="text-sm font-medium text-foreground capitalize">{name}</p>
                <p className="text-xs text-muted-foreground">{detail}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
