import { useEffect, useState } from 'react'
import { Loader2, Mic } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface LiveConfig {
  model: string
  window_s: number
  poll_interval_s: number
  loaded: boolean
}

const MODELS = ['tiny', 'base', 'small', 'medium', 'large-v3'] as const

async function fetchLive(path: string, init?: RequestInit) {
  const r = await fetch(`/host-agent${path}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...init?.headers },
    ...init,
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }))
    throw new Error(err.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

export function LiveTranscriptModelPicker() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  const config = useQuery({
    queryKey: ['live-transcript', 'config'],
    queryFn: () => fetchLive('/live-transcript/config') as Promise<LiveConfig>,
    staleTime: 60_000,
  })

  const swap = useMutation({
    mutationFn: (model: string) =>
      fetchLive('/live-transcript/config', {
        method: 'POST',
        body: JSON.stringify({ model }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['live-transcript'] })
      toast({ title: 'Live transcript model updated' })
    },
    onError: (e) =>
      toast({
        title: 'Could not swap model',
        description: String(e),
        variant: 'destructive',
      }),
  })

  useEffect(() => {
    if (!open) return
    const handler = (ev: MouseEvent) => {
      const target = ev.target as HTMLElement
      if (!target.closest('[data-live-picker]')) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const current = config.data?.model ?? '—'

  return (
    <div className="relative inline-flex" data-live-picker>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={config.isLoading}
        className="text-xs px-2.5 py-1.5 rounded bg-gray-700/50 text-gray-200 hover:bg-gray-600/60 disabled:opacity-50 flex items-center gap-1"
        title="Whisper model used for live transcript"
      >
        <Mic className="w-3 h-3" />
        Live STT: <span className="font-mono text-gray-100">{current}</span>
        {swap.isPending && <Loader2 className="w-3 h-3 animate-spin ml-1" />}
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 w-44 rounded border border-gray-700 bg-gray-900 shadow-xl">
          <div className="py-1">
            {MODELS.map((m) => (
              <button
                key={m}
                onClick={() => {
                  setOpen(false)
                  swap.mutate(m)
                }}
                className={`w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-gray-800 ${
                  m === current ? 'text-emerald-300' : 'text-gray-200'
                }`}
              >
                {m}
                {m === current && <span className="ml-2 text-[10px]">●</span>}
              </button>
            ))}
          </div>
          <div className="px-3 py-1 text-[10px] text-gray-500 border-t border-gray-800">
            Larger = slower. <span className="font-mono">base</span> is the sweet spot.
          </div>
        </div>
      )}
    </div>
  )
}
