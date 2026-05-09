import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Brain,
  Clock,
  Save,
  ChevronRight,
  ChevronDown,
  CheckCircle,
  XCircle,
  Loader2,
  AlertTriangle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useSkill,
  useSkillRuns,
  usePatchSkill,
  type Skill,
  type SkillRun,
  type SkillPatch,
} from '@/hooks/useSkillsApi'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROJECT_COLORS: Record<string, string> = {
  zero: 'bg-indigo-500/20 text-indigo-400',
  legion: 'bg-purple-500/20 text-purple-400',
  ada: 'bg-cyan-500/20 text-cyan-400',
  llmrouter: 'bg-teal-500/20 text-teal-400',
  global: 'bg-amber-500/20 text-amber-400',
}

const CATEGORY_COLORS: Record<string, string> = {
  review: 'bg-rose-500/20 text-rose-300',
  audit: 'bg-orange-500/20 text-orange-300',
  build: 'bg-sky-500/20 text-sky-300',
  ops: 'bg-emerald-500/20 text-emerald-300',
  meta: 'bg-violet-500/20 text-violet-300',
}

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

type Tab = 'overview' | 'runs' | 'schedule'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(dateStr?: string | null): string {
  if (!dateStr) return 'never'
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 0) return 'soon'
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function scoreColor(score?: number | null): string {
  if (score == null) return 'text-zinc-500'
  if (score >= 80) return 'text-green-400'
  if (score >= 60) return 'text-amber-400'
  return 'text-red-400'
}

// VS Code deep link from absolute path. Container paths get a best-effort host translation.
function vscodeLink(p: string): string {
  let host = p
  if (host.startsWith('/global-skills'))
    host = host.replace('/global-skills', 'C:/Users/hadam/.claude/skills')
  else if (host.startsWith('/managed/zero')) host = host.replace('/managed/zero', 'C:/code/zero')
  else if (host.startsWith('/managed/ada')) host = host.replace('/managed/ada', 'C:/code/ADA')
  else if (host.startsWith('/managed/legion'))
    host = host.replace('/managed/legion', 'C:/code/Legion')
  else if (host.startsWith('/managed/llmrouter'))
    host = host.replace('/managed/llmrouter', 'C:/code/LLMRouter')
  else if (host.startsWith('/app/workspace'))
    host = host.replace('/app/workspace', 'C:/code/Legion')
  return `vscode://file/${host}`
}

// ---------------------------------------------------------------------------
// Run Row
// ---------------------------------------------------------------------------

