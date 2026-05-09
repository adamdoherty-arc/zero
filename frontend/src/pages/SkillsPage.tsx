import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, RefreshCw, Search, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { useSkills, useSyncSkills, type Skill, type SkillFilters } from '@/hooks/useSkillsApi'

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

const PROJECT_TABS = ['all', 'zero', 'legion', 'ada', 'llmrouter', 'global'] as const
type ProjectTab = (typeof PROJECT_TABS)[number]

const CATEGORIES = ['all', 'review', 'audit', 'build', 'ops', 'meta'] as const
type CategoryFilter = (typeof CATEGORIES)[number]

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

function truncate(s: string | undefined | null, n: number): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

// ---------------------------------------------------------------------------
// Skill Card
// ---------------------------------------------------------------------------

function SkillCard({ skill }: { skill: Skill }) {
  const navigate = useNavigate()
  return (
    <button
      onClick={() => navigate(`/skills/${encodeURIComponent(skill.name)}`)}
      className={`w-full text-left bg-zinc-900 border rounded-lg p-4 transition-colors hover:border-indigo-500/40 hover:bg-zinc-900/80 ${
        skill.deprecated
          ? 'border-amber-700/40 opacity-70'
          : 'border-zinc-800'
      }`}
    >
      {skill.deprecated && (
        <div className="mb-2 -mt-1 -mx-1 px-2 py-1 bg-amber-500/10 text-amber-400 text-xs rounded flex items-center gap-1">
          deprecated{skill.superseded_by ? ` → ${skill.superseded_by}` : ''}
        </div>
      )}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                skill.enabled ? 'bg-green-400' : 'bg-zinc-600'
              }`}
            />
            <h3 className="text-sm font-mono font-semibold text-zinc-100 truncate">
              {skill.name}
            </h3>
          </div>
          <p className="text-xs text-zinc-400 mt-1 line-clamp-2">
            {truncate(skill.description, 160) || skill.display_name}
          </p>
        </div>
      </div>
      <div className="flex items-center flex-wrap gap-1.5 mt-3">
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
        {skill.tags?.slice(0, 2).map((t) => (
          <Badge key={t} className="bg-zinc-800 text-zinc-400">
            {t}
          </Badge>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2 mt-3 text-xs">
        <div>
          <div className="text-zinc-500">last run</div>
          <div className="text-zinc-300 mt-0.5">{timeAgo(skill.last_run_at)}</div>
        </div>
        <div>
          <div className="text-zinc-500">runs</div>
          <div className="text-zinc-300 mt-0.5">{skill.run_count.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-zinc-500">last score</div>
          <div className={`mt-0.5 ${scoreColor(skill.last_score)}`}>
            {skill.last_score == null ? '—' : skill.last_score.toFixed(1)}
          </div>
        </div>
      </div>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function SkillsPage() {
  const [project, setProject] = useState<ProjectTab>('all')
  const [category, setCategory] = useState<CategoryFilter>('all')
  const [search, setSearch] = useState('')
  const [showDeprecated, setShowDeprecated] = useState(false)

  const filters: SkillFilters | undefined = useMemo(() => {
    const f: SkillFilters = {}
    if (project !== 'all') f.owner_project = project
    if (category !== 'all') f.category = category
    if (search) f.search = search
    if (!showDeprecated) f.deprecated = false
    return Object.keys(f).length ? f : undefined
  }, [project, category, search, showDeprecated])

  const { data: skills, isLoading } = useSkills(filters)
  const syncSkills = useSyncSkills()

  const summary = useMemo(() => {
    if (!skills) return null
    return {
      total: skills.length,
      enabled: skills.filter((s) => s.enabled).length,
      deprecated: skills.filter((s) => s.deprecated).length,
      byProject: {
        zero: skills.filter((s) => s.owner_project === 'zero').length,
        legion: skills.filter((s) => s.owner_project === 'legion').length,
        ada: skills.filter((s) => s.owner_project === 'ada').length,
        global: skills.filter((s) => s.owner_project === 'global').length,
      },
    }
  }, [skills])

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <Brain className="w-6 h-6 text-indigo-400" />
            Skills
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            First-class AI agents — prompt body lives on disk, orchestration metadata in Legion.
            Card edits write through to the canonical registry.
          </p>
        </div>
        <button
          onClick={() => syncSkills.mutate()}
          disabled={syncSkills.isPending}
          className="text-xs px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-zinc-700 text-white rounded-md flex items-center gap-1.5"
        >
          {syncSkills.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          Resync filesystem
        </button>
      </div>

      {summary && (
        <div className="grid grid-cols-6 gap-3 mb-6">
          <SummaryCard label="Total skills" value={summary.total} />
          <SummaryCard label="Enabled" value={summary.enabled} accent="green" />
          <SummaryCard label="Zero" value={summary.byProject.zero} accent="indigo" />
          <SummaryCard label="Legion" value={summary.byProject.legion} accent="purple" />
          <SummaryCard label="ADA" value={summary.byProject.ada} accent="cyan" />
          <SummaryCard label="Global" value={summary.byProject.global} accent="amber" />
        </div>
      )}

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 mb-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500 mr-1">Project:</span>
          {PROJECT_TABS.map((p) => (
            <button
              key={p}
              onClick={() => setProject(p)}
              className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
                project === p
                  ? 'bg-indigo-500/20 text-indigo-300 ring-1 ring-indigo-500/40'
                  : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500 mr-1">Category:</span>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
                category === c
                  ? 'bg-indigo-500/20 text-indigo-300 ring-1 ring-indigo-500/40'
                  : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
              }`}
            >
              {c}
            </button>
          ))}
          <div className="flex-1" />
          <label className="flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
            <input
              type="checkbox"
              checked={showDeprecated}
              onChange={(e) => setShowDeprecated(e.target.checked)}
              className="rounded border-zinc-700 bg-zinc-800"
            />
            Show deprecated
          </label>
        </div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or description…"
            className="w-full pl-9 pr-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500/40 focus:ring-1 focus:ring-indigo-500/40"
          />
        </div>
      </div>

      {isLoading && <LoadingSkeleton />}
      {!isLoading && skills && skills.length === 0 && (
        <p className="text-sm text-zinc-500 text-center py-12 bg-zinc-900 border border-zinc-800 rounded-lg">
          No skills match the current filters. Try clearing the search or toggling
          "Show deprecated".
        </p>
      )}
      {!isLoading && skills && skills.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {skills.map((s) => (
            <SkillCard key={s.id} skill={s} />
          ))}
        </div>
      )}
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
  accent?: 'zinc' | 'green' | 'indigo' | 'purple' | 'cyan' | 'amber'
}) {
  const colors: Record<string, string> = {
    zinc: 'text-zinc-200',
    green: 'text-green-400',
    indigo: 'text-indigo-400',
    purple: 'text-purple-400',
    cyan: 'text-cyan-400',
    amber: 'text-amber-400',
  }
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`text-2xl font-semibold ${colors[accent]} mt-1`}>{value}</div>
    </div>
  )
}

export default SkillsPage
