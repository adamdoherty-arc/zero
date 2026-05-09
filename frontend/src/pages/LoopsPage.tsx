import { useState } from 'react'
import {
  Play, Clock, CheckCircle, XCircle, Loader2,
  Pause, AlertTriangle, ChevronRight, ChevronDown, Zap,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useLoops, useLoop, useLoopRuns, useLoopVariants,
  useEnableLoop, useTriggerLoop,
  type Loop, type LoopRun,
} from '@/hooks/useLoopsApi'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-500/20 text-blue-400',
  success: 'bg-green-500/20 text-green-400',
  failure: 'bg-red-500/20 text-red-400',
  timeout: 'bg-orange-500/20 text-orange-400',
  budget_paused: 'bg-amber-500/20 text-amber-400',
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  running: <Loader2 className="w-3.5 h-3.5 animate-spin" />,
  success: <CheckCircle className="w-3.5 h-3.5" />,
  failure: <XCircle className="w-3.5 h-3.5" />,
  timeout: <Clock className="w-3.5 h-3.5" />,
  budget_paused: <AlertTriangle className="w-3.5 h-3.5" />,
}

const PROJECT_COLORS: Record<string, string> = {
  zero: 'bg-indigo-500/20 text-indigo-400',
  legion: 'bg-purple-500/20 text-purple-400',
  ada: 'bg-cyan-500/20 text-cyan-400',
}

const RUNNER_COLORS: Record<string, string> = {
  claude_skill: 'bg-amber-500/20 text-amber-400',
  opencode: 'bg-emerald-500/20 text-emerald-400',
  http: 'bg-sky-500/20 text-sky-400',
  prompt_variant: 'bg-pink-500/20 text-pink-400',
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 0) return 'soon'
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function timeUntil(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const diff = new Date(dateStr).getTime() - Date.now()
  if (diff < 0) return 'now'
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s`
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h`
  return `${Math.floor(diff / 86_400_000)}d`
}

function formatScore(score?: number | null): string {
  if (score == null) return '—'
  return score.toFixed(1)
}

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

type DetailTab = 'runs' | 'variants' | 'config'

function LoopDetail({ loopId, onClose }: { loopId: number; onClose: () => void }) {
  const [tab, setTab] = useState<DetailTab>('runs')
  const { data: loop } = useLoop(loopId)
  const { data: runs, isLoading: runsLoading } = useLoopRuns(loopId, 100)
  const { data: variants } = useLoopVariants(loopId)
  const triggerLoop = useTriggerLoop()
  const enableLoop = useEnableLoop()

  if (!loop) return <LoadingSkeleton />

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-lg font-semibold text-zinc-100">{loop.name}</h2>
            <Badge className={PROJECT_COLORS[loop.owner_project]}>{loop.owner_project}</Badge>
            <Badge className={RUNNER_COLORS[loop.runner_kind]}>{loop.runner_kind}</Badge>
            {loop.enabled ? (
              <Badge className="bg-green-500/20 text-green-400">enabled</Badge>
            ) : (
              <Badge className="bg-zinc-700 text-zinc-400">disabled</Badge>
            )}
          </div>
          {loop.description && <p className="text-sm text-zinc-400">{loop.description}</p>}
          <div className="text-xs text-zinc-500 mt-2 font-mono">
            cron: <span className="text-zinc-300">{loop.cron}</span> ·
            target: <span className="text-zinc-300">{loop.runner_target}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => triggerLoop.mutate(loopId)}
            disabled={triggerLoop.isPending}
            className="text-xs px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-zinc-700 text-white rounded-md flex items-center gap-1.5"
          >
            {triggerLoop.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            Trigger now
          </button>
          <button
            onClick={() => enableLoop.mutate({ loopId, enabled: !loop.enabled })}
            disabled={enableLoop.isPending}
            className="text-xs px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded-md flex items-center gap-1.5"
          >
            {loop.enabled ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            {loop.enabled ? 'Disable' : 'Enable'}
          </button>
          <button
            onClick={onClose}
            className="text-xs px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded-md"
          >
            Close
          </button>
        </div>
      </div>

      <div className="flex gap-2 border-b border-zinc-800 mb-4">
        {(['runs', 'variants', 'config'] as DetailTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              tab === t
                ? 'border-indigo-500 text-indigo-300'
                : 'border-transparent text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {t === 'runs' && `Runs ${runs ? `(${runs.length})` : ''}`}
            {t === 'variants' && `Variants ${variants ? `(${variants.length})` : ''}`}
            {t === 'config' && 'Config'}
          </button>
        ))}
      </div>

      {tab === 'runs' && (
        <div className="space-y-2 max-h-[600px] overflow-y-auto">
          {runsLoading && <LoadingSkeleton />}
          {!runsLoading && runs && runs.length === 0 && (
            <p className="text-sm text-zinc-500 text-center py-8">
              No runs yet. Click "Trigger now" to dispatch one manually.
            </p>
          )}
          {runs?.map((run) => <RunRow key={run.id} run={run} />)}
        </div>
      )}

      {tab === 'variants' && (
        <div className="space-y-2 max-h-[600px] overflow-y-auto">
          {variants && variants.length === 0 && (
            <p className="text-sm text-zinc-500 text-center py-8">
              No variants yet. Variants are created by the prompt-evolution loop (P2).
            </p>
          )}
          {variants?.map((v) => (
            <div key={v.id} className="bg-zinc-800/50 border border-zinc-800 rounded-md p-3">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-mono text-zinc-200">{v.variant_label}</span>
                  {v.is_active && <Badge className="bg-green-500/20 text-green-400">active</Badge>}
                  {v.is_canary && <Badge className="bg-blue-500/20 text-blue-400">canary {v.canary_traffic_pct}%</Badge>}
                  {v.retired_at && <Badge className="bg-zinc-700 text-zinc-400">retired</Badge>}
                </div>
                <span className="text-xs text-zinc-500">
                  {v.runs_count} runs · {v.success_rate != null ? `${(v.success_rate * 100).toFixed(0)}% ok` : '—'} · score {formatScore(v.avg_score)}
                </span>
              </div>
              <pre className="text-xs text-zinc-500 font-mono whitespace-pre-wrap line-clamp-3 mt-1">{v.payload.slice(0, 400)}{v.payload.length > 400 ? '…' : ''}</pre>
            </div>
          ))}
        </div>
      )}

      {tab === 'config' && (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <ConfigRow label="Sandbox required" value={String(loop.sandbox_required)} />
          <ConfigRow label="Judge tier" value={loop.judge_tier} />
          <ConfigRow label="Auto-promote" value={String(loop.auto_promote_enabled)} />
          <ConfigRow label="Daily token budget" value={loop.daily_token_budget.toLocaleString()} />
          <ConfigRow label="Daily run cap" value={String(loop.daily_run_cap)} />
          <ConfigRow label="Wall-clock budget" value={`${loop.wall_clock_budget_s}s`} />
          <ConfigRow label="Baseline score" value={formatScore(loop.baseline_score)} />
          <ConfigRow label="Consecutive regressions" value={String(loop.consecutive_regressions)} />
          <ConfigRow label="Last run" value={timeAgo(loop.last_run_at)} />
          <ConfigRow label="Next due" value={loop.next_due_at ? `in ${timeUntil(loop.next_due_at)}` : '—'} />
        </div>
      )}
    </div>
  )
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-zinc-800/40 px-3 py-2 rounded-md">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-sm text-zinc-200 font-mono">{value}</div>
    </div>
  )
}