function RunRow({ run }: { run: SkillRun }) {
  const [expanded, setExpanded] = useState(false)
  const status = run.status
  return (
    <div className="bg-zinc-800/50 border border-zinc-800 rounded-md">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-zinc-800/80"
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-zinc-500" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />
          )}
          <Badge className={STATUS_COLORS[status] || 'bg-zinc-700 text-zinc-300'}>
            <span className="flex items-center gap-1">
              {STATUS_ICONS[status]}
              {status}
            </span>
          </Badge>
          <span className="text-xs text-zinc-300 font-mono">#{run.id}</span>
          {run.judge_score != null && (
            <span className={`text-xs ${scoreColor(run.judge_score)}`}>
              score {run.judge_score.toFixed(1)}
            </span>
          )}
          {run.duration_s != null && (
            <span className="text-xs text-zinc-500">{run.duration_s.toFixed(1)}s</span>
          )}
          {run.cost_tokens != null && (
            <span className="text-xs text-zinc-500">{run.cost_tokens.toLocaleString()} tok</span>
          )}
        </div>
        <span className="text-xs text-zinc-500">{timeAgo(run.received_at)}</span>
      </button>
      {expanded && (
        <div className="px-3 py-2 border-t border-zinc-800 text-xs space-y-2">
          {run.vault_path && (
            <div className="text-zinc-500">
              vault: <span className="text-zinc-300 font-mono">{run.vault_path}</span>
            </div>
          )}
          {run.variant_label && (
            <div className="text-zinc-500">
              variant: <span className="text-zinc-300 font-mono">{run.variant_label}</span>
            </div>
          )}
          {run.payload && Object.keys(run.payload).length > 0 && (
            <div>
              <div className="text-indigo-400 mb-1">Payload</div>
              <pre className="bg-zinc-900 p-2 rounded text-zinc-300 whitespace-pre-wrap max-h-64 overflow-y-auto">
                {JSON.stringify(run.payload, null, 2)}
              </pre>
            </div>
          )}
          <div className="text-zinc-500">
            zero_run_id: <span className="text-zinc-300">#{run.zero_run_id}</span> · loop:{' '}
            <span className="text-zinc-300">{run.loop_name}</span> · owner:{' '}
            <span className="text-zinc-300">{run.owner_project}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Schedule Tab
// ---------------------------------------------------------------------------

function ScheduleTab({ skill }: { skill: Skill }) {
  const patch = usePatchSkill()
  const [form, setForm] = useState<SkillPatch>({
    cron: skill.cron,
    judge_tier: skill.judge_tier,
    daily_token_budget: skill.daily_token_budget,
    wallclock_budget_s: skill.wallclock_budget_s,
    auto_promote: skill.auto_promote,
    enabled: skill.enabled,
  })
  const [saved, setSaved] = useState(false)

  const submit = () => {
    patch.mutate(
      { name: skill.name, patch: form },
      {
        onSuccess: () => {
          setSaved(true)
          setTimeout(() => setSaved(false), 2500)
        },
      },
    )
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Cron expression">
          <input
            type="text"
            value={form.cron ?? ''}
            onChange={(e) => setForm({ ...form, cron: e.target.value })}
            placeholder="0 */4 * * *"
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 font-mono focus:outline-none focus:border-indigo-500/40 focus:ring-1 focus:ring-indigo-500/40"
          />
        </Field>
        <Field label="Judge tier">
          <select
            value={form.judge_tier ?? 'local'}
            onChange={(e) =>
              setForm({ ...form, judge_tier: e.target.value as 'local' | 'none' })
            }
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 focus:outline-none focus:border-indigo-500/40"
          >
            <option value="local">local</option>
            <option value="none">none</option>
          </select>
        </Field>
        <Field label="Daily token budget">
          <input
            type="number"
            value={form.daily_token_budget ?? 0}
            onChange={(e) =>
              setForm({ ...form, daily_token_budget: Number(e.target.value) })
            }
            min={0}
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 font-mono focus:outline-none focus:border-indigo-500/40"
          />
        </Field>
        <Field label="Wall-clock budget (s)">
          <input
            type="number"
            value={form.wallclock_budget_s ?? 0}
            onChange={(e) =>
              setForm({ ...form, wallclock_budget_s: Number(e.target.value) })
            }
            min={10}
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 font-mono focus:outline-none focus:border-indigo-500/40"
          />
        </Field>
      </div>
      <div className="flex items-center gap-6">
        <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
          <input
            type="checkbox"
            checked={form.enabled ?? true}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
            className="rounded border-zinc-700 bg-zinc-800"
          />
          Enabled
        </label>
        <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
          <input
            type="checkbox"
            checked={form.auto_promote ?? true}
            onChange={(e) => setForm({ ...form, auto_promote: e.target.checked })}
            className="rounded border-zinc-700 bg-zinc-800"
          />
          Auto-promote
        </label>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={submit}
          disabled={patch.isPending}
          className="text-xs px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-zinc-700 text-white rounded-md flex items-center gap-1.5"
        >
          {patch.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Save className="w-3.5 h-3.5" />
          )}
          Save
        </button>
        {saved && <span className="text-xs text-green-400">Saved · propagated to /loops</span>}
        {patch.isError && (
          <span className="text-xs text-red-400">
            Failed: {(patch.error as Error)?.message ?? 'unknown'}
          </span>
        )}
      </div>
      <p className="text-xs text-zinc-500 mt-4">
        Saving writes to Legion's canonical registry and propagates cron/enabled/budget changes
        to Zero's loops table so the local scheduler reflects the change immediately. The
        SKILL.md frontmatter on disk is <strong>not</strong> rewritten — file is the source of
        truth for the prompt body, DB is the source of truth for orchestration.
      </p>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-zinc-500 mb-1">{label}</label>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({ skill }: { skill: Skill }) {
  return (
    <div className="space-y-5">
      <p className="text-sm text-zinc-300 leading-relaxed">{skill.description}</p>

      <div className="grid grid-cols-3 gap-3">
        <StatBox label="Run count" value={skill.run_count.toLocaleString()} />
        <StatBox
          label="Success rate"
          value={
            skill.run_count > 0
              ? `${((skill.success_count / skill.run_count) * 100).toFixed(0)}%`
              : '—'
          }
        />
        <StatBox
          label="Avg score"
          value={skill.avg_score != null ? skill.avg_score.toFixed(1) : '—'}
          valueColor={scoreColor(skill.avg_score)}
        />
        <StatBox
          label="Last score"
          value={skill.last_score != null ? skill.last_score.toFixed(1) : '—'}
          valueColor={scoreColor(skill.last_score)}
        />
        <StatBox label="Last run" value={timeAgo(skill.last_run_at)} />
        <StatBox
          label="Avg tokens"
          value={skill.avg_tokens != null ? Math.round(skill.avg_tokens).toLocaleString() : '—'}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Section title="Identity">
          <Row label="Display name" value={skill.display_name} />
          <Row label="Owner" value={skill.owner_project} mono />
          <Row label="Category" value={skill.category} mono />
          <Row label="Tags" value={skill.tags?.length ? skill.tags.join(', ') : '—'} />
          <Row label="Team ID" value={skill.team_id != null ? `#${skill.team_id}` : '—'} mono />
          <Row label="Zero loop ID" value={skill.zero_loop_id ? `#${skill.zero_loop_id}` : '—'} mono />
        </Section>
        <Section title="Lifecycle">
          <Row label="Enabled" value={String(skill.enabled)} mono />
          <Row label="Deprecated" value={String(skill.deprecated)} mono />
          {skill.superseded_by && <Row label="Superseded by" value={skill.superseded_by} mono />}
          <Row label="Cron" value={skill.cron} mono />
          <Row label="Judge tier" value={skill.judge_tier} mono />
          <Row label="Auto-promote" value={String(skill.auto_promote)} mono />
          <Row label="Last synced" value={timeAgo(skill.last_synced_at)} />
        </Section>
      </div>

      <Section title="Source">
        <div className="text-xs text-zinc-400 mb-2">
          <span className="font-mono break-all">{skill.source_path}</span>
          <a
            href={vscodeLink(skill.source_path)}
            className="ml-2 text-indigo-400 hover:text-indigo-300"
          >
            open in VS Code →
          </a>
        </div>
        <div className="text-xs text-zinc-500 font-mono">
          content_hash: <span className="text-zinc-400">{skill.content_hash.slice(0, 16)}…</span>
        </div>
      </Section>

      {skill.deprecated && skill.superseded_by && (
        <div className="bg-amber-500/10 border border-amber-700/40 rounded-md p-3 text-sm text-amber-300">
          This skill is <strong>deprecated</strong>. Use{' '}
          <span className="font-mono">{skill.superseded_by}</span> instead.
        </div>
      )}
    </div>
  )
}

function StatBox({
  label,
  value,
  valueColor = 'text-zinc-200',
}: {
  label: string
  value: string
  valueColor?: string
}) {
  return (
    <div className="bg-zinc-800/40 px-3 py-2 rounded-md">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`text-lg font-semibold mt-0.5 ${valueColor}`}>{value}</div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-zinc-800/30 border border-zinc-800 rounded-md p-3">
      <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-zinc-500">{label}</span>
      <span className={`text-zinc-300 truncate ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function SkillDetailPage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('overview')
  const { data: skill, isLoading, isError } = useSkill(name ?? null)
  const { data: runs, isLoading: runsLoading } = useSkillRuns(
    tab === 'runs' ? name ?? null : null,
    50,
  )

  if (isLoading) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <LoadingSkeleton />
      </div>
    )
  }

  if (isError || !skill) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <button
          onClick={() => navigate('/skills')}
          className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1 mb-4"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> All skills
        </button>
        <p className="text-sm text-red-400">
          Skill <span className="font-mono">{name}</span> not found.
        </p>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <button
        onClick={() => navigate('/skills')}
        className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1 mb-4"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> All skills
      </button>

      <div className="flex items-start justify-between mb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Brain className="w-5 h-5 text-indigo-400" />
            <h1 className="text-xl font-semibold text-zinc-100 font-mono">{skill.name}</h1>
            {skill.enabled ? (
              <Badge className="bg-green-500/20 text-green-400">enabled</Badge>
            ) : (
              <Badge className="bg-zinc-700 text-zinc-400">disabled</Badge>
            )}
            {skill.deprecated && (
              <Badge className="bg-amber-500/20 text-amber-400">deprecated</Badge>
            )}
          </div>
          <p className="text-sm text-zinc-400">{skill.display_name}</p>
          <div className="flex items-center gap-1.5 mt-2">
            <Badge className={PROJECT_COLORS[skill.owner_project] || 'bg-zinc-700 text-zinc-300'}>
              {skill.owner_project}
            </Badge>
            {skill.category && (
              <Badge className={CATEGORY_COLORS[skill.category] || 'bg-zinc-700 text-zinc-300'}>
                {skill.category}
              </Badge>
            )}
            {skill.team_id != null && (
              <Badge className="bg-fuchsia-500/20 text-fuchsia-300">team#{skill.team_id}</Badge>
            )}
          </div>
        </div>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5">
        <div className="flex gap-2 border-b border-zinc-800 mb-4 -mx-5 -mt-5 px-5 pt-3">
          {(['overview', 'runs', 'schedule'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors capitalize ${
                tab === t
                  ? 'border-indigo-500 text-indigo-300'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t}
              {t === 'runs' && runs ? ` (${runs.length})` : ''}
            </button>
          ))}
        </div>

        {tab === 'overview' && <OverviewTab skill={skill} />}
        {tab === 'runs' && (
          <div className="space-y-2 max-h-[700px] overflow-y-auto">
            {runsLoading && <LoadingSkeleton />}
            {!runsLoading && runs && runs.length === 0 && (
              <p className="text-sm text-zinc-500 text-center py-8">
                No runs yet. Run-event mirrors arrive via Zero's loop_runner_service.
              </p>
            )}
            {runs?.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </div>
        )}
        {tab === 'schedule' && <ScheduleTab skill={skill} />}
      </div>
    </div>
  )
}

export default SkillDetailPage
