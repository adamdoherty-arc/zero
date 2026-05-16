import { CheckCircle2, Mic, Speaker, XCircle, Zap } from 'lucide-react'
import { DaemonPanel } from '@/components/reachy/DaemonPanel'
import { StreamingHealthCard } from '@/components/reachy/StreamingHealthCard'
import { useReachyAssistantStatus, type ReachyAssistantActivity } from '@/hooks/useReachyApi'
import { useSharedRealtimeVoice } from '@/hooks/useSharedRealtimeVoice'

function fmtRelative(epoch: number): string {
  if (!epoch || !Number.isFinite(epoch)) return '—'
  const deltaMs = Date.now() - epoch * 1000
  const s = Math.floor(deltaMs / 1000)
  if (s < 0) return 'now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  return `${h}h ago`
}

function ActivityRow({ a }: { a: ReachyAssistantActivity }) {
  const Icon = a.ok ? CheckCircle2 : XCircle
  const tone = a.ok ? 'text-emerald-300' : 'text-red-300'
  return (
    <li className="flex items-start gap-2 py-1 text-xs">
      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${tone}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-gray-200">{a.event}</span>
          {a.state && <span className="text-[10px] uppercase tracking-wide text-gray-500">{a.state}</span>}
        </div>
        <div className="text-gray-400 truncate" title={a.detail}>
          {a.detail || '—'}
        </div>
      </div>
      <span className="shrink-0 text-[10px] text-gray-500">{fmtRelative(a.at)}</span>
    </li>
  )
}

/**
 * AssistantDebugPanel — the one expander that answers "what is the robot
 * doing right now?". Lives below DaemonStatusBar on /zero.
 *
 * Composes four already-existing surfaces under one toggle:
 *  1. Activity feed — recent assistant events (already on /assistant/status)
 *  2. Session — voice phase / duration / input + output health
 *  3. Daemon — existing DaemonPanel (start/stop/logs/diagnostics/Smart Re-link)
 *  4. Streaming health — existing 4-card grid
 *
 * No new backend endpoints. All data is already on the assistant status
 * payload + the shared realtime voice hook.
 */
export function AssistantDebugPanel() {
  const assistant = useReachyAssistantStatus(5_000)
  const voice = useSharedRealtimeVoice()

  const activity = assistant.data?.recent_activity ?? []
  const phase = voice.sessionPhase ?? assistant.data?.session_phase ?? 'idle'
  const stalledReason = voice.stalledReason ?? assistant.data?.stalled_reason
  const inputHealth = voice.inputHealth ?? assistant.data?.input_health ?? null
  const outputHealth = voice.outputHealth ?? assistant.data?.output_health ?? null

  return (
    <div className="space-y-4">
      {/* === Session — live voice state, mic + speaker readiness === */}
      <div className="glass-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="h-4 w-4 text-indigo-300" />
          <h3 className="text-sm font-semibold text-white">Session</h3>
          <span className="ml-auto text-[10px] uppercase tracking-wide text-gray-500">
            voice {voice.state} · phase {phase}
          </span>
        </div>
        {stalledReason && (
          <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200">
            Stalled: {stalledReason}
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div className="rounded border border-gray-800 bg-gray-900/40 px-3 py-2">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-gray-500">
              <Mic className="h-3.5 w-3.5" /> Microphone
            </div>
            <div className="mt-1 text-xs text-gray-200">
              {inputHealth ? (
                <>
                  <span className="font-semibold">{inputHealth.source ?? '—'}</span>
                  <span className="text-gray-400"> · {inputHealth.ready ? 'ready' : 'not ready'}</span>
                  <span className="text-gray-500"> · {inputHealth.confidence_state ?? 'unknown'}</span>
                  {inputHealth.last_error && (
                    <div className="mt-0.5 text-[11px] text-red-300 truncate" title={inputHealth.last_error}>
                      {inputHealth.last_error}
                    </div>
                  )}
                </>
              ) : (
                <span className="text-gray-500">offline</span>
              )}
            </div>
          </div>
          <div className="rounded border border-gray-800 bg-gray-900/40 px-3 py-2">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-gray-500">
              <Speaker className="h-3.5 w-3.5" /> Speaker
            </div>
            <div className="mt-1 text-xs text-gray-200">
              {outputHealth ? (
                <>
                  <span className="font-semibold">{outputHealth.sink ?? '—'}</span>
                  <span className="text-gray-400"> · {outputHealth.ready ? 'ready' : 'not ready'}</span>
                  {typeof outputHealth.queued_ms === 'number' && (
                    <span className="text-gray-500"> · {Math.round(outputHealth.queued_ms)} ms queued</span>
                  )}
                  {outputHealth.last_error && (
                    <div className="mt-0.5 text-[11px] text-red-300 truncate" title={outputHealth.last_error}>
                      {outputHealth.last_error}
                    </div>
                  )}
                </>
              ) : (
                <span className="text-gray-500">offline</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* === Activity — what the assistant just did === */}
      <div className="glass-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-300" />
          <h3 className="text-sm font-semibold text-white">Recent assistant activity</h3>
          <span className="ml-auto text-[10px] uppercase tracking-wide text-gray-500">
            last {activity.length} events
          </span>
        </div>
        {activity.length === 0 ? (
          <p className="text-xs text-gray-500">No events yet. Start a session or trigger a skill.</p>
        ) : (
          <ul className="divide-y divide-gray-800/60">
            {activity.map((a, i) => (
              <ActivityRow key={`${a.at}-${i}`} a={a} />
            ))}
          </ul>
        )}
      </div>

      {/* === Streaming health — 4-card Pollen-style grid === */}
      <StreamingHealthCard />

      {/* === Daemon — full control panel (start/stop/logs/diagnostics) === */}
      <DaemonPanel />
    </div>
  )
}
