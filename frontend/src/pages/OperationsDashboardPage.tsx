import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  MessageCircle,
  RefreshCw,
  XCircle,
  Zap,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useOperationsDashboard,
  type OperationsKpis,
  type ActiveIssue,
  type RecentFailure,
  type LiveActivityEvent,
  type LlmProviderStatus,
} from '@/hooks/useOperationsDashboard'

// ─── KPI Strip ───────────────────────────────────────────────────────

function gradeColor(grade: number | null): string {
  if (grade === null) return 'text-gray-500'
  if (grade >= 90) return 'text-green-400'
  if (grade >= 70) return 'text-yellow-400'
  return 'text-red-400'
}

function rateColor(rate: number | null): string {
  if (rate === null) return 'text-gray-500'
  if (rate >= 98) return 'text-green-400'
  if (rate >= 95) return 'text-yellow-400'
  return 'text-red-400'
}

function alertColor(count: number): string {
  if (count === 0) return 'text-green-400'
  if (count <= 3) return 'text-yellow-400'
  return 'text-red-400'
}

function KpiCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      {children}
    </div>
  )
}

function KpiStrip({ kpis }: { kpis: OperationsKpis }) {
  const budgetPct = kpis.llm_budget_usd > 0
    ? Math.min((kpis.llm_spend_usd / kpis.llm_budget_usd) * 100, 100)
    : 0

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <KpiCard label="Daily Grade">
        <div className={`text-3xl font-bold ${gradeColor(kpis.daily_grade)}`}>
          {kpis.daily_grade !== null ? (
            <>{kpis.daily_grade}<span className="text-lg">/100</span></>
          ) : (
            <span className="text-gray-500">--</span>
          )}
        </div>
      </KpiCard>

      <KpiCard label="Success Rate (24h)">
        <div className={`text-3xl font-bold ${rateColor(kpis.success_rate_24h)}`}>
          {kpis.success_rate_24h !== null ? `${kpis.success_rate_24h}%` : '--'}
        </div>
      </KpiCard>

      <KpiCard label="Job Runs (24h)">
        <div className="text-3xl font-bold text-gray-100">
          {kpis.total_runs_24h.toLocaleString()}
        </div>
      </KpiCard>

      <KpiCard label="Active Alerts">
        <div className={`text-3xl font-bold ${alertColor(kpis.active_alerts)}`}>
          {kpis.active_alerts}
        </div>
      </KpiCard>

      <KpiCard label="LLM Spend Today">
        <div className="text-2xl font-bold text-green-400">
          ${kpis.llm_spend_usd.toFixed(3)}
        </div>
        {kpis.llm_budget_usd > 0 && (
          <div className="mt-1.5">
            <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-500 rounded-full transition-all"
                style={{ width: `${budgetPct}%` }}
              />
            </div>
            <div className="text-[10px] text-gray-500 mt-0.5">
              of ${kpis.llm_budget_usd.toFixed(2)} budget
            </div>
          </div>
        )}
      </KpiCard>

      <KpiCard label="Conversations Today">
        <div className="text-3xl font-bold text-indigo-400">
          {kpis.conversations_today}
        </div>
      </KpiCard>
    </div>
  )
}

// ─── Service Health Row ──────────────────────────────────────────────

function statusDot(status: string): string {
  if (status === 'ok') return 'bg-green-500'
  if (status === 'degraded') return 'bg-yellow-500'
  return 'bg-red-500'
}

