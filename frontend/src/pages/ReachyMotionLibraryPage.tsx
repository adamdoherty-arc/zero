import * as React from 'react'
import { useMemo, useRef, useState } from 'react'
import { Bot, Music, Sparkles, Play, Hand, MoonStar, Sun, Search, UserRound, Mic, MicOff, Timer, Coffee, CalendarClock, Volume2, Loader2, Brain, Trash2, Star, Settings2, X } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { Link } from 'react-router-dom'
import { VoiceModelSettings } from '@/components/reachy/VoiceModelSettings'
import { useVoiceConfig } from '@/hooks/useReachyVoiceConfig'
import {
  useMotionLibrary,
  usePersonas,
  usePlayMotion,
  useReachyStatus,
  useSelectPersona,
  usePreviewPersona,
  usePersonaIntros,
  useSetPersonaIntro,
  useClearPersonaIntro,
  useSequences,
  useRecentMotions,
  useSettleReachyAssistant,
  useWakeUp,
  useGoToSleep,
  usePomodoroState,
  useStartPomodoro,
  useStopPomodoro,
  useMeetingState,
  useStartMeetingMode,
  useStopMeetingMode,
  useContextDebug,
  useUserMemory,
  useAddMemoryNote,
  useDeleteMemoryNote,
  useReachyCompanionStatus,
  type MotionClip,
  type MotionKind,
  type MemoryNote,
} from '@/hooks/useReachyApi'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { AssistantHero } from '@/components/reachy/AssistantHero'
import { AssistantDebugPanel } from '@/components/reachy/AssistantDebugPanel'
import { DaemonStatusBar } from '@/components/reachy/DaemonStatusBar'
import { HostAgentOfflineBanner } from '@/components/reachy/HostAgentOfflineBanner'
import { LlmProviderBanner } from '@/components/reachy/LlmProviderBanner'
import { ReachyCameraViewer } from '@/components/reachy/ReachyCameraViewer'
import { SequenceBuilder } from '@/components/reachy/SequenceBuilder'
import { HardwarePanel, SubPagesNav } from '@/components/reachy/ReachyManagementPanels'
import { useToast } from '@/hooks/use-toast'

function ConnectionBadge() {
  const { data } = useReachyStatus()
  const bodyConnected = data?.connected ?? false
  const bodyReady = data?.robot_ready ?? bodyConnected
  const daemonConnected = data?.daemon_connected ?? false
  const mode = String(data?.body_control_mode ?? '').toLowerCase()
  const bodyActivity = data?.body_activity
  const hardwareFaultSource = data?.motion_sources?.find((source) => source.id === 'hardware_faults')
  const hardwareFault = (data?.active_source_ids ?? []).includes('hardware_faults')
  const hardwareFaultRaw = hardwareFaultSource?.raw as { faults?: unknown[]; stale?: boolean } | undefined
  const staleHardwareFault = Boolean(!hardwareFault && hardwareFaultRaw?.stale && hardwareFaultRaw?.faults?.length)
  const hardwareFaultDetail = hardwareFaultSource?.detail
  const asleep = bodyConnected && !bodyReady && mode === 'disabled'
  const label = hardwareFault
    ? 'Hardware fault'
    : staleHardwareFault
      ? 'Previous fault'
    : bodyActivity === 'shaky'
      ? 'Needs Settle'
      : bodyReady
    ? 'Zero ready'
    : asleep
      ? 'Zero asleep'
      : bodyConnected
        ? 'Body not ready'
        : daemonConnected
          ? 'Daemon only'
          : 'Zero offline'
  const tint = hardwareFault || bodyActivity === 'shaky'
    ? 'bg-red-500/20 text-red-300'
    : staleHardwareFault
      ? 'bg-yellow-500/20 text-yellow-300'
    : bodyReady
    ? 'bg-green-500/20 text-green-400'
    : asleep || daemonConnected
      ? 'bg-yellow-500/20 text-yellow-300'
      : 'bg-red-500/20 text-red-400'
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${tint}`}
      title={hardwareFaultDetail ?? data?.robot_detail ?? data?.base_url}
    >
      {label}
    </span>
  )
}
// Outer timeout on the browser side. Backend budgets 48 s total; we give
// ourselves a 2 s cushion before aborting.
const VOICE_FETCH_TIMEOUT_MS = 50_000

type Phase = 'stt' | 'llm' | 'tts'
type PhaseEntry = {
  phase: Phase
  ms: number
  ok: boolean
  error?: string
  provider?: string | null
  model?: string | null
}
type GestureAction = { kind: string; payload: string; offset?: number }
type ActiveModel = { provider?: string | null; model?: string | null }
type ActiveModels = { stt?: ActiveModel; llm?: ActiveModel; tts?: ActiveModel }

type VoiceTurn = {
  heard: string
  said: string
  gestures: GestureAction[]
  phases: PhaseEntry[]
  activeModels: ActiveModels | null
  error: { stage: string; message: string } | null
}

type UiPhase = 'idle' | 'recording' | 'stt' | 'llm' | 'tts' | 'done' | 'error'

function phaseLabel(p: UiPhase): string {
  switch (p) {
    case 'recording':
      return 'Listening — release to send'
    case 'stt':
      return 'Transcribing…'
    case 'llm':
      return 'Thinking…'
    case 'tts':
      return 'Speaking…'
    case 'error':
      return 'Try again'
    case 'done':
    case 'idle':
    default:
      return 'Hold to talk to Zero'
  }
}

function PhaseIndicator({ phase }: { phase: UiPhase }) {
  const steps: { key: Phase; label: string }[] = [
    { key: 'stt', label: 'Hear' },
    { key: 'llm', label: 'Think' },
    { key: 'tts', label: 'Speak' },
  ]
  const active: Record<Phase, boolean> = {
    stt: phase === 'stt' || phase === 'llm' || phase === 'tts' || phase === 'done',
    llm: phase === 'llm' || phase === 'tts' || phase === 'done',
    tts: phase === 'tts' || phase === 'done',
  }
  const live: Record<Phase, boolean> = {
    stt: phase === 'stt',
    llm: phase === 'llm',
    tts: phase === 'tts',
  }
  return (
    <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
      {steps.map((s, i) => (
        <div key={s.key} className="flex items-center gap-1.5">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              live[s.key]
                ? 'bg-emerald-400 animate-pulse'
                : active[s.key]
                  ? 'bg-emerald-500/70'
                  : 'bg-gray-600'
            }`}
          />
          <span className={active[s.key] ? 'text-gray-200' : 'text-gray-500'}>{s.label}</span>
          {i < steps.length - 1 && <span className="text-gray-600">→</span>}
        </div>
      ))}
    </div>
  )
}

