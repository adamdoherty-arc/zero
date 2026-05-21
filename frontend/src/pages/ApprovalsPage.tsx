import { useMemo, useState } from 'react'
import { CheckCircle2, Clock, ShieldAlert, Trash2, XCircle } from 'lucide-react'
import {
  type AgentApproval,
  type ApprovalTier,
  useAllApprovals,
  useDecideApproval,
  useExpireStale,
} from '@/hooks/useApprovalsApi'

const TIER_ORDER: ApprovalTier[] = ['financial', 'write_external', 'write_local', 'read']

const TIER_STYLES: Record<ApprovalTier, { tone: string; label: string; expiry: string }> = {
  financial: {
    tone: 'border-rose-500/50 bg-rose-500/10 text-rose-200',
    label: 'Financial',
    expiry: '30 min',
  },
  write_external: {
    tone: 'border-amber-500/50 bg-amber-500/10 text-amber-200',
    label: 'External write',
    expiry: '6 hr',
  },
  write_local: {
    tone: 'border-sky-500/50 bg-sky-500/10 text-sky-200',
    label: 'Local write',
    expiry: '2 hr',
  },
  read: {
    tone: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200',
    label: 'Read',
    expiry: '5 min',
  },
}

const STATUS_TONE: Record<string, string> = {
  pending: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-200',
  approved: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  rejected: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  expired: 'border-gray-500/30 bg-gray-500/10 text-gray-400',
}

function ApprovalCard({ row }: { row: AgentApproval }) {
  const decide = useDecideApproval()
  const tier = TIER_STYLES[row.tier]
  const args = useMemo(() => {
    try {
      return JSON.stringify(row.arguments ?? {}, null, 2)
    } catch {
      return String(row.arguments ?? '')
    }
  }, [row.arguments])
  return (
    <div className="glass-card p-4 space-y-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap text-[11px] uppercase tracking-wide text-gray-500">
            <span className={`rounded-full border px-2 py-0.5 ${tier?.tone ?? ''}`}>
              {tier?.label ?? row.tier}
            </span>
            <span className={`rounded-full border px-2 py-0.5 ${STATUS_TONE[row.status] ?? ''}`}>
              {row.status}
            </span>
            <span className="text-gray-500">expires in {tier?.expiry ?? '?'}</span>
          </div>
          <div className="mt-2 text-base font-semibold text-white truncate">
            {row.tool_name}
          </div>
          <div className="text-sm text-gray-300 whitespace-pre-wrap">{row.summary}</div>
        </div>
        {row.status === 'pending' && (
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() =>
                decide.mutate({ id: row.id, status: 'approved', reason: 'manual' })
              }
              className="inline-flex items-center gap-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
            >
              <CheckCircle2 className="w-4 h-4" /> Approve
            </button>
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() =>
                decide.mutate({ id: row.id, status: 'rejected', reason: 'manual' })
              }
              className="inline-flex items-center gap-1 rounded-md bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
            >
              <XCircle className="w-4 h-4" /> Reject
            </button>
          </div>
        )}
      </div>
      <details className="text-xs text-gray-400">
        <summary className="cursor-pointer hover:text-gray-200">
          arguments • requested by {row.requested_by}
        </summary>
        <pre className="mt-2 rounded bg-gray-950/60 p-2 overflow-x-auto whitespace-pre-wrap">
          {args}
        </pre>
      </details>
    </div>
  )
}

export function ApprovalsPage() {
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'approved' | 'rejected' | 'expired'>('pending')
  const all = useAllApprovals(statusFilter)
  const expireStale = useExpireStale()
  const grouped = useMemo(() => {
    const m: Record<ApprovalTier, AgentApproval[]> = {
      financial: [],
      write_external: [],
      write_local: [],
      read: [],
    }
    for (const a of all.data ?? []) {
      const t = (a.tier as ApprovalTier) || 'read'
      if (!m[t]) continue
      m[t].push(a)
    }
    return m
  }, [all.data])
  const totalPending = (all.data ?? []).filter((a) => a.status === 'pending').length
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
            <ShieldAlert className="w-4 h-4 text-indigo-300" />
            Approvals inbox
          </div>
          <h1 className="text-2xl font-bold text-white">
            {totalPending} pending {totalPending === 1 ? 'request' : 'requests'}
          </h1>
          <p className="text-sm text-gray-400">
            Agent actions that need human sign-off — meeting-followup external tasks,
            financial actions, external writes, and anything tagged write_external.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(['pending', 'approved', 'rejected', 'expired', 'all'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`rounded-md border px-3 py-1.5 text-sm capitalize ${
                statusFilter === s
                  ? 'border-indigo-500 bg-indigo-500/15 text-white'
                  : 'border-gray-800 bg-gray-900/50 text-gray-400 hover:text-white'
              }`}
            >
              {s}
            </button>
          ))}
          <button
            type="button"
            onClick={() => expireStale.mutate()}
            disabled={expireStale.isPending}
            className="inline-flex items-center gap-1 rounded-md border border-gray-800 bg-gray-900/50 text-gray-300 hover:text-white px-3 py-1.5 text-sm disabled:opacity-50"
            title="Mark any past-expiry pending approvals as expired"
          >
            <Trash2 className="w-4 h-4" /> Expire stale
          </button>
        </div>
      </div>

      {all.isLoading && (
        <div className="glass-card p-6 text-center text-gray-400">
          <Clock className="w-5 h-5 inline mr-2" /> Loading approvals…
        </div>
      )}
      {all.isError && (
        <div className="glass-card p-6 text-center text-rose-400">
          Couldn't load approvals: {String(all.error)}
        </div>
      )}
      {!all.isLoading && (all.data?.length ?? 0) === 0 && (
        <div className="glass-card p-6 text-center text-gray-400">
          No {statusFilter === 'all' ? '' : statusFilter} approvals.
        </div>
      )}
      {TIER_ORDER.map((t) => {
        const items = grouped[t] || []
        if (!items.length) return null
        return (
          <section key={t} className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-gray-500">
              {TIER_STYLES[t].label} — {items.length}
            </div>
            <div className="space-y-2">
              {items.map((row) => (
                <ApprovalCard key={row.id} row={row} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
