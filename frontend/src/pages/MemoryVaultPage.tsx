/**
 * MemoryVaultPage — browse what Zero remembers.
 *
 * Three views:
 *   - Stats (per-source / per-topic / global counts)
 *   - Search across the whole vault
 *   - Single-entry view (path-addressed markdown chunk)
 *
 * The vault is genuine Obsidian-compatible Markdown on disk, so power users
 * can also point Obsidian itself at the canonical /vault mount.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2, Search, FileText, Folder } from 'lucide-react'

import { getAuthHeaders } from '@/lib/auth'

interface MemoryStats {
  sources: Record<string, Record<string, number>>
  topics: Record<string, number>
  global_count: number
  root: string
}

interface SearchHit {
  path: string
  title: string
  source: string
  level: number | null
  score: number
  snippet: string
}

interface EntryView {
  path: string
  frontmatter: Record<string, unknown>
  body: string
}

export function MemoryVaultPage() {
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'' | 'source' | 'topic' | 'global'>('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [openEntry, setOpenEntry] = useState<EntryView | null>(null)

  const fetchStats = useCallback(async () => {
    const res = await fetch('/api/memory-vault/stats', { headers: getAuthHeaders() })
    if (res.ok) setStats(await res.json())
  }, [])

  useEffect(() => {
    void fetchStats()
  }, [fetchStats])

  const doSearch = useCallback(async () => {
    if (!query.trim()) {
      setHits([])
      return
    }
    setSearching(true)
    try {
      const params = new URLSearchParams({ q: query, limit: '25' })
      if (scope) params.set('scope', scope)
      const res = await fetch(`/api/memory-vault/search?${params}`, { headers: getAuthHeaders() })
      if (res.ok) {
        const json = await res.json()
        setHits(json.hits ?? [])
      }
    } finally {
      setSearching(false)
    }
  }, [query, scope])

  const onSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      void doSearch()
    },
    [doSearch],
  )

  const openEntryByPath = useCallback(async (path: string) => {
    const res = await fetch(`/api/memory-vault/entry?path=${encodeURIComponent(path)}`, {
      headers: getAuthHeaders(),
    })
    if (res.ok) setOpenEntry(await res.json())
  }, [])

  const totalChunks = useMemo(() => {
    if (!stats) return 0
    let total = stats.global_count
    for (const buckets of Object.values(stats.sources)) {
      total += Object.values(buckets).reduce((a, b) => a + b, 0)
    }
    for (const c of Object.values(stats.topics)) total += c
    return total
  }, [stats])

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Folder className="w-5 h-5" /> Memory Vault
        </h1>
        <p className="text-zinc-400 text-sm mt-1">
          Every chunk Zero remembers, as a real Markdown file.{' '}
          {stats ? (
            <span className="text-zinc-500">
              <code className="text-xs">{stats.root}</code> - {totalChunks} chunks
            </span>
          ) : null}
        </p>
      </header>

      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the vault..."
            className="w-full pl-9 pr-3 py-2 rounded-md bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-indigo-600"
          />
        </div>
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as typeof scope)}
          className="rounded-md bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 px-3 py-2"
        >
          <option value="">All scopes</option>
          <option value="source">Sources</option>
          <option value="topic">Topics</option>
          <option value="global">Global</option>
        </select>
        <button
          type="submit"
          className="rounded-md border border-indigo-700 bg-indigo-900/40 px-4 py-2 text-sm text-indigo-100 hover:bg-indigo-900/60 flex items-center gap-2"
        >
          {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          Search
        </button>
      </form>

      {hits.length > 0 ? (
        <section>
          <h2 className="text-sm uppercase tracking-widest text-zinc-500 mb-3">
            {hits.length} results
          </h2>
          <ul className="space-y-2">
            {hits.map((hit) => (
              <li key={hit.path}>
                <button
                  type="button"
                  onClick={() => openEntryByPath(hit.path)}
                  className="w-full text-left rounded border border-zinc-800 bg-zinc-900/60 p-3 hover:bg-zinc-900"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-semibold flex items-center gap-2">
                      <FileText className="w-4 h-4 text-zinc-400" />
                      {hit.title}
                    </span>
                    <span className="text-xs font-mono text-zinc-500">
                      {hit.source} {hit.level !== null ? `L${hit.level}` : ''} - score{' '}
                      {hit.score}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-400 mt-1 line-clamp-2">{hit.snippet}</p>
                  <p className="text-[10px] font-mono text-zinc-600 mt-1">{hit.path}</p>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {stats ? (
        <section>
          <h2 className="text-sm uppercase tracking-widest text-zinc-500 mb-3">Sources</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Object.entries(stats.sources).map(([src, buckets]) => (
              <article
                key={src}
                className="rounded border border-zinc-800 bg-zinc-900/60 p-3"
              >
                <h3 className="font-semibold text-zinc-100 mb-1">{src}</h3>
                <div className="flex gap-4 text-xs text-zinc-400">
                  {Object.entries(buckets).map(([level, count]) => (
                    <span key={level}>
                      <span className="font-mono text-zinc-300">{level}</span> - {count}
                    </span>
                  ))}
                </div>
              </article>
            ))}
            {Object.keys(stats.sources).length === 0 ? (
              <p className="text-zinc-500 text-sm">No source chunks yet.</p>
            ) : null}
          </div>

          <h2 className="text-sm uppercase tracking-widest text-zinc-500 mt-6 mb-3">Topics</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {Object.entries(stats.topics).map(([t, c]) => (
              <span
                key={t}
                className="rounded-full border border-zinc-800 bg-zinc-900/60 px-3 py-1 text-xs text-zinc-300"
              >
                {t} - {c}
              </span>
            ))}
            {Object.keys(stats.topics).length === 0 ? (
              <p className="text-zinc-500 text-sm col-span-full">No topic entries yet.</p>
            ) : null}
          </div>

          <h2 className="text-sm uppercase tracking-widest text-zinc-500 mt-6 mb-3">
            Global digests
          </h2>
          <p className="text-zinc-400 text-sm">{stats.global_count} daily digest file(s).</p>
        </section>
      ) : null}

      {openEntry ? (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6">
          <div className="bg-zinc-950 border border-zinc-700 rounded-lg max-w-3xl w-full max-h-[80vh] overflow-auto p-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <h2 className="text-xl font-semibold">
                {String(openEntry.frontmatter.title ?? openEntry.path)}
              </h2>
              <button
                onClick={() => setOpenEntry(null)}
                className="text-zinc-400 hover:text-zinc-100"
              >
                x
              </button>
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mb-3">{openEntry.path}</p>
            <pre className="whitespace-pre-wrap text-sm text-zinc-200">{openEntry.body}</pre>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default MemoryVaultPage
