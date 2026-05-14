/**
 * OpenHandsTasksPage — dispatch + monitor OpenHands code-agent tasks.
 *
 * OpenHands stays disabled until a real runtime is approved. The page shows
 * historical records and blocks new dispatch instead of pretending the
 * integration is operational.
 */

import { useCallback, useEffect, useState } from 'react'
import { Loader2, Send, Cpu, Box, X } from 'lucide-react'

import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface OpenHandsTask {
  id: string
  instruction: string
  status: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  workspace: string
  model: string | null
  events: Array<{ type: string; ts?: string; message?: string }>
  final_message: string | null
  error: string | null
}

interface StatusResponse {
  available: boolean
  task_count: number
}

const STATUS_COLORS: Record<string, string> = {
  queued: 'bg-zinc-900 text-zinc-300 border-zinc-700',
  running: 'bg-indigo-900/40 text-indigo-100 border-indigo-700',
  completed: 'bg-emerald-900/40 text-emerald-100 border-emerald-700',
  failed: 'bg-red-900/40 text-red-100 border-red-700',
  cancelled: 'bg-zinc-900 text-zinc-500 border-zinc-800',
}

export function OpenHandsTasksPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [tasks, setTasks] = useState<OpenHandsTask[]>([])
  const [instruction, setInstruction] = useState('')
  const [workspace, setWorkspace] = useState<'local' | 'docker'>('local')
  const [busy, setBusy] = useState(false)
  const [openTask, setOpenTask] = useState<OpenHandsTask | null>(null)

  const refresh = useCallback(async () => {
    const [s, l] = await Promise.all([
      fetch('/api/openhands/status', { headers: getAuthHeaders() }).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch('/api/openhands/tasks', { headers: getAuthHeaders() }).then((r) =>
        r.ok ? r.json() : { tasks: [] },
      ),
    ])
    if (s) setStatus(s)
    setTasks(l.tasks ?? [])
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(refresh, 4000)
    return () => window.clearInterval(id)
  }, [refresh])

  const dispatch = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!instruction.trim()) return
      setBusy(true)
      try {
        const res = await fetch('/api/openhands/tasks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ instruction, workspace }),
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          toast({
            title: 'Dispatch failed',
            description: body.detail ?? `HTTP ${res.status}`,
            variant: 'destructive',
          })
          return
        }
        const t = await res.json()
        if (t.status === 'unavailable') {
          toast({
            title: 'OpenHands unavailable',
            description: t.error ?? 'Runtime disabled.',
            variant: 'destructive',
          })
          await refresh()
          return
        }
        if (t.status === 'approval_required') {
          toast({
            title: 'Approval queued',
            description: t.approval_id ? `Approval ${t.approval_id}` : 'Approval queue unavailable.',
          })
          setInstruction('')
          await refresh()
          return
        }
        toast({
          title: t.status === 'failed' ? 'Recorded (unavailable)' : 'Task dispatched',
          description: t.error ?? `id=${t.id}`,
          variant: t.status === 'failed' ? 'destructive' : undefined,
        })
        setInstruction('')
        await refresh()
      } finally {
        setBusy(false)
      }
    },
    [instruction, workspace, refresh],
  )

  const cancel = useCallback(
    async (taskId: string) => {
      await fetch(`/api/openhands/tasks/${taskId}/cancel`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      toast({ title: 'Cancelled' })
      await refresh()
    },
    [refresh],
  )

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Cpu className="w-5 h-5" /> OpenHands
        </h1>
        <p className="text-zinc-400 text-sm mt-1">
          OpenHands is disabled for now. Code delegation should flow through Legion or an
          approved runtime path before any external workspace action executes.
        </p>
        {status ? (
          <p className="text-xs text-zinc-500 mt-2">
            SDK:{' '}
            <span className={status.available ? 'text-emerald-400' : 'text-amber-400'}>
              {status.available ? 'available' : 'unavailable (disabled)'}
            </span>{' '}
            - {status.task_count} task(s) on file
          </p>
        ) : null}
      </header>

      <form onSubmit={dispatch} className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="What should the agent do? (e.g. 'Refactor src/foo.py so it returns a Pydantic model')"
          rows={4}
          className="w-full px-3 py-2 rounded-md bg-zinc-950 border border-zinc-700 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-indigo-600 resize-none"
        />
        <div className="flex items-center gap-3">
          <label className="text-xs text-zinc-400 flex items-center gap-1.5">
            <Box className="w-3.5 h-3.5" /> Workspace
          </label>
          <div className="flex gap-1">
            {(['local', 'docker'] as const).map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => setWorkspace(w)}
                className={[
                  'rounded-md border px-3 py-1 text-xs',
                  workspace === w
                    ? 'bg-indigo-900/40 border-indigo-600 text-indigo-100'
                    : 'bg-zinc-900 border-zinc-700 text-zinc-300 hover:bg-zinc-800',
                ].join(' ')}
              >
                {w}
              </button>
            ))}
          </div>
          <button
            type="submit"
            disabled={busy || !instruction.trim()}
            className="ml-auto rounded-md border border-indigo-700 bg-indigo-900/40 px-4 py-2 text-sm text-indigo-100 hover:bg-indigo-900/60 disabled:opacity-50 flex items-center gap-2"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Dispatch
          </button>
        </div>
      </form>

      <section>
        <h2 className="text-sm uppercase tracking-widest text-zinc-500 mb-3">Tasks</h2>
        {tasks.length === 0 ? (
          <p className="text-zinc-500 text-sm">No tasks yet.</p>
        ) : (
          <ul className="space-y-2">
            {tasks.map((t) => (
              <li
                key={t.id}
                className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 flex items-start justify-between gap-4"
              >
                <button
                  onClick={() => setOpenTask(t)}
                  className="flex-1 text-left min-w-0"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={[
                        'text-xs rounded-full px-2 py-0.5 border',
                        STATUS_COLORS[t.status] ?? STATUS_COLORS.queued,
                      ].join(' ')}
                    >
                      {t.status}
                    </span>
                    <span className="text-xs font-mono text-zinc-500">{t.workspace}</span>
                    {t.model ? (
                      <span className="text-xs font-mono text-zinc-500">{t.model}</span>
                    ) : null}
                    <span className="text-xs text-zinc-500 ml-auto">{t.created_at}</span>
                  </div>
                  <p className="text-sm text-zinc-200 line-clamp-2">{t.instruction}</p>
                  {t.error ? (
                    <p className="text-xs text-red-400 mt-1">⚠ {t.error}</p>
                  ) : null}
                </button>
                {(t.status === 'queued' || t.status === 'running') && (
                  <button
                    type="button"
                    onClick={() => cancel(t.id)}
                    className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {openTask ? (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6">
          <div className="bg-zinc-950 border border-zinc-700 rounded-lg max-w-3xl w-full max-h-[80vh] overflow-auto p-6">
            <div className="flex items-start justify-between mb-3">
              <h2 className="text-lg font-semibold">{openTask.id}</h2>
              <button
                onClick={() => setOpenTask(null)}
                className="text-zinc-400 hover:text-zinc-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <pre className="bg-zinc-900 rounded p-3 text-sm text-zinc-200 whitespace-pre-wrap mb-4">
              {openTask.instruction}
            </pre>
            <h3 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">
              Events ({openTask.events?.length ?? 0})
            </h3>
            <ul className="space-y-1 mb-4">
              {openTask.events?.map((ev, i) => (
                <li key={i} className="text-xs font-mono text-zinc-400">
                  <span className="text-zinc-600">{ev.ts}</span> - {ev.type}
                  {ev.message ? `: ${ev.message}` : ''}
                </li>
              ))}
            </ul>
            {openTask.final_message ? (
              <>
                <h3 className="text-xs uppercase tracking-widest text-zinc-500 mb-2">
                  Final
                </h3>
                <pre className="bg-zinc-900 rounded p-3 text-sm text-zinc-200 whitespace-pre-wrap">
                  {openTask.final_message}
                </pre>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default OpenHandsTasksPage
