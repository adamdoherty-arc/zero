import { useState } from 'react'
import { TrendingUp, DollarSign, Clock, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useOutcomeDashboard } from '@/hooks/useVisualWorkflowApi'

const kpiIcons: Record<string, typeof TrendingUp> = {
  revenue: DollarSign,
  time_saved: Clock,
  engagement: TrendingUp,
  tasks_automated: Zap,
}

export function OutcomeDashboardPage() {
  const [days, setDays] = useState(30)
  const { data: rawDashboard, isLoading } = useOutcomeDashboard(days)
  const dashboard = rawDashboard as { by_kpi_type?: Record<string, unknown>[]; by_source?: Record<string, unknown>[]; recent?: Record<string, unknown>[] } | undefined

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-24" />)}
        </div>
      </div>
    )
  }

  const byKpi = dashboard?.by_kpi_type || []
  const bySource = dashboard?.by_source || []
  const recent = dashboard?.recent || []

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-end">
        <div className="flex gap-2">
          {[7, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1 rounded text-sm ${days === d ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400'}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {byKpi.map((kpi: Record<string, unknown>) => {
          const Icon = kpiIcons[kpi.kpi_type as string] || TrendingUp
          return (
            <div key={kpi.kpi_type as string} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center gap-2 mb-2">
                <Icon className="w-4 h-4 text-emerald-400" />
                <span className="text-sm text-gray-400 capitalize">{(kpi.kpi_type as string).replace(/_/g, ' ')}</span>
              </div>
              <div className="text-2xl font-bold text-white">{(kpi.total_value as number).toLocaleString()}</div>
              <div className="text-xs text-gray-500">{kpi.count as number} events</div>
            </div>
          )
        })}
        {byKpi.length === 0 && (
          <div className="col-span-4 bg-gray-800/50 border border-gray-700 rounded-lg p-8 text-center">
            <TrendingUp className="w-8 h-8 text-gray-600 mx-auto mb-2" />
            <p className="text-gray-400 text-sm">No outcomes recorded yet</p>
          </div>
        )}
      </div>

      {/* By Source */}
      {bySource.length > 0 && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
          <h3 className="text-sm font-medium text-gray-400 mb-3">Outcomes by Source</h3>
          <div className="space-y-2">
            {bySource.map((s: Record<string, unknown>) => {
              const maxVal = Math.max(...bySource.map((x: Record<string, unknown>) => x.total_value as number))
              const pct = maxVal > 0 ? ((s.total_value as number) / maxVal) * 100 : 0
              return (
                <div key={s.source as string} className="flex items-center gap-3">
                  <span className="text-sm text-gray-300 w-32 truncate">{s.source as string}</span>
                  <div className="flex-1 bg-gray-700 rounded-full h-2">
                    <div className="bg-emerald-500 rounded-full h-2" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-sm text-gray-400 w-20 text-right">{(s.total_value as number).toLocaleString()}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Recent Outcomes */}
      {recent.length > 0 && (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
          <h3 className="text-sm font-medium text-gray-400 mb-3">Recent Outcomes</h3>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {recent.map((o: Record<string, unknown>) => (
              <div key={o.id as string} className="flex items-center gap-3 text-sm py-1">
                <span className="text-gray-500 w-28 shrink-0">
                  {o.recorded_at ? new Date(o.recorded_at as string).toLocaleDateString() : '-'}
                </span>
                <Badge variant="outline" className="text-xs">{o.source as string}</Badge>
                <span className="text-gray-300 capitalize">{(o.kpi_type as string).replace(/_/g, ' ')}</span>
                <span className="text-white font-medium ml-auto">{(o.value as number).toLocaleString()} {o.unit as string}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
