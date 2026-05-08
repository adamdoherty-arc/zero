import { useState } from 'react'
import { ChevronDown, Plus, Mail, Briefcase, User, Loader2, X } from 'lucide-react'
import { useOAuthAccounts, useDisconnectAccount, startAuthUrl, type OAuthAccount } from '@/hooks/useOAuthAccounts'

interface Props {
  /** Selected account id, or null for "All Accounts" merged view. */
  value: string | null
  onChange: (account_id: string | null) => void
  /** Allow the "All Accounts" option (merged view). */
  allowAll?: boolean
  /** Compact pill (vs full button row). */
  compact?: boolean
}

function labelIcon(label: string) {
  const l = label.toLowerCase()
  if (l.includes('work') || l.includes('eightfold')) return <Briefcase className="w-3.5 h-3.5" />
  if (l.includes('personal')) return <User className="w-3.5 h-3.5" />
  return <Mail className="w-3.5 h-3.5" />
}

export function AccountSwitcher({ value, onChange, allowAll = true, compact = false }: Props) {
  const accounts = useOAuthAccounts()
  const disconnect = useDisconnectAccount()
  const [open, setOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newLabel, setNewLabel] = useState('work')

  const list = accounts.data?.accounts ?? []
  const selected = list.find((a) => a.id === value) || null

  function startAdd() {
    const label = newLabel.trim() || 'work'
    window.location.href = startAuthUrl(label)
  }

  async function handleDisconnect(a: OAuthAccount, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm(`Disconnect ${a.email} (${a.label})? Cached emails and events stay; only the OAuth tokens are revoked.`)) return
    await disconnect.mutateAsync(a.id)
    if (value === a.id) onChange(null)
  }

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 ${
          compact
            ? 'px-2 py-1 text-xs bg-gray-800/60 hover:bg-gray-700/70'
            : 'px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700'
        } rounded border border-gray-700`}
        type="button"
      >
        {selected ? (
          <>
            {labelIcon(selected.label)}
            <span className="truncate max-w-[180px]">{selected.email}</span>
            <span className="text-gray-500">({selected.label})</span>
          </>
        ) : (
          <>
            <Mail className="w-3.5 h-3.5" />
            <span>{allowAll ? 'All Accounts' : 'Choose account'}</span>
          </>
        )}
        <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute z-20 mt-1 w-72 right-0 bg-gray-900 border border-gray-700 rounded shadow-xl">
            {accounts.isLoading && (
              <div className="px-3 py-3 text-sm text-gray-400 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
              </div>
            )}
            {accounts.error && (
              <div className="px-3 py-3 text-sm text-red-400">Failed to load accounts.</div>
            )}

            {allowAll && (
              <button
                type="button"
                onClick={() => { onChange(null); setOpen(false) }}
                className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-800 ${value === null ? 'bg-indigo-500/10 text-indigo-300' : ''}`}
              >
                All Accounts
              </button>
            )}

            {list.map((a) => (
              <button
                type="button"
                key={a.id}
                onClick={() => { onChange(a.id); setOpen(false) }}
                className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-800 flex items-center gap-2 ${value === a.id ? 'bg-indigo-500/10 text-indigo-200' : ''}`}
              >
                {labelIcon(a.label)}
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{a.email}</span>
                  <span className="block text-[10px] text-gray-500 uppercase tracking-wider">
                    {a.label}{a.is_default && ' · default'}
                  </span>
                </span>
                <span
                  onClick={(e) => handleDisconnect(a, e)}
                  className="text-gray-500 hover:text-red-400 cursor-pointer"
                  title="Disconnect"
                >
                  <X className="w-3.5 h-3.5" />
                </span>
              </button>
            ))}

            <div className="border-t border-gray-700/60 px-2 py-2">
              {!adding ? (
                <button
                  type="button"
                  onClick={() => setAdding(true)}
                  className="w-full px-2 py-1.5 text-sm flex items-center gap-2 text-emerald-300 hover:bg-emerald-500/10 rounded"
                >
                  <Plus className="w-3.5 h-3.5" /> Add another account
                </button>
              ) : (
                <div className="px-1 space-y-2">
                  <label className="block text-[10px] uppercase tracking-wider text-gray-400">Label this account</label>
                  <input
                    autoFocus
                    type="text"
                    value={newLabel}
                    onChange={(e) => setNewLabel(e.target.value)}
                    placeholder="e.g. work, eightfold, side-project"
                    className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={startAdd}
                      className="flex-1 px-2 py-1 text-xs bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 rounded"
                    >
                      Connect Google account
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdding(false)}
                      className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
                    >
                      Cancel
                    </button>
                  </div>
                  <p className="text-[10px] text-gray-500">
                    Sign in with the Google account you want to add. You'll be redirected back here when done.
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
