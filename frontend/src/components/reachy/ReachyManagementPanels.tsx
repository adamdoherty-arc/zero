import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Radio,
  Mic,
  MicOff,
  Loader2,
  Volume2,
  Camera,
  Cpu,
  Ear,
  Gamepad2,
  CalendarClock,
  Home,
  AudioLines,
  PlayCircle,
  ChevronRight,
  X,
  Send,
  RotateCcw,
  Square,
  Hand,
  Settings2,
  ArrowLeftRight,
  Speaker,
  Eye,
} from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import { useRealtimeVoice } from '@/hooks/useRealtimeVoice'
import {
  useVolume,
  useSetVolume,
  useTestSound,
  useMotorStatus,
  useSetMotorMode,
  useWakeWordStatus,
  useCameraStatus,
  useLookAt,
} from '@/hooks/useReachyApi'

/**
 * Three panels that round out the Reachy Management page so it surfaces
 * every backend capability the user can actually drive from the UI:
 *
 *  - <InteractiveModeHero/>: page-level live-conversation toggle. Bigger
 *    than the TopBar pill — shows duration, cost, partial transcript, and
 *    an end-session button. Connects to the same useRealtimeVoice hook so
 *    starting from here ↔ TopBar is the same session.
 *  - <HardwarePanel/>: camera state, speaker + mic volume, wake-word mode,
 *    motor compliance, quick test-sound. All hit existing endpoints in
 *    [backend/app/routers/reachy.py].
 *  - <SubPagesNav/>: cards linking to Teleop, Meetings, Home Assistant,
 *    Voice Settings, Radio. Makes /reachy a hub rather than a dead-end.
 */

type Backend = 'openai' | 'gemini' | 'local'

interface RealtimeCfg {
  backend: Backend
  preferred_backend: Backend | null
  realtime_available: boolean
  has_openai_key: boolean
  has_gemini_key: boolean
  has_local?: boolean
  profile: string | null
  voice: string
  model: string
  idle_timeout_min?: number
  hotkey_enabled?: boolean
  cost_cap_usd?: number
  // Catalogs returned by /api/reachy/realtime/config; consumed by the
  // pre-start picker so the dropdowns are populated without a second fetch.
  voices?: Record<string, string[]>
  default_models?: Record<string, string>
  default_voices?: Record<string, string>
}

const BACKEND_LABEL: Record<string, string> = {
  openai: 'OpenAI Realtime',
  gemini: 'Gemini Live',
  local: 'Local (vLLM)',
}

// Cycle order matters: pressing "Swap" rotates through the available
// backends. Local is always available (no key), so it sits at the end.
const BACKEND_CYCLE: Backend[] = ['openai', 'gemini', 'local']

// -------------------------------------------------------------------------
// Interactive Mode hero (page-level, larger surface than the TopBar pill)
// -------------------------------------------------------------------------

