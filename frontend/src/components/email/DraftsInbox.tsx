import { useEffect, useState } from 'react'
import { getAuthHeaders } from '@/lib/auth'

interface PoolDraft {
  id: string
  account_id: string
  thread_id?: string | null
  to: string
  subject: string
  body: string
  status: 'pending' | 'approved' | 'rejected' | 'sent' | 'failed'
  created_at: number
  updated_at: number
  meta: Record<string, unknown>
  sent_message_id?: string | null
  error?: string | null
  rejection_reason?: string | null
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-amber-700/40 text-amber-200',
  approved: 'bg-blue-700/40 text-blue-200',
  rejected: 'bg-gray-700/40 text-gray-300',
  sent: 'bg-emerald-700/40 text-emerald-200',
  failed: 'bg-red-700/40 text-red-200',
}

/**
 * Per-account email drafts inbox.
 *
 * Zero drops drafts here (via the supervisor email adapter or the voice
 * loop). Adam approves/edits/rejects. Approving sends through Gmail using
 * the right account token; rejecting marks discarded.
 */
export function DraftsInbox() {
  const [drafts, setDrafts] = useState<PoolDraft[]>([])
  const [account, setAccount] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('pending')
  const [selected, setSelected] = useState<PoolDraft | null>(null)
  const [editBody, setEditBody] = useState<string>('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    const params = new URLSearchParams()
    if (account) params.set('account_id', account)
    if (statusFilter) params.set('status', statusFilter)
    try {
      const r = await fetch(`/api/email/drafts/pool?${params}`, {
        headers: { ...getAuthHeaders() },
      })
      if (!r.ok) throw new Error(`pool ${r.status}`)
      const data = (await r.json()) as { drafts: PoolDraft[] }
      setDrafts(data.drafts || [])
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    void load()
  }, [account, statusFilter])

  const refresh = () => {
    void load()
  }

  const onSelect = (d: PoolDraft) => {
    setSelected(d)
    setEditBody(d.body)
  }

  const post = async (path: string, body?: unknown) => {
    setBusy(path)
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`${path} ${r.status}`)
      return await r.json()
    } finally {
      setBusy(null)
    }
  }

  const patchBody = async () => {
    if (!selected) return
    setBusy('patch')
    try {
      await fetch(`/api/email/drafts/pool/${selected.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ body: editBody }),
      })
      refresh()
    } finally {
      setBusy(null)
    }
  }

  const approve = async () => {
    if (!selected) return
    await post(`/api/email/drafts/pool/${selected.id}/approve`)
    setSelected(null)
    refresh()
  }

  const reject = async () => {
    if (!selected) return
    const reason = window.prompt('Reason (optional):') ?? ''
    await post(`/api/email/drafts/pool/${selected.id}/reject`, { reason })
    setSelected(null)
    refresh()
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div className="md:col-span-1 space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Drafts inbox</h2>
          <button
            onClick={refresh}
            className="text-xs rounded bg-gray-800 px-2 py-1 text-gray-200 hover:bg-gray-700"
          >
            Refresh
          </button>
        </div>
        <div className="flex gap-1 text-xs">
          <input
            placeholder="account_id"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            className="flex-1 rounded bg-gray-900 border border-gray-700 px-2 py-1 text-gray-200"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded bg-gray-900 border border-gray-700 px-2 py-1 text-gray-200"
          >
            <option value="">all</option>
            <option value="pending">pending</option>
            <option value="approved">approved</option>
            <option value="sent">sent</option>
            <option value="rejected">rejected</option>
            <option value="failed">failed</option>
          </select>
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
        <div className="space-y-1 max-h-[60vh] overflow-y-auto">
          {drafts.length === 0 && (
            <div className="text-xs text-gray-500">No drafts.</div>
          )}
          {drafts.map((d) => (
            <button
              key={d.id}
              onClick={() => onSelect(d)}
              className={`w-full text-left rounded border border-gray-800 bg-gray-900 px-2 py-1.5 hover:border-indigo-500 ${
                selected?.id === d.id ? 'border-indigo-500' : ''
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">{d.account_id}</span>
                <span
                  className={`text-[10px] uppercase rounded px-1 ${
                    STATUS_COLOR[d.status] || 'bg-gray-700 text-gray-200'
                  }`}
                >
                  {d.status}
                </span>
              </div>
              <div className="text-sm text-gray-100 truncate">{d.subject || '(no subject)'}</div>
              <div className="text-xs text-gray-500 truncate">to {d.to}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="md:col-span-2">
        {!selected ? (
          <div className="rounded border border-gray-800 bg-gray-900 p-6 text-gray-500 text-sm">
            Select a draft to review.
          </div>
        ) : (
          <div className="rounded border border-gray-800 bg-gray-900 p-4 space-y-3">
            <div>
              <div className="text-xs text-gray-500">{selected.account_id} → {selected.to}</div>
              <div className="text-base font-medium text-white">{selected.subject}</div>
            </div>
            <textarea
              value={editBody}
              onChange={(e) => setEditBody(e.target.value)}
              rows={14}
              className="w-full rounded bg-gray-950 border border-gray-700 px-3 py-2 text-sm text-gray-100 font-mono"
            />
            <div className="flex gap-2 text-xs">
              <button
                disabled={!!busy}
                onClick={patchBody}
                className="rounded bg-gray-800 px-3 py-1 text-gray-200 hover:bg-gray-700"
              >
                Save edits
              </button>
              <button
                disabled={!!busy || selected.status !== 'pending'}
                onClick={approve}
                className="rounded bg-emerald-600 px-3 py-1 text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                Approve & send
              </button>
              <button
                disabled={!!busy || selected.status !== 'pending'}
                onClick={reject}
                className="rounded bg-red-700 px-3 py-1 text-white hover:bg-red-600 disabled:opacity-50"
              >
                Reject
              </button>
            </div>
            {selected.error && (
              <div className="text-xs text-red-400">error: {selected.error}</div>
            )}
            {selected.sent_message_id && (
              <div className="text-xs text-emerald-300">
                sent: {selected.sent_message_id}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
