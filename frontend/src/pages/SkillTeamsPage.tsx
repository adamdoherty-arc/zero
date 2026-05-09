import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Users, Plus, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { useSkillTeams, useCreateTeam, type SkillTeam } from '@/hooks/useSkillTeamsApi'

function scoreColor(score?: number | null): string {
  if (score == null) return 'text-zinc-500'
  if (score >= 80) return 'text-green-400'
  if (score >= 60) return 'text-amber-400'
  return 'text-red-400'
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

function TeamCard({ team }: { team: SkillTeam }) {
  const navigate = useNavigate()
  return (
    <button
      onClick={() => navigate(`/skills/teams/${team.id}`)}
      className="w-full text-left bg-zinc-900 border border-zinc-800 hover:border-fuchsia-500/40 hover:bg-zinc-900/80 rounded-lg p-4 transition-colors"
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h3 className="text-sm font-mono font-semibold text-zinc-100">{team.name}</h3>
          <p className="text-xs text-zinc-400 mt-0.5">{team.display_name}</p>
        </div>
        <Badge className="bg-fuchsia-500/20 text-fuchsia-300">team#{team.id}</Badge>
      </div>
      {team.description && (
        <p className="text-xs text-zinc-500 line-clamp-2 mb-3">{team.description}</p>
      )}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-zinc-500">members</div>
          <div className="text-zinc-300 mt-0.5">{team.member_count}</div>
        </div>
        <div>
          <div className="text-zinc-500">last composite</div>
          <div className={`mt-0.5 ${scoreColor(team.last_composite_score)}`}>
            {team.last_composite_score == null
              ? '—'
              : team.last_composite_score.toFixed(1)}
          </div>
        </div>
        <div>
          <div className="text-zinc-500">last run</div>
          <div className="text-zinc-300 mt-0.5">{timeAgo(team.last_run_at)}</div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        <Badge className="bg-zinc-800 text-zinc-400">{team.run_strategy}</Badge>
        {team.last_status && (
          <Badge className="bg-zinc-800 text-zinc-300">{team.last_status}</Badge>
        )}
      </div>
    </button>
  )
}

function CreateTeamForm({ onCancel, onCreated }: { onCancel: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [strategy, setStrategy] = useState<'parallel' | 'sequential'>('parallel')
  const create = useCreateTeam()

  const submit = () => {
    if (!name || !displayName) return
    create.mutate(
      { name, display_name: displayName, description, run_strategy: strategy },
      { onSuccess: onCreated },
    )
  }

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 mb-4">
      <h3 className="text-sm font-semibold text-zinc-100 mb-3">Create team</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Name (slug)</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="audit-team"
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 font-mono focus:outline-none focus:border-fuchsia-500/40"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Display name</label>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Audit Team"
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 focus:outline-none focus:border-fuchsia-500/40"
          />
        </div>
        <div className="col-span-2">
          <label className="block text-xs text-zinc-500 mb-1">Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What this team does"
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 focus:outline-none focus:border-fuchsia-500/40"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Run strategy</label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value as 'parallel' | 'sequential')}
            className="w-full px-3 py-2 bg-zinc-800/60 border border-zinc-800 rounded-md text-sm text-zinc-200 focus:outline-none focus:border-fuchsia-500/40"
          >
            <option value="parallel">parallel</option>
            <option value="sequential">sequential</option>
          </select>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={submit}
          disabled={create.isPending || !name || !displayName}
          className="text-xs px-4 py-2 bg-fuchsia-600 hover:bg-fuchsia-700 disabled:bg-zinc-700 text-white rounded-md flex items-center gap-1.5"
        >
          {create.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          Create
        </button>
        <button
          onClick={onCancel}
          className="text-xs px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-md"
        >
          Cancel
        </button>
        {create.isError && (
          <span className="text-xs text-red-400">
            {(create.error as Error)?.message ?? 'failed'}
          </span>
        )}
      </div>
    </div>
  )
}

export function SkillTeamsPage() {
  const { data: teams, isLoading } = useSkillTeams()
  const [showCreate, setShowCreate] = useState(false)

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100 flex items-center gap-2">
            <Users className="w-6 h-6 text-fuchsia-400" />
            Skill Teams
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Groups of skills that run together with a composite score. Trigger a team run to fan
            out across all members in parallel; the team-run completer daemon closes them out
            once every child finishes.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="text-xs px-3 py-1.5 bg-fuchsia-600 hover:bg-fuchsia-700 text-white rounded-md flex items-center gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          {showCreate ? 'Close' : 'Create team'}
        </button>
      </div>

      {showCreate && (
        <CreateTeamForm onCancel={() => setShowCreate(false)} onCreated={() => setShowCreate(false)} />
      )}

      {isLoading && <LoadingSkeleton />}
      {!isLoading && teams && teams.length === 0 && (
        <p className="text-sm text-zinc-500 text-center py-12 bg-zinc-900 border border-zinc-800 rounded-lg">
          No teams yet. The skill sync service auto-creates teams from SKILL.md
          frontmatter `team:` declarations — or click "Create team".
        </p>
      )}
      {!isLoading && teams && teams.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {teams.map((t) => (
            <TeamCard key={t.id} team={t} />
          ))}
        </div>
      )}
    </div>
  )
}

export default SkillTeamsPage
