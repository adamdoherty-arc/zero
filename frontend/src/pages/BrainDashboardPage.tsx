import { useState } from 'react'
import {
  Brain, Activity, Zap, FlaskConical, BarChart3, Search,
  Loader2, TrendingUp, TrendingDown, Minus, RefreshCw,
  Target, Lightbulb, Clock, FileText, Gavel, CheckCircle2, XCircle,
} from 'lucide-react'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useBrainStatus,
  useBenchmarkHistory,
  useBrainLearnings,
  useCalibrationReport,
  useBrainExperiments,
  useMemorySearch,
  useLearningCycles,
  useTriggerBenchmark,
  useTriggerLearningCycle,
  useTriggerImprovement,
  usePromptRuns,
  usePromptRun,
  usePromptRunStats,
  useTriggerPromptGrading,
  type BrainStatus,
  type BenchmarkSnapshot,
  type CalibrationBucket,
  type PromptRun,
} from '@/hooks/useBrainApi'

// Dimension display config
const DIMENSION_CONFIG: Record<string, { label: string; icon: string }> = {
  content_quality: { label: 'Content Quality', icon: '🎬' },
  learning_velocity: { label: 'Learning Velocity', icon: '🚀' },
  research_depth: { label: 'Research Depth', icon: '🔬' },
  task_execution: { label: 'Task Execution', icon: '✅' },
  system_health: { label: 'System Health', icon: '💚' },
  experiment_rigor: { label: 'Experiment Rigor', icon: '🧪' },
  cost_efficiency: { label: 'Cost Efficiency', icon: '💰' },
  communication_quality: { label: 'Communication', icon: '📣' },
  calibration_accuracy: { label: 'Calibration', icon: '🎯' },
  knowledge_growth: { label: 'Knowledge Growth', icon: '📚' },
}

function getScoreColor(score: number): string {
  if (score >= 80) return 'text-green-400'
  if (score >= 60) return 'text-yellow-400'
  if (score >= 40) return 'text-orange-400'
  return 'text-red-400'
}

function getScoreBg(score: number): string {
  if (score >= 80) return 'bg-green-500/20'
  if (score >= 60) return 'bg-yellow-500/20'
  if (score >= 40) return 'bg-orange-500/20'
  return 'bg-red-500/20'
}

function getGradeLabel(score: number): string {
  if (score >= 90) return 'A'
  if (score >= 80) return 'B'
  if (score >= 70) return 'C'
  if (score >= 60) return 'D'
  return 'F'
}

// ---------------------------------------------------------------------------
// Stats Cards
// ---------------------------------------------------------------------------

