/**
 * MeetingAgentPage — drop a Meet/Zoom URL, Zero joins as a real participant.
 *
 * Mirrors openhuman's "drop a link, mascot joins" UX. While the headless
 * driver runs server-side, this page shows live session state and lets the
 * user push prompts that Zero speaks back into the call.
 */

import { useCallback, useEffect, useState } from 'react'
import { Loader2, Video, LogOut, Megaphone, Plug } from 'lucide-react'

import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface Session {
  id: string
  url: string
  title: string
  status: string
  joined_at: string
  ended_at: string | null
  transcript_chars: number
  spoken_turns: number
  error: string | null
  notes_vault_paths: string[]
}

interface StatusResponse {
  available: boolean
  session_count: number
}

const STATUS_COLORS: Record<string, string> = {
  joining: 'bg-amber-900/40 text-amber-200 border-amber-700',
  active: 'bg-emerald-900/40 text-emerald-100 border-emerald-700',
  speaking: 'bg-indigo-900/40 text-indigo-100 border-indigo-700',
  leaving: 'bg-zinc-900 text-zinc-300 border-zinc-700',
  ended: 'bg-zinc-900 text-zinc-500 border-zinc-800',
  error: 'bg-red-900/40 text-red-100 border-red-700',
}

export function MeetingAgentPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const [s, l] = await Promise.all([
      fetch('/api/meeting-agent/status', { headers: getAuthHeaders() }).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch('/api/meeting-agent/sessions', { headers: getAuthHeaders() }).then((r) =>
        r.ok ? r.json() : { sessions: [] },
      ),
    ])
    if (s) setStatus(s)
    setSessions(l.sessions ?? [])
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(refresh, 5000)
    return () => window.clearInterval(id)
  }, [refresh])

  const join = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!url.trim()) return
      setBusy(true)
      try {
        const res = await fetch('/api/meeting-agent/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ url, display_name: 'Zero' }),
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          toast({
            title: 'Failed to join',
            description: body.detail ?? `HTTP ${res.status}`,
            variant: 'destructive',
          })
          return
        }
        const s = await res.json()
        toast({ title: 'Joining…', description: s.title })
        setUrl('')
        await refresh()
      } finally {
        setBusy(false)
      }
    },
    [url, refresh],
  )

  const speak = useCallback(
    async (sessionId: string) => {
      const text = window.prompt('What should Zero say?')
      if (!text) return
      const res = await fetch(`/api/meeting-agent/sessions/${sessionId}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ text }),
      })
      const json = await res.json()
      toast({
        title: 'Speak',
        description: json.status === 'ok' ? `${text}` : `Status: ${json.status}`,
        variant: json.status === 'ok' ? undefined : 'destructive',
      })
      await refresh()
    },
    [refresh],
  )

  const leave = useCallback(
    async (sessionId: string) => {
      await fetch(`/api/meeting-agent/sessions/${sessionId}/leave`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      toast({ title: 'Left meeting' })
      await refresh()
    },
    [refresh],
  )

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Video className="w-5 h-5" /> Meeting Agent
        </h1>
        <p className="text-zinc-400 text-sm mt-1">
          Drop a Meet or Zoom URL and Zero joins as a real participant: it listens, takes notes
          into the Memory Tree, and can speak back when you ask it to.
        </p>
        {status ? (
          <p className="text-xs text-zinc-500 mt-2">
            Driver:{' '}
            <span className={status.available ? 'text-emerald-400' : 'text-amber-400'}>
              {status.available ? 'available' : 'unavailable (install playwright)'}
            </span>{' '}
            · {status.session_count} session(s) on file
          </p>
        ) : null}
      </header>

      <form onSubmit={join} className="flex items-center gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://meet.google.com/abc-defg-hij"
          className="flex-1 px-3 py-2 rounded-md bg-zinc-900 border border-zinc-700 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-indigo-600"
        />
        <button
          type="submit"
          disabled={busy || !url.trim()}
          className="rounded-md border border-indigo-700 bg-indigo-900/40 px-4 py-2 text-sm text-indigo-100 hover:bg-indigo-900/60 disabled:opacity-50 flex items-center gap-2"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />}
          Join
        </button>
      </form>

      <section>
        <h2 className="text-sm uppercase tracking-widest text-zinc-500 mb-3">Sessions</h2>
        {sessions.length === 0 ? (
          <p className="text-zinc-500 text-sm">No sessions yet.</p>
        ) : (
          <ul className="space-y-2">
            {sessions.map((s) => (
              <li
                key={s.id}
                className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 flex items-start justify-between gap-4"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold truncate">{s.title}</span>
                    <span
                      className={[
                        'text-xs rounded-full px-2 py-0.5 border',
                        STATUS_COLORS[s.status] ?? STATUS_COLORS.ended,
                      ].join(' ')}
                    >
                      {s.status}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 mt-1 break-all">{s.url}</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    transcript: {s.transcript_chars} chars · spoken: {s.spoken_turns}
                  </p>
                  {s.error ? (
                    <p className="text-xs text-red-400 mt-1">⚠ {s.error}</p>
                  ) : null}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {s.status === 'active' || s.status === 'speaking' ? (
                    <>
                      <button
                        onClick={() => speak(s.id)}
                        className="rounded border border-indigo-700 px-2 py-1 text-xs text-indigo-100 hover:bg-indigo-900/40"
                      >
                        <Megaphone className="inline w-3 h-3 mr-1" /> Speak
                      </button>
                      <button
                        onClick={() => leave(s.id)}
                        className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-800"
                      >
                        <LogOut className="inline w-3 h-3 mr-1" /> Leave
                      </button>
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

export default MeetingAgentPage
