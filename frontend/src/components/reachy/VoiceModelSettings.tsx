import { useMemo } from 'react'
import { Loader2 } from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import {
  useUpdateVoiceConfig,
  useVoiceConfig,
  useVoiceModels,
} from '@/hooks/useReachyVoiceConfig'

interface Props {
  compact?: boolean
}

export function VoiceModelSettings({ compact = false }: Props) {
  const { data: cfg, isLoading: cfgLoading } = useVoiceConfig()
  const { data: models, isLoading: modelsLoading } = useVoiceModels()
  const update = useUpdateVoiceConfig()
  const { toast } = useToast()

  const sttChoices = models?.stt ?? []
  const llmChoices = models?.llm ?? []
  const ttsChoices = models?.tts ?? []

  const currentLlmSpec = cfg?.llm.spec ?? ''

  const llmBySpec = useMemo(() => {
    const map = new Map<string, { provider: string; model: string }>()
    for (const c of llmChoices) map.set(c.spec, { provider: c.provider, model: c.model })
    return map
  }, [llmChoices])

  const handleUpdate = async (patch: {
    stt_model?: string
    llm_model?: string
    tts_voice?: string
  }) => {
    try {
      await update.mutateAsync(patch)
      const [field, value] = Object.entries(patch)[0] ?? ['', '']
      toast({ title: 'Voice config updated', description: `${field} → ${value}` })
    } catch (err) {
      toast({
        title: 'Failed to update voice config',
        description: String(err),
        variant: 'destructive',
      })
    }
  }

  if (cfgLoading || modelsLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <Loader2 className="w-3 h-3 animate-spin" /> Loading voice config…
      </div>
    )
  }
  if (!cfg || !models) {
    return <div className="text-xs text-red-400">Voice config unavailable.</div>
  }

  const rowCls = compact
    ? 'flex items-center gap-2 text-xs'
    : 'flex flex-col gap-1 text-sm'
  const labelCls = compact
    ? 'text-gray-400 w-14 shrink-0'
    : 'text-xs uppercase tracking-wide text-gray-500'
  const selectCls =
    'bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500 flex-1 min-w-0'

  return (
    <div className="flex flex-col gap-3">
      <div className={rowCls}>
        <label className={labelCls}>STT (Whisper)</label>
        <select
          className={selectCls}
          value={cfg.stt_model}
          disabled={update.isPending}
          onChange={(e) => handleUpdate({ stt_model: e.target.value })}
        >
          {sttChoices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} — {c.description}
            </option>
          ))}
        </select>
      </div>

      <div className={rowCls}>
        <label className={labelCls}>LLM (voice_reply)</label>
        <select
          className={selectCls}
          value={currentLlmSpec}
          disabled={update.isPending || llmChoices.length === 0}
          onChange={(e) => handleUpdate({ llm_model: e.target.value })}
        >
          {!llmBySpec.has(currentLlmSpec) && currentLlmSpec && (
            <option value={currentLlmSpec}>{currentLlmSpec} (current)</option>
          )}
          {llmChoices.map((c) => (
            <option key={c.spec} value={c.spec}>
              {c.provider} / {c.model}
            </option>
          ))}
        </select>
      </div>

      <div className={rowCls}>
        <label className={labelCls}>TTS Voice</label>
        <select
          className={selectCls}
          value={cfg.tts_voice}
          disabled={update.isPending}
          onChange={(e) => handleUpdate({ tts_voice: e.target.value })}
        >
          {!ttsChoices.some((c) => c.id === cfg.tts_voice) && (
            <option value={cfg.tts_voice}>{cfg.tts_voice} (current)</option>
          )}
          {ttsChoices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label} ({c.engine})
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
