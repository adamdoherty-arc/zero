import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Loader2, Settings, Radio } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import { useRealtimeVoice } from '@/hooks/useRealtimeVoice'
import { ReachyRealtimeSettings } from '@/components/reachy/ReachyRealtimeSettings'

interface Provider {
  id: string
  label: string
  provider: string
  model: string
  description: string
}

interface ProvidersResponse {
  active_id: string
  providers: Provider[]
}

interface RealtimeConfigHint {
  backend: 'local' | 'openai' | 'gemini'
  has_openai_key: boolean
  has_gemini_key: boolean
  preferred_backend: 'local' | 'openai' | 'gemini' | null
  realtime_available: boolean
  profile: string | null
  voice: string
  model: string
}

type VoiceMode = 'classic' | 'realtime'

/**
 * Global voice surface for Reachy.
 *
 * Two modes:
 * - **Classic** (existing): push-to-talk STT → LLM → TTS round-trip via the
 *   /api/reachy-intent endpoints. Works fully offline.
 * - **Realtime**: bidirectional streaming via OpenAI Realtime or Gemini Live
 *   through the /api/reachy/realtime/ws bridge. Needs a provider API key.
 *
 * The mode picker lives behind the gear. Ctrl+Shift+J triggers whichever
 * mode is active. Realtime mode auto-selects when a key is configured.
 */
// Hard ceiling on classic voice stop. Backend proxy caps at 30s and per-provider
// LLM call caps at 12s; 35s here means a server-side abort surfaces as a
// user-visible failure, not an eternal "Thinking…" spinner.
const VOICE_STOP_TIMEOUT_MS = 35_000

