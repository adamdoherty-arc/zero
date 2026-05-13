/**
 * IntegrationsPage — connect & inspect third-party integrations.
 *
 * Mirrors openhuman's "Connect → next 20-min tick → in your memory" pattern.
 * Each row shows: icon, name, category, connection status, last-synced time,
 * and a connect/disconnect/sync button. A header card shows the auto-fetch
 * loop's interval and last-tick time and lets the user start/stop it.
 */

import { useCallback, useEffect, useState } from 'react'
import { Loader2, Plug, Plug2, RefreshCw, Clock, ArrowRight } from 'lucide-react'

import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface IntegrationItem {
  id: string
  name: string
  category: string
  description: string
  icon: string
  composio_app_name: string
  triggers: string[]
  connected: boolean
  connection: null | {
    id: string
    connected_at: string
    last_synced_at: string | null
    sync_count: number
  }
}

interface AutoFetchStatus {
  running: boolean
  interval_minutes: number
  last_tick_at: string | null
  last_results: Record<string, unknown>
}

interface ApiResponse {
  integrations: IntegrationItem[]
  auto_fetch: AutoFetchStatus
}

function fmtRelative(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const seconds = Math.max(0, (Date.now() - then) / 1000)
  if (seconds < 60) return `${Math.floor(seconds)}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function IntegrationsPage() {
  const [data, setData] = useState<ApiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/integrations/', { headers: getAuthHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = (await res.json()) as ApiResponse
      setData(json)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'unknown error'
      toast({ title: 'Failed to load integrations', description: message, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(refresh, 15_000)
    return () => window.clearInterval(id)
  }, [refresh])

  const handleConnect = useCallback(
    async (id: string) => {
      setBusy(id)
      try {
        const res = await fetch('/api/integrations/connect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ integration: id }),
        })
        const json = await res.json()
        if (json.status === 'connected') {
          toast({ title: 'Connected', description: `${id} is now syncing.` })
        } else if (json.status === 'unavailable') {
          toast({
            title: 'Composio unavailable',
            description: json.message ?? 'SDK or API key missing',
            variant: 'destructive',
          })
        }
        await refresh()
      } finally {
        setBusy(null)
      }
    },
    [refresh],
  )

  const handleDisconnect = useCallback(
    async (id: string) => {
      setBusy(id)
      try {
        await fetch(`/api/integrations/disconnect/${id}`, {
          method: 'POST',
          headers: getAuthHeaders(),
        })
        await refresh()
        toast({ title: 'Disconnected', description: id })
      } finally {
        setBusy(null)
      }
    },
    [refresh],
  )

  const handleSyncNow = useCallback(
    async (id: string) => {
      setBusy(id)
      try {
        const res = await fetch(`/api/integrations/sync/${id}`, {
          method: 'POST',
          headers: getAuthHeaders(),
        })
        const json = await res.json()
        toast({
          title: `Synced ${id}`,
          description: `${json.chunks_written ?? 0} new chunk(s) in vault`,
        })
        await refresh()
      } finally {
        setBusy(null)
      }
    },
    [refresh],
  )

  const handleLoopToggle = useCallback(async () => {
    if (!data) return
    const url = data.auto_fetch.running
      ? '/api/integrations/auto-fetch/stop'
      : '/api/integrations/auto-fetch/start'
    await fetch(url, { method: 'POST', headers: getAuthHeaders() })
    await refresh()
  }, [data, refresh])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-zinc-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> loading integrations
      </div>
    )
  }
  if (!data) return <div className="text-red-400">no data</div>

  const grouped = data.integrations.reduce<Record<string, IntegrationItem[]>>((acc, item) => {
    ;(acc[item.category] ??= []).push(item)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Integrations</h1>
          <p className="text-zinc-400 text-sm mt-1">
            Connect a service and Zero auto-syncs it into your Memory Tree every{' '}
            {data.auto_fetch.interval_minutes} minutes.
          </p>
        </div>
        <button
          type="button"
          onClick={handleLoopToggle}
          className={[
            'flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-colors',
            data.auto_fetch.running
              ? 'bg-emerald-900/40 border-emerald-600 text-emerald-100 hover:bg-emerald-900/60'
              : 'bg-zinc-900 border-zinc-700 text-zinc-100 hover:bg-zinc-800',
          ].join(' ')}
        >
          <RefreshCw
            className={`w-4 h-4 ${data.auto_fetch.running ? 'animate-spin-slow' : ''}`}
          />
          {data.auto_fetch.running ? 'Auto-fetch running' : 'Auto-fetch paused'}
          <span className="text-xs text-zinc-400 ml-2">
            <Clock className="inline w-3 h-3 mr-1" />
            {fmtRelative(data.auto_fetch.last_tick_at)}
          </span>
        </button>
      </header>

      {Object.entries(grouped).map(([category, items]) => (
        <section key={category}>
          <h2 className="text-sm uppercase tracking-widest text-zinc-500 mb-3">{category}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {items.map((it) => (
              <article
                key={it.id}
                className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 flex flex-col gap-3"
              >
                <div className="flex items-start gap-3">
                  <span className="text-2xl">{it.icon}</span>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold truncate">{it.name}</h3>
                    <p className="text-xs text-zinc-400 truncate">{it.description}</p>
                  </div>
                  {it.connected ? (
                    <span className="rounded-full bg-emerald-900/40 border border-emerald-700 px-2 py-0.5 text-xs text-emerald-200">
                      connected
                    </span>
                  ) : null}
                </div>
                {it.triggers.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {it.triggers.map((t) => (
                      <span
                        key={t}
                        className="text-[10px] font-mono text-zinc-500 bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 rounded"
                      >
                        <ArrowRight className="inline w-2.5 h-2.5 -mt-px" /> {t}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="mt-auto flex items-center justify-between text-xs">
                  <span className="text-zinc-500">
                    {it.connection
                      ? `synced ${fmtRelative(it.connection.last_synced_at)} · ${it.connection.sync_count}x`
                      : 'not synced'}
                  </span>
                  <div className="flex items-center gap-2">
                    {it.connected ? (
                      <>
                        <button
                          type="button"
                          onClick={() => handleSyncNow(it.id)}
                          disabled={busy === it.id}
                          className="rounded border border-zinc-700 px-2 py-1 text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
                        >
                          {busy === it.id ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : (
                            'Sync now'
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDisconnect(it.id)}
                          disabled={busy === it.id}
                          className="rounded border border-zinc-700 px-2 py-1 text-zinc-400 hover:bg-zinc-800 disabled:opacity-50"
                        >
                          <Plug2 className="inline w-3 h-3 mr-1" />
                          Disconnect
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleConnect(it.id)}
                        disabled={busy === it.id}
                        className="rounded border border-emerald-700 bg-emerald-900/40 px-2 py-1 text-emerald-100 hover:bg-emerald-900/60 disabled:opacity-50"
                      >
                        {busy === it.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <>
                            <Plug className="inline w-3 h-3 mr-1" />
                            Connect
                          </>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

export default IntegrationsPage
