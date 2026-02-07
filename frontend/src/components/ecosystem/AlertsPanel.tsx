import type { EcosystemAlert } from '@/hooks/useSprintApi'
import { AlertCircle, AlertTriangle, Info } from 'lucide-react'

interface AlertsPanelProps {
  alerts: EcosystemAlert[]
}

const severityConfig = {
  critical: {
    icon: AlertCircle,
    bg: 'border-red-500/30 bg-red-500/5',
    text: 'text-red-400',
    badge: 'bg-red-500/20 text-red-400',
  },
  warning: {
    icon: AlertTriangle,
    bg: 'border-yellow-500/30 bg-yellow-500/5',
    text: 'text-yellow-400',
    badge: 'bg-yellow-500/20 text-yellow-400',
  },
  info: {
    icon: Info,
    bg: 'border-blue-500/30 bg-blue-500/5',
    text: 'text-blue-400',
    badge: 'bg-blue-500/20 text-blue-400',
  },
}

export function AlertsPanel({ alerts }: AlertsPanelProps) {
  if (alerts.length === 0) return null

  return (
    <div className="glass-card p-5 mb-6">
      <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
        <AlertCircle className="w-4 h-4 text-red-400" />
        Active Alerts ({alerts.length})
      </h2>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {alerts.map((alert) => {
          const config = severityConfig[alert.severity] || severityConfig.info
          const Icon = config.icon
          return (
            <div
              key={alert.id}
              className={`flex items-start gap-3 p-3 rounded-lg border ${config.bg}`}
            >
              <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${config.text}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${config.badge}`}>
                    {alert.severity}
                  </span>
                  <span className="text-[11px] text-muted-foreground">{alert.project}</span>
                </div>
                <p className="text-xs text-foreground/90 leading-relaxed">{alert.message}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