export function FloatingVoiceButton() {
  // FloatingVoiceButton now serves as the classic push-to-talk surface only.
  // Realtime/Interactive Mode is driven exclusively by InteractiveModeBar +
  // InteractiveModeHero, and ALL voice configuration (classic + realtime +
  // memory + brain) lives in the unified ReachyRealtimeSettings modal that
  // the gear button opens.
  const [mode] = useState<VoiceMode>('classic')
  const [realtimeCfg, setRealtimeCfg] = useState<RealtimeConfigHint | null>(null)
  const [realtimeSettingsOpen, setRealtimeSettingsOpen] = useState(false)
  // modeTouched used to guard the popup's auto-promote-to-realtime path.
  // Popup is gone; keep the ref read-only so the loadRealtimeCfg dep-array
  // below stays stable without re-implementing the auto-promote logic.
  const [modeTouched] = useState(false)

  // --- Classic mode state ---
  const [state, setState] = useState<'idle' | 'starting' | 'listening' | 'processing'>(
    'idle',
  )
  const [thinkingSince, setThinkingSince] = useState<number | null>(null)
  const [thinkingSecs, setThinkingSecs] = useState<number>(0)
  const [lastReply, setLastReply] = useState<{
    text: string
    intent: string | null
    response: string | null
    providerLabel: string | null
  } | null>(null)
  const [lastReplyAt, setLastReplyAt] = useState<number | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const hideTimerRef = useRef<number | null>(null)

  // --- Realtime mode state ---
  const voice = useRealtimeVoice()

  const callApi = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    // Long-running endpoint (/voice/stop) gets a hard client-side deadline so
    // an unresponsive backend can't freeze the UI in "Thinking…".
    const timed = path.startsWith('/voice/stop')
    const controller = timed ? new AbortController() : undefined
    const timer = timed
      ? window.setTimeout(() => controller?.abort(), VOICE_STOP_TIMEOUT_MS)
      : undefined
    try {
      const res = await fetch(`/api/reachy-intent${path}`, {
        method: 'POST',
        ...init,
        signal: controller?.signal,
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
          ...init?.headers,
        },
      })
      if (!res.ok) {
        const body = await res.text().catch(() => '')
        throw new Error(body || `HTTP ${res.status}`)
      }
      return (await res.json()) as T
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new Error(`Zero took more than ${VOICE_STOP_TIMEOUT_MS / 1000}s to respond.`)
      }
      throw err
    } finally {
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [])

  const loadProviders = useCallback(async () => {
    try {
      const data = await callApi<ProvidersResponse>('/providers', { method: 'GET' })
      setProviders(data.providers)
      setActiveId(data.active_id)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: 'Could not load voice providers',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }, [callApi])

  const loadRealtimeCfg = useCallback(async () => {
    try {
      const res = await fetch('/api/reachy/realtime/config', { headers: getAuthHeaders() })
      if (!res.ok) return
      const cfg = (await res.json()) as RealtimeConfigHint
      setRealtimeCfg(cfg)
      // NOTE: auto-promote to realtime mode removed — Interactive Mode lives
      // in the TopBar now (InteractiveModeBar). The floating button is the
      // classic push-to-talk surface. Users who want realtime from here can
      // still pick it explicitly via the settings cog; we just don't open a
      // second concurrent WebSocket session by default.
    } catch {
      // Silent — realtime is optional.
    }
  }, [modeTouched])

  useEffect(() => {
    loadProviders()
    loadRealtimeCfg()
  }, [loadProviders, loadRealtimeCfg])

  const realtimeAvailable = Boolean(realtimeCfg?.realtime_available)

  // handleSetProvider used to back the in-popup classic LLM brain picker.
  // The popup is gone; classic provider switching now lives in the unified
  // settings modal (or wherever the project-wide LLM router page lives).
  // Kept activeId in scope because TopBar / FloatingVoiceButton tooltip
  // still render the active provider label.

  const handleClickClassic = useCallback(async () => {
    if (state === 'starting' || state === 'processing') return
    if (state === 'idle') {
      setState('starting')
      try {
        await callApi('/voice/start')
        setState('listening')
      } catch (err) {
        setState('idle')
        toast({
          variant: 'destructive',
          title: 'Voice capture failed',
          description: err instanceof Error ? err.message : 'Could not start capture',
        })
      }
      return
    }
    if (state === 'listening') {
      setState('processing')
      setThinkingSince(Date.now())
      try {
        const result = await callApi<{
          text?: string
          intent?: string
          response_text?: string
          detail?: {
            provider_id?: string
            tried_providers?: { id: string; status: string; error?: string }[]
            suggested_provider?: string | null
            last_error?: string
          }
        }>('/voice/stop')
        const provLabel =
          providers.find((p) => p.id === result.detail?.provider_id)?.label ?? null
        setLastReply({
          text: result.text || '',
          intent: result.intent || null,
          response: result.response_text || null,
          providerLabel: provLabel,
        })
        setLastReplyAt(Date.now())
        // Even on "success", all providers may have failed and we returned a
        // canned line. Surface that in a toast so the user can swap providers.
        const tried = result.detail?.tried_providers ?? []
        const allFailed = tried.length > 0 && !tried.some((t) => t.status === 'succeeded')
        if (allFailed) {
          const summary = tried
            .map((t) => {
              const label = providers.find((p) => p.id === t.id)?.label ?? t.id
              return `${label} (${t.status})`
            })
            .join(', ')
          toast({
            variant: 'destructive',
            title: 'All voice brains failed',
            description: `Tried ${summary}. Pick a different brain from the LLM badge next to the mic.`,
          })
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Could not stop capture'
        toast({
          variant: 'destructive',
          title: 'Voice command failed',
          description: realtimeAvailable
            ? `${msg} — switch to Realtime mode via the settings cog for a faster path.`
            : msg,
        })
      } finally {
        setState('idle')
        setThinkingSince(null)
        setThinkingSecs(0)
      }
    }
  }, [state, callApi, providers, realtimeAvailable])

  // Tick the "Thinking… 12s" counter while the classic pipeline is working.
  useEffect(() => {
    if (thinkingSince === null) return
    const id = window.setInterval(() => {
      setThinkingSecs(Math.floor((Date.now() - thinkingSince) / 1000))
    }, 500)
    return () => window.clearInterval(id)
  }, [thinkingSince])

  const handleClickRealtime = useCallback(async () => {
    if (voice.state === 'connecting') return
    if (voice.state === 'connected') {
      await voice.stop()
      return
    }
    if (!realtimeCfg || !realtimeAvailable) {
      toast({
        variant: 'destructive',
        title: 'Realtime voice needs an API key',
        description:
          realtimeCfg?.backend === 'gemini'
            ? 'Add a Gemini API key in the settings cog.'
            : 'Add an OpenAI API key in the settings cog.',
      })
      setRealtimeSettingsOpen(true)
      return
    }
    // Prefer the backend the server says is viable right now, falling back to
    // whatever the user explicitly configured. This lets the button "just work"
    // when only one of the two keys is installed.
    const backend = realtimeCfg.preferred_backend ?? realtimeCfg.backend
    await voice.start({
      backend,
      profile: realtimeCfg.profile,
      voice: realtimeCfg.voice,
      model: realtimeCfg.model,
    })
  }, [realtimeAvailable, realtimeCfg, voice])

  const handleClick = useCallback(() => {
    if (mode === 'realtime') return handleClickRealtime()
    return handleClickClassic()
  }, [mode, handleClickClassic, handleClickRealtime])

  // Toast realtime errors as they happen.
  useEffect(() => {
    const staleBrowserMicError = Boolean(
      voice.state === 'connected' &&
        voice.inputSource === 'reachy' &&
        voice.error &&
        /microphone permission denied|computer mic permission/i.test(voice.error),
    )
    if (staleBrowserMicError) return
    if (voice.error) {
      toast({
        variant: 'destructive',
        title: 'Realtime voice error',
        description: voice.error,
      })
    }
  }, [voice.error, voice.inputSource, voice.state])

  useEffect(() => {
    if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
    if (lastReplyAt) {
      hideTimerRef.current = window.setTimeout(() => {
        setLastReply(null)
        setLastReplyAt(null)
      }, 12000)
    }
    return () => {
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current)
    }
  }, [lastReplyAt])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && (e.key === 'J' || e.key === 'j')) {
        e.preventDefault()
        handleClick()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handleClick])

  // --- Derived display state (both modes) ---

  const isListening = mode === 'classic' ? state === 'listening' : voice.state === 'connected'
  const isBusy =
    mode === 'classic'
      ? state === 'starting' || state === 'processing'
      : voice.state === 'connecting'
  const activeProvider = providers.find((p) => p.id === activeId)

  const realtimeTranscript = voice.transcripts.slice(-3)

  return (
    <>
      {lastReply && (lastReply.response || lastReply.text) && mode === 'classic' && (
        <div className="fixed bottom-24 right-6 z-50 max-w-md pointer-events-none">
          <div className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded-lg shadow-lg p-3 text-sm">
            {lastReply.text && (
              <div className="text-zinc-400 italic mb-1">You said: "{lastReply.text}"</div>
            )}
            <div className="flex items-center gap-2 mb-1 text-xs">
              {lastReply.intent && (
                <span className="text-indigo-400 uppercase tracking-wide">
                  {lastReply.intent.replace('_', ' ')}
                </span>
              )}
              {lastReply.providerLabel && (
                <span className="text-zinc-500">via {lastReply.providerLabel}</span>
              )}
            </div>
            {lastReply.response && <div>{lastReply.response}</div>}
          </div>
        </div>
      )}

      {mode === 'realtime' && voice.state === 'connected' && realtimeTranscript.length > 0 && (
        <div className="fixed bottom-24 right-6 z-50 max-w-md pointer-events-none">
          <div className="bg-zinc-900 border border-indigo-700 text-zinc-100 rounded-lg shadow-lg p-3 text-sm">
            <div className="flex items-center gap-2 text-xs mb-1">
              <Radio className="w-3 h-3 text-indigo-400 animate-pulse" />
              <span className="text-indigo-400 uppercase tracking-wide">
                realtime · {voice.model ?? ''}
              </span>
              {voice.cost > 0 && (
                <span className="text-zinc-500 ml-auto">${voice.cost.toFixed(4)}</span>
              )}
            </div>
            {realtimeTranscript.map((t) => (
              <div key={t.id} className={t.role === 'user' ? 'text-zinc-400 italic' : ''}>
                {t.role === 'user' ? '🧑 ' : '🤖 '}
                {t.content}
                {t.partial && <span className="text-zinc-500">…</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Settings popup removed — gear button now opens the unified
          Interactive Mode Settings modal directly. The classic-vs-realtime
          mode toggle and the classic-LLM-brain picker live inside that
          modal as dedicated tabs, so users have ONE place to configure the
          voice loop instead of bouncing between a popover and a dialog. */}

      <button
        type="button"
        onClick={() => setRealtimeSettingsOpen(true)}
        aria-label="Voice settings"
        title={activeProvider ? `Brain: ${activeProvider.label}` : 'Voice settings'}
        className="fixed bottom-6 right-24 z-50 w-10 h-10 rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-600 text-zinc-200 flex items-center justify-center shadow-lg transition-colors"
      >
        <Settings className="w-4 h-4" />
      </button>

      {mode === 'classic' && state === 'processing' && thinkingSecs >= 3 && (
        <div
          className="fixed bottom-24 right-6 z-50 pointer-events-none"
          aria-live="polite"
        >
          <div
            className={[
              'rounded-md px-2 py-1 text-xs font-mono border shadow',
              thinkingSecs >= 15
                ? 'bg-amber-900/80 border-amber-600 text-amber-100'
                : 'bg-zinc-900/90 border-zinc-700 text-zinc-300',
            ].join(' ')}
          >
            Thinking… {thinkingSecs}s
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={handleClick}
        disabled={isBusy}
        aria-label={
          isListening
            ? 'Stop recording and send voice command'
            : 'Start recording a voice command'
        }
        title={`Talk to Zero (${mode} mode · Ctrl+Shift+J)`}
        className={[
          'fixed bottom-6 right-6 z-50',
          'w-14 h-14 rounded-full shadow-lg',
          'flex items-center justify-center',
          'transition-all duration-200',
          'border',
          isListening
            ? mode === 'realtime'
              ? 'bg-indigo-600 hover:bg-indigo-500 border-indigo-400 animate-pulse'
              : 'bg-red-600 hover:bg-red-500 border-red-400 animate-pulse'
            : isBusy
              ? 'bg-zinc-700 border-zinc-600 cursor-wait'
              : mode === 'realtime'
                ? 'bg-emerald-600 hover:bg-emerald-500 border-emerald-400'
                : 'bg-indigo-600 hover:bg-indigo-500 border-indigo-400',
          'text-white',
        ].join(' ')}
      >
        {isBusy ? (
          <Loader2 className="w-6 h-6 animate-spin" />
        ) : isListening ? (
          <MicOff className="w-6 h-6" />
        ) : mode === 'realtime' ? (
          <Radio className="w-6 h-6" />
        ) : (
          <Mic className="w-6 h-6" />
        )}
      </button>

      <ReachyRealtimeSettings
        open={realtimeSettingsOpen}
        onOpenChange={setRealtimeSettingsOpen}
        onSaved={() => loadRealtimeCfg()}
      />
    </>
  )
}
