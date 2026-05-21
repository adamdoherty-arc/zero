import { useMemo } from 'react'
import { Headphones, Volume2, VolumeX } from 'lucide-react'
import {
  useReachyCompanionStatus,
  usePatchCompanionPolicy,
} from '@/hooks/useReachyApi'

/**
 * F-60 — one-click TopBar pill that toggles Reachy speaker output
 * (output_audio_enabled in CompanionPolicy) without leaving the dashboard.
 *
 * States:
 *   • Speaker  → both (Reachy + browser audio)
 *   • Browser  → browser_only (mute Reachy speaker)
 *   • Mute     → output_audio_enabled=false (Reachy + browser silent;
 *                  transcript still streams to UI)
 */
export function SpeakerOutputPill() {
  const status = useReachyCompanionStatus()
  const patch = usePatchCompanionPolicy()
  const policy = status.data?.policy

  const state = useMemo(() => {
    if (!policy) return 'loading' as const
    if (!policy.output_audio_enabled) return 'mute' as const
    if (policy.tts_sink === 'browser_only') return 'browser' as const
    return 'speaker' as const
  }, [policy])

  if (state === 'loading') return null

  const cycle = () => {
    // speaker → browser → mute → speaker
    if (state === 'speaker') {
      patch.mutate({ output_audio_enabled: true, tts_sink: 'browser_only' })
    } else if (state === 'browser') {
      patch.mutate({ output_audio_enabled: false, tts_sink: 'browser_only' })
    } else {
      patch.mutate({ output_audio_enabled: true, tts_sink: 'reachy_speaker' })
    }
  }

  const cfg =
    state === 'speaker'
      ? {
          icon: Volume2,
          label: 'Reachy speaker',
          title: 'Reachy speaker — click to mute Reachy and play through browser',
          tone: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
        }
      : state === 'browser'
        ? {
            icon: Headphones,
            label: 'Headphones',
            title: 'Browser-only output — click to silence both',
            tone: 'border-sky-500/40 bg-sky-500/10 text-sky-200',
          }
        : {
            icon: VolumeX,
            label: 'Muted',
            title: 'No audio (transcript streams to UI) — click to enable Reachy speaker',
            tone: 'border-gray-700 bg-gray-900/50 text-gray-300',
          }
  const Icon = cfg.icon

  return (
    <button
      type="button"
      onClick={cycle}
      title={cfg.title}
      disabled={patch.isPending}
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition disabled:opacity-50 ${cfg.tone}`}
    >
      <Icon className="w-3.5 h-3.5" />
      <span className="hidden md:inline">{cfg.label}</span>
    </button>
  )
}
