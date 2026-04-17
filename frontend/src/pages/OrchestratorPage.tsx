import { useState } from 'react'
import {
  MessageSquare, GitBranch, BarChart3, Clock,
  AlertCircle, CheckCircle, Wifi, WifiOff, Hash,
  ChevronDown, ChevronRight, Zap, ArrowRight, ShieldCheck, Activity,
  ThumbsUp, ThumbsDown,
} from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useConversations,
  useConversationDetail,
  useThreads,
  useThreadHistory,
  useRouteStats,
  useActivityFeed,
  useGraphStatus,
} from '@/hooks/useOrchestratorApi'
import { useActivityStream } from '@/hooks/useActivityStream'
import {
  usePendingApprovals,
  useApprovalStats,
  useApproveRequest,
  useRejectRequest,
} from '@/hooks/useApprovalApi'
import type {
  OrchestratorConversation,
  OrchestratorTrace,
  ThreadSummary,
  RouteStatEntry,
  ApprovalRequest as ApprovalRequestType,
} from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CHANNEL_COLORS: Record<string, string> = {
  api: 'bg-blue-500/20 text-blue-400',
  discord: 'bg-indigo-500/20 text-indigo-400',
  whatsapp: 'bg-green-500/20 text-green-400',
  slack: 'bg-purple-500/20 text-purple-400',
}

