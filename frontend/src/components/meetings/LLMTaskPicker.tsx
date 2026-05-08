import { useEffect, useMemo, useState } from 'react'
import { Brain, Loader2 } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface AvailableModels {
  [provider: string]: string[]
}

interface ResolveResponse {
  task_type: string
  model: string
  assignment: {
    model: string
    temperature?: number
    num_predict?: number
    fallbacks?: string[]
  } | null
  is_default: boolean
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...init?.headers },
    ...init,
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

interface Props {
  task: string
  label: string
}

/**
 * Compact dropdown that writes the LLM router task assignment for a given
 * task type. Used here for "summary" so meetings can be summarised by the
 * model the user prefers (Kimi, Gemini, Claude, local vLLM, etc.).
 */
export function LLMTaskPicker({ task, label }: Props) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  const available = useQuery({
    queryKey: ['llm', 'available-models'],
    queryFn: async () => {
      const data = await fetchJson<{ models_by_provider: AvailableModels }>(
        '/llm/available-models',
      )
      return data.models_by_provider
    },
    staleTime: 5 * 60_000,
  })

  const resolve = useQuery({
    queryKey: ['llm', 'resolve', task],
    queryFn: () => fetchJson<ResolveResponse>(`/llm/resolve/${task}`),
    staleTime: 60_000,
  })

  const assign = useMutation({
    mutationFn: (model: string) =>
      fetchJson(`/llm/task/${task}`, {
        method: 'PUT',
        body: JSON.stringify({ model }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['llm'] })
      toast({ title: 'Model updated' })
    },
    onError: (e) =>
      toast({
        title: 'Could not change model',
        description: String(e),
        variant: 'destructive',
      }),
  })

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (ev: MouseEvent) => {
      const target = ev.target as HTMLElement
      if (!target.closest('[data-llm-picker]')) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const flatModels = useMemo(() => {
    const groups = available.data ?? {}
    return Object.entries(groups).flatMap(([provider, models]) =>
      (models ?? []).map((model) => ({ provider, model })),
    )
  }, [available.data])

  const current = resolve.data?.model ?? '—'
  const isDefault = resolve.data?.is_default ?? false

  return (
    <div className="relative inline-flex" data-llm-picker>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={available.isLoading}
        className="text-xs px-2.5 py-1.5 rounded bg-gray-700/50 text-gray-200 hover:bg-gray-600/60 disabled:opacity-50 flex items-center gap-1"
        title={`${label}: choose the model used for ${task}`}
      >
        <Brain className="w-3 h-3" />
        {label}: <span className="font-mono text-gray-100">{current}</span>
        {isDefault && <span className="text-[10px] text-gray-500 ml-1">(default)</span>}
        {assign.isPending && <Loader2 className="w-3 h-3 animate-spin ml-1" />}
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 w-72 max-h-80 overflow-y-auto rounded border border-gray-700 bg-gray-900 shadow-xl">
          {available.isLoading ? (
            <div className="p-3 text-xs text-gray-400">
              <Loader2 className="w-3 h-3 animate-spin inline mr-1" />
              Loading…
            </div>
          ) : flatModels.length === 0 ? (
            <div className="p-3 text-xs text-gray-400">No models available.</div>
          ) : (
            <div className="py-1">
              {Object.entries(available.data ?? {}).map(([provider, models]) => (
                <div key={provider}>
                  <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-gray-500 sticky top-0 bg-gray-900">
                    {provider}
                  </div>
                  {(models ?? []).map((m) => (
                    <button
                      key={`${provider}/${m}`}
                      onClick={() => {
                        setOpen(false)
                        assign.mutate(m)
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
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
