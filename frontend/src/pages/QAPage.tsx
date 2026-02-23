import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  ShieldCheck,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  Play,
  Container,
  FileCode,
  Globe,
  Server,
  FileText,
} from 'lucide-react'

const API_BASE = ''

interface QACheckResult {
  category: string
  name: string
  status: 'passed' | 'failed' | 'warning' | 'error' | 'skipped'
  duration_seconds: number
  details: string | null
  errors: string[]
  warnings: string[]
  metrics: Record<string, unknown>
}

interface QAReport {
  report_id: string
  started_at: string
  completed_at: string
  trigger: string
  overall_status: 'passed' | 'failed' | 'warning' | 'error'
  can_deploy: boolean
  blocking_issues: string[]
  warnings: string[]
  checks: QACheckResult[]
  total_checks: number
  passed_count: number
  failed_count: number
  warning_count: number
  legion_tasks_created: number[]
}

const categoryIcons: Record<string, React.ElementType> = {
  docker_health: Container,
  docker_build: Container,
  frontend_build: FileCode,
  typescript: FileCode,
  browser: Globe,
  api: Server,
  logs: FileText,
}

const statusColors: Record<string, string> = {
  passed: 'text-green-400',
  failed: 'text-red-400',
  warning: 'text-yellow-400',
  error: 'text-orange-400',
  skipped: 'text-gray-500',
}

const statusBorderColors: Record<string, string> = {
  passed: 'border-l-green-500',
  failed: 'border-l-red-500',
  warning: 'border-l-yellow-500',
  error: 'border-l-orange-500',
}

const statusIcons: Record<string, React.ElementType> = {
  passed: CheckCircle,
  failed: XCircle,
  warning: AlertTriangle,
  error: AlertTriangle,
  skipped: Clock,
}