function StatsRow({ status }: { status: BrainStatus }) {
  const stats = [
    {
      label: 'Overall Score',
      value: `${status.overall_score.toFixed(1)}`,
      sub: getGradeLabel(status.overall_score),
      icon: Brain,
      color: getScoreColor(status.overall_score),
    },
    {
      label: 'Weakest Dimension',
      value: DIMENSION_CONFIG[status.weakest_dimension]?.label || status.weakest_dimension,
      sub: `${(status.dimension_scores[status.weakest_dimension]?.score ?? 0).toFixed(0)}/100`,
      icon: Target,
      color: 'text-red-400',
    },
    {
      label: 'Episodic Memories',
      value: status.total_memories.toLocaleString(),
      sub: `${status.total_prompt_variants} prompt variants`,
      icon: Lightbulb,
      color: 'text-purple-400',
    },
    {
      label: 'Active Experiments',
      value: status.active_experiments.toString(),
      sub: `${status.total_outcomes} outcomes tracked`,
      icon: FlaskConical,
      color: 'text-blue-400',
    },
  ]

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((s) => (
        <div key={s.label} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <span className="text-gray-400 text-sm">{s.label}</span>
            <s.icon className={`w-5 h-5 ${s.color}`} />
          </div>
          <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
          <div className="text-gray-500 text-xs mt-1">{s.sub}</div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dimension Breakdown
// ---------------------------------------------------------------------------

function DimensionBreakdown({ status, history }: { status: BrainStatus; history: BenchmarkSnapshot[] }) {
  const sorted = Object.entries(status.dimension_scores).sort(
    (a, b) => b[1].score - a[1].score
  )

  // Calculate trends from history
  const getTrend = (dim: string): 'up' | 'down' | 'flat' => {
    if (history.length < 2) return 'flat'
    const recent = history[0]?.dimension_scores?.[dim] ?? 0
    const prev = history[1]?.dimension_scores?.[dim] ?? 0
    if (recent - prev > 2) return 'up'
    if (prev - recent > 2) return 'down'
    return 'flat'
  }

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <BarChart3 className="w-5 h-5 text-indigo-400" />
        Dimension Breakdown
      </h3>
      <div className="space-y-3">
        {sorted.map(([dim, data]) => {
          const config = DIMENSION_CONFIG[dim] || { label: dim, icon: '?' }
          const trend = getTrend(dim)
          return (
            <div key={dim} className="flex items-center gap-3">
              <span className="w-6 text-center">{config.icon}</span>
              <span className="text-gray-300 text-sm w-36 truncate">{config.label}</span>
              <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    data.score >= 80 ? 'bg-green-500' :
                    data.score >= 60 ? 'bg-yellow-500' :
                    data.score >= 40 ? 'bg-orange-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${Math.min(100, data.score)}%` }}
                />
              </div>
              <span className={`text-sm font-mono w-10 text-right ${getScoreColor(data.score)}`}>
                {data.score.toFixed(0)}
              </span>
              <span className="w-5">
                {trend === 'up' && <TrendingUp className="w-4 h-4 text-green-400" />}
                {trend === 'down' && <TrendingDown className="w-4 h-4 text-red-400" />}
                {trend === 'flat' && <Minus className="w-4 h-4 text-gray-500" />}
              </span>
              <span className="text-gray-500 text-xs w-10">
                {(data.weight * 100).toFixed(0)}%
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Score History
// ---------------------------------------------------------------------------

function ScoreHistory({ history }: { history: BenchmarkSnapshot[] }) {
  if (history.length === 0) return null

  const reversed = [...history].reverse()
  const max = Math.max(...reversed.map(h => h.overall_score), 100)
  const min = Math.min(...reversed.map(h => h.overall_score), 0)
  const range = max - min || 1

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Activity className="w-5 h-5 text-green-400" />
        Score History
      </h3>
      <div className="flex items-end gap-1 h-32">
        {reversed.map((snap, i) => {
          const height = ((snap.overall_score - min) / range) * 100
          return (
            <div
              key={i}
              className="flex-1 group relative"
              title={`${snap.overall_score.toFixed(1)} - ${new Date(snap.snapshot_at).toLocaleDateString()}`}
            >
              <div
                className={`w-full rounded-t transition-all ${getScoreBg(snap.overall_score)} border-t-2 ${
                  snap.overall_score >= 80 ? 'border-green-500' :
                  snap.overall_score >= 60 ? 'border-yellow-500' :
                  snap.overall_score >= 40 ? 'border-orange-500' : 'border-red-500'
                }`}
                style={{ height: `${Math.max(4, height)}%` }}
              />
              <div className="hidden group-hover:block absolute bottom-full mb-1 left-1/2 -translate-x-1/2 bg-gray-700 text-white text-xs px-2 py-1 rounded whitespace-nowrap z-10">
                {snap.overall_score.toFixed(1)} - {new Date(snap.snapshot_at).toLocaleDateString()}
              </div>
            </div>
          )
        })}
      </div>
      {reversed.length > 0 && (
        <div className="flex justify-between text-xs text-gray-500 mt-2">
          <span>{new Date(reversed[0].snapshot_at).toLocaleDateString()}</span>
          <span>{new Date(reversed[reversed.length - 1].snapshot_at).toLocaleDateString()}</span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Learnings Feed
// ---------------------------------------------------------------------------

function LearningsFeed({ learnings }: { learnings: string[] }) {
  if (learnings.length === 0) {
    return (
      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
        <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
          <Lightbulb className="w-5 h-5 text-yellow-400" />
          Recent Learnings
        </h3>
        <p className="text-gray-500 text-sm">No learnings recorded yet.</p>
      </div>
    )
  }

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
        <Lightbulb className="w-5 h-5 text-yellow-400" />
        Recent Learnings
      </h3>
      <div className="space-y-2">
        {learnings.map((l, i) => (
          <div key={i} className="text-gray-300 text-sm bg-gray-900 rounded p-2">
            {l}
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Calibration Panel
// ---------------------------------------------------------------------------

function CalibrationPanel({ buckets }: { buckets: CalibrationBucket[] }) {
  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
        <Target className="w-5 h-5 text-indigo-400" />
        Calibration Report
      </h3>
      {buckets.length === 0 ? (
        <p className="text-gray-500 text-sm">No calibration data yet.</p>
      ) : (
        <div className="space-y-2">
          {buckets.map((b) => (
            <div key={b.range_label} className="flex items-center gap-3 text-sm">
              <span className="text-gray-400 w-14 font-mono">{b.range_label}</span>
              <span className="text-gray-500 w-8 text-right">{b.count}</span>
              <div className="flex-1 flex items-center gap-2">
                <span className="text-blue-400">P:{b.avg_predicted.toFixed(0)}</span>
                <span className="text-gray-600">/</span>
                <span className="text-green-400">A:{b.avg_actual.toFixed(0)}</span>
              </div>
              <span className={`font-mono w-16 text-right ${b.mae > 20 ? 'text-red-400' : 'text-green-400'}`}>
                MAE {b.mae.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Experiments Panel
// ---------------------------------------------------------------------------

function ExperimentsPanel() {
  const { data: experiments, isLoading } = useBrainExperiments()

  if (isLoading) return <LoadingSkeleton />

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
        <FlaskConical className="w-5 h-5 text-purple-400" />
        Content Experiments
      </h3>
      {!experiments || experiments.length === 0 ? (
        <p className="text-gray-500 text-sm">No experiments yet.</p>
      ) : (
        <div className="space-y-3">
          {experiments.slice(0, 5).map((exp) => (
            <div key={exp.id} className="bg-gray-900 rounded p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-white text-sm font-medium">{exp.name}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  exp.status === 'active' ? 'bg-blue-500/20 text-blue-400' :
                  exp.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                  'bg-gray-500/20 text-gray-400'
                }`}>
                  {exp.status}
                </span>
              </div>
              <p className="text-gray-400 text-xs">{exp.hypothesis}</p>
              {exp.winner && (
                <p className="text-green-400 text-xs mt-1">Winner: {exp.winner}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Memory Search
// ---------------------------------------------------------------------------

function MemorySearchPanel() {
  const [query, setQuery] = useState('')
  const { data: results, isLoading } = useMemorySearch(query)

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
        <Search className="w-5 h-5 text-cyan-400" />
        Memory Search
      </h3>
      <div className="relative mb-3">
        <input
          type="text"
          placeholder="Search episodic memories..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
        />
        {isLoading && (
          <Loader2 className="absolute right-3 top-2.5 w-4 h-4 text-gray-500 animate-spin" />
        )}
      </div>
      {results && results.length > 0 && (
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {results.map((r) => (
            <div key={r.memory.id} className="bg-gray-900 rounded p-2 text-sm">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400">
                  {r.memory.namespace}
                </span>
                <span className="text-xs text-gray-500">
                  {(r.similarity * 100).toFixed(0)}% match
                </span>
              </div>
              <p className="text-gray-300">{r.memory.content}</p>
            </div>
          ))}
        </div>
      )}
      {query.length >= 2 && results && results.length === 0 && (
        <p className="text-gray-500 text-sm">No matching memories.</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Learning Cycles
// ---------------------------------------------------------------------------

function CyclesPanel() {
  const { data: cycles, isLoading } = useLearningCycles()

  if (isLoading) return <LoadingSkeleton />

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
        <Clock className="w-5 h-5 text-gray-400" />
        Recent Learning Cycles
      </h3>
      {!cycles || cycles.length === 0 ? (
        <p className="text-gray-500 text-sm">No cycles run yet.</p>
      ) : (
        <div className="space-y-2">
          {cycles.slice(0, 5).map((c) => (
            <div key={c.id} className="flex items-center gap-3 text-sm">
              <span className={`w-2 h-2 rounded-full ${
                c.status === 'completed' ? 'bg-green-500' :
                c.status === 'running' ? 'bg-blue-500 animate-pulse' :
                'bg-red-500'
              }`} />
              <span className="text-gray-400 w-24">{c.cycle_type}</span>
              <span className="text-gray-500 flex-1">
                {c.completed_at ? new Date(c.completed_at).toLocaleString() : 'Running...'}
              </span>
              <span className={`${c.status === 'completed' ? 'text-green-400' : 'text-gray-500'}`}>
                {c.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Prompt Runs Panel
// ---------------------------------------------------------------------------

function RunDetailModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { data: run, isLoading } = usePromptRun(runId)

  return (
    <div
      className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-gray-800 rounded-lg border border-gray-700 p-5 w-full max-w-3xl max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-indigo-400" />
            Prompt Run Detail
          </h3>
          <button
            className="text-gray-400 hover:text-white text-sm px-2 py-1 rounded"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        {isLoading || !run ? (
          <LoadingSkeleton />
        ) : (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <div className="text-xs text-gray-500">Task Type</div>
                <div className="text-white font-mono">{run.task_type}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Source</div>
                <div className="text-white font-mono">{run.source}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Provider / Model</div>
                <div className="text-white font-mono">{run.provider} / {run.model}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Latency</div>
                <div className="text-white font-mono">{run.latency_ms.toFixed(0)}ms</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Tokens (in/out)</div>
                <div className="text-white font-mono">{run.prompt_tokens} / {run.completion_tokens}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Cost</div>
                <div className="text-white font-mono">${run.cost_usd.toFixed(4)}</div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Quality</div>
                <div className={`font-mono ${run.quality_score != null ? getScoreColor(run.quality_score) : 'text-gray-500'}`}>
                  {run.quality_score != null ? run.quality_score.toFixed(1) : '—'}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-500">Outcome</div>
                <div className={`font-mono ${run.outcome_score != null ? getScoreColor(run.outcome_score) : 'text-gray-500'}`}>
                  {run.outcome_score != null ? run.outcome_score.toFixed(1) : '—'}
                </div>
              </div>
            </div>
            {run.quality_summary && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Grader Summary</div>
                <div className="bg-gray-900 rounded p-2 text-gray-200">{run.quality_summary}</div>
                {run.quality_flags.length > 0 && (
                  <div className="flex gap-1 flex-wrap mt-2">
                    {run.quality_flags.map((f, i) => (
                      <span key={i} className="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-300">
                        {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
            {run.system_prompt && (
              <div>
                <div className="text-xs text-gray-500 mb-1">System Prompt</div>
                <pre className="bg-gray-900 rounded p-2 text-gray-300 text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {run.system_prompt}
                </pre>
              </div>
            )}
            <div>
              <div className="text-xs text-gray-500 mb-1">User Prompt</div>
              <pre className="bg-gray-900 rounded p-2 text-gray-300 text-xs whitespace-pre-wrap max-h-60 overflow-y-auto">
                {run.user_prompt}
              </pre>
            </div>
            {run.response_text && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Response</div>
                <pre className="bg-gray-900 rounded p-2 text-gray-300 text-xs whitespace-pre-wrap max-h-60 overflow-y-auto">
                  {run.response_text}
                </pre>
              </div>
            )}
            {run.error_message && (
              <div>
                <div className="text-xs text-red-400 mb-1">Error ({run.error_type})</div>
                <pre className="bg-red-900/20 border border-red-800 rounded p-2 text-red-300 text-xs whitespace-pre-wrap max-h-32 overflow-y-auto">
                  {run.error_message}
                </pre>
              </div>
            )}
            <div className="text-xs text-gray-500">
              Created: {new Date(run.created_at).toLocaleString()}
              {run.graded_at && <> · Graded: {new Date(run.graded_at).toLocaleString()}</>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PromptRunsPanel() {
  const [taskTypeFilter, setTaskTypeFilter] = useState<string>('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const { data: stats } = usePromptRunStats()
  const { data: runs, isLoading } = usePromptRuns({
    taskType: taskTypeFilter || undefined,
    limit: 50,
  })
  const gradeMutation = useTriggerPromptGrading()

  const taskTypes = stats?.by_task_type.map((t) => t.task_type) || []

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <FileText className="w-5 h-5 text-indigo-400" />
          Prompt Runs
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={taskTypeFilter}
            onChange={(e) => setTaskTypeFilter(e.target.value)}
            className="bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-indigo-500"
          >
            <option value="">All task types</option>
            {taskTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button
            onClick={() => gradeMutation.mutate(20)}
            disabled={gradeMutation.isPending}
            className="flex items-center gap-2 px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-sm disabled:opacity-50"
          >
            {gradeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gavel className="w-4 h-4" />}
            Grade Pending
          </button>
        </div>
      </div>

      {/* Stats summary */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div className="bg-gray-900 rounded p-3">
            <div className="text-xs text-gray-500">Total Runs</div>
            <div className="text-xl font-bold text-white">{stats.totals.total}</div>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <div className="text-xs text-gray-500">Graded</div>
            <div className="text-xl font-bold text-green-400">{stats.totals.graded}</div>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <div className="text-xs text-gray-500">Ungraded</div>
            <div className="text-xl font-bold text-yellow-400">{stats.totals.ungraded}</div>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <div className="text-xs text-gray-500">Total Cost</div>
            <div className="text-xl font-bold text-white">${stats.totals.total_cost_usd.toFixed(4)}</div>
          </div>
        </div>
      )}

      {/* Per task-type breakdown */}
      {stats && stats.by_task_type.length > 0 && (
        <div className="mb-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-700">
                <th className="text-left py-1 px-2">Task Type</th>
                <th className="text-right py-1 px-2">Runs</th>
                <th className="text-right py-1 px-2">Graded</th>
                <th className="text-right py-1 px-2">Avg Quality</th>
                <th className="text-right py-1 px-2">Avg Outcome</th>
                <th className="text-right py-1 px-2">Avg Latency</th>
                <th className="text-right py-1 px-2">Cost</th>
              </tr>
            </thead>
            <tbody>
              {stats.by_task_type.map((t) => (
                <tr key={t.task_type} className="border-b border-gray-800">
                  <td className="py-1 px-2 text-gray-300 font-mono text-xs">{t.task_type}</td>
                  <td className="py-1 px-2 text-right text-white">{t.total}</td>
                  <td className="py-1 px-2 text-right text-green-400">{t.graded}</td>
                  <td className={`py-1 px-2 text-right font-mono ${t.avg_quality != null ? getScoreColor(t.avg_quality) : 'text-gray-500'}`}>
                    {t.avg_quality != null ? t.avg_quality.toFixed(1) : '—'}
                  </td>
                  <td className={`py-1 px-2 text-right font-mono ${t.avg_outcome != null ? getScoreColor(t.avg_outcome) : 'text-gray-500'}`}>
                    {t.avg_outcome != null ? t.avg_outcome.toFixed(1) : '—'}
                  </td>
                  <td className="py-1 px-2 text-right text-gray-400">
                    {t.avg_latency_ms != null ? `${t.avg_latency_ms.toFixed(0)}ms` : '—'}
                  </td>
                  <td className="py-1 px-2 text-right text-gray-300">${t.total_cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Runs list */}
      {isLoading ? (
        <LoadingSkeleton />
      ) : !runs || runs.length === 0 ? (
        <p className="text-gray-500 text-sm">No prompt runs yet. Run the character content pipeline to see data.</p>
      ) : (
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {runs.map((run: PromptRun) => (
            <button
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
              className="w-full flex items-center gap-2 bg-gray-900 hover:bg-gray-700 rounded p-2 text-left text-sm transition-colors"
            >
              {run.success ? (
                <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
              ) : (
                <XCircle className="w-4 h-4 text-red-400 shrink-0" />
              )}
              <span className="text-xs text-gray-500 w-28 shrink-0">
                {new Date(run.created_at).toLocaleTimeString()}
              </span>
              <span className="text-xs font-mono text-indigo-300 truncate w-56">{run.task_type}</span>
              <span className="text-xs text-gray-500 w-24 truncate">{run.source}</span>
              <span className="text-xs text-gray-400 w-20 truncate">{run.provider}</span>
              <span className="flex-1" />
              {run.quality_score != null && (
                <span className={`text-xs font-mono ${getScoreColor(run.quality_score)}`}>
                  Q:{run.quality_score.toFixed(0)}
                </span>
              )}
              {run.outcome_score != null && (
                <span className={`text-xs font-mono ${getScoreColor(run.outcome_score)}`}>
                  O:{run.outcome_score.toFixed(0)}
                </span>
              )}
              <span className="text-xs text-gray-500 w-16 text-right">{run.latency_ms.toFixed(0)}ms</span>
            </button>
          ))}
        </div>
      )}

      {selectedRunId && (
        <RunDetailModal runId={selectedRunId} onClose={() => setSelectedRunId(null)} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Action Bar
// ---------------------------------------------------------------------------

function ActionBar() {
  const benchmarkMutation = useTriggerBenchmark()
  const cycleMutation = useTriggerLearningCycle()
  const improveMutation = useTriggerImprovement()

  return (
    <div className="flex gap-3 flex-wrap">
      <button
        onClick={() => benchmarkMutation.mutate()}
        disabled={benchmarkMutation.isPending}
        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm disabled:opacity-50 transition-colors"
      >
        {benchmarkMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
        Run Benchmark
      </button>
      <button
        onClick={() => cycleMutation.mutate()}
        disabled={cycleMutation.isPending}
        className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm disabled:opacity-50 transition-colors"
      >
        {cycleMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
        Learning Cycle
      </button>
      <button
        onClick={() => improveMutation.mutate(undefined)}
        disabled={improveMutation.isPending}
        className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm disabled:opacity-50 transition-colors"
      >
        {improveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
        Improve Weakest
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function BrainDashboardPage() {
  const { data: status, isLoading: statusLoading } = useBrainStatus()
  const { data: history } = useBenchmarkHistory()
  const { data: learnings } = useBrainLearnings()
  const { data: calibration } = useCalibrationReport()

  if (statusLoading) return <LoadingSkeleton />

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex justify-end">
        <ActionBar />
      </div>

      {/* Stats Row */}
      {status && <StatsRow status={status} />}

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column */}
        <div className="space-y-6">
          {status && history && (
            <DimensionBreakdown status={status} history={history || []} />
          )}
          <ScoreHistory history={history || []} />
          <CyclesPanel />
        </div>

        {/* Right Column */}
        <div className="space-y-6">
          <LearningsFeed learnings={learnings || []} />
          <CalibrationPanel buckets={calibration?.buckets || []} />
          <ExperimentsPanel />
          <MemorySearchPanel />
        </div>
      </div>

      {/* Full-width Prompt Runs section */}
      <PromptRunsPanel />
    </div>
  )
}
