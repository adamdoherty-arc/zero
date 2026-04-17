import { useState } from 'react'
import {
  FlaskConical, Play, Clock, CheckCircle, XCircle, Loader2,
  Plus, FileText, DollarSign, Lightbulb, ChevronDown, ChevronRight,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useExperiments, useExperiment, useDesignExperiment, useRunExperiment,
  type Experiment,
} from '@/hooks/useExperimentApi'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  designed: 'bg-indigo-500/20 text-indigo-400',
  running: 'bg-blue-500/20 text-blue-400',
  completed: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  designed: <Lightbulb className="w-3.5 h-3.5" />,
  running: <Loader2 className="w-3.5 h-3.5 animate-spin" />,
  completed: <CheckCircle className="w-3.5 h-3.5" />,
  failed: <XCircle className="w-3.5 h-3.5" />,
}

const TYPE_COLORS: Record<string, string> = {
  benchmark: 'bg-purple-500/20 text-purple-400',
  validation: 'bg-cyan-500/20 text-cyan-400',
  ab_test: 'bg-orange-500/20 text-orange-400',
  prototype: 'bg-pink-500/20 text-pink-400',
}

const EXPERIMENT_TYPES = ['benchmark', 'validation', 'ab_test', 'prototype'] as const

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function formatCost(cost?: number | null): string {
  if (cost == null) return '-'
  return `$${cost.toFixed(2)}`
}

// ---------------------------------------------------------------------------
// Design Form
// ---------------------------------------------------------------------------

function DesignForm() {
  const [hypothesis, setHypothesis] = useState('')
  const [type, setType] = useState<string>('')
  const design = useDesignExperiment()

  const handleSubmit = () => {
    if (!hypothesis.trim()) return
    design.mutate(
      { hypothesis: hypothesis.trim(), experiment_type: type || undefined },
      { onSuccess: () => { setHypothesis(''); setType('') } },
    )
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
      <h2 className="text-sm font-semibold text-zinc-300 mb-3 flex items-center gap-2">
        <Plus className="w-4 h-4 text-indigo-400" />
        Design New Experiment
      </h2>
      <textarea
        value={hypothesis}
        onChange={e => setHypothesis(e.target.value)}
        placeholder="Describe your hypothesis... e.g. 'Using Kimi K2.5 for email classification will improve accuracy by 15% over the current Ollama model'"
        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
        rows={3}
      />
      <div className="flex items-center gap-3 mt-3">
        <select
          value={type}
          onChange={e => setType(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">Type (optional)</option>
          {EXPERIMENT_TYPES.map(t => (
            <option key={t} value={t}>{t.replace('_', ' ')}</option>
          ))}
        </select>
        <button
          onClick={handleSubmit}
          disabled={!hypothesis.trim() || design.isPending}
          className="ml-auto flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          {design.isPending
            ? <Loader2 className="w-4 h-4 animate-spin" />
            : <FlaskConical className="w-4 h-4" />}
          Design
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Experiment Card
// ---------------------------------------------------------------------------

function ExperimentCard({ experiment }: { experiment: Experiment }) {
  const [expanded, setExpanded] = useState(false)
  const detail = useExperiment(expanded ? experiment.id : '')
  const run = useRunExperiment()
  const exp = detail.data ?? experiment

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-start gap-3 p-4 text-left hover:bg-zinc-800/50 transition-colors"
      >
        <div className="pt-0.5 text-zinc-500">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-zinc-200 truncate">
              {exp.title || `Experiment #${exp.id}`}
            </span>
            <Badge className={STATUS_COLORS[exp.status] ?? 'bg-zinc-700 text-zinc-300'}>
              <span className="flex items-center gap-1">
                {STATUS_ICONS[exp.status]}
                {exp.status}
              </span>
            </Badge>
            {exp.experiment_type && (
              <Badge className={TYPE_COLORS[exp.experiment_type] ?? 'bg-zinc-700 text-zinc-300'}>
                {exp.experiment_type.replace('_', ' ')}
              </Badge>
            )}
          </div>
          <p className="text-xs text-zinc-500 mt-1 line-clamp-2">{exp.hypothesis}</p>
          <div className="flex items-center gap-4 mt-2 text-xs text-zinc-500">
            {exp.created_at && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {timeAgo(exp.created_at)}
              </span>
            )}
            {exp.cost_usd != null && (
              <span className="flex items-center gap-1">
                <DollarSign className="w-3 h-3" />
                {formatCost(exp.cost_usd)}
              </span>
            )}
          </div>
        </div>
        {exp.status === 'designed' && (
          <button
            onClick={e => { e.stopPropagation(); run.mutate(exp.id) }}
            disabled={run.isPending}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-md transition-colors shrink-0"
          >
            {run.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            Run
          </button>
        )}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-zinc-800 p-4 space-y-4 text-sm">
          {detail.isLoading && <LoadingSkeleton variant="inline" message="Loading details..." />}

          {exp.methodology && (
            <div>
              <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                <FileText className="w-3 h-3" /> Methodology
              </h4>
              <p className="text-zinc-300 whitespace-pre-wrap">{exp.methodology}</p>
            </div>
          )}

          {exp.results && Object.keys(exp.results).length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                <FileText className="w-3 h-3" /> Results
              </h4>
              <pre className="text-zinc-300 whitespace-pre-wrap text-xs bg-zinc-800 rounded p-2">{JSON.stringify(exp.results, null, 2)}</pre>
            </div>
          )}

          {exp.conclusion && (
            <div>
              <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                <Lightbulb className="w-3 h-3" /> Conclusion
              </h4>
              <p className="text-zinc-300 whitespace-pre-wrap">{exp.conclusion}</p>
            </div>
          )}

          {!detail.isLoading && !exp.methodology && !exp.results && !exp.conclusion && (
            <p className="text-zinc-500 text-xs italic">No detailed results yet.</p>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function ExperimentLabPage() {
  const experiments = useExperiments()

  return (
    <div className="space-y-6">
      {/* Experiment count */}
      {experiments.data && (
        <div className="flex items-center justify-end">
          <div className="text-xs text-zinc-500">
            {experiments.data.length} experiment{experiments.data.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}

      {/* Design form */}
      <DesignForm />

      {/* Experiments list */}
      {experiments.isLoading ? (
        <LoadingSkeleton variant="cards" count={4} message="Loading experiments..." />
      ) : experiments.data && experiments.data.length > 0 ? (
        <div className="space-y-3">
          {experiments.data.map(exp => (
            <ExperimentCard key={exp.id} experiment={exp} />
          ))}
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-12 text-center">
          <FlaskConical className="w-10 h-10 text-zinc-700 mx-auto mb-3" />
          <p className="text-zinc-400 text-sm">No experiments yet</p>
          <p className="text-zinc-600 text-xs mt-1">Design your first experiment above</p>
        </div>
      )}
    </div>
  )
}
