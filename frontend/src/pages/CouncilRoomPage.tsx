import { useState } from 'react'
import {
  Scale, Users, CheckCircle, XCircle, AlertTriangle,
  Loader2, Plus, MessageSquare, ThumbsUp, ThumbsDown, ChevronDown, ChevronRight,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useCouncilDecisions, useCouncilDecision, useProposeDecision, useConductVote,
  type CouncilDecision, type CouncilVote, type CouncilRound,
} from '@/hooks/useCouncilApi'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  proposed: 'bg-gray-500/20 text-gray-300 border-gray-600',
  approved: 'bg-green-500/20 text-green-400 border-green-600',
  rejected: 'bg-red-500/20 text-red-400 border-red-600',
  needs_revision: 'bg-yellow-500/20 text-yellow-400 border-yellow-600',
}

function statusLabel(s?: string): string {
  if (!s) return 'proposed'
  return s.replace('_', ' ')
}

function confidenceColor(score: number): string {
  if (score > 80) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-red-400'
}

function confidenceBarColor(score: number): string {
  if (score > 80) return 'bg-green-500'
  if (score >= 50) return 'bg-yellow-500'
  return 'bg-red-500'
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function positionIcon(position: string) {
  if (position === 'for') return <ThumbsUp className="w-4 h-4 text-green-400" />
  if (position === 'against') return <ThumbsDown className="w-4 h-4 text-red-400" />
  return <AlertTriangle className="w-4 h-4 text-yellow-400" />
}

// ---------------------------------------------------------------------------
// Propose Form
// ---------------------------------------------------------------------------

function ProposeForm() {
  const [topic, setTopic] = useState('')
  const propose = useProposeDecision()

  const handleSubmit = () => {
    if (!topic.trim()) return
    propose.mutate({ topic: topic.trim() }, { onSuccess: () => setTopic('') })
  }

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-5">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
        Propose Decision
      </h2>
      <textarea
        value={topic}
        onChange={e => setTopic(e.target.value)}
        placeholder="Describe the topic or decision for the council to debate..."
        rows={3}
        className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-white placeholder-gray-500 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
      />
      <div className="flex justify-end mt-3">
        <button
          onClick={handleSubmit}
          disabled={!topic.trim() || propose.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
        >
          {propose.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          Propose
        </button>
      </div>
      {propose.isError && (
        <p className="text-red-400 text-xs mt-2">Failed to submit proposal. Try again.</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Vote Card (single council member vote)
// ---------------------------------------------------------------------------

function VoteCard({ vote }: { vote: CouncilVote }) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-700 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-indigo-400" />
          <span className="text-sm font-medium text-white capitalize">{vote.role}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {positionIcon(vote.position)}
          <span className="text-xs text-gray-400 capitalize">{vote.position}</span>
        </div>
      </div>
      <p className="text-xs text-gray-400 line-clamp-2">{vote.reasoning}</p>
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${confidenceBarColor(vote.confidence)}`}
            style={{ width: `${vote.confidence}%` }}
          />
        </div>
        <span className={`text-xs font-mono ${confidenceColor(vote.confidence)}`}>
          {vote.confidence}%
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Decision Detail (expanded view)
// ---------------------------------------------------------------------------

function DecisionDetail({ decisionId }: { decisionId: string }) {
  const { data: decision, isLoading } = useCouncilDecision(decisionId)
  const conductVote = useConductVote()

  if (isLoading || !decision) {
    return <LoadingSkeleton variant="inline" message="Loading decision details..." />
  }

  const status = decision.decision || 'proposed'
  const canVote = status === 'proposed'

  return (
    <div className="space-y-4 pt-3 border-t border-gray-700">
      {/* Debate Rounds */}
      {decision.rounds.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-indigo-400" />
            Debate Rounds
          </h3>
          {decision.rounds.map((round: CouncilRound) => (
            <div key={round.round} className="space-y-2">
              <div className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Round {round.round}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {round.positions.map((pos: CouncilVote, i: number) => (
                  <VoteCard key={`${round.round}-${i}`} vote={pos} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Final Votes */}
      {Object.keys(decision.votes).length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
            <Scale className="w-4 h-4 text-indigo-400" />
            Final Votes
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {Object.entries(decision.votes).map(([role, vote]: [string, CouncilVote]) => (
              <VoteCard key={role} vote={{ ...vote, role }} />
            ))}
          </div>
        </div>
      )}

      {/* Overall Decision */}
      {decision.decision && (
        <div className="bg-gray-900/50 rounded-lg border border-gray-700 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {decision.decision === 'approved' ? (
              <CheckCircle className="w-5 h-5 text-green-400" />
            ) : decision.decision === 'rejected' ? (
              <XCircle className="w-5 h-5 text-red-400" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-yellow-400" />
            )}
            <div>
              <span className="text-sm font-medium text-white capitalize">{statusLabel(decision.decision)}</span>
              {decision.decided_at && (
                <span className="text-xs text-gray-500 ml-2">
                  decided {timeAgo(decision.decided_at)}
                </span>
              )}
            </div>
          </div>
          <span className={`text-lg font-bold font-mono ${confidenceColor(decision.confidence_score)}`}>
            {decision.confidence_score}%
          </span>
        </div>
      )}

      {/* Conduct Vote button */}
      {canVote && (
        <button
          onClick={() => conductVote.mutate(decision.id)}
          disabled={conductVote.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {conductVote.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Scale className="w-4 h-4" />
          )}
          Conduct Vote
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Decision Card
// ---------------------------------------------------------------------------

function DecisionCard({ decision }: { decision: CouncilDecision }) {
  const [expanded, setExpanded] = useState(false)
  const status = decision.decision || 'proposed'
  const badgeStyle = STATUS_STYLES[status] || STATUS_STYLES.proposed

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-3">
      <div
        className="flex items-start gap-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="mt-0.5">
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-gray-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-500" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-medium text-white truncate">{decision.topic}</h3>
            <Badge className={`text-[10px] border ${badgeStyle}`}>
              {statusLabel(status)}
            </Badge>
          </div>
          <div className="flex items-center gap-4 mt-1.5 text-xs text-gray-500">
            <span>by {decision.proposer_role || 'user'}</span>
            <span>{timeAgo(decision.created_at)}</span>
            <span>{decision.rounds.length} round{decision.rounds.length !== 1 ? 's' : ''}</span>
            <span>{Object.keys(decision.votes).length} vote{Object.keys(decision.votes).length !== 1 ? 's' : ''}</span>
          </div>
        </div>
        <span className={`text-sm font-bold font-mono ${confidenceColor(decision.confidence_score)}`}>
          {decision.confidence_score}%
        </span>
      </div>

      {expanded && <DecisionDetail decisionId={decision.id} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function CouncilRoomPage() {
  const [statusFilter, setStatusFilter] = useState<string>('')
  const { data: decisions, isLoading } = useCouncilDecisions(
    statusFilter ? { status: statusFilter } : undefined,
  )

  const filters = ['all', 'proposed', 'approved', 'rejected', 'needs_revision']

  return (
    <div className="p-6 space-y-6">
      {/* Propose Form */}
      <ProposeForm />

      {/* Status Filters */}
      <div className="flex items-center gap-2">
        {filters.map(f => (
          <button
            key={f}
            onClick={() => setStatusFilter(f === 'all' ? '' : f)}
            className={`px-3 py-1 text-xs rounded-full transition-colors capitalize ${
              (f === 'all' && !statusFilter) || f === statusFilter
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white border border-gray-700'
            }`}
          >
            {f.replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Decisions List */}
      {isLoading ? (
        <LoadingSkeleton variant="cards" count={4} message="Loading decisions..." />
      ) : !decisions?.length ? (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-12 text-center">
          <Scale className="w-10 h-10 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400">No decisions yet. Propose a topic above to get started.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {decisions.map((d: CouncilDecision) => (
            <DecisionCard key={d.id} decision={d} />
          ))}
        </div>
      )}
    </div>
  )
}