function ServiceHealthRow({ health }: { health: Record<string, string> }) {
  const entries = Object.entries(health)
  if (entries.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-medium text-gray-300 mb-3">Service Health</h3>
      <div className="flex flex-wrap gap-4">
        {entries.map(([service, status]) => (
          <div key={service} className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${statusDot(status)}`} />
            <span className="text-sm text-gray-300 capitalize">{service}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Active Issues Panel ─────────────────────────────────────────────

function ActiveIssuesPanel({ issues }: { issues: ActiveIssue[] }) {
  if (issues.length === 0) {
    return (
      <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
        <div className="flex items-center gap-2 text-green-400 py-4 justify-center">
          <CheckCircle className="w-5 h-5" />
          <span className="text-sm font-medium">All systems nominal</span>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-medium text-gray-300 mb-3">
        Active Issues ({issues.length})
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {issues.map((issue, i) => (
          <div key={i} className="flex items-start gap-2 p-3 rounded bg-gray-900/50 border border-gray-700/50">
            <AlertTriangle className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
              issue.severity === 'error' ? 'text-red-400' : 'text-yellow-400'
            }`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-200">{issue.name}</div>
              <div className="text-xs text-gray-400 mt-0.5">{issue.message}</div>
              {issue.since && (
                <div className="text-xs text-gray-500 mt-1">
                  Since {new Date(issue.since).toLocaleTimeString()}
                </div>
              )}
            </div>
            <Badge
              variant="outline"
              className={
                issue.severity === 'error'
                  ? 'border-red-500/30 text-red-400'
                  : 'border-yellow-500/30 text-yellow-400'
              }
            >
              {issue.type === 'circuit_breaker' ? 'breaker' : 'alert'}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Recent Failures ─────────────────────────────────────────────────

function RecentFailuresPanel({ failures }: { failures: RecentFailure[] }) {
  const [expanded, setExpanded] = useState<number | null>(null)

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-medium text-gray-300 mb-3">
        Recent Failures ({failures.length})
      </h3>
      {failures.length === 0 ? (
        <div className="text-center text-gray-500 py-6 text-sm">
          No failures in last 24h
        </div>
      ) : (
        <div className="space-y-1 max-h-72 overflow-y-auto">
          {failures.map((f, i) => (
            <button
              key={i}
              onClick={() => setExpanded(expanded === i ? null : i)}
              className="w-full text-left p-2 rounded hover:bg-gray-900/50 transition-colors"
            >
              <div className="flex items-start gap-2">
                {expanded === i ? (
                  <ChevronDown className="w-3.5 h-3.5 text-gray-500 mt-0.5 flex-shrink-0" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-gray-500 mt-0.5 flex-shrink-0" />
                )}
                <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono text-gray-300">{f.job_name}</span>
                    <span className="text-xs text-gray-500">
                      {f.duration_s > 0 ? `${f.duration_s}s` : ''}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500">
                    {f.failed_at ? new Date(f.failed_at).toLocaleString() : 'Unknown time'}
                  </div>
                  {expanded === i && f.error && (
                    <div className="mt-2 p-2 rounded bg-red-950/30 border border-red-900/30 text-xs text-red-300 break-all">
                      {f.error}
                    </div>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Live Activity Feed ──────────────────────────────────────────────

function LiveActivityFeed({ activity }: { activity: LiveActivityEvent[] }) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-medium text-gray-300 mb-3">
        <Activity className="w-4 h-4 inline mr-1.5" />
        Live Activity
      </h3>
      {activity.length === 0 ? (
        <div className="text-center text-gray-500 py-6 text-sm">No recent activity</div>
      ) : (
        <div className="space-y-0.5 max-h-80 overflow-y-auto">
          {activity.map((event, i) => (
            <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-900/30">
              {event.type === 'conversation' ? (
                <MessageCircle className="w-3 h-3 flex-shrink-0 text-indigo-400" />
              ) : (
                <Zap className={`w-3 h-3 flex-shrink-0 ${
                  event.status === 'completed' ? 'text-green-400' :
                  event.status === 'failed' ? 'text-red-400' : 'text-yellow-400'
                }`} />
              )}
              <span className="text-xs text-gray-500 w-16 flex-shrink-0 font-mono">
                {event.timestamp ? new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'}
              </span>
              <span className="text-xs text-gray-300 truncate flex-1">
                {event.summary}
              </span>
              <Badge
                variant="outline"
                className={`text-[10px] flex-shrink-0 ${
                  event.type === 'conversation'
                    ? 'border-indigo-500/30 text-indigo-400'
                    : 'border-gray-600 text-gray-400'
                }`}
              >
                {event.type === 'conversation' ? 'chat' : 'job'}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── LLM Providers Panel ────────────────────────────────────────────

function LlmProvidersPanel({ providers }: { providers: LlmProviderStatus[] }) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h3 className="text-sm font-medium text-gray-300 mb-3">LLM Providers</h3>
      {providers.length === 0 ? (
        <div className="text-center text-gray-500 py-6 text-sm">No provider data</div>
      ) : (
        <div className="space-y-2">
          {providers.map((p) => (
            <div key={p.name} className="p-3 rounded bg-gray-900/50 border border-gray-700/50">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${p.healthy ? 'bg-green-500' : 'bg-red-500'}`} />
                  <span className="text-sm font-medium text-gray-200 capitalize">{p.name}</span>
                  <Badge
                    variant="outline"
                    className={`text-[10px] ${
                      p.circuit_state === 'closed'
                        ? 'border-green-500/30 text-green-400'
                        : p.circuit_state === 'half_open'
                        ? 'border-yellow-500/30 text-yellow-400'
                        : 'border-red-500/30 text-red-400'
                    }`}
                  >
                    {p.circuit_state}
                  </Badge>
                </div>
                <span className="text-xs text-green-400 font-mono">
                  ${p.spend_today_usd.toFixed(4)}
                </span>
              </div>
              {p.error && (
                <div className="text-xs text-red-400 mt-1.5">{p.error}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Drill-Down Links ───────────────────────────────────────────────

function DrillDownLinks() {
  const links = [
    { label: 'System Health', href: '/system-health' },
    { label: 'Exec Dashboard', href: '/execution-dashboard' },
    { label: 'Gateway', href: '/orchestrator' },
    { label: 'LLM Settings', href: '/settings' },
  ]

  return (
    <div className="flex flex-wrap gap-2">
      {links.map((link) => (
        <Link
          key={link.href}
          to={link.href}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
        >
          {link.label}
          <ExternalLink className="w-3 h-3" />
        </Link>
      ))}
    </div>
  )
}

// ─── Loading Skeleton ───────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="p-6 space-y-6">
      <Skeleton className="h-8 w-64 bg-gray-800" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-24 bg-gray-800 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-16 bg-gray-800 rounded-lg" />
      <Skeleton className="h-32 bg-gray-800 rounded-lg" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Skeleton className="h-64 bg-gray-800 rounded-lg" />
        <Skeleton className="h-64 bg-gray-800 rounded-lg" />
      </div>
    </div>
  )
}

// ─── Main Page ──────────────────────────────────────────────────────

export function OperationsDashboardPage() {
  const { data, isLoading, isError, error, dataUpdatedAt } = useOperationsDashboard()

  if (isLoading) return <LoadingSkeleton />

  if (isError || !data) {
    return (
      <div className="p-6">
        <div className="bg-red-950/30 border border-red-900/30 rounded-lg p-6 text-center">
          <XCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
          <p className="text-red-300 font-medium">Failed to load operations data</p>
          <p className="text-red-400/70 text-sm mt-1">{error?.message || 'Unknown error'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      {/* Updated timestamp */}
      <div className="flex items-center justify-end">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <RefreshCw className="w-3 h-3 animate-spin-slow" />
          Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
        </div>
      </div>

      {/* Backend errors banner */}
      {data.errors.length > 0 && (
        <div className="bg-yellow-950/30 border border-yellow-900/30 rounded-lg p-3">
          <div className="flex items-center gap-2 text-yellow-400 text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            <span>
              {data.errors.length} subsystem{data.errors.length > 1 ? 's' : ''} unavailable:
              {' '}{data.errors.map(e => e.split(':')[0]).join(', ')}
            </span>
          </div>
        </div>
      )}

      {/* KPI Strip */}
      <KpiStrip kpis={data.kpis} />

      {/* Service Health */}
      <ServiceHealthRow health={data.service_health} />

      {/* Active Issues */}
      <ActiveIssuesPanel issues={data.active_issues} />

      {/* Two-column: Recent Failures + Live Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <RecentFailuresPanel failures={data.recent_failures} />
        <LiveActivityFeed activity={data.live_activity} />
      </div>

      {/* LLM Providers */}
      <LlmProvidersPanel providers={data.llm_providers} />

      {/* Drill-down links */}
      <div>
        <h3 className="text-sm font-medium text-gray-400 mb-2">Drill Down</h3>
        <DrillDownLinks />
      </div>
    </div>
  )
}