export function InteractiveModeHero() {
  const [cfg, setCfg] = useState<RealtimeCfg | null>(null)
  const [duration, setDuration] = useState(0)
  const [connectingSec, setConnectingSec] = useState(0)
  const [textInput, setTextInput] = useState('')
  const [showTranscript, setShowTranscript] = useState(false)
  const [swapping, setSwapping] = useState(false)
  const [models, setModels] = useState<Record<string, { id: string; label: string; description?: string }[]>>({})
  const [profiles, setProfiles] = useState<{ id: string; label: string }[]>([])
  const [savingCfg, setSavingCfg] = useState(false)
  const voice = useRealtimeVoice()
  const startedAtRef = useRef<number | null>(null)
  const connectStartedAtRef = useRef<number | null>(null)
  const { data: speakerVol } = useVolume('speaker')
  const setSpeakerVol = useSetVolume('speaker')
  const lookAt = useLookAt()

  const refreshCfg = async () => {
    try {
      const r = await fetch('/api/reachy/realtime/config', { headers: getAuthHeaders() })
      if (r.ok) setCfg((await r.json()) as RealtimeCfg)
    } catch {
      /* non-fatal */
    }
  }

  useEffect(() => {
    void refreshCfg()
    // Pre-load picker catalogs so the dropdowns aren't empty when the user
    // first sees them.
    fetch('/api/reachy/realtime/models', { headers: getAuthHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.backends && setModels(d.backends))
      .catch(() => undefined)
    fetch('/api/reachy/realtime/profiles', { headers: getAuthHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const list = (d?.profiles ?? d ?? []) as Array<Record<string, unknown>>
        if (Array.isArray(list)) {
          setProfiles(
            list.map((p) => ({
              id: String(p.id ?? p.slug ?? p.name ?? 'default'),
              label: String(p.label ?? p.name ?? p.id ?? 'default'),
            })),
          )
        }
      })
      .catch(() => undefined)
  }, [])

  // PUT /config helper used by the pre-start picker. Fire-and-forget; we
  // refresh the local cfg state from the server response so the picker
  // shows the now-saved values.
  const saveCfgPatch = async (patch: Record<string, unknown>) => {
    setSavingCfg(true)
    try {
      const r = await fetch('/api/reachy/realtime/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(patch),
      })
      if (r.ok) setCfg((await r.json()) as RealtimeCfg)
    } catch {
      /* non-fatal */
    } finally {
      setSavingCfg(false)
    }
  }

  useEffect(() => {
    if (voice.state !== 'connected') {
      startedAtRef.current = null
      setDuration(0)
      return
    }
    startedAtRef.current = Date.now()
    const id = window.setInterval(() => {
      if (startedAtRef.current !== null) {
        setDuration(Math.floor((Date.now() - startedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [voice.state])

  // Tick a "connecting for Ns" counter so the user can see the wait, and
  // knows when to give up rather than staring at a static spinner.
  useEffect(() => {
    if (voice.state !== 'connecting') {
      connectStartedAtRef.current = null
      setConnectingSec(0)
      return
    }
    connectStartedAtRef.current = Date.now()
    const id = window.setInterval(() => {
      if (connectStartedAtRef.current !== null) {
        setConnectingSec(Math.floor((Date.now() - connectStartedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [voice.state])

  const realtimeAvailable = Boolean(cfg?.realtime_available)
  const effectiveBackend = cfg?.preferred_backend ?? cfg?.backend ?? 'gemini'
  const connected = voice.state === 'connected'
  const connecting = voice.state === 'connecting'
  const errored = voice.state === 'error'

  // Compute the next backend in the 3-way cycle that is actually available.
  // Local is always available (no key), so it always shows up.
  const backendAvailable = (b: Backend): boolean => {
    if (b === 'openai') return Boolean(cfg?.has_openai_key)
    if (b === 'gemini') return Boolean(cfg?.has_gemini_key)
    return true // local
  }
  const nextBackend: Backend = (() => {
    const idx = BACKEND_CYCLE.indexOf(effectiveBackend as Backend)
    for (let step = 1; step <= BACKEND_CYCLE.length; step++) {
      const cand = BACKEND_CYCLE[(idx + step) % BACKEND_CYCLE.length]
      if (backendAvailable(cand) && cand !== effectiveBackend) return cand
    }
    return effectiveBackend as Backend
  })()
  const otherBackend = nextBackend
  const otherBackendKeyed = backendAvailable(nextBackend)

  const partialTranscript = useMemo(
    () =>
      voice.transcripts
        .slice(-1)
        .filter((t) => t.partial)
        .map((t) => t.content)
        .join(' '),
    [voice.transcripts],
  )
  const lastFullTurn = useMemo(() => {
    const filt = voice.transcripts.filter((t) => !t.partial)
    return filt.slice(-1)[0]?.content ?? ''
  }, [voice.transcripts])

  const startSession = async (overrideBackend?: Backend) => {
    if (!cfg) return
    const target = overrideBackend ?? (effectiveBackend as Backend)
    // Local doesn't need keys; only gate cloud backends.
    if (target !== 'local' && !realtimeAvailable) {
      toast({
        variant: 'destructive',
        title: 'Interactive Mode needs an API key',
        description:
          'Add OpenAI or Gemini key, or swap to Local (vLLM) which runs on-device.',
      })
      return
    }
    await voice.start({
      backend: target,
      profile: cfg.profile,
      voice: cfg.voice,
      model: cfg.model,
    })
  }

  const toggle = async () => {
    if (!cfg) return
    if (connecting) {
      await voice.cancel()
      return
    }
    if (connected) {
      await voice.stop()
      return
    }
    await startSession()
  }

  const handleSwapBackend = async () => {
    if (!cfg || swapping) return
    setSwapping(true)
    try {
      // Persist the preference so the next session picks the same backend.
      // Fire-and-forget — we don't gate the swap on the PUT roundtrip.
      void fetch('/api/reachy/realtime/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ backend: otherBackend }),
      })
        .catch(() => {/* non-fatal */})
        .finally(() => {
          void refreshCfg()
        })

      // If a session is already live, do a true hot-swap over the existing
      // WS — keeps mic, speaker sink, head wobbler, and transcript intact.
      // Falls back to the old "cancel + restart" path only when the WS is
      // not in a state that can carry a swap_backend frame (e.g. mid-
      // connect handshake).
      if (connected) {
        const sent = voice.swapBackend({ backend: otherBackend })
        if (!sent) {
          await voice.cancel()
          await new Promise((r) => setTimeout(r, 50))
          await startSession(otherBackend)
        }
      } else if (connecting) {
        await voice.cancel()
        await new Promise((r) => setTimeout(r, 50))
        await startSession(otherBackend)
      }
    } finally {
      setSwapping(false)
    }
  }

  const handleReset = async () => {
    await voice.cancel()
    await new Promise((r) => setTimeout(r, 50))
    await startSession()
  }

  const handleSendText = () => {
    const t = textInput.trim()
    if (!t || !connected) return
    voice.sendText(t)
    setTextInput('')
  }

  const fmtDuration = (s: number) => {
    const m = Math.floor(s / 60)
    const r = s % 60
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  const recentTurns = useMemo(
    () => voice.transcripts.filter((t) => !t.partial).slice(-6),
    [voice.transcripts],
  )

  return (
    <div
      className={[
        'rounded-xl border mb-4 transition-colors',
        connected
          ? 'bg-emerald-950/40 border-emerald-700/50'
          : connecting
            ? 'bg-amber-950/40 border-amber-700/50'
            : errored
              ? 'bg-red-950/40 border-red-700/50'
              : 'bg-zinc-900/40 border-zinc-800',
      ].join(' ')}
    >
      {/* ---- Row 1: status + primary toggle ---- */}
      <div className="flex items-center gap-3 p-4">
        <div
          className={[
            'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
            connected
              ? 'bg-emerald-500/20 text-emerald-300'
              : connecting
                ? 'bg-amber-500/20 text-amber-300'
                : errored
                  ? 'bg-red-500/20 text-red-300'
                  : realtimeAvailable
                    ? 'bg-indigo-500/15 text-indigo-300'
                    : 'bg-zinc-800 text-zinc-600',
          ].join(' ')}
        >
          {connecting ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : connected ? (
            <Radio className="w-5 h-5 animate-pulse" />
          ) : realtimeAvailable ? (
            <Mic className="w-5 h-5" />
          ) : (
            <MicOff className="w-5 h-5" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-zinc-100">
              {connected
                ? 'Interactive Mode — live'
                : connecting
                  ? `Connecting… (${connectingSec}s)`
                  : errored
                    ? 'Interactive Mode — error'
                    : 'Interactive Mode'}
            </span>
            {connected && (
              <>
                <span className="text-[10px] text-emerald-300 font-mono px-2 py-0.5 rounded bg-emerald-500/10">
                  {fmtDuration(duration)}
                </span>
                {voice.cost > 0 && (
                  <span className="text-[10px] text-emerald-300 font-mono px-2 py-0.5 rounded bg-emerald-500/10">
                    ${voice.cost.toFixed(3)}
                  </span>
                )}
                <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded bg-zinc-800">
                  via {BACKEND_LABEL[effectiveBackend] ?? effectiveBackend}
                </span>
                {voice.model && (
                  <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded bg-zinc-800">
                    {voice.model}
                  </span>
                )}
                {voice.voice && (
                  <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded bg-zinc-800">
                    voice: {voice.voice}
                  </span>
                )}
              </>
            )}
            {connecting && (
              <span className="text-[11px] text-amber-300/80">
                via {BACKEND_LABEL[effectiveBackend] ?? effectiveBackend}
              </span>
            )}
            {errored && voice.error && (
              <span className="text-[11px] text-red-300 truncate max-w-md">{voice.error}</span>
            )}
            {!connected && !connecting && !errored && (
              <span className="text-[11px] text-zinc-500">
                {realtimeAvailable
                  ? `Tap to start a live conversation (${BACKEND_LABEL[effectiveBackend]})`
                  : 'Add a key in voice settings to enable.'}
              </span>
            )}
          </div>
          {(partialTranscript || lastFullTurn) && connected && (
            <div className="text-xs text-zinc-300 italic mt-1.5 truncate">
              {partialTranscript ? `you: ${partialTranscript}…` : `${lastFullTurn}`}
            </div>
          )}
        </div>

        {/* Connecting state: Cancel + Try other backend */}
        {connecting && (
          <div className="flex items-center gap-2 shrink-0">
            {otherBackendKeyed && (
              <button
                type="button"
                onClick={() => void handleSwapBackend()}
                disabled={swapping}
                className="rounded-lg px-3 py-2 text-xs font-medium bg-zinc-800 hover:bg-zinc-700 text-zinc-100 border border-zinc-700 flex items-center gap-1.5"
                title={`Cancel and retry on ${BACKEND_LABEL[otherBackend]}`}
              >
                <ArrowLeftRight className="w-3.5 h-3.5" />
                Try {BACKEND_LABEL[otherBackend]}
              </button>
            )}
            <button
              type="button"
              onClick={() => void voice.cancel()}
              className="rounded-lg px-4 py-2 text-sm font-semibold bg-red-600 hover:bg-red-500 text-white flex items-center gap-1.5"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          </div>
        )}

        {/* Idle / connected / error: single primary toggle */}
        {!connecting && (
          <button
            type="button"
            onClick={() => void toggle()}
            disabled={!realtimeAvailable && !connected}
            className={[
              'shrink-0 rounded-lg px-4 py-2 text-sm font-semibold transition-colors',
              connected
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : errored
                  ? 'bg-amber-600 hover:bg-amber-500 text-white'
                  : realtimeAvailable
                    ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                    : 'bg-zinc-800 text-zinc-500 cursor-not-allowed',
            ].join(' ')}
          >
            {connected ? 'End session' : errored ? 'Retry' : 'Start'}
          </button>
        )}
      </div>

      {/* ---- Pre-start picker: backend, model, voice, profile ---- */}
      {/* Only shown when off (not connecting / connected). Lets the user */}
      {/* dial in everything before hitting Start so we don't start a */}
      {/* session on a stale or invalid model. PUT /config persists every */}
      {/* change so the choices stick across page reloads. */}
      {!connected && !connecting && cfg && (
        <div className="border-t border-zinc-800 px-4 py-3 flex flex-wrap items-center gap-2">
          {/* Backend chips — same role as the in-flight Swap pill, but */}
          {/* visible up-front so users can pick before starting. */}
          <span className="text-[11px] text-zinc-500 font-semibold uppercase tracking-wider mr-1">
            Brain
          </span>
          {(['openai', 'gemini', 'local'] as Backend[]).map((b) => {
            const isCurrent = effectiveBackend === b
            const ok = backendAvailable(b)
            return (
              <button
                key={b}
                type="button"
                disabled={!ok || savingCfg}
                onClick={() => void saveCfgPatch({ backend: b, model: null })}
                className={[
                  'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
                  isCurrent
                    ? 'bg-indigo-900/40 border-indigo-600 text-indigo-100'
                    : ok
                      ? 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800'
                      : 'bg-zinc-900/40 border-zinc-800 text-zinc-600 cursor-not-allowed',
                ].join(' ')}
                title={
                  ok
                    ? `Use ${BACKEND_LABEL[b]}`
                    : `${BACKEND_LABEL[b]} needs an API key`
                }
              >
                {BACKEND_LABEL[b]}
                {!ok && b !== 'local' ? ' (no key)' : ''}
              </button>
            )
          })}

          {/* Model picker — uses the catalog from /api/reachy/realtime/models */}
          {/* The local backend's catalog comes from LiteLLM at request time, */}
          {/* so it always reflects what's actually loadable. */}
          <select
            value={cfg.model || ''}
            disabled={savingCfg}
            onChange={(e) => void saveCfgPatch({ model: e.target.value })}
            className="rounded-md px-2 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-indigo-500"
            title="Model"
          >
            <option value="">{`(default: ${cfg.model || '—'})`}</option>
            {(models[effectiveBackend] ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>

          <select
            value={cfg.voice || ''}
            disabled={savingCfg}
            onChange={(e) => void saveCfgPatch({ voice: e.target.value })}
            className="rounded-md px-2 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-indigo-500"
            title="Voice"
          >
            <option value="">{`voice: ${cfg.voice || '—'}`}</option>
            {(cfg.voices?.[effectiveBackend] ?? []).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>

          <select
            value={cfg.profile || ''}
            disabled={savingCfg || profiles.length === 0}
            onChange={(e) => void saveCfgPatch({ profile: e.target.value || null })}
            className="rounded-md px-2 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-indigo-500"
            title="Persona / profile"
          >
            <option value="">persona: default</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>

          {savingCfg && (
            <span className="text-[10px] text-zinc-500 italic">saving…</span>
          )}
        </div>
      )}

      {/* ---- Row 2: cockpit controls (only when live) ---- */}
      {connected && (
        <div className="border-t border-emerald-700/30 px-4 py-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => voice.toggleMute()}
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
              voice.muted
                ? 'bg-amber-900/40 border-amber-700 text-amber-100'
                : 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800',
            ].join(' ')}
            title={voice.muted ? 'Mic muted — click to unmute' : 'Mute mic (session stays open)'}
          >
            {voice.muted ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
            {voice.muted ? 'Muted' : 'Mic on'}
          </button>

          <button
            type="button"
            onClick={() => voice.cancelResponse()}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Interrupt the assistant's current reply"
          >
            <Hand className="w-3.5 h-3.5" />
            Interrupt
          </button>

          <button
            type="button"
            onClick={() => void handleSwapBackend()}
            disabled={swapping || !otherBackendKeyed}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              otherBackendKeyed
                ? `Hot-swap to ${BACKEND_LABEL[otherBackend]} (mic stays live)`
                : `No ${BACKEND_LABEL[otherBackend]} key configured`
            }
          >
            <ArrowLeftRight className="w-3.5 h-3.5" />
            Swap → {BACKEND_LABEL[otherBackend]}
          </button>

          <button
            type="button"
            onClick={() => void handleReset()}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="End and immediately restart the session"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Reset
          </button>

          <button
            type="button"
            onClick={() => void voice.stop()}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-red-950/40 border-red-700/60 text-red-200 hover:bg-red-900/60 flex items-center gap-1.5"
            title="Hard-stop the live session"
          >
            <Square className="w-3.5 h-3.5" />
            End
          </button>

          <Link
            to="/reachy/voice-settings"
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Open voice settings (voice, persona, idle timer, cost cap)"
          >
            <Settings2 className="w-3.5 h-3.5" />
            Settings
          </Link>

          {/* Speaker sink — robot speaker is always on (host_agent stream); */}
          {/* this toggle controls whether browser ALSO plays the audio. */}
          <button
            type="button"
            onClick={() => voice.setLocalPlayback(!voice.localPlayback)}
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
              voice.localPlayback
                ? 'bg-indigo-900/40 border-indigo-700 text-indigo-100'
                : 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800',
            ].join(' ')}
            title={
              voice.localPlayback
                ? 'Audio plays on Reachy AND your PC. Click to silence PC.'
                : 'Audio plays on Reachy only (recommended). Click to also play on PC.'
            }
          >
            <Speaker className="w-3.5 h-3.5" />
            {voice.localPlayback ? 'PC + Reachy' : 'Reachy only'}
          </button>

          {/* Reachy speaker volume — controls the robot's own speaker via daemon. */}
          {/* Daemon returns volume in 0..100 already; older code multiplied by 100 */}
          {/* on top of that and showed "10000%". Treat ``volume`` as percent. */}
          <div className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 flex items-center gap-1.5">
            <Volume2 className="w-3.5 h-3.5" />
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={speakerVol?.volume != null ? Math.round(speakerVol.volume) : 70}
              onChange={(e) => setSpeakerVol.mutate(Number(e.target.value))}
              className="w-20 accent-indigo-500"
              title="Reachy speaker volume"
            />
            <span className="font-mono text-[10px] text-indigo-300 w-9 text-right">
              {speakerVol?.volume != null ? `${Math.round(speakerVol.volume)}%` : '—'}
            </span>
          </div>

          {/* Look at the user / look ahead — quick gaze cues during conversation. */}
          <button
            type="button"
            onClick={() => lookAt.mutate({ x: 0.5, y: 0, z: 0, duration: 0.6 })}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Look at me (gaze toward camera)"
          >
            <Eye className="w-3.5 h-3.5" />
            Look at me
          </button>
          <button
            type="button"
            onClick={() => lookAt.mutate({ x: 1, y: 0, z: 0, duration: 0.6 })}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Look ahead (neutral gaze)"
          >
            <Eye className="w-3.5 h-3.5 opacity-60" />
            Ahead
          </button>

          {/* Send-text fallback — speak with hands when speech doesn't land */}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSendText()
            }}
            className="flex items-center gap-1.5 ml-auto min-w-0"
          >
            <input
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder="Type a message…"
              className="rounded-md px-2.5 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-indigo-500 w-48 md:w-64"
            />
            <button
              type="submit"
              disabled={!textInput.trim()}
              className="rounded-md px-2 py-1.5 text-xs font-medium border bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:border-zinc-700 disabled:cursor-not-allowed border-indigo-500 text-white flex items-center gap-1"
              title="Send text turn"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      )}

      {/* ---- Row 3: transcript drawer (only when live) ---- */}
      {connected && (
        <details
          className="border-t border-emerald-700/30 px-4 py-2"
          open={showTranscript}
          onToggle={(e) => setShowTranscript((e.target as HTMLDetailsElement).open)}
        >
          <summary className="text-[11px] text-zinc-400 cursor-pointer hover:text-zinc-200 select-none">
            Transcript ({recentTurns.length} recent · {voice.tools.length} tool calls)
          </summary>
          <div className="mt-2 space-y-1 max-h-48 overflow-y-auto pb-1">
            {recentTurns.length === 0 ? (
              <div className="text-[11px] text-zinc-500 italic">No turns yet — speak to Reachy.</div>
            ) : (
              recentTurns.map((t) => (
                <div key={t.id} className="text-xs text-zinc-200">
                  <span
                    className={
                      t.role === 'user'
                        ? 'text-indigo-300 font-medium'
                        : 'text-emerald-300 font-medium'
                    }
                  >
                    {t.role === 'user' ? 'you' : 'reachy'}:
                  </span>{' '}
                  <span className="text-zinc-300">{t.content}</span>
                </div>
              ))
            )}
            {voice.tools.length > 0 && (
              <div className="pt-2 border-t border-zinc-800/60 mt-2">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">
                  Tool calls
                </div>
                {voice.tools.slice(-4).map((t) => (
                  <div key={t.call_id} className="text-[11px] text-zinc-400">
                    <span className="font-mono">{t.tool_name}</span>{' '}
                    <span
                      className={
                        t.status === 'failed'
                          ? 'text-red-300'
                          : t.status === 'completed'
                            ? 'text-emerald-300'
                            : 'text-amber-300'
                      }
                    >
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  )
}

// -------------------------------------------------------------------------
// Hardware panel — exposes endpoints that had no UI surface yet
// -------------------------------------------------------------------------

export function HardwarePanel() {
  const { data: speakerVol } = useVolume('speaker')
  const { data: micVol } = useVolume('mic')
  const setSpeakerVol = useSetVolume('speaker')
  const setMicVol = useSetVolume('mic')
  const testSound = useTestSound()
  const { data: motors } = useMotorStatus(15_000)
  const setMotorMode = useSetMotorMode()
  const { data: wake } = useWakeWordStatus(8_000)
  const { data: cam } = useCameraStatus(5_000)

  const motorMode = (motors?.mode as string | undefined) ?? 'unknown'

  const cameraOk = Boolean(cam?.active)
  const wakeAvailable = Boolean(wake?.available)
  const wakeKeyword = wake?.model ?? '—'
  const wakeImportError = wake?.import_error ?? null

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <Cpu className="w-3.5 h-3.5" /> Hardware
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Speaker volume */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Volume2 className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Speaker</span>
            <span className="ml-auto text-[10px] text-indigo-300 font-mono">
              {speakerVol?.volume != null ? `${Math.round(speakerVol.volume)}%` : '—'}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={speakerVol?.volume != null ? Math.round(speakerVol.volume) : 50}
            onChange={(e) => setSpeakerVol.mutate(Number(e.target.value))}
            className="w-full accent-indigo-500"
          />
          <button
            type="button"
            onClick={() => testSound.mutate()}
            disabled={testSound.isPending}
            className="mt-2 w-full text-[11px] rounded-md border border-zinc-700 bg-zinc-800/60 hover:bg-zinc-800 px-2 py-1 flex items-center justify-center gap-1.5 text-zinc-300"
          >
            <PlayCircle className="w-3 h-3" />
            {testSound.isPending ? 'Playing…' : 'Test sound'}
          </button>
        </div>

        {/* Mic volume */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Mic className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Microphone</span>
            <span className="ml-auto text-[10px] text-indigo-300 font-mono">
              {micVol?.volume != null ? `${Math.round(micVol.volume)}%` : '—'}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={micVol?.volume != null ? Math.round(micVol.volume) : 50}
            onChange={(e) => setMicVol.mutate(Number(e.target.value))}
            className="w-full accent-indigo-500"
          />
          <div className="text-[10px] text-zinc-500 mt-2">
            Voice + wake-word listen on the Reachy Mini speakerphone mic.
          </div>
        </div>

        {/* Wake word */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Ear className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Wake word</span>
            <span
              className={[
                'ml-auto text-[10px] px-2 py-0.5 rounded font-mono',
                wakeAvailable
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-zinc-800 text-zinc-500',
              ].join(' ')}
            >
              {wakeAvailable ? 'listening' : 'off'}
            </span>
          </div>
          <div className="text-[11px] text-zinc-400 truncate">
            Keyword:{' '}
            <span className="font-mono text-zinc-300">{wakeKeyword}</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-1.5">
            {wakeImportError
              ? `Import error: ${wakeImportError}`
              : wakeAvailable
                ? 'Say the keyword to start a voice command.'
                : 'host_agent not running, or wake-loop disabled. Run host_agent and set ZERO_PICOVOICE_ACCESS_KEY (or use openWakeWord) to enable.'}
          </div>
        </div>

        {/* Motor mode */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Cpu className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Motors</span>
            <span
              className={[
                'ml-auto text-[10px] px-2 py-0.5 rounded font-mono capitalize',
                motorMode === 'enabled'
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : motorMode === 'compliant'
                    ? 'bg-amber-500/15 text-amber-300'
                    : motorMode === 'disabled'
                      ? 'bg-zinc-800 text-zinc-500'
                      : 'bg-zinc-800 text-zinc-500',
              ].join(' ')}
            >
              {motorMode}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1">
            {(['enabled', 'compliant', 'disabled'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMotorMode.mutate(m)}
                disabled={setMotorMode.isPending}
                className={[
                  'text-[11px] rounded border px-2 py-1 capitalize transition-colors',
                  motorMode === m
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                    : 'border-zinc-700 bg-zinc-800/40 hover:bg-zinc-800 text-zinc-300',
                ].join(' ')}
              >
                {m}
              </button>
            ))}
          </div>
          <div className="text-[10px] text-zinc-500 mt-1.5">
            Compliant = soft (free to move by hand). Disabled = power off.
          </div>
        </div>

        {/* Camera */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 md:col-span-2">
          <div className="flex items-center gap-2 mb-1.5">
            <Camera className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Camera</span>
            <span
              className={[
                'ml-auto text-[10px] px-2 py-0.5 rounded font-mono',
                cameraOk
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-zinc-800 text-zinc-500',
              ].join(' ')}
            >
              {cameraOk ? 'live' : 'idle'}
            </span>
          </div>
          {cameraOk ? (
            <img
              src="/api/reachy/camera/mjpeg"
              alt="Reachy live camera"
              className="w-full max-h-64 object-contain rounded border border-zinc-800 bg-black"
            />
          ) : (
            <div className="text-[11px] text-zinc-500">
              Camera worker not running.{' '}
              {String(
                (cam as Record<string, unknown> | undefined)?.error ??
                  'Start host_agent or check the daemon.',
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------
// Sub-page nav (Teleop, Meetings, HA, Voice Settings, Radio)
// -------------------------------------------------------------------------

const SUBPAGES: { href: string; label: string; description: string; icon: typeof Gamepad2 }[] = [
  {
    href: '/reachy/teleop',
    label: 'Teleop',
    description: 'Direct head, body, antenna control with sliders and target pose.',
    icon: Gamepad2,
  },
  {
    href: '/reachy/meetings',
    label: 'Meetings',
    description: 'Meeting recording with Reachy presence and direction-of-arrival tracking.',
    icon: CalendarClock,
  },
  {
    href: '/reachy/voice-settings',
    label: 'Voice Settings',
    description: 'STT/LLM/TTS picker for the classic push-to-talk pipeline.',
    icon: AudioLines,
  },
  {
    href: '/reachy/home-assistant',
    label: 'Home Assistant',
    description: 'Bridge Reachy to your HA entities (lights, locks, sensors).',
    icon: Home,
  },
  {
    href: '/reachy/radio',
    label: 'Radio',
    description: 'Beat-tracked dance mode — Reachy moves to the music.',
    icon: Radio,
  },
]

export function SubPagesNav() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
      {SUBPAGES.map((p) => {
        const Icon = p.icon
        return (
          <Link
            key={p.href}
            to={p.href}
            className="group rounded-lg border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 hover:border-indigo-500/40 transition-colors p-3 flex items-start gap-3"
          >
            <div className="w-8 h-8 rounded-md bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center shrink-0 group-hover:bg-indigo-500/20">
              <Icon className="w-4 h-4 text-indigo-300" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-zinc-100 flex items-center gap-1">
                {p.label}
                <ChevronRight className="w-3.5 h-3.5 text-zinc-500 group-hover:text-indigo-300 group-hover:translate-x-0.5 transition-transform" />
              </div>
              <div className="text-[11px] text-zinc-500 leading-tight mt-0.5">
                {p.description}
              </div>
            </div>
          </Link>
        )
      })}
    </div>
  )
}