function RunRow({ run }: { run: LoopRun }) {
  const [expanded, setExpanded] = useState(false)
  const status = run.status
  return (
    <div className="bg-zinc-800/50 border border-zinc-800 rounded-md">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-zinc-800/80"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown className="w-3.5 h-3.5 text-zinc-500" /> : <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />}
          <Badge className={STATUS_COLORS[status] || 'bg-zinc-700 text-zinc-300'}>
            <span className="flex items-center gap-1">
              {STATUS_ICONS[status]}
              {status}
            </span>
          </Badge>
          <span className="text-xs text-zinc-300 font-mono">#{run.id}</span>
          {run.judge_score != null && (
            <span className="text-xs text-zinc-400">score {formatScore(run.judge_score)}</span>
          )}
          {run.duration_s != null && (
            <span className="text-xs text-zinc-500">{run.duration_s.toFixed(1)}s</span>
          )}
        </div>
        <span className="text-xs text-zinc-500">{timeAgo(run.started_at)}</span>
      </button>
      {expanded && (
        <div className="px-3 py-2 border-t border-zinc-800 text-xs space-y-2">
          {run.error && (
            <div>
              <div className="text-red-400 mb-1">Error</div>
              <pre className="bg-zinc-900 p-2 rounded text-zinc-300 whitespace-pre-wrap">{run.error}</pre>
            </div>
          )}
          {run.judge_notes && (
            <div>
              <div className="text-indigo-400 mb-1">Judge notes</div>
              <pre className="bg-zinc-900 p-2 rounded text-zinc-300 whitespace-pre-wrap">{run.judge_notes}</pre>
            </div>
          )}
          {run.output && (
            <div>
              <div className="text-zinc-400 mb-1">Output</div>
              <pre className="bg-zinc-900 p-2 rounded text-zinc-300 whitespace-pre-wrap max-h-64 overflow-y-auto">{run.output}</pre>
            </div>
          )}
          {run.vault_path && (
            <div className="text-zinc-500">
              vault: <span className="text-zinc-300 font-mono">{run.vault_path}</span>
            </div>
          )}
          <div className="text-zinc-500">
            runner: <span className="text-zinc-300">{run.runner_kind}</span>
            {run.runner_id && <> · <span className="text-zinc-300 font-mono">{run.runner_id}</span></>}
            {run.cost_tokens != null && <> · {run.cost_tokens.toLocaleString()} tok</>}
            {run.legion_run_id && <> · legion#{run.legion_run_id}</>}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Registry Table Row
// ---------------------------------------------------------------------------

function LoopRow({ loop, onSelect, selected }: { loop: Loop; onSelect: () => void; selected: boolean }) {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left px-3 py-2.5 rounded-md transition-colors flex items-center justify-between gap-3 ${
        selected ? 'bg-indigo-500/10 ring-1 ring-indigo-500/40' : 'hover:bg-zinc-800/60'
      }`}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className={`w-2 h-2 rounded-full shrink-0 ${loop.enabled ? 'bg-green-400' : 'bg-zinc-600'}`} />
        <span className="text-sm font-mono text-zinc-100 truncate">{loop.name}</span>
        <Badge className={`${PROJECT_COLORS[loop.owner_project]} shrink-0`}>{loop.owner_project}</Badge>
        <Badge className={`${RUNNER_COLORS[loop.runner_kind]} shrink-0`}>{loop.runner_kind}</Badge>
      </div>
      <div className="flex items-center gap-3 text-xs text-zinc-400 shrink-0">
        <span className="font-mono">{loop.cron}</span>
        <span>last: {timeAgo(loop.last_run_at)}</span>
        <span>next: {loop.enabled ? timeUntil(loop.next_due_at) : '—'}</span>
        <ChevronRight className="w-3.5 h-3.5 text-zinc-600" />
      </div>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function LoopsPage() {
  const [filter, setFilter] = useState<'all' | 'zero' | 'legion' | 'ada' | 'enabled'>('all')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const filters = filter === 'all' ? undefined :
    filter === 'enabled' ? { enabled_only: true } :
    { owner_project: filter }

  const { data: loops, isLoading } = useLoops(filters)

  const summary = (() => {
    if (!loops) return null
    const total = loops.length
    const enabled = loops.filter((l) => l.enabled).length
    const byProject = {
      zero: loops.filter((l) => l.owner_project === 'zero').length,
      legion: loops.filter((l) => l.owner_project === 'legion').length,
      ada: loops.filter((l) => l.owner_project === 'ada').length,
    }
    return { total, enabled, byProject }
  })()

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
          <Zap className="w-6 h-6 text-indigo-400" />
          Loops
        </h1>
        <p className="text-sm text-zinc-400 mt-1">
          24/7 self-improvement loops across ADA · Legion · Zero. Karpathy autoresearch pattern: small scope,
          fixed budget, one metric, keep winners, roll back losers.
        </p>
      </div>

      {summary && (
        <div className="grid grid-cols-5 gap-3 mb-6">
          <SummaryCard label="Total loops" value={summary.total} />
          <SummaryCard label="Enabled" value={summary.enabled} accent="green" />
          <SummaryCard label="Zero" value={summary.byProject.zero} accent="indigo" />
          <SummaryCard label="Legion" value={summary.byProject.legion} accent="purple" />
          <SummaryCard label="ADA" value={summary.byProject.ada} accent="cyan" />
        </div>
      )}

      <div className="flex gap-2 mb-4">
        {(['all', 'enabled', 'zero', 'legion', 'ada'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
              filter === f
                ? 'bg-indigo-500/20 text-indigo-300 ring-1 ring-indigo-500/40'
                : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className={selectedId ? 'col-span-5' : 'col-span-12'}>
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
            {isLoading && <LoadingSkeleton />}
            {!isLoading && loops && loops.length === 0 && (
              <p className="text-sm text-zinc-500 text-center py-8">
                No loops in registry. Seed via <span className="font-mono text-zinc-300">scripts/seed_loops.py</span>.
              </p>
            )}
            <div className="space-y-1">
              {loops?.map((loop) => (
                <LoopRow
                  key={loop.id}
                  loop={loop}
                  selected={selectedId === loop.id}
                  onSelect={() => setSelectedId(loop.id === selectedId ? null : loop.id)}
                />
              ))}
            </div>
          </div>
        </div>
        {selectedId && (
          <div className="col-span-7">
            <LoopDetail loopId={selectedId} onClose={() => setSelectedId(null)} />
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  accent = 'zinc',
}: {
  label: string
  value: number
  accent?: 'zinc' | 'green' | 'indigo' | 'purple' | 'cyan'
}) {
  const colors: Record<string, string> = {
    zinc: 'text-zinc-200',
    green: 'text-green-400',
    indigo: 'text-indigo-400',
    purple: 'text-purple-400',
    cyan: 'text-cyan-400',
  }
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`text-2xl font-semibold ${colors[accent]} mt-1`}>{value}</div>
    </div>
  )
}

export default LoopsPage
