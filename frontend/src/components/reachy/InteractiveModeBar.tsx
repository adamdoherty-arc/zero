import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Mic, MicOff, Loader2, AlertCircle, Radio, X } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import { useSharedRealtimeVoice } from '@/hooks/useSharedRealtimeVoice'

/**
 * Primary "Interactive Mode" toggle lives in the TopBar. One click puts
 * Reachy into a live bidirectional voice session (OpenAI Realtime or Gemini
 * Live WebSocket) — same "just works" UX as the native Pollen conversation
 * app. No settings-cog navigation required.
 *
 * States:
 *   off         — grey, "Talk to Reachy" pill. Space / Ctrl+Shift+J to start.
 *   connecting  — amber pulsing dot, "Connecting…"
 *   listening   — emerald dot + pulse, shows session duration + cost. Robot
 *                 is awake and listening; speak naturally.
 *   speaking    — indigo dot + animated 3-bar waveform.
 *   error       — red dot, error text, click to retry.
 *
 * Idle auto-off: if no user speech frame arrives for IDLE_TIMEOUT_MS the
 * session auto-disconnects so we don't bleed cost while you walk away. The
 * timer resets on every user.speech_started event from the backend.
 */

interface RealtimeCfg {
  backend: 'local' | 'openai' | 'gemini'
  preferred_backend: 'local' | 'openai' | 'gemini' | null
  realtime_available: boolean
  has_openai_key: boolean
  has_gemini_key: boolean
  profile: string | null
  voice: string
  model: string
  idle_timeout_min?: number
  hotkey_enabled?: boolean
  cost_cap_usd?: number
}

const POLL_ACTIVITY_MS = 10_000        // check idle every 10 s

const BACKEND_LABELS: Record<string, string> = {
  local: 'Local (vLLM)',
  openai: 'OpenAI Realtime',
  gemini: 'Gemini Live',
}

