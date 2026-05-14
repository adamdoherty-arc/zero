import { useCallback, useEffect, useMemo, useState } from 'react'
import { Brain, History, Save, RotateCcw, Loader2, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface BlockEdit {
  ts: number
  by: string
  reason: string
  previous_value: string
  new_value: string
}

interface Block {
  label: string
  value: string
  max_chars: number
  chars: number
  last_updated_by: string
  last_updated_at: number
  user_editable: boolean
  edit_history?: BlockEdit[]
}

interface Snapshot {
  filename: string
  date: string
  bytes: number
  modified: string
}

const BLOCK_LABELS: Record<string, { title: string; hint: string }> = {
  persona: {
    title: 'Persona tuning',
    hint: 'Persistent overrides on top of the active persona ("user prefers I skip greetings", "always speak in short sentences"). Zero obeys these every turn.',
  },
  human: {
    title: 'Who you are',
    hint: 'Durable facts about you — name, projects, communication preferences, what matters. Updated by the nightly synthesis job; you can edit directly.',
  },
  relationship: {
    title: 'History together',
    hint: 'Shared shorthand, recurring topics, threads-in-progress. Built from the last seven days of voice turns.',
  },
}

const BLOCK_ORDER = ['persona', 'human', 'relationship'] as const

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...getAuthHeaders(), ...(init?.headers || {}) },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${body || res.statusText}`)
  }
  return (await res.json()) as T
}

function fmtAgo(ts: number): string {
  if (!ts) return '—'
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function ReachyMemoryPage() {
  const [blocks, setBlocks] = useState<Record<string, Block>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [savingLabel, setSavingLabel] = useState<string | null>(null)
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [activeSnapshot, setActiveSnapshot] = useState<{ filename: string; content: string } | null>(null)
  const [loading, setLoading] = useState(true)

  const loadBlocks = useCallback(async () => {
    try {
      const detailed = await Promise.all(
        BLOCK_ORDER.map((label) => fetchJson<Block>(`/api/reachy/memory/blocks/${label}`)),
      )
      const map: Record<string, Block> = {}
      detailed.forEach((b) => {
        map[b.label] = b
      })
      setBlocks(map)
      setDrafts((prev) => {
        const next = { ...prev }
        for (const b of detailed) {
          if (next[b.label] === undefined) next[b.label] = b.value
        }
        return next
      })
    } catch (e) {
      console.error('block load failed', e)
      toast({ variant: 'destructive', title: 'Failed to load memory blocks', description: String(e) })
    }
  }, [])

  const loadSnapshots = useCallback(async () => {
    try {
      const r = await fetchJson<{ snapshots: Snapshot[] }>('/api/reachy/memory/history')
      setSnapshots(r.snapshots || [])
    } catch (e) {
      console.error('snapshots load failed', e)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      setLoading(true)
      await Promise.all([loadBlocks(), loadSnapshots()])
      setLoading(false)
    })()
  }, [loadBlocks, loadSnapshots])

  const saveBlock = useCallback(
    async (label: string) => {
      const block = blocks[label]
      if (!block) return
      if (!block.user_editable) {
        toast({ variant: 'destructive', title: 'Read-only', description: `${label} is not user-editable.` })
        return
      }
      setSavingLabel(label)
      try {
        const updated = await fetchJson<Block>(`/api/reachy/memory/blocks/${label}`, {
          method: 'PUT',
          body: JSON.stringify({ value: drafts[label] ?? '', reason: reasons[label] ?? '' }),
        })
        setBlocks((prev) => ({ ...prev, [label]: updated }))
        setReasons((prev) => ({ ...prev, [label]: '' }))
        toast({ title: 'Saved', description: `${label} updated (${updated.chars} chars).` })
      } catch (e) {
        toast({ variant: 'destructive', title: 'Save failed', description: String(e) })
      } finally {
        setSavingLabel(null)
      }
    },
    [blocks, drafts, reasons],
  )

  const revertLastEdit = useCallback(
    async (label: string) => {
      try {
        const updated = await fetchJson<Block>(`/api/reachy/memory/blocks/${label}/revert`, {
          method: 'POST',
          body: JSON.stringify({ edit_index: -1 }),
        })
        setBlocks((prev) => ({ ...prev, [label]: updated }))
        setDrafts((prev) => ({ ...prev, [label]: updated.value }))
        toast({ title: 'Reverted', description: `${label} restored to previous value.` })
      } catch (e) {
        toast({ variant: 'destructive', title: 'Revert failed', description: String(e) })
      }
    },
    [],
  )

  const openSnapshot = useCallback(async (filename: string) => {
    try {
      const r = await fetchJson<{ filename: string; content: string }>(
        `/api/reachy/memory/history/${encodeURIComponent(filename)}`,
      )
      setActiveSnapshot(r)
    } catch (e) {
      toast({ variant: 'destructive', title: 'Failed to load snapshot', description: String(e) })
    }
  }, [])

  const recentEdits = useMemo(() => {
    const all: Array<BlockEdit & { label: string }> = []
    for (const label of BLOCK_ORDER) {
      const b = blocks[label]
      if (!b?.edit_history) continue
      for (const e of b.edit_history) all.push({ ...e, label })
    }
    return all.sort((a, b) => b.ts - a.ts).slice(0, 30)
  }, [blocks])

  return (
    <div className="p-4 md:p-6 space-y-6">
      <header className="flex items-center gap-2">
        <Brain className="w-5 h-5 text-indigo-400" />
        <h1 className="text-xl font-semibold text-gray-100">Zero Memory</h1>
        <span className="text-xs text-gray-500">Long-term memory blocks composed into every voice turn</span>
      </header>

      {loading ? (
        <div className="flex items-center gap-2 text-gray-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : (
        <>
          {/* Blocks */}
          <section className="space-y-4">
            {BLOCK_ORDER.map((label) => {
              const block = blocks[label]
              const meta = BLOCK_LABELS[label]
              const draft = drafts[label] ?? ''
              const hasChanges = block && draft !== block.value
              if (!block) return null
              return (
                <div key={label} className="glass-card p-4 space-y-2">
                  <div className="flex items-baseline gap-2">
                    <h2 className="text-sm font-semibold text-gray-100">{meta.title}</h2>
                    <span className="text-[10px] uppercase tracking-wide text-gray-500 font-mono">{label}</span>
                    <span className="ml-auto text-[10px] text-gray-500">
                      {block.chars}/{block.max_chars} chars · updated {fmtAgo(block.last_updated_at)} by {block.last_updated_by}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400">{meta.hint}</p>
                  <textarea
                    value={draft}
                    onChange={(e) =>
                      setDrafts((prev) => ({ ...prev, [label]: e.target.value }))
                    }
                    rows={Math.max(6, Math.min(20, draft.split('\n').length + 2))}
                    className="w-full rounded border border-zinc-800 bg-zinc-950 p-2 font-mono text-xs text-gray-200 focus:outline-none focus:border-indigo-500 disabled:opacity-60"
                    disabled={!block.user_editable}
                  />
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      placeholder="Reason for change (optional)"
                      value={reasons[label] ?? ''}
                      onChange={(e) =>
                        setReasons((prev) => ({ ...prev, [label]: e.target.value }))
                      }
                      className="flex-1 h-8 rounded border border-zinc-800 bg-zinc-950 px-2 text-xs text-gray-200"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!block.edit_history?.length}
                      onClick={() => void revertLastEdit(label)}
                      title="Revert to the previous value"
                    >
                      <RotateCcw className="w-3.5 h-3.5 mr-1" /> Revert
                    </Button>
                    <Button
                      size="sm"
                      disabled={!hasChanges || savingLabel === label}
                      onClick={() => void saveBlock(label)}
                    >
                      {savingLabel === label ? (
                        <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
                      ) : (
                        <Save className="w-3.5 h-3.5 mr-1" />
                      )}
                      Save
                    </Button>
                  </div>
                </div>
              )
            })}
          </section>

          {/* Recent edits */}
          <section className="glass-card p-4">
            <h2 className="text-sm font-semibold text-gray-100 flex items-center gap-2 mb-3">
              <History className="w-4 h-4 text-indigo-400" /> Recent edits
            </h2>
            {recentEdits.length === 0 ? (
              <div className="text-xs text-gray-500">No edits yet.</div>
            ) : (
              <ul className="space-y-1.5 text-xs">
                {recentEdits.map((e, i) => (
                  <li key={`${e.label}-${e.ts}-${i}`} className="flex gap-2 items-start">
                    <span className="font-mono text-[10px] text-gray-500 w-20 shrink-0">{fmtAgo(e.ts)}</span>
                    <span className="font-mono text-[10px] text-indigo-300 w-24 shrink-0">{e.label}</span>
                    <span className="text-[10px] text-gray-500 w-16 shrink-0">{e.by}</span>
                    <span className="text-gray-300 truncate">{e.reason || '(no reason)'}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Personality history snapshots */}
          <section className="glass-card p-4">
            <h2 className="text-sm font-semibold text-gray-100 flex items-center gap-2 mb-3">
              <FileText className="w-4 h-4 text-indigo-400" /> Personality history
              <span className="ml-auto text-[10px] text-gray-500">
                Nightly snapshots from your Obsidian vault
              </span>
            </h2>
            {snapshots.length === 0 ? (
              <div className="text-xs text-gray-500">
                No snapshots yet. The first one writes after the next nightly synthesis run (02:30 daily) — or run it manually with{' '}
                <code className="text-[10px] bg-zinc-900 px-1 py-0.5 rounded">
                  docker exec zero-api python -m app.services.reachy_personality_synthesis_service --run-now
                </code>
                .
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <ul className="space-y-1.5 text-xs">
                  {snapshots.map((s) => (
                    <li key={s.filename}>
                      <button
                        type="button"
                        onClick={() => void openSnapshot(s.filename)}
                        className={[
                          'w-full text-left rounded px-2 py-1.5 transition-colors',
                          activeSnapshot?.filename === s.filename
                            ? 'bg-indigo-900/30 text-indigo-100'
                            : 'hover:bg-zinc-800/40 text-gray-300',
                        ].join(' ')}
                      >
                        <span className="font-mono">{s.date}</span>
                        <span className="ml-2 text-[10px] text-gray-500">{s.bytes} bytes</span>
                      </button>
                    </li>
                  ))}
                </ul>
                <pre className="rounded bg-zinc-950 border border-zinc-800 p-3 text-[10.5px] text-gray-300 whitespace-pre-wrap overflow-auto max-h-96 font-mono">
                  {activeSnapshot?.content ?? 'Pick a date to read.'}
                </pre>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
