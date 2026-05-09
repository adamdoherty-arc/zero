import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Users, Play, Loader2, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useSkillTeam,
  useTeamRuns,
  useTriggerTeamRun,
  type SkillTeamRun,
} from '@/hooks/useSkillTeamsApi'

const STATUS_COLORS: Record<string, string> = {
  running: 'bg-blue-500/20 text-blue-400',
  success: 'bg-green-500/20 text-green-400',
  degraded: 'bg-amber-500/20 text-amber-400',
  failure: 'bg-red-500/20 text-red-400',
  skipped: 'bg-zinc-700 text-zinc-300',
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
  running: <Loader2 className="w-3.5 h-3.5 animate-spin" />,
  success: <CheckCircle className="w-3.5 h-3.5" />,
  degraded: <AlertTriangle className="w-3.5 h-3.5" />,
  failure: <XCircle className="w-3.5 h-3.5" />,
  skipped: <Clock className="w-3.5 h-3.5" />,
}

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

function TeamRunRow({ run }: { run: SkillTeamRun }) {
  return (
    <div className="bg-zinc-800/50 border border-zinc-800 rounded-md px-3 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Badge className={STATUS_COLORS[run.status] || 'bg-zinc-700 text-zinc-300'}>
          <span className="flex items-center gap-1">
            {STATUS_ICONS[run.status]}
            {run.status}
          </span>
        </Badge>
        <span className="text-xs text-zinc-300 font-mono">#{run.id}</span>
        {run.composite_score != null && (
          <span className={`text-xs ${scoreColor(run.composite_score)}`}>
            composite {run.composite_score.toFixed(1)}
          </span>
        )}
        <span className="text-xs text-zinc-500">{run.child_run_ids.length} children</span>
        <span className="text-xs text-zinc-500">{run.trigger_source}</span>
      </div>
      <span className="text-xs text-zinc-500">{timeAgo(run.started_at)}</span>
    </div>
  )
}

export function SkillTeamDetailPage() {
  const { teamId } = useParams<{ teamId: string }>()
  const id = teamId ? parseInt(teamId, 10) : null
  const navigate = useNavigate()
  const { data: team, isLoading } = useSkillTeam(id)
  const { data: runs } = useTeamRuns(id, 20)
  const trigger = useTriggerTeamRun()
  const [scope, setScope] = useState('head')
  const [pr, setPr] = useState('')

  if (isLoading || !team) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <LoadingSkeleton />
      </div>
    )
  }

  const submit = () => {
    const args: Record<string, unknown> = {}
    if (scope) args.scope = scope
    if (pr) args.pr = pr
    trigger.mutate({ id: team.id, req: { trigger_source: 'manual', trigger_args: args } })
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <button
        onClick={() => navigate('/skills/teams')}
        className="text-xs text-zinc-400 hover:text-zinc-200 flex items-center gap-1 mb-4"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> All teams
      </button>

      <div className="flex items-start justify-between mb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Users className="w-5 h-5 text-fuchsia-400" />
            <h1 className="text-xl font-semibold text-zinc-100 font-mono">{team.name}</h1>
            <Badge className="bg-fuchsia-500/20 text-fuchsia-300">team#{team.id}</Badge>
          </div>
          <p className="text-sm text-zinc-400">{team.display_name}</p>
          {team.description && <p className="text-xs text-zinc-500 mt-1">{team.description}</p>}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-7 bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
            Members ({team.member_count})
          </h2>
          {team.members.length === 0 && (
            <p className="text-sm text-zinc-500">
              No members yet. Add `team: {team.name}` to a SKILL.md frontmatter and the sync
              service will auto-link.
            </p>
          )}
          <div className="space-y-1">
            {team.members
              .sort((a, b) => a.position - b.position)
              .map((m) => (
                <div
                  key={m.id}
                  className="bg-zinc-800/50 border border-zinc-800 rounded-md px-3 py-2 flex items-center justify-between"
                >
                  <button
                    onClick={() => navigate(`/skills/${encodeURIComponent(m.name)}`)}
                    className="text-sm font-mono text-zinc-200 hover:text-indigo-300"
                  >
                    {m.name}
                  </button>
                  <span className="text-xs text-zinc-500">pos {m.position}</span>
                </div>
              ))}
          </div>
        </div>

        <div className="col-span-5 bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
            Trigger run
          </h2>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-zinc-500 mb-1">scope</label>
              <input
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 font-mono focus:outline-none focus:border-fuchsia-500/40"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">pr (optional)</label>
              <input
                value={pr}
                onChange={(e) => setPr(e.target.value)}
                placeholder="123 or branch:foo"
                className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 font-mono focus:outline-none focus:border-fuchsia-500/40"
              />
            </div>
            <button
              onClick={submit}
              disabled={trigger.isPending}
              className="w-full text-xs px-4 py-2 bg-fuchsia-600 hover:bg-fuchsia-700 disabled:bg-zinc-700 text-white rounded-md flex items-center justify-center gap-1.5"
            >
              {trigger.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5" />
              )}
              Run team now
            </button>
            {trigger.isError && (
              <p className="text-xs text-red-400">
                {(trigger.error as Error)?.message ?? 'failed'}
              </p>
            )}
          </div>
          <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mt-4 mb-2">
            Composite weights
          </h3>
          {Object.keys(team.composite_weights || {}).length === 0 ? (
            <p className="text-xs text-zinc-500">Uniform (mean of children).</p>
          ) : (
            <div className="space-y-1 text-xs">
              {Object.entries(team.composite_weights).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-zinc-400 font-mono">{k}</span>
                  <span className="text-zinc-300">{v.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="col-span-12 bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
            Recent runs
          </h2>
          <div className="space-y-1">
            {(!runs || runs.length === 0) && (
              <p className="text-sm text-zinc-500">No runs yet.</p>
            )}
            {runs?.map((run) => <TeamRunRow key={run.id} run={run} />)}
          </div>
        </div>
      </div>
    </div>
  )
}

export default SkillTeamDetailPage