export function QAPage() {
  const queryClient = useQueryClient()
  const [expandedCheck, setExpandedCheck] = useState<string | null>(null)

  const { data: report, isLoading } = useQuery<QAReport | null>({
    queryKey: ['qa', 'latest'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/qa/latest`, { headers: getAuthHeaders() })
      if (res.status === 404) return null
      if (!res.ok) throw new Error('Failed to fetch QA report')
      return res.json()
    },
    refetchInterval: 30000,
  })

  const triggerQA = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/api/qa/verify/sync`, { method: 'POST', headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to trigger QA')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qa'] })
    },
  })

  if (isLoading) {
    return (
      <div className="page-content">
        <div className="flex items-center gap-3 mb-8">
          <ShieldCheck className="w-8 h-8 text-primary" />
          <h1 className="page-title">QA Verification</h1>
        </div>
        <LoadingSkeleton variant="page" message="Loading QA report..." />
      </div>
    )
  }

  // No reports yet
  if (!report) {
    return (
      <div className="page-content">
        <div className="flex items-center gap-3 mb-8">
          <ShieldCheck className="w-8 h-8 text-primary" />
          <h1 className="page-title">QA Verification</h1>
        </div>
        <div className="glass-card p-12 text-center">
          <ShieldCheck className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-lg font-semibold text-foreground mb-2">No QA Reports</h2>
          <p className="text-sm text-muted-foreground mb-4">
            Run a verification to check Docker, builds, types, API, and logs.
          </p>
          <button
            onClick={() => triggerQA.mutate()}
            disabled={triggerQA.isPending}
            className="btn-primary text-sm flex items-center gap-2 mx-auto"
          >
            {triggerQA.isPending ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {triggerQA.isPending ? 'Running...' : 'Run QA Verification'}
          </button>
        </div>
      </div>
    )
  }

  const StatusIcon = statusIcons[report.overall_status] || AlertTriangle
  const duration = report.completed_at && report.started_at
    ? ((new Date(report.completed_at).getTime() - new Date(report.started_at).getTime()) / 1000).toFixed(1)
    : '—'

  return (
    <div className="page-content">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-8 h-8 text-primary" />
          <div>
            <h1 className="page-title">QA Verification</h1>
            <p className="text-xs text-muted-foreground">
              {report.report_id} &middot; {new Date(report.completed_at).toLocaleString()}
            </p>
          </div>
        </div>
        <button
          onClick={() => triggerQA.mutate()}
          disabled={triggerQA.isPending}
          className="btn-primary text-xs flex items-center gap-1.5"
        >
          {triggerQA.isPending ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Play className="w-3.5 h-3.5" />
          )}
          {triggerQA.isPending ? 'Running...' : 'Run QA'}
        </button>
      </div>

      {/* Overall Status Card */}
      <div className={`glass-card p-6 mb-6 border-l-4 ${statusBorderColors[report.overall_status] || 'border-l-gray-500'}`}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <StatusIcon className={`w-8 h-8 ${statusColors[report.overall_status]}`} />
            <div>
              <h2 className="text-xl font-bold text-foreground">
                {report.can_deploy ? 'Ready to Deploy' : 'Deployment Blocked'}
              </h2>
              <p className="text-xs text-muted-foreground">
                Trigger: {report.trigger} &middot; Duration: {duration}s
              </p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold text-primary">
              {report.passed_count}/{report.total_checks}
            </div>
            <div className="text-[11px] text-muted-foreground">checks passed</div>
          </div>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-4 gap-3">
          <div className="bg-white/5 rounded p-3 text-center">
            <div className="text-xl font-bold text-green-400">{report.passed_count}</div>
            <div className="text-[11px] text-muted-foreground">Passed</div>
          </div>
          <div className="bg-white/5 rounded p-3 text-center">
            <div className="text-xl font-bold text-red-400">{report.failed_count}</div>
            <div className="text-[11px] text-muted-foreground">Failed</div>
          </div>
          <div className="bg-white/5 rounded p-3 text-center">
            <div className="text-xl font-bold text-yellow-400">{report.warning_count}</div>
            <div className="text-[11px] text-muted-foreground">Warnings</div>
          </div>
          <div className="bg-white/5 rounded p-3 text-center">
            <div className="text-xl font-bold text-primary">{duration}s</div>
            <div className="text-[11px] text-muted-foreground">Duration</div>
          </div>
        </div>

        {/* Blocking Issues */}
        {report.blocking_issues.length > 0 && (
          <div className="mt-4 p-4 bg-red-500/10 border border-red-500/20 rounded">
            <h3 className="font-semibold text-red-400 text-sm mb-2">Blocking Issues:</h3>
            <ul className="space-y-1">
              {report.blocking_issues.map((issue, i) => (
                <li key={i} className="text-xs text-red-300">&bull; {issue}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Legion Tasks */}
        {report.legion_tasks_created.length > 0 && (
          <div className="mt-3 p-3 bg-blue-500/10 border border-blue-500/20 rounded">
            <p className="text-xs text-blue-300">
              Created {report.legion_tasks_created.length} Legion fix task(s)
            </p>
          </div>
        )}
      </div>

      {/* Individual Checks */}
      <h2 className="text-sm font-semibold text-foreground mb-3">Verification Checks</h2>
      <div className="space-y-2">
        {report.checks.map((check, index) => {
          const Icon = categoryIcons[check.category] || FileCode
          const SIcon = statusIcons[check.status] || Clock
          const isExpanded = expandedCheck === `${index}-${check.name}`

          return (
            <div
              key={index}
              className="glass-card overflow-hidden cursor-pointer hover:bg-white/5 transition-colors"
              onClick={() => setExpandedCheck(isExpanded ? null : `${index}-${check.name}`)}
            >
              <div className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <Icon className="w-4 h-4 text-primary shrink-0" />
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-foreground truncate">{check.name}</h3>
                    <p className="text-[11px] text-muted-foreground">
                      {check.category.replace('_', ' ')} &middot; {check.duration_seconds.toFixed(2)}s
                    </p>
                  </div>
                </div>
                <SIcon className={`w-5 h-5 ${statusColors[check.status]} shrink-0`} />
              </div>

              {isExpanded && (
                <div className="px-4 pb-4 border-t border-white/10 pt-3 space-y-3">
                  {check.details && (
                    <p className="text-xs text-muted-foreground">{check.details}</p>
                  )}

                  {check.errors.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-red-400 mb-1">Errors:</h4>
                      <div className="bg-red-500/10 border border-red-500/20 rounded p-3 space-y-1 max-h-48 overflow-y-auto">
                        {check.errors.map((err, i) => (
                          <div key={i} className="text-[11px] font-mono text-red-300 break-all">{err}</div>
                        ))}
                      </div>
                    </div>
                  )}

                  {check.warnings.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-yellow-400 mb-1">Warnings:</h4>
                      <div className="bg-yellow-500/10 border border-yellow-500/20 rounded p-3 space-y-1 max-h-48 overflow-y-auto">
                        {check.warnings.map((w, i) => (
                          <div key={i} className="text-[11px] text-yellow-300 break-all">{w}</div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
