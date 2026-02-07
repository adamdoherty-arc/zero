import { Activity, Play, Square, RefreshCw, AlertCircle, CheckCircle } from 'lucide-react'
import {
  useOrchestratorStatus,
  useStartOrchestrator,
  useStopOrchestrator,
  useEnhancementStats,
  useTriggerEnhancementScan,
} from '../hooks/useSprintApi'

export function OrchestratorPanel() {
  const { data: status, isLoading: isLoadingStatus } = useOrchestratorStatus()
  const { data: enhancementStats, isLoading: isLoadingStats } = useEnhancementStats()

  const startOrchestrator = useStartOrchestrator()
  const stopOrchestrator = useStopOrchestrator()
  const triggerScan = useTriggerEnhancementScan()

  const isRunning = status?.status === 'running'

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">Orchestrator & Enhancements</h2>

      {/* Orchestrator Status */}
      <div className="glass-card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Activity className={`w-6 h-6 ${isRunning ? 'text-green-400' : 'text-gray-500'}`} />
            <div>
              <h3 className="font-semibold text-lg">Code Orchestrator</h3>
              <p className="text-sm text-gray-400">
                Automated task execution and code management
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {isRunning ? (
              <button
                onClick={() => stopOrchestrator.mutate()}
                disabled={stopOrchestrator.isPending}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg font-medium flex items-center gap-2 transition-colors"
              >
                <Square className="w-4 h-4" />
                Stop
              </button>
            ) : (
              <button
                onClick={() => startOrchestrator.mutate()}
                disabled={startOrchestrator.isPending}
                className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg font-medium flex items-center gap-2 transition-colors"
              >
                <Play className="w-4 h-4" />
                Start
              </button>
            )}
          </div>
        </div>

        {/* Status details */}
        {isLoadingStatus ? (
          <div className="text-gray-400">Loading status...</div>
        ) : status ? (
          <div className="grid grid-cols-4 gap-4">
            <div className="stat-card">
              <div className="text-sm text-gray-400 mb-1">Status</div>
              <div className={`font-semibold ${isRunning ? 'text-accent' : 'text-gray-400'}`}>
                {(status.status ?? 'unknown').charAt(0).toUpperCase() + (status.status ?? 'unknown').slice(1)}
              </div>
            </div>

            <div className="stat-card">
              <div className="text-sm text-gray-400 mb-1">Uptime</div>
              <div className="font-semibold">
                {status.uptime_seconds
                  ? `${Math.floor(status.uptime_seconds / 60)}m ${status.uptime_seconds % 60}s`
                  : '-'}
              </div>
            </div>

            <div className="stat-card">
              <div className="text-sm text-gray-400 mb-1">Tasks Completed</div>
              <div className="font-semibold text-primary">{status.completed_tasks}</div>
            </div>

            <div className="stat-card">
              <div className="text-sm text-gray-400 mb-1">Errors</div>
              <div className={`font-semibold ${status.errors > 0 ? 'text-danger' : 'text-gray-400'}`}>
                {status.errors}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Enhancement System */}
      <div className="glass-card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <RefreshCw className="w-6 h-6 text-primary" />
            <div>
              <h3 className="font-semibold text-lg">Enhancement System</h3>
              <p className="text-sm text-gray-400">
                Automatic detection of code improvements and issues
              </p>
            </div>
          </div>

          <button
            onClick={() => triggerScan.mutate()}
            disabled={triggerScan.isPending}
            className="btn-primary gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${triggerScan.isPending ? 'animate-spin' : ''}`} />
            Scan Now
          </button>
        </div>

        {/* Enhancement stats */}
        {isLoadingStats ? (
          <div className="text-gray-400">Loading stats...</div>
        ) : enhancementStats ? (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              <div className="stat-card">
                <div className="text-sm text-gray-400 mb-1">Total Signals</div>
                <div className="font-semibold text-xl">{enhancementStats.total_signals}</div>
              </div>

              <div className="stat-card">
                <div className="text-sm text-gray-400 mb-1 flex items-center gap-1">
                  <AlertCircle className="w-3.5 h-3.5 text-warning" />
                  Pending
                </div>
                <div className="font-semibold text-xl text-warning">{enhancementStats.pending}</div>
              </div>

              <div className="stat-card">
                <div className="text-sm text-gray-400 mb-1 flex items-center gap-1">
                  <CheckCircle className="w-3.5 h-3.5 text-accent" />
                  Converted
                </div>
                <div className="font-semibold text-xl text-accent">{enhancementStats.converted_to_tasks}</div>
              </div>

              <div className="stat-card">
                <div className="text-sm text-gray-400 mb-1">Dismissed</div>
                <div className="font-semibold text-xl text-gray-400">{enhancementStats.dismissed}</div>
              </div>
            </div>

            {/* By type breakdown */}
            {Object.keys(enhancementStats.by_type).length > 0 && (
              <div className="stat-card">
                <div className="text-sm text-gray-400 mb-2">By Type</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(enhancementStats.by_type).map(([type, count]) => (
                    <span
                      key={type}
                      className="badge badge-info"
                    >
                      {type}: <span className="text-primary ml-1">{count}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* By severity breakdown */}
            {Object.keys(enhancementStats.by_severity).length > 0 && (
              <div className="stat-card">
                <div className="text-sm text-gray-400 mb-2">By Severity</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(enhancementStats.by_severity).map(([severity, count]) => {
                    const colorMap: Record<string, string> = {
                      critical: 'text-danger',
                      high: 'text-orange-400',
                      medium: 'text-warning',
                      low: 'text-gray-400',
                    }
                    return (
                      <span
                        key={severity}
                        className="badge badge-neutral"
                      >
                        {severity}: <span className={`ml-1 ${colorMap[severity] || 'text-gray-400'}`}>{count}</span>
                      </span>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-400">
            No enhancement signals detected yet. Run a scan to find improvements.
          </div>
        )}
      </div>
    </div>
  )
}
