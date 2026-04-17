import { useState } from 'react'
import { Clock, CheckCircle, XCircle, Timer, ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useSchedulerDashboard, useJobTimeline } from '@/hooks/useExecutionApi'

const healthColors: Record<string, string> = {
  green: 'bg-green-500',
  yellow: 'bg-yellow-500',
  red: 'bg-red-500',
  gray: 'bg-gray-500',
}

interface JobCard {
  name: string
  category: string
  schedule: string
  next_run?: string | null
  health: string
  total_runs?: number
  success_count?: number
  failure_count?: number
  avg_duration_s?: number
  last_run?: string | null
  enabled?: boolean
}

export function ExecutionDashboardPage() {
  const { data: rawDashboard, isLoading } = useSchedulerDashboard()
  const dashboard = rawDashboard as { jobs?: JobCard[]; total_jobs?: number; total_runs_24h?: number; success_rate_24h?: number; errors_today?: number } | undefined
  const { data: rawTimeline } = useJobTimeline(24)
  const timelineData = rawTimeline as { events?: Record<string, unknown>[] } | Record<string, unknown>[] | undefined
  const timeline = Array.isArray(timelineData) ? timelineData : (timelineData as { events?: Record<string, unknown>[] } | undefined)?.events
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'grid' | 'timeline'>('grid')

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

  const jobs: JobCard[] = dashboard?.jobs || []
  const categories = [...new Set(jobs.map(j => j.category))].sort()

  return (
    <div className="p-6 space-y-6">
      {/* Top Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-sm text-gray-400">Jobs Registered</div>
          <div className="text-2xl font-bold text-white">{dashboard?.total_jobs || 0}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-sm text-gray-400">Runs (24h)</div>
          <div className="text-2xl font-bold text-white">{dashboard?.total_runs_24h || 0}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-sm text-gray-400">Success Rate</div>
          <div className="text-2xl font-bold text-green-400">{dashboard?.success_rate_24h || 100}%</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-sm text-gray-400">Errors Today</div>
          <div className={`text-2xl font-bold ${(dashboard?.errors_today || 0) > 0 ? 'text-red-400' : 'text-green-400'}`}>
            {dashboard?.errors_today || 0}
          </div>
        </div>
      </div>

      {/* View Toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setViewMode('grid')}
          className={`px-3 py-1 rounded text-sm ${viewMode === 'grid' ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400'}`}
        >Grid View</button>
        <button
          onClick={() => setViewMode('timeline')}
          className={`px-3 py-1 rounded text-sm ${viewMode === 'timeline' ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400'}`}
        >Timeline</button>
      </div>

      {viewMode === 'grid' ? (
        /* Job Grid by Category */
        <div className="space-y-4">
          {categories.map(cat => {
            const catJobs = jobs.filter(j => j.category === cat)
            const isExpanded = expandedCategory === cat || expandedCategory === null
            return (
              <div key={cat} className="bg-gray-800/50 rounded-lg border border-gray-700">
                <button
                  onClick={() => setExpandedCategory(expandedCategory === cat ? null : cat)}
                  className="w-full flex items-center justify-between p-3 hover:bg-gray-800"
                >
                  <div className="flex items-center gap-2">
                    {isExpanded ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                    <span className="font-medium text-white">{cat}</span>
                    <Badge variant="outline" className="text-xs">{catJobs.length} jobs</Badge>
                  </div>
                </button>
                {isExpanded && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 p-3 pt-0">
                    {catJobs.map(job => (
                      <div key={job.name} className="bg-gray-900 rounded p-3 border border-gray-700 hover:border-gray-600 transition-colors">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <div className={`w-2 h-2 rounded-full ${healthColors[job.health] || 'bg-gray-500'}`} />
                            <span className="text-sm font-medium text-white truncate">{job.name}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-400">
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {job.schedule || '-'}
                          </span>
                          {job.total_runs !== undefined && (
                            <span className="flex items-center gap-1">
                              <CheckCircle className="w-3 h-3 text-green-500" />
                              {job.success_count || 0}
                            </span>
                          )}
                          {(job.failure_count || 0) > 0 && (
                            <span className="flex items-center gap-1">
                              <XCircle className="w-3 h-3 text-red-500" />
                              {job.failure_count}
                            </span>
                          )}
                          {job.avg_duration_s !== undefined && (
                            <span className="flex items-center gap-1">
                              <Timer className="w-3 h-3" />
                              {job.avg_duration_s}s
                            </span>
                          )}
                        </div>
                        {job.last_run && (
                          <div className="text-xs text-gray-500 mt-1">
                            Last: {new Date(job.last_run).toLocaleTimeString()}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        /* Timeline View */
        <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-4">
          <h3 className="text-sm font-medium text-gray-400 mb-3">Execution Timeline (24h)</h3>
          <div className="space-y-1 max-h-[600px] overflow-y-auto">
            {(timeline || []).slice(-100).reverse().map((entry: Record<string, unknown>, i: number) => (
              <div key={i} className="flex items-center gap-3 py-1 text-xs">
                <span className="text-gray-500 w-16 shrink-0">
                  {entry.started_at ? new Date(entry.started_at as string).toLocaleTimeString() : '-'}
                </span>
                <div className={`w-2 h-2 rounded-full shrink-0 ${entry.status === 'completed' ? 'bg-green-500' : 'bg-red-500'}`} />
                <span className="text-gray-300 truncate">{entry.job_name as string}</span>
                <Badge variant="outline" className="text-xs shrink-0">{entry.category as string}</Badge>
                {entry.duration_s != null && (
                  <span className="text-gray-500 shrink-0">{String(entry.duration_s)}s</span>
                )}
                {entry.error != null && (
                  <span className="text-red-400 truncate">{String(entry.error).slice(0, 50)}</span>
                )}
              </div>
            ))}
            {(!timeline || timeline.length === 0) && (
              <div className="text-gray-500 text-sm py-4 text-center">No executions in the last 24 hours</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
