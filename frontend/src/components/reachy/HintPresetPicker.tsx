/**
 * HintPresetPicker — pick which routing preset hint:* calls use.
 *
 * Backed by ``/api/llm/hints`` (list) + ``/api/llm/hints/preset`` (set).
 * Lives in the ReachyRealtimeSettings modal so the user can flip between
 * "everything local" (zero cost, fast) and "embeddings only" (cheap chat
 * via cloud) without leaving the voice settings.
 */

import { useCallback, useEffect, useState } from 'react'
import { Loader2, Cpu, Cloud, Brain } from 'lucide-react'

import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

interface HintsResponse {
  active_preset: string
  presets: string[]
  hints: Array<{
    name: string
    task_type: string
    resolved_model: string
    local_eligible: boolean
  }>
}

const PRESET_META: Record<string, { label: string; description: string; icon: typeof Cpu }> = {
  default: {
    label: 'Default',
    description: 'Use each task’s normal model assignment.',
    icon: Brain,
  },
  embeddings_only: {
    label: 'Embeddings only',
    description: 'Push chat hints to cloud; reserve local for embeddings.',
    icon: Cloud,
  },
  memory_reflection: {
    label: 'Memory + reflection',
    description: 'Run summarize/reflect/tool_lite locally; default the rest.',
    icon: Brain,
  },
  everything_local: {
    label: 'Everything local',
    description: 'All local-eligible hints route to Local. Heavy hints stay cloud.',
    icon: Cpu,
  },
}

export function HintPresetPicker() {
  const [data, setData] = useState<HintsResponse | null>(null)
  const [saving, setSaving] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const res = await fetch('/api/llm/hints', { headers: getAuthHeaders() })
    if (res.ok) setData(await res.json())
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const pick = useCallback(
    async (preset: string) => {
      setSaving(preset)
      try {
        const res = await fetch('/api/llm/hints/preset', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ preset }),
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          toast({
            title: 'Could not switch preset',
            description: body.detail ?? `HTTP ${res.status}`,
            variant: 'destructive',
          })
          return
        }
        toast({ title: 'Hint preset', description: preset })
        await refresh()
      } finally {
        setSaving(null)
      }
    },
    [refresh],
  )

  if (!data) return null

  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <Cpu className="w-3.5 h-3.5 text-zinc-500" />
        <span className="text-xs font-semibold text-zinc-300">Routing preset</span>
        <span className="text-[10px] text-zinc-500">
          biases every <code>hint:*</code> call
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {data.presets.map((preset) => {
          const meta = PRESET_META[preset] ?? {
            label: preset,
            description: '',
            icon: Brain,
          }
          const active = data.active_preset === preset
          const Icon = meta.icon
          return (
            <button
              key={preset}
              type="button"
              onClick={() => pick(preset)}
              disabled={saving !== null}
              className={[
                'text-left rounded-lg border p-2.5 transition-colors disabled:opacity-50',
                active
                  ? 'bg-emerald-900/30 border-emerald-600 ring-1 ring-emerald-500/40'
                  : 'bg-zinc-900/40 border-zinc-800 hover:border-zinc-600',
              ].join(' ')}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <Icon
                  className={`w-3 h-3 ${active ? 'text-emerald-300' : 'text-zinc-400'}`}
                />
                <span
                  className={`text-xs font-semibold ${active ? 'text-emerald-100' : 'text-zinc-100'}`}
                >
                  {meta.label}
                </span>
                {saving === preset ? (
                  <Loader2 className="w-3 h-3 ml-auto animate-spin text-zinc-400" />
                ) : null}
              </div>
              <p className="text-[11px] text-zinc-400 leading-snug">{meta.description}</p>
            </button>
          )
        })}
      </div>
    </section>
  )
}

export default HintPresetPicker