const ROUTE_COLORS: Record<string, string> = {
  sprint: 'bg-blue-500/20 text-blue-300',
  email: 'bg-yellow-500/20 text-yellow-300',
  calendar: 'bg-green-500/20 text-green-300',
  task: 'bg-orange-500/20 text-orange-300',
  knowledge: 'bg-purple-500/20 text-purple-300',
  research: 'bg-cyan-500/20 text-cyan-300',
  tiktok: 'bg-pink-500/20 text-pink-300',
  system: 'bg-gray-500/20 text-gray-300',
  general: 'bg-gray-500/20 text-gray-400',
  planner: 'bg-amber-500/20 text-amber-300',
  money_maker: 'bg-emerald-500/20 text-emerald-300',
  prediction_market: 'bg-red-500/20 text-red-300',
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function formatMs(ms?: number | null): string {
  if (!ms) return '-'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ---------------------------------------------------------------------------
// Conversations Tab
// ---------------------------------------------------------------------------

function ConversationsTab() {
  const [channelFilter, setChannelFilter] = useState<string>('')
  const [routeFilter, setRouteFilter] = useState<string>('')
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { data, isLoading } = useConversations({
    channel: channelFilter || undefined,
    route: routeFilter || undefined,
    errors_only: errorsOnly || undefined,
    limit: 50,
  })
  const { data: detail } = useConversationDetail(expandedId)

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-300"
          value={channelFilter}
          onChange={(e) => setChannelFilter(e.target.value)}
        >
          <option value="">All Channels</option>
          <option value="discord">Discord</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="slack">Slack</option>
          <option value="api">API</option>
        </select>
        <select
          className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-gray-300"
          value={routeFilter}
          onChange={(e) => setRouteFilter(e.target.value)}
        >
          <option value="">All Routes</option>
          {Object.keys(ROUTE_COLORS).map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <label className="flex items-center gap-1 text-sm text-gray-400">
          <input
            type="checkbox"
            checked={errorsOnly}
            onChange={(e) => setErrorsOnly(e.target.checked)}
            className="rounded bg-gray-800 border-gray-600"
          />
          Errors only
        </label>
        {data && (
          <span className="ml-auto text-xs text-gray-500">{data.total} total</span>
        )}
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 bg-gray-800" />)}
        </div>
      ) : (
        <div className="space-y-1">
          {data?.items.map((conv) => (
            <ConversationRow
              key={conv.id}
              conv={conv}
              isExpanded={expandedId === conv.id}
              onToggle={() => setExpandedId(expandedId === conv.id ? null : conv.id)}
              traces={expandedId === conv.id ? detail?.traces : undefined}
            />
          ))}
          {data?.items.length === 0 && (
            <div className="text-center text-gray-500 py-12">
              No conversations yet. Send a message through the gateway to see it here.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ConversationRow({
  conv,
  isExpanded,
  onToggle,
  traces,
}: {
  conv: OrchestratorConversation
  isExpanded: boolean
  onToggle: () => void
  traces?: OrchestratorTrace[]
}) {
  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-800/50 transition-colors text-left"
      >
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0" />
        )}

        <span className="text-xs text-gray-500 w-16 flex-shrink-0">{timeAgo(conv.created_at)}</span>

        <Badge className={`text-xs ${CHANNEL_COLORS[conv.channel] ?? 'bg-gray-700 text-gray-300'}`}>
          {conv.channel}
        </Badge>

        <span className="text-sm text-gray-200 truncate flex-1">{conv.message}</span>

        {conv.route && (
          <Badge className={`text-xs ${ROUTE_COLORS[conv.route] ?? 'bg-gray-700 text-gray-300'}`}>
            {conv.route}
          </Badge>
        )}

        <span className="text-xs text-gray-500 w-16 text-right flex-shrink-0">
          {formatMs(conv.latency_ms)}
        </span>

        {conv.error && <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
      </button>

      {isExpanded && (
        <div className="border-t border-gray-800 bg-gray-900/50 px-4 py-3">
          <h4 className="text-xs font-medium text-gray-400 mb-2 flex items-center gap-1">
            <GitBranch className="w-3 h-3" /> Execution Trace
          </h4>
          {traces ? (
            <div className="space-y-2">
              {traces.map((t) => (
                <TraceNodeRow key={t.id} trace={t} />
              ))}
              {traces.length === 0 && (
                <p className="text-xs text-gray-500">No trace data recorded.</p>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <Skeleton className="h-8 bg-gray-800" />
              <Skeleton className="h-8 bg-gray-800" />
            </div>
          )}

          <div className="mt-3 flex gap-4 text-xs text-gray-500">
            <span>Thread: <code className="text-gray-400">{conv.thread_id}</code></span>
            <span>Method: <code className="text-gray-400">{conv.route_method ?? '-'}</code></span>
            <span>Confidence: <code className="text-gray-400">{conv.route_confidence ?? '-'}</code></span>
            <span>Tokens: <code className="text-gray-400">{conv.tokens_used}</code></span>
          </div>
        </div>
      )}
    </div>
  )
}

function TraceNodeRow({ trace }: { trace: OrchestratorTrace }) {
  const [showDetail, setShowDetail] = useState(false)
  const statusIcon = trace.status === 'completed' ? (
    <CheckCircle className="w-3.5 h-3.5 text-green-400" />
  ) : trace.status === 'failed' ? (
    <AlertCircle className="w-3.5 h-3.5 text-red-400" />
  ) : (
    <Clock className="w-3.5 h-3.5 text-yellow-400 animate-pulse" />
  )

  return (
    <div className="border border-gray-800 rounded px-3 py-2">
      <button
        onClick={() => setShowDetail(!showDetail)}
        className="w-full flex items-center gap-2 text-left"
      >
        {statusIcon}
        <span className="text-sm text-gray-300 font-mono">{trace.node_name}</span>
        <ArrowRight className="w-3 h-3 text-gray-600" />
        <span className="text-xs text-gray-500 ml-auto">{formatMs(trace.duration_ms)}</span>
        {trace.tokens_used > 0 && (
          <span className="text-xs text-gray-600">{trace.tokens_used} tok</span>
        )}
      </button>
      {showDetail && (
        <div className="mt-2 space-y-1 text-xs">
          {trace.input_preview && (
            <div>
              <span className="text-gray-500">Input: </span>
              <code className="text-gray-400 break-all">{trace.input_preview}</code>
            </div>
          )}
          {trace.output_preview && (
            <div>
              <span className="text-gray-500">Output: </span>
              <code className="text-gray-400 break-all">{trace.output_preview}</code>
            </div>
          )}
          {trace.error && (
            <div className="text-red-400">Error: {trace.error}</div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Threads Tab
// ---------------------------------------------------------------------------

function ThreadsTab() {
  const [selectedThread, setSelectedThread] = useState<string | null>(null)
  const { data: threads, isLoading } = useThreads()
  const { data: history } = useThreadHistory(selectedThread)

  if (selectedThread && history) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setSelectedThread(null)}
          className="text-sm text-indigo-400 hover:text-indigo-300"
        >
          &larr; Back to threads
        </button>
        <h3 className="text-sm font-medium text-gray-300">
          Thread: <code>{selectedThread}</code>
        </h3>
        <div className="space-y-2 max-h-[600px] overflow-y-auto pr-2">
          {history.map((msg) => (
            <div
              key={msg.id}
              className={`px-4 py-2 rounded-lg max-w-[85%] ${
                msg.direction === 'inbound'
                  ? 'bg-indigo-500/10 border border-indigo-500/20 ml-0'
                  : 'bg-gray-800 border border-gray-700 ml-auto'
              }`}
            >
              <div className="flex justify-between mb-1">
                <span className="text-xs text-gray-500">
                  {msg.direction === 'inbound' ? 'User' : 'Zero'}
                </span>
                <span className="text-xs text-gray-600">{timeAgo(msg.created_at)}</span>
              </div>
              <p className="text-sm text-gray-200 whitespace-pre-wrap">{msg.message}</p>
              {msg.route && (
                <Badge className={`mt-1 text-xs ${ROUTE_COLORS[msg.route] ?? 'bg-gray-700 text-gray-300'}`}>
                  {msg.route}
                </Badge>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {isLoading ? (
        [...Array(5)].map((_, i) => <Skeleton key={i} className="h-16 bg-gray-800" />)
      ) : (
        threads?.map((t: ThreadSummary) => (
          <button
            key={t.thread_id}
            onClick={() => setSelectedThread(t.thread_id)}
            className="w-full flex items-center gap-3 px-4 py-3 border border-gray-800 rounded-lg hover:bg-gray-800/50 transition-colors text-left"
          >
            <Hash className="w-4 h-4 text-gray-500" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <code className="text-sm text-gray-300 truncate">{t.thread_id}</code>
                <Badge className={`text-xs ${CHANNEL_COLORS[t.channel] ?? 'bg-gray-700 text-gray-300'}`}>
                  {t.channel}
                </Badge>
              </div>
              <p className="text-xs text-gray-500 truncate mt-0.5">{t.last_message}</p>
            </div>
            <div className="text-right flex-shrink-0">
              <div className="text-sm text-gray-400">{t.message_count} msgs</div>
              <div className="text-xs text-gray-600">{timeAgo(t.last_active)}</div>
            </div>
          </button>
        ))
      )}
      {!isLoading && threads?.length === 0 && (
        <div className="text-center text-gray-500 py-12">No conversation threads yet.</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Route Analytics Tab
// ---------------------------------------------------------------------------

function RouteAnalyticsTab() {
  const [hours, setHours] = useState(24)
  const { data: stats, isLoading } = useRouteStats(hours)

  const maxCount = Math.max(...(stats?.map((s: RouteStatEntry) => s.invocation_count) ?? [1]))

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {[24, 168, 720].map((h) => (
          <button
            key={h}
            onClick={() => setHours(h)}
            className={`px-3 py-1 text-xs rounded ${
              hours === h ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30' : 'bg-gray-800 text-gray-400 border border-gray-700'
            }`}
          >
            {h === 24 ? '24h' : h === 168 ? '7d' : '30d'}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 bg-gray-800" />)}
        </div>
      ) : (
        <div className="space-y-3">
          {stats?.map((s: RouteStatEntry) => (
            <div key={s.route} className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Badge className={`text-xs ${ROUTE_COLORS[s.route] ?? 'bg-gray-700 text-gray-300'}`}>
                    {s.route}
                  </Badge>
                  <span className="text-sm text-gray-300">{s.invocation_count} calls</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  <span>avg {formatMs(s.avg_latency_ms)}</span>
                  {s.error_count > 0 && (
                    <span className="text-red-400">{s.error_count} errors ({(s.error_rate * 100).toFixed(1)}%)</span>
                  )}
                  <span>{s.total_tokens.toLocaleString()} tok</span>
                  {s.total_cost_usd > 0 && (
                    <span className="text-green-400">${s.total_cost_usd.toFixed(4)}</span>
                  )}
                </div>
              </div>
              <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500/50 rounded-full transition-all"
                  style={{ width: `${(s.invocation_count / maxCount) * 100}%` }}
                />
              </div>
            </div>
          ))}
          {stats?.length === 0 && (
            <div className="text-center text-gray-500 py-12">No route data for this period.</div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Activity Feed Tab
// ---------------------------------------------------------------------------

function ActivityFeedTab() {
  const { events, isConnected } = useActivityStream()
  const { data: feedData } = useActivityFeed()

  // Merge SSE events with polling fallback
  const displayEvents = events.length > 0 ? events : feedData ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-gray-500">
        {isConnected ? (
          <>
            <Wifi className="w-3 h-3 text-green-400" />
            <span className="text-green-400">Live</span>
          </>
        ) : (
          <>
            <WifiOff className="w-3 h-3 text-yellow-400" />
            <span className="text-yellow-400">Reconnecting...</span>
          </>
        )}
        <span className="ml-auto">{displayEvents.length} events</span>
      </div>

      <div className="space-y-1 max-h-[600px] overflow-y-auto">
        {displayEvents.map((evt, i) => (
          <div
            key={evt.id ?? i}
            className="flex items-center gap-2 px-3 py-2 border border-gray-800 rounded text-sm"
          >
            {evt.status === 'error' ? (
              <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
            ) : evt.event_type === 'invocation' ? (
              <Zap className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
            ) : (
              <CheckCircle className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />
            )}
            <span className="text-gray-300 truncate flex-1">{evt.summary}</span>
            {evt.route && (
              <Badge className={`text-xs ${ROUTE_COLORS[evt.route] ?? 'bg-gray-700 text-gray-300'}`}>
                {evt.route}
              </Badge>
            )}
            <span className="text-xs text-gray-500 flex-shrink-0">
              {timeAgo(evt.timestamp)}
            </span>
          </div>
        ))}
        {displayEvents.length === 0 && (
          <div className="text-center text-gray-500 py-12">
            Waiting for activity... Send a message through the gateway.
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Performance Tab (Sprint 3)
// ---------------------------------------------------------------------------

function PerformanceTab() {
  const [hours, setHours] = useState(24)
  const { data: stats, isLoading } = useRouteStats(hours)

  if (isLoading) {
    return <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 bg-gray-800" />)}</div>
  }

  const totalCalls = stats?.reduce((a: number, s: RouteStatEntry) => a + s.invocation_count, 0) ?? 0
  const totalTokens = stats?.reduce((a: number, s: RouteStatEntry) => a + s.total_tokens, 0) ?? 0
  const totalCost = stats?.reduce((a: number, s: RouteStatEntry) => a + s.total_cost_usd, 0) ?? 0
  const avgLatency = totalCalls > 0
    ? stats!.reduce((a: number, s: RouteStatEntry) => a + s.avg_latency_ms * s.invocation_count, 0) / totalCalls
    : 0
  const totalErrors = stats?.reduce((a: number, s: RouteStatEntry) => a + s.error_count, 0) ?? 0

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        {[24, 168, 720].map((h) => (
          <button
            key={h}
            onClick={() => setHours(h)}
            className={`px-3 py-1 text-xs rounded ${
              hours === h ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30' : 'bg-gray-800 text-gray-400 border border-gray-700'
            }`}
          >
            {h === 24 ? '24h' : h === 168 ? '7d' : '30d'}
          </button>
        ))}
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 mb-1">Total Calls</div>
          <div className="text-2xl font-semibold text-gray-100">{totalCalls.toLocaleString()}</div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 mb-1">Avg Latency</div>
          <div className="text-2xl font-semibold text-gray-100">{formatMs(avgLatency)}</div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 mb-1">Total Tokens</div>
          <div className="text-2xl font-semibold text-gray-100">{totalTokens.toLocaleString()}</div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 mb-1">Total Cost</div>
          <div className="text-2xl font-semibold text-green-400">${totalCost.toFixed(4)}</div>
        </div>
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <div className="text-xs text-gray-400 mb-1">Errors</div>
          <div className={`text-2xl font-semibold ${totalErrors > 0 ? 'text-red-400' : 'text-gray-100'}`}>
            {totalErrors}
          </div>
        </div>
      </div>

      {/* Cost Breakdown by Route */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
          <Activity className="w-4 h-4" /> Cost & Latency by Route
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="py-2 text-left">Route</th>
                <th className="py-2 text-right">Calls</th>
                <th className="py-2 text-right">Avg Latency</th>
                <th className="py-2 text-right">Tokens</th>
                <th className="py-2 text-right">Cost</th>
                <th className="py-2 text-right">Error Rate</th>
              </tr>
            </thead>
            <tbody>
              {stats?.map((s: RouteStatEntry) => (
                <tr key={s.route} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="py-2">
                    <Badge className={`text-xs ${ROUTE_COLORS[s.route] ?? 'bg-gray-700 text-gray-300'}`}>
                      {s.route}
                    </Badge>
                  </td>
                  <td className="py-2 text-right text-gray-300">{s.invocation_count}</td>
                  <td className="py-2 text-right text-gray-300">{formatMs(s.avg_latency_ms)}</td>
                  <td className="py-2 text-right text-gray-400">{s.total_tokens.toLocaleString()}</td>
                  <td className="py-2 text-right text-green-400">${s.total_cost_usd.toFixed(4)}</td>
                  <td className={`py-2 text-right ${s.error_rate > 0 ? 'text-red-400' : 'text-gray-500'}`}>
                    {(s.error_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Approvals Tab (Sprint 3)
// ---------------------------------------------------------------------------

function ApprovalsTab() {
  const { data: rawPending, isLoading } = usePendingApprovals()
  const pending = (Array.isArray(rawPending) ? rawPending : []) as ApprovalRequestType[]
  const { data: rawStats } = useApprovalStats()
  const stats = rawStats as { pending: number; approved: number; rejected: number; expired: number; avg_decision_time_hours: number } | undefined
  const approveMut = useApproveRequest()
  const rejectMut = useRejectRequest()

  return (
    <div className="space-y-6">
      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-400 mb-1">Pending</div>
            <div className="text-2xl font-semibold text-yellow-400">{stats.pending}</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-400 mb-1">Approved</div>
            <div className="text-2xl font-semibold text-green-400">{stats.approved}</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-400 mb-1">Rejected</div>
            <div className="text-2xl font-semibold text-red-400">{stats.rejected}</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-400 mb-1">Expired</div>
            <div className="text-2xl font-semibold text-gray-400">{stats.expired}</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
            <div className="text-xs text-gray-400 mb-1">Avg Decision</div>
            <div className="text-2xl font-semibold text-gray-100">
              {stats.avg_decision_time_hours > 0 ? `${stats.avg_decision_time_hours.toFixed(1)}h` : '-'}
            </div>
          </div>
        </div>
      )}

      {/* Pending Queue */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3">Pending Approvals</h3>
        {isLoading ? (
          <div className="space-y-2">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 bg-gray-800" />)}</div>
        ) : (
          <div className="space-y-3">
            {pending?.map((req: ApprovalRequestType) => (
              <div key={req.id} className="border border-gray-700 rounded-lg p-4 bg-gray-800/30">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h4 className="text-sm font-medium text-gray-200">{req.title}</h4>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge className="text-xs bg-yellow-500/20 text-yellow-300">{req.request_type}</Badge>
                      <span className="text-xs text-gray-500">by {req.initiated_by}</span>
                      <span className="text-xs text-gray-600">{timeAgo(req.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => approveMut.mutate({ id: req.id })}
                      disabled={approveMut.isPending}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30"
                    >
                      <ThumbsUp className="w-3 h-3" /> Approve
                    </button>
                    <button
                      onClick={() => rejectMut.mutate({ id: req.id })}
                      disabled={rejectMut.isPending}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30"
                    >
                      <ThumbsDown className="w-3 h-3" /> Reject
                    </button>
                  </div>
                </div>
                {req.description && (
                  <p className="text-xs text-gray-400 mt-1">{req.description}</p>
                )}
                {req.expires_at && (
                  <p className="text-xs text-orange-400 mt-1">
                    Expires {timeAgo(req.expires_at)} — auto {req.auto_action_on_expiry}
                  </p>
                )}
              </div>
            ))}
            {pending.length === 0 && (
              <div className="text-center text-gray-500 py-12">
                No pending approvals. The system is running autonomously.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export function OrchestratorPage() {
  const { data: graphStatus } = useGraphStatus()

  return (
    <div className="page-content">
      <div className="flex items-center gap-3 mb-4">
        {graphStatus?.graph_compiled ? (
          <Badge className="bg-green-500/20 text-green-400 text-xs">Graph Active</Badge>
        ) : (
          <Badge className="bg-red-500/20 text-red-400 text-xs">Graph Offline</Badge>
        )}
        {graphStatus && (
          <span className="text-xs text-gray-500">
            {graphStatus.available_routes.length} routes | {graphStatus.checkpointer} checkpointer
          </span>
        )}
      </div>

      <Tabs defaultValue="conversations" className="w-full">
        <TabsList className="bg-gray-800/50 border border-gray-700 mb-4">
          <TabsTrigger value="conversations" className="data-[state=active]:bg-gray-700">
            <MessageSquare className="w-4 h-4 mr-1.5" />
            Conversations
          </TabsTrigger>
          <TabsTrigger value="threads" className="data-[state=active]:bg-gray-700">
            <Hash className="w-4 h-4 mr-1.5" />
            Threads
          </TabsTrigger>
          <TabsTrigger value="analytics" className="data-[state=active]:bg-gray-700">
            <BarChart3 className="w-4 h-4 mr-1.5" />
            Route Analytics
          </TabsTrigger>
          <TabsTrigger value="activity" className="data-[state=active]:bg-gray-700">
            <Zap className="w-4 h-4 mr-1.5" />
            Live Activity
          </TabsTrigger>
          <TabsTrigger value="performance" className="data-[state=active]:bg-gray-700">
            <Activity className="w-4 h-4 mr-1.5" />
            Performance
          </TabsTrigger>
          <TabsTrigger value="approvals" className="data-[state=active]:bg-gray-700">
            <ShieldCheck className="w-4 h-4 mr-1.5" />
            Approvals
          </TabsTrigger>
        </TabsList>

        <TabsContent value="conversations">
          <ConversationsTab />
        </TabsContent>
        <TabsContent value="threads">
          <ThreadsTab />
        </TabsContent>
        <TabsContent value="analytics">
          <RouteAnalyticsTab />
        </TabsContent>
        <TabsContent value="activity">
          <ActivityFeedTab />
        </TabsContent>
        <TabsContent value="performance">
          <PerformanceTab />
        </TabsContent>
        <TabsContent value="approvals">
          <ApprovalsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
