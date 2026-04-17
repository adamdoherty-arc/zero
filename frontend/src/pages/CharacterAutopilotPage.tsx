import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Compass,
  DollarSign,
  FlaskConical,
  Image as ImageIcon,
  Loader2,
  PowerOff,
  Rocket,
  Search,
  Sparkles,
  Users,
  Wand2,
  Zap,
} from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  type AutopilotJob,
  useAutopilotActions,
  useAutopilotActivity,
  useAutopilotBudget,
  useAutopilotHumanQueue,
  useAutopilotStats,
  useAutopilotToggle,
  useAutopilotTrigger,
} from '@/hooks/useCharacterAutopilotApi'

const JOB_LABELS: Record<AutopilotJob, string> = {
  character_auto_approval: 'Auto-Approval',
  character_publish_backlog: 'Publish Backlog',
  character_gap_audit: 'Gap Audit',
  character_discovery: 'Full Discovery',
  character_discovery_refvideos: 'Ref Video Discovery',
  character_hook_audit: 'Hook Audit',
}

const JOB_ORDER: AutopilotJob[] = [
  'character_auto_approval',
  'character_publish_backlog',
  'character_gap_audit',
  'character_hook_audit',
  'character_discovery',
  'character_discovery_refvideos',
]

function formatDuration(sec?: number | null): string {
  if (sec == null) return '-'
  if (sec < 1) return `${(sec * 1000).toFixed(0)}ms`
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m${s}s`
}

function formatTimestamp(iso?: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString()
}

function statusColor(status: string): string {
  switch (status) {
    case 'success':
      return 'bg-green-500/10 text-green-400 border-green-500/30'
    case 'failed':
    case 'error':
      return 'bg-red-500/10 text-red-400 border-red-500/30'
    case 'running':
      return 'bg-blue-500/10 text-blue-400 border-blue-500/30'
    case 'skipped':
      return 'bg-gray-500/10 text-gray-400 border-gray-500/30'
    default:
      return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30'
  }
}

function tierColor(tier?: string | null): string {
  switch (tier) {
    case 'priority':
      return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
    case 'probation':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/30'
    default:
      return 'bg-slate-500/15 text-slate-300 border-slate-500/30'
  }
}

function sourceColor(source?: string | null): string {
  switch ((source || '').toLowerCase()) {
    case 'wikipedia':
      return 'bg-sky-500/15 text-sky-300 border-sky-500/30'
    case 'tmdb':
      return 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
    case 'reddit':
      return 'bg-orange-500/15 text-orange-300 border-orange-500/30'
    case 'searxng':
      return 'bg-purple-500/15 text-purple-300 border-purple-500/30'
    case 'reference_video':
    case 'tiktok_refvideo':
      return 'bg-pink-500/15 text-pink-300 border-pink-500/30'
    default:
      return 'bg-slate-500/15 text-slate-300 border-slate-500/30'
  }
}

function researchStatusColor(status?: string | null): string {
  switch ((status || '').toLowerCase()) {
    case 'researching':
      return 'bg-blue-500/15 text-blue-300 border-blue-500/30'
    case 'pending':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/30'
    case 'completed':
      return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
    default:
      return 'bg-slate-500/15 text-slate-300 border-slate-500/30'
  }
}

function carouselStatusColor(status: string): string {
  switch (status) {
    case 'approved':
      return 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
    case 'review':
    case 'pending_review':
    case 'ai_reviewed':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/30'
    case 'needs_work':
    case 'rejected':
      return 'bg-red-500/15 text-red-300 border-red-500/30'
    case 'published':
      return 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
    default:
      return 'bg-slate-500/15 text-slate-300 border-slate-500/30'
  }
}

function timeAgo(iso?: string | null): string {
  if (!iso) return '-'
  const d = new Date(iso).getTime()
  const diff = (Date.now() - d) / 1000
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

function InlineError({ error, onRetry, label }: { error: Error | null; onRetry?: () => void; label: string }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center py-8 text-center" aria-live="polite">
      <AlertTriangle className="w-6 h-6 text-red-400 mb-2" aria-hidden="true" />
      <p className="text-sm text-gray-300 mb-1">Failed to load {label}</p>
      <p className="text-xs text-gray-500 mb-3">{error?.message || 'Unknown error'}</p>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded text-white text-xs"
          aria-label={`Retry loading ${label}`}
        >
          Try Again
        </button>
      ) : null}
    </div>
  )
}

export function CharacterAutopilotPage() {
  const stats = useAutopilotStats()
  const actions = useAutopilotActions(20)
  const humanQueue = useAutopilotHumanQueue(20)
  const budget = useAutopilotBudget()
  const activity = useAutopilotActivity(10)
  const toggle = useAutopilotToggle()
  const trigger = useAutopilotTrigger()

  const [activeJob, setActiveJob] = useState<AutopilotJob | null>(null)

  const enabled = stats.data?.autopilot_enabled ?? false

  const minimaxPct = stats.data?.minimax_pct_of_cap ?? 0
  const minimaxBarColor = useMemo(() => {
    if (minimaxPct >= 90) return 'bg-red-500'
    if (minimaxPct >= 60) return 'bg-amber-500'
    return 'bg-emerald-500'
  }, [minimaxPct])

  const onTrigger = async (job: AutopilotJob) => {
    setActiveJob(job)
    try {
      await trigger.mutateAsync(job)
    } finally {
      setActiveJob(null)
    }
  }

  const providerRows = useMemo(() => {
    if (!budget.data?.providers) return []
    return Object.entries(budget.data.providers).sort((a, b) => b[1] - a[1])
  }, [budget.data])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Rocket className="w-6 h-6 text-indigo-400" />
            Character Autopilot
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            24/7 discovery, gap-filling, hook polish, and auto-approval.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge
            variant="outline"
            className={enabled ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' : 'bg-red-500/10 text-red-300 border-red-500/30'}
          >
            {enabled ? 'ENABLED' : 'DISABLED'}
          </Badge>
          <Button
            variant={enabled ? 'destructive' : 'default'}
            size="sm"
            onClick={() => toggle.mutate(!enabled)}
            disabled={toggle.isPending || stats.isLoading}
            aria-label={enabled ? 'Disable autopilot (kill switch)' : 'Enable autopilot'}
          >
            {toggle.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
            ) : enabled ? (
              <PowerOff className="w-4 h-4 mr-2" aria-hidden="true" />
            ) : (
              <Zap className="w-4 h-4 mr-2" aria-hidden="true" />
            )}
            {enabled ? 'Kill Switch' : 'Enable Autopilot'}
          </Button>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          icon={<Users className="w-4 h-4" />}
          label="Characters discovered (24h)"
          value={stats.data?.characters_discovered_24h}
          loading={stats.isLoading}
          sub={stats.data ? `${stats.data.priority_characters} priority, ${stats.data.probation_characters} probation` : undefined}
        />
        <KpiCard
          icon={<CheckCircle2 className="w-4 h-4" />}
          label="Auto-approved (24h)"
          value={stats.data?.carousels_auto_approved_24h}
          loading={stats.isLoading}
          sub={stats.data ? `${stats.data.approved_queued_count} queued to publish` : undefined}
        />
        <KpiCard
          icon={<Wand2 className="w-4 h-4" />}
          label="Gaps filled (24h)"
          value={stats.data?.gaps_filled_24h}
          loading={stats.isLoading}
          sub={stats.data ? `${stats.data.human_review_queue_count} need human review` : undefined}
        />
        <Card className="bg-gray-900 border-gray-700">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <DollarSign className="w-4 h-4" />
                MiniMax today
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            {stats.isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : stats.isError ? (
              <InlineError error={stats.error as Error} onRetry={() => stats.refetch()} label="MiniMax spend" />
            ) : (
              <>
                <div className="text-2xl font-bold">
                  ${stats.data?.minimax_spend_today_usd.toFixed(4) ?? '0.00'}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  of ${stats.data?.minimax_daily_cap_usd.toFixed(2) ?? '0.00'} cap
                </div>
                <div className="w-full bg-gray-800 rounded-full h-1.5 mt-2 overflow-hidden">
                  <div
                    className={`h-full transition-all ${minimaxBarColor}`}
                    style={{ width: `${Math.min(100, minimaxPct)}%` }}
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* What the autopilot is doing right now */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Recently discovered */}
        <Card className="bg-gray-900 border-gray-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Compass className="w-4 h-4 text-sky-400" />
              Recently Discovered
              {activity.data && (
                <Badge variant="outline" className="ml-auto text-xs">
                  {activity.data.counts.total_discovered} total
                </Badge>
              )}
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              New characters autopilot found from Wikipedia, TMDB, Reddit, SearXNG and ref videos.
            </p>
          </CardHeader>
          <CardContent>
            {activity.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : activity.isError ? (
              <InlineError error={activity.error as Error} onRetry={() => activity.refetch()} label="discovery activity" />
            ) : activity.data && activity.data.recently_discovered.length > 0 ? (
              <div className="space-y-1.5 max-h-[360px] overflow-y-auto">
                {activity.data.recently_discovered.map((c) => (
                  <Link
                    key={c.id}
                    to={`/characters/${c.id}`}
                    className="block p-2 rounded border border-gray-800 hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-sm truncate">{c.name}</span>
                          {c.discovery_hits > 1 && (
                            <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-300 border-amber-500/30">
                              x{c.discovery_hits}
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <Badge variant="outline" className={`text-[10px] ${sourceColor(c.discovery_source)}`}>
                            {c.discovery_source || 'unknown'}
                          </Badge>
                          <span className="text-[10px] text-muted-foreground">
                            {c.universe} -  {timeAgo(c.created_at)}
                          </span>
                        </div>
                        {c.evidence_summary && (
                          <div className="text-[11px] text-muted-foreground truncate mt-0.5" title={c.evidence_summary}>
                            {c.evidence_summary}
                          </div>
                        )}
                      </div>
                      <Badge variant="outline" className={`text-[10px] ${researchStatusColor(c.research_status)}`}>
                        {c.research_status || 'new'}
                      </Badge>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No characters discovered yet. Trigger discovery below.</p>
            )}
          </CardContent>
        </Card>

        {/* Currently researching */}
        <Card className="bg-gray-900 border-gray-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Search className="w-4 h-4 text-blue-400" />
              Researching Now
              {activity.data && (
                <Badge variant="outline" className="ml-auto text-xs">
                  {activity.data.counts.total_researching} active
                  {activity.data.counts.total_pending_research > 0 && (
                    <>  -  {activity.data.counts.total_pending_research} queued</>
                  )}
                </Badge>
              )}
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Characters being enriched with facts and images right now.
            </p>
          </CardHeader>
          <CardContent>
            {activity.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : activity.isError ? (
              <InlineError error={activity.error as Error} onRetry={() => activity.refetch()} label="research activity" />
            ) : activity.data && activity.data.currently_researching.length > 0 ? (
              <div className="space-y-1.5 max-h-[360px] overflow-y-auto">
                {activity.data.currently_researching.map((c) => (
                  <Link
                    key={c.id}
                    to={`/characters/${c.id}`}
                    className="block p-2 rounded border border-gray-800 hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-sm truncate">{c.name}</div>
                        <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <FlaskConical className="w-3 h-3" />
                            {c.fact_count} facts
                          </span>
                          <span className="flex items-center gap-1">
                            <ImageIcon className="w-3 h-3" />
                            {c.image_count} imgs
                          </span>
                          <span>depth {c.research_depth_score.toFixed(1)}</span>
                        </div>
                      </div>
                      <Badge variant="outline" className={`text-[10px] ${researchStatusColor(c.research_status)}`}>
                        {c.research_status}
                      </Badge>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Nothing in the research queue.</p>
            )}
          </CardContent>
        </Card>

        {/* Recent carousels being built */}
        <Card className="bg-gray-900 border-gray-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-emerald-400" />
              Latest Carousels
              {activity.data && (
                <Badge variant="outline" className="ml-auto text-xs">
                  {activity.data.counts.total_in_progress_carousels} in progress
                </Badge>
              )}
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Most recent carousels generated and reviewed by autopilot.
            </p>
          </CardHeader>
          <CardContent>
            {activity.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
              </div>
            ) : activity.isError ? (
              <InlineError error={activity.error as Error} onRetry={() => activity.refetch()} label="recent carousels" />
            ) : activity.data && activity.data.recent_carousels.length > 0 ? (
              <div className="space-y-1.5 max-h-[360px] overflow-y-auto">
                {activity.data.recent_carousels.map((c) => (
                  <Link
                    key={c.id}
                    to={`/characters/${c.character_id}?carousel=${c.id}`}
                    className="block p-2 rounded border border-gray-800 hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-sm truncate">{c.character_name || 'Unknown'}</span>
                          {c.auto_approved && (
                            <Badge variant="outline" className="text-[10px] bg-emerald-500/15 text-emerald-300 border-emerald-500/30">
                              AUTO
                            </Badge>
                          )}
                        </div>
                        {c.hook_text && (
                          <div className="text-[11px] text-muted-foreground truncate mt-0.5" title={c.hook_text}>
                            "{c.hook_text}"
                          </div>
                        )}
                        <div className="text-[10px] text-muted-foreground mt-0.5">
                          {c.angle ?? ''} -  {timeAgo(c.created_at)}
                        </div>
                      </div>
                      <div className="text-right">
                        {c.final_review_score != null && (
                          <div className="text-sm font-bold">{c.final_review_score.toFixed(0)}</div>
                        )}
                        <Badge variant="outline" className={`text-[10px] ${carouselStatusColor(c.status)}`}>
                          {c.status}
                        </Badge>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No carousels yet.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Manual trigger grid */}
      <Card className="bg-gray-900 border-gray-700">
        <CardHeader>
          <CardTitle className="text-base">Manual Triggers</CardTitle>
          <p className="text-xs text-muted-foreground">
            Run a job now. Useful when testing and for debugging why the cron didn't produce output.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {JOB_ORDER.map((job) => (
              <Button
                key={job}
                variant="outline"
                size="sm"
                disabled={!enabled || trigger.isPending}
                onClick={() => onTrigger(job)}
                className="justify-start"
                aria-label={`Run ${JOB_LABELS[job]} job now`}
              >
                {activeJob === job && trigger.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                ) : (
                  <ChevronRight className="w-4 h-4 mr-2" aria-hidden="true" />
                )}
                {JOB_LABELS[job]}
              </Button>
            ))}
          </div>
          {!enabled && (
            <div className="flex items-center gap-2 mt-4 text-xs text-amber-400">
              <AlertTriangle className="w-3 h-3" />
              Autopilot is disabled. Enable it to run jobs.
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent actions */}
        <Card className="bg-gray-900 border-gray-700">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="w-4 h-4" />
              Recent Autopilot Actions
            </CardTitle>
          </CardHeader>
          <CardContent>
            {actions.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : actions.isError ? (
              <InlineError error={actions.error as Error} onRetry={() => actions.refetch()} label="autopilot actions" />
            ) : actions.data && actions.data.length > 0 ? (
              <div className="space-y-1.5 max-h-[480px] overflow-y-auto">
                {actions.data.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between text-xs p-2 rounded border border-gray-800 hover:bg-gray-800/50"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{a.job_name}</div>
                      <div className="text-muted-foreground">
                        {formatTimestamp(a.started_at)} -  {formatDuration(a.duration_seconds)}
                      </div>
                      {a.error && (
                        <div className="text-red-400 mt-0.5 truncate" title={a.error}>
                          {a.error}
                        </div>
                      )}
                    </div>
                    <Badge variant="outline" className={statusColor(a.status)}>
                      {a.status}
                    </Badge>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No autopilot runs yet.</p>
            )}
          </CardContent>
        </Card>

        {/* Human review queue */}
        <Card className="bg-gray-900 border-gray-700">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              Human Review Queue
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Carousels scoring 75-84 that need a human decision. Priority tier first.
            </p>
          </CardHeader>
          <CardContent>
            {humanQueue.isLoading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : humanQueue.isError ? (
              <InlineError error={humanQueue.error as Error} onRetry={() => humanQueue.refetch()} label="human review queue" />
            ) : humanQueue.data && humanQueue.data.length > 0 ? (
              <div className="space-y-2 max-h-[480px] overflow-y-auto">
                {humanQueue.data.map((item) => (
                  <Link
                    key={item.carousel_id}
                    to={`/characters/${item.character_id}?carousel=${item.carousel_id}`}
                    className="block p-2 rounded border border-gray-800 hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm truncate">{item.character_name || 'Unknown'}</span>
                          <Badge variant="outline" className={tierColor(item.priority_tier)}>
                            {item.priority_tier ?? 'standard'}
                          </Badge>
                        </div>
                        {item.hook_text && (
                          <div className="text-xs text-muted-foreground truncate mt-0.5">
                            "{item.hook_text}"
                          </div>
                        )}
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-bold text-amber-300">
                          {item.final_review_score?.toFixed(0) ?? '-'}
                        </div>
                        <div className="text-xs text-muted-foreground">{item.angle ?? ''}</div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No carousels pending human review.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Provider budget table */}
      <Card className="bg-gray-900 border-gray-700">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <DollarSign className="w-4 h-4" />
            Provider Budget (today)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {budget.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : budget.isError ? (
            <InlineError error={budget.error as Error} onRetry={() => budget.refetch()} label="provider budget" />
          ) : providerRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">No LLM spend recorded today.</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {providerRows.map(([provider, spend]) => (
                <div key={provider} className="p-3 rounded border border-gray-800 bg-gray-950/50">
                  <div className="text-xs text-muted-foreground uppercase">{provider}</div>
                  <div className="text-lg font-bold mt-1">${spend.toFixed(4)}</div>
                  {provider === 'minimax' && budget.data && (
                    <div className={`text-xs mt-1 ${budget.data.minimax.exceeded ? 'text-red-400' : 'text-muted-foreground'}`}>
                      {budget.data.minimax.pct_of_cap.toFixed(0)}% of cap
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

interface KpiCardProps {
  icon: React.ReactNode
  label: string
  value?: number
  sub?: string
  loading: boolean
}

function KpiCard({ icon, label, value, sub, loading }: KpiCardProps) {
  return (
    <Card className="bg-gray-900 border-gray-700">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          {icon}
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <>
            <div className="text-2xl font-bold">{value ?? 0}</div>
            {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export default CharacterAutopilotPage