export function InteractiveModeBar() {
  const [cfg, setCfg] = useState<RealtimeCfg | null>(null)
  const [durationSec, setDurationSec] = useState(0)

  const voice = useSharedRealtimeVoice()
  const connectStartedAtRef = useRef<number | null>(null)
  const lastActivityAtRef = useRef<number>(0)

  const loadCfg = useCallback(async () => {
    try {
      const res = await fetch('/api/reachy/realtime/config', { headers: getAuthHeaders() })
      if (!res.ok) return
      setCfg((await res.json()) as RealtimeCfg)
    } catch {
      /* optional */
    }
  }, [])

  useEffect(() => {
    void loadCfg()
  }, [loadCfg])

  // Session-duration ticker. Only runs while connected to avoid unnecessary work.
  useEffect(() => {
    if (voice.state !== 'connected') {
      connectStartedAtRef.current = null
      setDurationSec(0)
      return
    }
    connectStartedAtRef.current = Date.now()
    lastActivityAtRef.current = Date.now()
    const id = window.setInterval(() => {
      if (connectStartedAtRef.current !== null) {
        setDurationSec(Math.floor((Date.now() - connectStartedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [voice.state])

  // Reset the idle timer whenever the user speaks — user.speech_started
  // arrives as a transcript event, so watch the transcripts array length
  // (cheaper than wiring a dedicated callback).
  useEffect(() => {
    if (voice.state === 'connected' && voice.transcripts.length > 0) {
      lastActivityAtRef.current = Date.now()
    }
  }, [voice.state, voice.transcripts.length])

  // Idle auto-off — drop the session if nobody's spoken in N minutes.
  // Configurable via the realtime settings dialog (idle_timeout_min).
  useEffect(() => {
    if (voice.state !== 'connected') return
    const idleMs = (cfg?.idle_timeout_min ?? 5) * 60 * 1000
    const capUsd = cfg?.cost_cap_usd ?? 0
    const id = window.setInterval(() => {
      if (Date.now() - lastActivityAtRef.current > idleMs) {
        toast({
          title: 'Interactive Mode idle',
          description: `No voice for ${idleMs / 60_000} min — session ended. Click to resume.`,
        })
        void voice.stop()
      } else if (capUsd > 0 && voice.cost >= capUsd) {
        toast({
          variant: 'destructive',
          title: 'Cost cap reached',
          description: `Live session ended after $${voice.cost.toFixed(2)} (cap $${capUsd.toFixed(2)}).`,
        })
        void voice.stop()
      }
    }, POLL_ACTIVITY_MS)
    return () => window.clearInterval(id)
  }, [voice.state, voice, cfg?.idle_timeout_min, cfg?.cost_cap_usd])

  const realtimeAvailable = Boolean(cfg?.realtime_available)
  const effectiveBackend = cfg?.preferred_backend ?? cfg?.backend ?? 'local'

  const toggle = useCallback(async () => {
    if (!cfg) return
    // Connecting → click acts as Cancel/abort. Without this the button
    // was disabled and the user had no escape from a stalled handshake.
    if (voice.state === 'connecting') {
      await voice.cancel()
      return
    }
    if (voice.state === 'connected') {
      await voice.stop()
      return
    }
    if (!realtimeAvailable) {
      toast({
        variant: 'destructive',
        title: 'Interactive Mode is unavailable',
        description: 'Local realtime is failing to initialize. Check that vLLM is up at host.docker.internal:18800, then retry.',
      })
      return
    }
    await voice.start({
      backend: effectiveBackend,
      profile: cfg.profile,
      voice: cfg.voice,
      model: cfg.model,
    })
  }, [cfg, realtimeAvailable, effectiveBackend, voice])

  // Keyboard: Space toggles when not typing in a field. `Esc` ends an
  // active session. Ctrl+Shift+J is still handled by FloatingVoiceButton.
  // Space binding can be disabled via realtime settings (hotkey_enabled).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const inInput =
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.isContentEditable
      if (inInput) return
      const hotkey = cfg?.hotkey_enabled ?? true
      if (
        hotkey &&
        e.code === 'Space' &&
        !e.ctrlKey && !e.altKey && !e.metaKey
      ) {
        e.preventDefault()
        void toggle()
      } else if (
        e.key === 'Escape' &&
        (voice.state === 'connected' || voice.state === 'connecting')
      ) {
        void voice.cancel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle, voice, cfg?.hotkey_enabled])

  const partial = useMemo(
    () => voice.transcripts.filter((t) => t.role === 'user' && t.partial).slice(-1)[0],
    [voice.transcripts],
  )

  // --- render ---
  const connected = voice.state === 'connected'
  const connecting = voice.state === 'connecting'
  const errored = voice.state === 'error'

  const dotClass = connecting
    ? 'bg-amber-400 animate-pulse'
    : connected
      ? 'bg-emerald-500 animate-pulse'
      : errored
        ? 'bg-red-500'
        : realtimeAvailable
          ? 'bg-zinc-500'
          : 'bg-zinc-700'

  const label = connecting
    ? 'Cancel'
    : connected
      ? 'Live'
      : errored
        ? 'Error'
        : realtimeAvailable
          ? 'Talk to Reachy'
          : 'Interactive Mode off'

  const title = connecting
    ? 'Connecting… click or press Esc to cancel'
    : connected
      ? `Live via ${BACKEND_LABELS[effectiveBackend] ?? effectiveBackend}. Space or Esc to end.`
      : realtimeAvailable
        ? `Start Interactive Mode (Space or Ctrl+Shift+J) — using ${BACKEND_LABELS[effectiveBackend] ?? effectiveBackend}`
        : 'Local realtime is initializing — check vLLM is reachable'

  const fmtDuration = (s: number) => {
    const m = Math.floor(s / 60)
    const r = s % 60
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      title={title}
      aria-pressed={connected}
      className={[
        'flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium',
        'transition-colors',
        connected
          ? 'bg-emerald-900/40 border-emerald-600 text-emerald-100 hover:bg-emerald-900/60'
          : connecting
            ? 'bg-amber-900/40 border-amber-600 text-amber-100 hover:bg-amber-900/60 cursor-pointer'
            : errored
              ? 'bg-red-900/40 border-red-600 text-red-100 hover:bg-red-900/60'
              : realtimeAvailable
                ? 'bg-zinc-900 border-zinc-700 text-zinc-100 hover:bg-zinc-800'
                : 'bg-zinc-900 border-zinc-800 text-zinc-500 cursor-not-allowed',
      ].join(' ')}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass}`} aria-hidden />
      {connecting ? (
        <>
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <X className="w-3.5 h-3.5" />
        </>
      ) : connected ? (
        <Radio className="w-3.5 h-3.5" />
      ) : errored ? (
        <AlertCircle className="w-3.5 h-3.5" />
      ) : realtimeAvailable ? (
        <Mic className="w-3.5 h-3.5" />
      ) : (
        <MicOff className="w-3.5 h-3.5" />
      )}
      <span>{label}</span>
      {connected && (
        <>
          <span className="text-emerald-300/80 font-mono">{fmtDuration(durationSec)}</span>
          {voice.cost > 0 && (
            <span className="text-emerald-300/80 font-mono">${voice.cost.toFixed(3)}</span>
          )}
          {partial?.content && (
            <span className="max-w-[160px] truncate text-emerald-200/80 italic hidden md:inline">
              {partial.content}…
            </span>
          )}
        </>
      )}
    </button>
  )
}