function ActiveStackRow({ models }: { models: ActiveModels | null | undefined }) {
  const { data: cfg } = useVoiceConfig()
  const stt = models?.stt?.model || cfg?.stt_model || '…'
  const sttProv = models?.stt?.provider || 'faster-whisper'
  const llmProv = models?.llm?.provider || cfg?.llm?.provider || '…'
  const llmModel = models?.llm?.model || cfg?.llm?.model || '…'
  const ttsProv = models?.tts?.provider || 'piper'
  const ttsModel = models?.tts?.model || cfg?.tts_voice || '…'
  const Chip = ({ label, value }: { label: string; value: string }) => (
    <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-gray-800/60 text-gray-300 font-mono">
      <span className="text-gray-500 uppercase">{label}</span>
      <span className="text-gray-200">{value}</span>
    </span>
  )
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <Chip label="STT" value={`${sttProv}/${stt}`} />
      <Chip label="LLM" value={`${llmProv}/${llmModel}`} />
      <Chip label="TTS" value={`${ttsProv}/${ttsModel}`} />
    </div>
  )
}

function PushToTalk() {
  const [phase, setPhase] = useState<UiPhase>('idle')
  const [lastResult, setLastResult] = useState<VoiceTurn | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const timeoutRef = useRef<number | null>(null)
  const { toast } = useToast()
  const companion = useReachyCompanionStatus()
  const bodyMotionLocked = companion.data?.policy?.body_motion_enabled === false

  const recording = phase === 'recording'
  const busy = phase === 'stt' || phase === 'llm' || phase === 'tts'

  // Fire-and-forget listening-posture gesture when the user starts holding
  // the mic. Don't await — we don't want to block recording on robot latency.
  const fireListeningPosture = () => {
    if (bodyMotionLocked) return
    fetch('/api/reachy/emotion', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ emotion: 'attentive1' }),
    }).catch(() => undefined)
  }

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mime = MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : MediaRecorder.isTypeSupported('audio/ogg')
          ? 'audio/ogg'
          : ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        if (blob.size < 400) {
          setPhase('idle')
          toast({ title: 'Too short', description: 'Press and hold to speak.', variant: 'destructive' })
          return
        }

        // Optimistic phase progression. The backend returns the real phase_log
        // in one shot after completion; we don't have progressive signal, so
        // we walk stt → llm → tts at rough timing to give the user a sense
        // of progress. If the real phase_log says otherwise when the response
        // arrives, we overwrite.
        setPhase('stt')
        const advanceTimers: number[] = []
        advanceTimers.push(window.setTimeout(() => setPhase((p) => (p === 'stt' ? 'llm' : p)), 1500))
        advanceTimers.push(window.setTimeout(() => setPhase((p) => (p === 'llm' ? 'tts' : p)), 6000))

        const controller = new AbortController()
        abortRef.current = controller
        timeoutRef.current = window.setTimeout(() => controller.abort(), VOICE_FETCH_TIMEOUT_MS)

        try {
          const form = new FormData()
          form.append('audio', blob, 'ptt.webm')
          const response = await fetch('/api/reachy/voice', {
            method: 'POST',
            headers: { ...getAuthHeaders() },
            body: form,
            signal: controller.signal,
          })
          const payload = await response.json().catch(() => ({}))
          if (!response.ok) {
            const detail = payload?.detail
            const stage = typeof detail === 'object' ? detail?.stage ?? 'server' : 'server'
            const message =
              typeof detail === 'object'
                ? detail?.message ?? JSON.stringify(detail)
                : detail ?? `HTTP ${response.status}`
            throw Object.assign(new Error(message), { stage })
          }

          const heard = payload.transcription?.text ?? ''
          const said = payload.llm_response ?? ''
          const gestures: GestureAction[] = Array.isArray(payload.gesture_actions)
            ? payload.gesture_actions
            : []
          const phases: PhaseEntry[] = Array.isArray(payload.phase_log) ? payload.phase_log : []
          const activeModels: ActiveModels | null = payload.active_models ?? null
          const err = payload.error ?? null

          setLastResult({ heard, said, gestures, phases, activeModels, error: err })

          // Play the reply in the browser ONLY when Reachy did not already
          // play it out of its own speaker. Prevents a doubled echo when
          // the robot is connected.
          const playedOnRobot = Boolean(payload.played_on_robot)
          if (!playedOnRobot && payload.audio_response_b64) {
            const audioBytes = Uint8Array.from(atob(payload.audio_response_b64), (c) =>
              c.charCodeAt(0),
            )
            const url = URL.createObjectURL(new Blob([audioBytes], { type: 'audio/wav' }))
            new Audio(url).play().catch(() => undefined)
          }

          if (err) {
            setPhase('error')
            toast({
              title: `Voice stalled at ${err.stage}`,
              description: err.message,
              variant: 'destructive',
            })
          } else {
            setPhase('done')
          }
        } catch (e) {
          const stage = (e as { stage?: string })?.stage ?? 'network'
          const aborted = (e as { name?: string })?.name === 'AbortError'
          const message = aborted
            ? `Timed out after ${VOICE_FETCH_TIMEOUT_MS / 1000}s. Check if the LLM provider is healthy.`
            : String(e)
          setPhase('error')
          toast({
            title: aborted ? 'Voice timed out' : `Voice failed at ${stage}`,
            description: message,
            variant: 'destructive',
          })
        } finally {
          advanceTimers.forEach((t) => window.clearTimeout(t))
          if (timeoutRef.current) {
            window.clearTimeout(timeoutRef.current)
            timeoutRef.current = null
          }
          abortRef.current = null
        }
      }
      recorder.start()
      mediaRecorderRef.current = recorder
      setPhase('recording')
      fireListeningPosture()
    } catch (e) {
      toast({ title: 'Mic access denied', description: String(e), variant: 'destructive' })
    }
  }

  const stop = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
  }

  const phases = lastResult?.phases ?? []
  const gestures = lastResult?.gestures ?? []
  const activeModels = lastResult?.activeModels ?? null

  return (
    <div className="glass-card p-3 mb-4">
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-gray-500">Active stack</span>
          <ActiveStackRow models={activeModels} />
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setShowSettings((s) => !s)}
            className="p-1.5 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-800"
            title="Voice model settings"
          >
            {showSettings ? <X className="w-4 h-4" /> : <Settings2 className="w-4 h-4" />}
          </button>
          <Link
            to="/zero/voice-settings"
            className="text-[10px] px-2 py-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-800"
            title="Open full voice-settings page"
          >
            Full settings
          </Link>
        </div>
      </div>

      {showSettings && (
        <div className="mb-3 p-3 rounded border border-gray-800 bg-gray-900/40">
          <VoiceModelSettings compact />
        </div>
      )}

      <div className="flex items-start gap-3 flex-wrap">
        <button
          onMouseDown={start}
          onMouseUp={stop}
          onMouseLeave={() => recording && stop()}
          onTouchStart={(e) => {
            e.preventDefault()
            start()
          }}
          onTouchEnd={(e) => {
            e.preventDefault()
            stop()
          }}
          disabled={busy}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg font-semibold select-none ${
            recording
              ? 'bg-red-500/30 text-red-200 ring-2 ring-red-500'
              : busy
                ? 'bg-gray-700 text-gray-300'
                : phase === 'error'
                  ? 'bg-amber-500/20 text-amber-300 hover:bg-amber-500/30'
                  : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'
          }`}
        >
          {recording ? <MicOff className="w-5 h-5 animate-pulse" /> : <Mic className="w-5 h-5" />}
          {phaseLabel(phase)}
        </button>

        <div className="flex-1 min-w-0">
          <PhaseIndicator phase={phase} />
          {lastResult?.heard && (
            <div className="text-xs text-gray-400 truncate mt-1.5">
              <span className="text-gray-500">you: </span>
              {lastResult.heard}
            </div>
          )}
          {lastResult?.said && (
            <div className="text-xs text-white truncate">
              <span className="text-gray-500">zero: </span>
              {lastResult.said}
            </div>
          )}
          {(gestures.length > 0 || phases.length > 0) && (
            <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
              {gestures.map((g, i) => (
                <span
                  key={`g-${i}`}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-500/20 text-fuchsia-300"
                  title={`${g.kind}:${g.payload}`}
                >
                  🎭 {g.payload}
                </span>
              ))}
              {phases.map((p, i) => {
                const model = p.model ? ` · ${p.provider ?? ''}${p.provider ? '/' : ''}${p.model}` : ''
                return (
                  <span
                    key={`p-${i}`}
                    className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                      p.ok ? 'bg-gray-800/60 text-gray-400' : 'bg-red-500/20 text-red-300'
                    }`}
                    title={p.error ? `${p.phase}: ${p.error}` : `${p.phase}${model}`}
                  >
                    {p.phase} {(p.ms / 1000).toFixed(1)}s
                    {p.model && (
                      <span className="opacity-60 ml-1">
                        {p.provider ?? ''}{p.provider ? '/' : ''}{p.model}
                      </span>
                    )}
                  </span>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function PersonaPicker() {
  const { data } = usePersonas()
  const select = useSelectPersona()
  const preview = usePreviewPersona()
  const intros = usePersonaIntros()
  const setIntro = useSetPersonaIntro()
  const clearIntro = useClearPersonaIntro()
  const sequences = useSequences()
  const [lastPreview, setLastPreview] = useState<{
    persona_id: string
    line: string
    gesture: string | null
  } | null>(null)
  const { toast } = useToast()

  if (!data) return null
  const active = data.personas.find((p) => p.id === data.active_id)
  const currentIntroId = active ? intros.data?.map[active.id] ?? null : null
  const availableSequences = sequences.data?.sequences ?? []

  const onChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value
    try {
      await select.mutateAsync(id)
      const p = data.personas.find((x) => x.id === id)
      toast({ title: `Persona: ${p?.name ?? id}`, description: p?.tagline })
    } catch (err) {
      toast({ title: 'Failed to switch persona', description: String(err), variant: 'destructive' })
    }
  }

  const onPreview = async () => {
    if (!active) return
    try {
      const res = await preview.mutateAsync(active.id)
      // Only play in the browser when Reachy did NOT speak it. Otherwise
      // we'd get a doubled echo: once out of Reachy, once out of the laptop.
      if (!res.played_on_robot) {
        const bytes = Uint8Array.from(atob(res.audio_b64), (c) => c.charCodeAt(0))
        const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
        new Audio(url).play().catch(() => undefined)
      }
      setLastPreview({ persona_id: res.persona_id, line: res.line, gesture: res.gesture })
    } catch (err) {
      toast({ title: 'Preview failed', description: String(err), variant: 'destructive' })
    }
  }

  return (
    <div className="glass-card p-3 mb-4">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-fuchsia-500/10">
          <UserRound className="w-5 h-5 text-fuchsia-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-400 mb-0.5">Active persona</div>
          <div className="flex items-center gap-2">
            <select
              value={data.active_id}
              onChange={onChange}
              disabled={select.isPending}
              className="flex-1 bg-gray-800/70 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-fuchsia-500"
            >
              {data.personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onPreview}
              disabled={preview.isPending || !active}
              title={active?.preview_line ?? 'Preview persona voice'}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-fuchsia-500/40 text-fuchsia-300 hover:bg-fuchsia-500/20 disabled:opacity-50 disabled:cursor-wait"
            >
              {preview.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Volume2 className="w-3.5 h-3.5" />
              )}
              Preview
            </button>
          </div>
          {active && (
            <p className="text-xs text-gray-500 mt-1 italic truncate">{active.tagline}</p>
          )}
          {active && availableSequences.length > 0 && (
            <div className="flex items-center gap-2 mt-2 text-[11px]">
              <span className="text-gray-500">Intro sequence:</span>
              <select
                value={currentIntroId ?? ''}
                onChange={async (e) => {
                  const v = e.target.value
                  try {
                    if (!v) {
                      await clearIntro.mutateAsync(active.id)
                      toast({ title: `${active.name}: intro cleared` })
                    } else {
                      await setIntro.mutateAsync({
                        persona_id: active.id,
                        sequence_id: Number(v),
                      })
                      toast({ title: `${active.name}: intro set` })
                    }
                  } catch (err) {
                    toast({ title: 'Failed to update intro', description: String(err), variant: 'destructive' })
                  }
                }}
                className="text-[11px] bg-gray-800/70 border border-gray-700 rounded px-1.5 py-0.5 text-gray-200"
              >
                <option value="">(none)</option>
                {availableSequences.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <span className="text-gray-600">— fires when you switch to this persona</span>
            </div>
          )}
          {lastPreview && lastPreview.persona_id === active?.id && (
            <div className="flex items-center gap-2 mt-1.5 text-[11px]">
              <span className="text-gray-400">🔊 {lastPreview.line}</span>
              {lastPreview.gesture && (
                <span className="px-1.5 py-0.5 rounded bg-fuchsia-500/20 text-fuchsia-300">
                  also played: {lastPreview.gesture}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ClipCard({
  clip,
  onPlay,
  busy,
  isFavorite,
  onToggleFavorite,
}: {
  clip: MotionClip
  onPlay: () => void
  busy: boolean
  isFavorite: boolean
  onToggleFavorite: () => void
}) {
  return (
    <div
      onClick={onPlay}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onPlay()
      }}
      aria-disabled={busy}
      className={`glass-card-hover p-3 text-left flex flex-col gap-1 relative cursor-pointer ${
        busy ? 'opacity-50 pointer-events-none' : ''
      }`}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onToggleFavorite()
        }}
        title={isFavorite ? 'Zero knows you like this. Click to forget.' : 'Tell Zero you prefer this clip'}
        className={`absolute top-1.5 right-1.5 p-1 rounded hover:bg-white/10 ${
          isFavorite ? 'text-amber-300' : 'text-gray-600 hover:text-amber-300'
        }`}
      >
        <Star className="w-3.5 h-3.5" fill={isFavorite ? 'currentColor' : 'none'} />
      </button>
      <div className="flex items-center justify-between gap-2 pr-6">
        <span className="font-semibold text-sm text-white truncate" title={clip.name}>
          {clip.name}
        </span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full ${
            clip.kind === 'emotion'
              ? 'bg-indigo-500/20 text-indigo-300'
              : 'bg-fuchsia-500/20 text-fuchsia-300'
          }`}
        >
          {clip.kind}
        </span>
      </div>
      <p className="text-xs text-gray-400 line-clamp-2">{clip.description}</p>
      {clip.aliases.length > 0 && (
        <p className="text-[10px] text-gray-500 truncate">
          aliases: {clip.aliases.join(', ')}
        </p>
      )}
    </div>
  )
}

const FAVORITE_CLIP_PREFIX = 'favorite clip: '

export function ReachyMotionLibraryPage() {
  const [debugOpen, setDebugOpen] = useState(false)
  const [kindFilter, setKindFilter] = useState<MotionKind | 'all'>('all')
  const [q, setQ] = useState('')
  const effectiveKind = kindFilter === 'all' ? undefined : kindFilter
  const { data, isLoading } = useMotionLibrary(effectiveKind)
  const play = usePlayMotion()
  const settle = useSettleReachyAssistant()
  const wakeUp = useWakeUp()
  const sleep = useGoToSleep()
  const companion = useReachyCompanionStatus()
  const memory = useUserMemory()
  const addNote = useAddMemoryNote()
  const deleteNote = useDeleteMemoryNote()
  const { toast } = useToast()
  const bodyMotionLocked = companion.data?.policy?.body_motion_enabled === false

  // Map clip name -> note id so we can toggle favorites. Notes stored as
  // preferences with text `favorite clip: <name>` are what Reachy ingests
  // as a durable liking, which means the persona prompt will see this
  // preference next time you talk.
  const favoriteNoteIdByClip = useMemo(() => {
    const out: Record<string, string> = {}
    for (const n of memory.data?.notes ?? []) {
      if (n.category === 'preference' && n.text.startsWith(FAVORITE_CLIP_PREFIX)) {
        const name = n.text.slice(FAVORITE_CLIP_PREFIX.length).trim()
        if (name) out[name] = n.id
      }
    }
    return out
  }, [memory.data])

  const toggleFavorite = async (clip: MotionClip) => {
    const existingId = favoriteNoteIdByClip[clip.name]
    try {
      if (existingId) {
        await deleteNote.mutateAsync(existingId)
        toast({ title: `Forgot favorite: ${clip.name}` })
      } else {
        await addNote.mutateAsync({
          category: 'preference',
          text: `${FAVORITE_CLIP_PREFIX}${clip.name}`,
          confidence: 1.0,
        })
        toast({ title: `Zero will remember you like ${clip.name}` })
      }
    } catch (err) {
      toast({ title: 'Favorite update failed', description: String(err), variant: 'destructive' })
    }
  }

  const filteredByCategory = useMemo(() => {
    if (!data) return {}
    const needle = q.trim().toLowerCase()
    const out: Record<string, MotionClip[]> = {}
    for (const [cat, clips] of Object.entries(data.by_category)) {
      const picks = needle
        ? clips.filter(
            (c) =>
              c.name.toLowerCase().includes(needle) ||
              c.description.toLowerCase().includes(needle) ||
              c.aliases.some((a) => a.toLowerCase().includes(needle)),
          )
        : clips
      if (picks.length) out[cat] = picks
    }
    return out
  }, [data, q])

  const handlePlay = async (clip: MotionClip) => {
    if (bodyMotionLocked) {
      toast({
        title: 'Body motion locked',
        description: 'Unlock body motion in companion policy before playing clips.',
        variant: 'destructive',
      })
      return
    }
    try {
      const result = await play.mutateAsync({ name: clip.name, kind: clip.kind })
      if ((result as { error?: string })?.error) {
        toast({
          title: `Failed to play ${clip.name}`,
          description: (result as { error?: string }).error,
          variant: 'destructive',
        })
      } else {
        toast({ title: `Playing ${clip.name}`, description: clip.description })
      }
    } catch (e) {
      toast({
        title: `Failed to play ${clip.name}`,
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  const handleSettle = async () => {
    try {
      const result = await settle.mutateAsync({
        keep_motors_enabled: false,
        neutral_pose: 'skip',
        reason: 'body_tab',
      })
      toast({
        title: result.body_activity === 'shaky' ? 'Zero settled, but jitter remains' : 'Zero settled',
        description:
          result.active_source_ids.length > 0
            ? `Still active: ${result.active_source_ids.join(', ')}`
            : 'Body motion sources are clear.',
        variant: result.body_activity === 'shaky' ? 'destructive' : 'default',
      })
    } catch (err) {
      toast({ title: 'Settle failed', description: String(err), variant: 'destructive' })
    }
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <HostAgentOfflineBanner />
      <LlmProviderBanner />

      <div className="flex items-center justify-between gap-4 mb-5 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-500/10">
            <Bot className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Zero Cockpit</h1>
            <p className="text-sm text-gray-400">
              Talk to Zero, watch what it sees, and debug — all in one place.
            </p>
          </div>
          <ConnectionBadge />
        </div>
      </div>

      {/* === HERO: merged console + assistant on the left, live camera on the right === */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px] gap-4 mb-4">
        <AssistantHero />
        <ReachyCameraViewer height={420} />
      </div>

      {/* === DAEMON STATUS BAR + DEBUG (one expander for everything Reachy is doing) === */}
      <DaemonStatusBar isOpen={debugOpen} onToggle={() => setDebugOpen((v) => !v)} />
      {debugOpen && (
        <div className="mt-4">
          <AssistantDebugPanel />
        </div>
      )}

      {/* === Collapsible: Presence & memory (default-closed; hero covers the live surface) === */}
      <details className="mb-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-gray-400 uppercase tracking-wider mt-4 mb-2 select-none">
          Presence &amp; memory
        </summary>
        <PersonaPicker />
        <ContextChips />
        <PushToTalk />
        <MemoryCard />
      </details>

      {/* === Collapsible: Body controls === */}
      <details className="mb-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-gray-400 uppercase tracking-wider mt-4 mb-2 select-none">
          Body controls
        </summary>
        <div className="glass-card mb-5 p-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="text-sm font-semibold text-white">Body Safety</div>
              <div className="text-xs text-gray-400">
                {bodyMotionLocked
                  ? 'Body motion is locked. Voice, camera, and memory stay available.'
                  : 'Settle is the calm default. Wake and Sleep are explicit body actions.'}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => void handleSettle()}
                disabled={settle.isPending}
                className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 text-emerald-200 bg-emerald-700/40 border-emerald-600/50 disabled:opacity-50"
              >
                {settle.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />}
                Settle
              </button>
              <button
                onClick={() => wakeUp.mutate()}
                disabled={bodyMotionLocked || wakeUp.isPending}
                title={bodyMotionLocked ? 'Body motion is locked' : 'Wake Zero'}
                className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
              >
                <Sun className="w-4 h-4" /> Wake
              </button>
              <button
                onClick={() => sleep.mutate()}
                disabled={bodyMotionLocked || sleep.isPending}
                title={bodyMotionLocked ? 'Body motion is locked' : 'Sleep Zero'}
                className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
              >
                <MoonStar className="w-4 h-4" /> Sleep
              </button>
            </div>
          </div>
        </div>
        <HardwarePanel />
        <RecentMotionsStrip />
      </details>

      {/* === Collapsible: Automations === */}
      <details className="mb-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-gray-400 uppercase tracking-wider mt-4 mb-2 select-none">
          Automations
        </summary>
        <ModesPanel />
      </details>

      {/* === Collapsible: More Zero (sub-pages) === */}
      <details className="mb-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-gray-400 uppercase tracking-wider mt-4 mb-2 select-none">
          More Zero
        </summary>
        <SubPagesNav />
      </details>

      {/* === Collapsible: Motion library === */}
      <details className="mb-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-gray-400 uppercase tracking-wider mt-4 mb-2 select-none">
          Motion library
        </summary>
        <RecentMotionsStrip />
        <SequenceBuilder />

        {bodyMotionLocked && (
          <div className="mb-4 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            Body motion is locked. Clips and sequences are saved, but playback stays disabled until the robot is physically stable.
          </div>
        )}

        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <div className="flex items-center gap-1 bg-gray-800/50 rounded-lg p-1">
            {(['all', 'emotion', 'dance'] as const).map((k) => (
              <button
                key={k}
                onClick={() => setKindFilter(k)}
                className={`px-3 py-1 text-sm rounded flex items-center gap-1.5 ${
                  kindFilter === k ? 'bg-indigo-500/30 text-white' : 'text-gray-400 hover:text-white'
                }`}
              >
                {k === 'emotion' && <Sparkles className="w-3.5 h-3.5" />}
                {k === 'dance' && <Music className="w-3.5 h-3.5" />}
                {k === 'all' && <Play className="w-3.5 h-3.5" />}
                <span className="capitalize">{k}</span>
              </button>
            ))}
          </div>
          <div className="relative flex-1 min-w-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search clips, descriptions, or aliases…"
              className="w-full pl-8 pr-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded-lg focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        {isLoading && <LoadingSkeleton />}

        {data && (
          <div className="space-y-6">
            {Object.entries(filteredByCategory)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([category, clips]) => (
                <section key={category}>
                  <h2 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wide">
                    {category}{' '}
                    <span className="text-gray-500 font-normal">({clips.length})</span>
                  </h2>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                    {clips.map((clip) => (
                      <ClipCard
                        key={`${clip.kind}-${clip.name}`}
                        clip={clip}
                        onPlay={() => handlePlay(clip)}
                        busy={play.isPending || bodyMotionLocked}
                        isFavorite={Boolean(favoriteNoteIdByClip[clip.name])}
                        onToggleFavorite={() => toggleFavorite(clip)}
                      />
                    ))}
                  </div>
                </section>
              ))}
            {Object.keys(filteredByCategory).length === 0 && (
              <p className="text-center text-gray-500 py-12">No clips match {JSON.stringify(q)}.</p>
            )}
          </div>
        )}
      </details>
    </div>
  )
}

function ModesPanel() {
  const pomo = usePomodoroState()
  const startPomo = useStartPomodoro()
  const stopPomo = useStopPomodoro()
  const meeting = useMeetingState()
  const startMeeting = useStartMeetingMode()
  const stopMeeting = useStopMeetingMode()
  const companion = useReachyCompanionStatus()
  const { toast } = useToast()

  const pomoActive = pomo.data?.active ?? false
  const meetingActive = meeting.data?.active ?? false
  const bodyMotionLocked = companion.data?.policy?.body_motion_enabled === false
  const [focusMin, setFocusMin] = useState(25)
  const [breakMin, setBreakMin] = useState(5)

  const formatElapsed = (s: number | null | undefined) => {
    if (!s) return '0s'
    if (s < 60) return `${s.toFixed(0)}s`
    return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`
  }

  return (
    <div className="glass-card p-4 mb-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Timer className="w-4 h-4" /> Modes
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Pomodoro */}
        <div className="bg-gray-800/40 rounded p-3">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
            <Coffee className="w-3 h-3" /> Pomodoro
          </div>
          {pomoActive ? (
            <div className="space-y-2">
              <div className="text-sm">
                <span className={`font-semibold ${pomo.data?.phase === 'focus' ? 'text-red-300' : 'text-emerald-300'}`}>
                  {pomo.data?.phase}
                </span>
                <span className="text-gray-400 ml-2">· cycle {pomo.data?.cycle_index}</span>
              </div>
              <div className="text-xs text-gray-400 font-mono">{formatElapsed(pomo.data?.elapsed_s)} elapsed</div>
              <button
                onClick={async () => {
                  try { await stopPomo.mutateAsync(); toast({ title: 'Pomodoro stopped' }) }
                  catch (e) { toast({ title: 'Stop failed', description: String(e), variant: 'destructive' }) }
                }}
                className="w-full px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
              >
                Stop
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-[10px] text-gray-500">Focus</label>
                  <input type="number" min={5} max={90} value={focusMin} onChange={(e) => setFocusMin(Number(e.target.value))}
                    className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-1 py-0.5" />
                </div>
                <div className="flex-1">
                  <label className="text-[10px] text-gray-500">Break</label>
                  <input type="number" min={1} max={30} value={breakMin} onChange={(e) => setBreakMin(Number(e.target.value))}
                    className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-1 py-0.5" />
                </div>
              </div>
              <button
                onClick={() => startPomo.mutate({ focus_minutes: focusMin, break_minutes: breakMin })}
                disabled={startPomo.isPending || bodyMotionLocked}
                title={bodyMotionLocked ? 'Body motion is locked' : 'Start pomodoro gestures'}
                className="w-full px-2 py-1 text-xs font-semibold bg-red-500/20 text-red-300 hover:bg-red-500/30 rounded"
              >
                Start {focusMin}/{breakMin}
              </button>
            </div>
          )}
        </div>

        {/* Meeting mode */}
        <div className="bg-gray-800/40 rounded p-3">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
            <Mic className="w-3 h-3" /> Meeting mode
          </div>
          {meetingActive ? (
            <div className="space-y-2">
              <div className="text-sm text-amber-300 font-semibold">Looking at speaker</div>
              <div className="text-xs text-gray-400 font-mono">{formatElapsed(meeting.data?.elapsed_s)}</div>
              {meeting.data?.doa_available === false && (
                <div className="text-[10px] text-amber-400/80 bg-amber-500/10 border border-amber-500/30 rounded px-1.5 py-1">
                  DoA unavailable. Head-tracking is off. Check host_agent + robot daemon mics.
                </div>
              )}
              <button
                onClick={async () => {
                  try { await stopMeeting.mutateAsync(); toast({ title: 'Meeting mode off' }) }
                  catch (e) { toast({ title: 'Stop failed', description: String(e), variant: 'destructive' }) }
                }}
                className="w-full px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
              >
                Exit meeting
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-gray-500">Tracks DoA and plays attentive gestures.</p>
              <button
                onClick={async () => {
                  try { await startMeeting.mutateAsync(undefined); toast({ title: 'Meeting mode on' }) }
                  catch (e) { toast({ title: 'Start failed', description: String(e), variant: 'destructive' }) }
                }}
                disabled={startMeeting.isPending || bodyMotionLocked}
                title={bodyMotionLocked ? 'Body motion is locked' : 'Start meeting mode'}
                className="w-full px-2 py-1 text-xs font-semibold bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 rounded disabled:opacity-50"
              >
                Start meeting mode
              </button>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

function MemoryCard() {
  const { data } = useUserMemory()
  const add = useAddMemoryNote()
  const remove = useDeleteMemoryNote()
  const { toast } = useToast()
  const [draft, setDraft] = useState('')
  const [draftCat, setDraftCat] =
    useState<MemoryNote['category']>('preference')

  const notes = data?.notes ?? []
  const stats = data?.stats

  const byCat: Record<MemoryNote['category'], MemoryNote[]> = {
    preference: [],
    correction: [],
    fact: [],
    topic: [],
  }
  for (const n of notes) {
    if (n.category in byCat) byCat[n.category].push(n)
  }

  const onAdd = async () => {
    const text = draft.trim()
    if (!text) return
    try {
      await add.mutateAsync({ category: draftCat, text })
      setDraft('')
      toast({ title: 'Zero will remember that.' })
    } catch (e) {
      toast({ title: 'Could not save note', description: String(e), variant: 'destructive' })
    }
  }

  const onDelete = async (id: string) => {
    try {
      await remove.mutateAsync(id)
    } catch (e) {
      toast({ title: 'Delete failed', description: String(e), variant: 'destructive' })
    }
  }

  const catStyle: Record<MemoryNote['category'], string> = {
    preference: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    correction: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    fact: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
    topic: 'bg-gray-700/50 text-gray-300 border-gray-600',
  }

  return (
    <div className="glass-card p-4 mb-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide flex items-center gap-2">
          <Brain className="w-4 h-4" /> Zero remembers
        </h2>
        {stats && (
          <div className="text-[11px] text-gray-500">
            {stats.total_turns} conversations · {stats.notes_count} notes
          </div>
        )}
      </div>

      {notes.length === 0 ? (
        <p className="text-xs text-gray-500 italic mb-3">
          No notes yet. After a few turns Zero will start remembering things about you
          automatically, or add one below.
        </p>
      ) : (
        <div className="space-y-2 mb-3">
          {(['preference', 'correction', 'fact', 'topic'] as const).map((cat) =>
            byCat[cat].length > 0 ? (
              <div key={cat}>
                <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                  {cat}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {byCat[cat].map((n) => (
                    <span
                      key={n.id}
                      className={`group inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded border ${catStyle[cat]}`}
                      title={`confidence ${n.confidence.toFixed(2)} · used ${n.uses}x`}
                    >
                      {n.text}
                      <button
                        type="button"
                        onClick={() => onDelete(n.id)}
                        disabled={remove.isPending}
                        className="opacity-60 hover:opacity-100 transition-opacity"
                        aria-label="Forget this"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ) : null,
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <select
          value={draftCat}
          onChange={(e) => setDraftCat(e.target.value as MemoryNote['category'])}
          className="text-xs bg-gray-800/70 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
        >
          <option value="preference">preference</option>
          <option value="correction">correction</option>
          <option value="fact">fact</option>
          <option value="topic">topic</option>
        </select>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onAdd()
          }}
          placeholder="Teach Zero something durable about you…"
          className="flex-1 text-xs bg-gray-800/70 border border-gray-700 rounded px-2 py-1.5 text-white focus:outline-none focus:border-fuchsia-500"
        />
        <button
          type="button"
          onClick={onAdd}
          disabled={add.isPending || !draft.trim()}
          className="text-xs px-3 py-1.5 rounded bg-fuchsia-500/20 text-fuchsia-300 hover:bg-fuchsia-500/30 disabled:opacity-50"
        >
          Remember
        </button>
      </div>
    </div>
  )
}

function ContextChips() {
  const { data } = useContextDebug()
  const ctx = data?.context
  if (!ctx) return null

  const chips: { key: string; emoji: string; label: string; highlight?: boolean }[] = []

  if (ctx.local_time) {
    const tod = ctx.time_of_day ? ` ${ctx.time_of_day}` : ''
    chips.push({ key: 'time', emoji: '🕒', label: `${ctx.local_time}${tod}` })
  }
  if (ctx.pomodoro) {
    const m = Math.floor((ctx.pomodoro.elapsed_s ?? 0) / 60)
    chips.push({
      key: 'pomo',
      emoji: '🎯',
      label: `Pomodoro: ${ctx.pomodoro.phase} (${m}m elapsed)`,
      highlight: ctx.pomodoro.phase === 'focus',
    })
  }
  if (ctx.meeting) {
    chips.push({ key: 'meeting', emoji: '🤝', label: 'Meeting mode on', highlight: true })
  }
  if (ctx.upcoming) {
    const mins = ctx.upcoming.minutes
    const when =
      mins === null
        ? 'soon'
        : mins < 1
          ? 'now'
          : `in ${Math.round(mins)}m`
    chips.push({
      key: 'upcoming',
      emoji: '📅',
      label: `Next: ${ctx.upcoming.label} ${when}`,
      highlight: ctx.upcoming.imminent,
    })
  }
  if (ctx.sight) {
    chips.push({ key: 'sight', emoji: '👀', label: `Can see: ${ctx.sight}` })
  }
  if (ctx.attention) {
    const map: Record<string, string> = {
      with_reachy: 'Engaged with Zero',
      at_screen: 'At screen',
      moving: 'Moving around',
      away: 'Away from desk',
    }
    chips.push({
      key: 'attention',
      emoji: '🙂',
      label: map[ctx.attention] ?? ctx.attention,
    })
  }

  if (chips.length === 0) return null

  return (
    <div className="glass-card p-3 mb-4">
      <div className="flex items-center gap-2 mb-2">
        <CalendarClock className="w-4 h-4 text-indigo-400" />
        <h2 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          What Zero knows right now
        </h2>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        {chips.map((c) => (
          <span
            key={c.key}
            className={`text-[11px] px-2 py-1 rounded-full ${
              c.highlight
                ? 'bg-amber-500/20 text-amber-200 border border-amber-500/40'
                : 'bg-gray-800/60 text-gray-300'
            }`}
          >
            {c.emoji} {c.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function RecentMotionsStrip() {
  const { data } = useRecentMotions(8)
  const play = usePlayMotion()
  const motions = data?.motions ?? []
  if (motions.length === 0) return null

  const relTime = (ts: number) => {
    const diff = Date.now() / 1000 - ts
    if (diff < 60) return `${Math.floor(diff)}s`
    if (diff < 3600) return `${Math.floor(diff / 60)}m`
    return `${Math.floor(diff / 3600)}h`
  }

  return (
    <div className="glass-card p-3 mb-4">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="w-4 h-4 text-indigo-400" />
        <h2 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">
          Recent motions
        </h2>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {motions.map((m, i) => (
          <button
            key={`${m.name}-${m.ts}-${i}`}
            onClick={() => play.mutate({ name: m.name, kind: m.kind === 'dance' ? 'dance' : 'emotion' })}
            className="group flex items-center gap-1.5 px-2 py-1 text-[11px] rounded bg-gray-800/60 hover:bg-indigo-500/20 hover:text-white text-gray-300 transition-colors"
            title={`Replay ${m.name} (${m.kind})`}
          >
            <Play className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
            <span>{m.name}</span>
            <span className="text-gray-500">· {relTime(m.ts)} ago</span>
          </button>
        ))}
      </div>
    </div>
  )
}
