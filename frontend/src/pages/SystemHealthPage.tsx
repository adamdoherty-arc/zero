import { useSchedulerStatus, useSchedulerAudit, useHealthReady, useTriggerJob } from '@/hooks/useSystemApi'
import { useSystemMetrics, useDiskStatus, useAlertingStatus } from '@/hooks/useHealthApi'

export function SystemHealthPage() {
  const { data: health } = useHealthReady()
  const { data: scheduler } = useSchedulerStatus()
  const { data: audit } = useSchedulerAudit(30)
  const { data: metrics } = useSystemMetrics()
  const { data: disk } = useDiskStatus()
  const { data: alerting } = useAlertingStatus()
  const triggerJob = useTriggerJob()

  const healthChecks = health?.checks ?? {}
  const jobs = scheduler?.jobs ?? []
  const executions = audit?.executions ?? []
  const activeIssues = alerting?.active_issues ?? {}
  const recentAlerts = alerting?.recent_alerts ?? {}

  // Compute job health from recent audit
  const jobStats: Record<string, { ok: number; fail: number }> = {}
  for (const e of executions) {
    if (!jobStats[e.job_name]) jobStats[e.job_name] = { ok: 0, fail: 0 }
    if (e.status === 'completed') jobStats[e.job_name].ok++
    else jobStats[e.job_name].fail++
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">System Health</h1>
        <p className="text-sm text-gray-400 mt-1">Real-time monitoring of all Zero subsystems</p>
      </div>

      {/* Service Health Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Object.entries(healthChecks).map(([name, status]) => (
          <div
            key={name}
            className={`rounded-lg border p-4 ${
              status === 'ok'
                ? 'border-green-500/30 bg-green-500/5'
                : status === 'degraded'
                ? 'border-yellow-500/30 bg-yellow-500/5'
                : 'border-red-500/30 bg-red-500/5'
            }`}
          >
            <div className="flex items-center gap-2">
              <div
                className={`h-2.5 w-2.5 rounded-full ${
                  status === 'ok' ? 'bg-green-500' : status === 'degraded' ? 'bg-yellow-500' : 'bg-red-500'
                }`}
              />
              <span className="text-sm font-medium text-white capitalize">{name}</span>
            </div>
            <p className="text-xs text-gray-400 mt-1 capitalize">{status}</p>
          </div>
        ))}
      </div>

      {/* Metrics + Disk + Alerts row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Disk Usage */}
        <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Disk Usage</h3>
          {disk?.total_gb ? (
            <>
              <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    (disk.percent_used ?? 0) > 85
                      ? 'bg-red-500'
                      : (disk.percent_used ?? 0) > 70
                      ? 'bg-yellow-500'
                      : 'bg-green-500'
                  }`}
                  style={{ width: `${disk.percent_used}%` }}
                />
              </div>
              <div className="flex justify-between mt-2 text-xs text-gray-400">
                <span>{disk.used_gb} GB used</span>
                <span>{disk.free_gb} GB free</span>
                <span>{disk.percent_used}%</span>
              </div>
            </>
          ) : (
            <p className="text-xs text-gray-500">Loading...</p>
          )}
        </div>

        {/* Ollama Metrics */}
        <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Ollama Performance</h3>
          {metrics?.metrics?.ollama_response_time ? (
            <div className="space-y-1 text-xs text-gray-300">
              <div className="flex justify-between">
                <span>p50</span>
                <span>{metrics.metrics.ollama_response_time.p50.toFixed(2)}s</span>
              </div>
              <div className="flex justify-between">
                <span>p95</span>
                <span>{metrics.metrics.ollama_response_time.p95.toFixed(2)}s</span>
              </div>
              <div className="flex justify-between">
                <span>p99</span>
                <span>{metrics.metrics.ollama_response_time.p99.toFixed(2)}s</span>
              </div>
              <div className="flex justify-between">
                <span>Requests</span>
                <span>{metrics.counters?.ollama_requests ?? 0}</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-500">No data yet</p>
          )}
        </div>

        {/* Active Alerts */}
        <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Alerts</h3>
          {Object.keys(activeIssues).length > 0 ? (
            <ul className="space-y-1">
              {Object.keys(activeIssues).map((k) => (
                <li key={k} className="text-xs text-red-400 flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                  {k.replace(/_/g, ' ')}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-green-400">No active issues</p>
          )}
          {Object.keys(recentAlerts).length > 0 && (
            <div className="mt-3 border-t border-gray-700 pt-2">
              <p className="text-xs text-gray-500 mb-1">Recent (1h)</p>
              {Object.entries(recentAlerts).map(([k, v]) => (
                <p key={k} className="text-xs text-gray-400">
                  {k.replace(/_/g, ' ')} — {typeof v === 'string' ? v : ''}
                </p>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Scheduled Jobs */}
      <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">
            Scheduled Jobs ({jobs.length})
          </h3>
          <span className={`text-xs px-2 py-0.5 rounded-full ${scheduler?.running ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
            {scheduler?.running ? 'Running' : 'Stopped'}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-400 border-b border-gray-700">
                <th className="text-left py-2 pr-4">Job</th>
                <th className="text-left py-2 pr-4">Next Run</th>
                <th className="text-center py-2 pr-4">OK</th>
                <th className="text-center py-2 pr-4">Fail</th>
                <th className="text-right py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const stats = jobStats[job.id] ?? { ok: 0, fail: 0 }
                return (
                  <tr key={job.id} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                    <td className="py-2 pr-4 text-gray-200">{job.id}</td>
                    <td className="py-2 pr-4 text-gray-400">
                      {job.next_run ? new Date(job.next_run).toLocaleTimeString() : '-'}
                    </td>
                    <td className="py-2 pr-4 text-center text-green-400">{stats.ok}</td>
                    <td className="py-2 pr-4 text-center text-red-400">{stats.fail}</td>
                    <td className="py-2 text-right">
                      <button
                        className="text-indigo-400 hover:text-indigo-300"
                        onClick={() => triggerJob.mutate(job.id)}
                        disabled={triggerJob.isPending}
                      >
                        Trigger
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Executions */}
      <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
        <h3 className="text-sm font-semibold text-white mb-3">Recent Executions</h3>
        <div className="overflow-x-auto max-h-64 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-800">
              <tr className="text-gray-400 border-b border-gray-700">
                <th className="text-left py-2 pr-4">Job</th>
                <th className="text-left py-2 pr-4">Time</th>
                <th className="text-center py-2 pr-4">Status</th>
                <th className="text-right py-2 pr-4">Duration</th>
                <th className="text-left py-2">Error</th>
              </tr>
            </thead>
            <tbody>
              {executions.slice(-30).reverse().map((e, i) => (
                <tr key={i} className="border-b border-gray-700/50">
                  <td className="py-1.5 pr-4 text-gray-200">{e.job_name}</td>
                  <td className="py-1.5 pr-4 text-gray-400">
                    {e.started_at ? new Date(e.started_at).toLocaleTimeString() : '-'}
                  </td>
                  <td className="py-1.5 pr-4 text-center">
                    <span className={`px-1.5 py-0.5 rounded ${e.status === 'completed' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                      {e.status}
                    </span>
                  </td>
                  <td className="py-1.5 pr-4 text-right text-gray-400">
                    {e.duration_seconds != null ? `${e.duration_seconds.toFixed(1)}s` : '-'}
                  </td>
                  <td className="py-1.5 text-red-400 max-w-xs truncate">{e.error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Job Counters */}
      {metrics?.counters && Object.keys(metrics.counters).length > 0 && (
        <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Job Counters</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {Object.entries(metrics.counters)
              .filter(([k]) => k.startsWith('job_'))
              .sort(([, a], [, b]) => (b as number) - (a as number))
              .slice(0, 12)
              .map(([name, value]) => (
                <div key={name} className="text-xs text-gray-300 flex justify-between">
                  <span className="truncate mr-2">{name.replace('job_', '')}</span>
                  <span className="text-gray-400 font-mono">{value as number}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
