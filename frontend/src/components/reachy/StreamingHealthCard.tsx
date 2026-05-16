import { useMemo } from 'react'
import { Activity, Cpu, Mic, Video } from 'lucide-react'
import { useReachyAssistantStatus, useReachyStatus } from '@/hooks/useReachyApi'

/**
 * Streaming health card — Pollen-style "is each subsystem talking?" grid.
 *
 * Surfaces the basics the official Reachy Mini Windows app shows on its
 * Connection Status dashboard, derived from data Zero already pulls. No
 * new backend instrumentation needed — when we add real FPS / latency
 * counters those land here too.
 *
 * Four cards (left to right): Robot, Daemon API, Video, Audio.
 */
export function StreamingHealthCard() {
  const reachy = useReachyStatus(8_000)
  const assistant = useReachyAssistantStatus(8_000)

  const cards = useMemo(() => {
    const status = reachy.data
    const a = assistant.data

    const daemonConnected = status?.daemon_connected ?? false
    const robotReady = status?.robot_ready ?? false
    const motorMode = status?.body_control_mode ?? null
    const inputReady = a?.input_health?.ready ?? false
    const inputSource = a?.input_health?.source ?? 'unknown'
    const outputReady = a?.output_health?.ready ?? false
    const outputSink = a?.output_health?.sink ?? 'unknown'

    // No dedicated video health endpoint yet — derive from daemon
    // reachability + any camera_fault signal in motion_sources.
    const cameraFault = (status?.motion_sources ?? []).some(
      (s) => s.id === 'camera_fault' && s.active,
    )

    return [
      {
        id: 'robot',
        label: 'Robot',
        icon: Activity,
        ok: robotReady,
        detail: robotReady
          ? `motors ${motorMode ?? 'enabled'}`
          : daemonConnected
            ? motorMode === 'disabled'
              ? 'motors disabled'
              : 'body not ready'
            : 'unreachable',
      },
      {
        id: 'daemon',
        label: 'Daemon API',
        icon: Cpu,
        ok: daemonConnected,
        detail: daemonConnected
          ? `uptime ${formatUptime(((status?.supervisor as { uptime_seconds?: number } | undefined)?.uptime_seconds))}`
          : 'no response',
      },
      {
        id: 'video',
        label: 'Video',
        icon: Video,
        ok: daemonConnected && !cameraFault,
        detail: cameraFault
          ? 'camera fault'
          : daemonConnected
            ? 'pipeline ready'
            : 'awaiting daemon',
      },
      {
        id: 'audio',
        label: 'Audio',
        icon: Mic,
        ok: inputReady && outputReady,
        detail: !inputReady
          ? `mic offline (${inputSource})`
          : !outputReady
            ? `speaker offline (${outputSink})`
            : `${inputSource} → ${outputSink}`,
      },
    ]
  }, [reachy.data, assistant.data])

  return (
    <div className="mb-5 grid grid-cols-2 md:grid-cols-4 gap-2">
      {cards.map((card) => {
        const Icon = card.icon
        const tone = card.ok
          ? 'border-green-500/30 bg-green-500/5 text-green-200'
          : 'border-amber-500/30 bg-amber-500/10 text-amber-100'
        return (
          <div
            key={card.id}
            className={`rounded-lg border px-3 py-2 ${tone}`}
            title={card.detail}
          >
            <div className="flex items-center gap-2">
              <Icon className="h-4 w-4 shrink-0 opacity-80" />
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-wide">
                  {card.label}
                </div>
                <div className="text-[11px] opacity-80 truncate">{card.detail}</div>
              </div>
              <span
                className={`ml-auto h-2 w-2 shrink-0 rounded-full ${
                  card.ok ? 'bg-green-400' : 'bg-amber-400'
                }`}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function formatUptime(s: number | null | undefined): string {
  if (s == null || s < 0) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}
