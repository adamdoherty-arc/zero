import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Loader2, Settings } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
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


/**
 * Classic push-to-talk surface for Reachy. Ctrl+Shift+J toggles recording.
 * Realtime/Interactive Mode is driven exclusively by InteractiveModeBar.
 * Settings (brain, realtime config) live in the gear → ReachyRealtimeSettings.
 */
// Hard ceiling on classic voice stop. Backend proxy caps at 30s and per-provider
// LLM call caps at 12s; 35s here means a server-side abort surfaces as a
// user-visible failure, not an eternal "Thinking…" spinner.
const VOICE_STOP_TIMEOUT_MS = 35_000

export function FloatingVoiceButton() {
  const [realtimeSettingsOpen, setRealtimeSettingsOpen] = useState(false)

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

  useEffect(() => {
    loadProviders()
  }, [loadProviders])

  // activeId kept for provider label tooltip.

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
          description: msg,
        })
      } finally {
        setState('idle')
        setThinkingSince(null)
        setThinkingSecs(0)
      }
    }
  }, [state, callApi, providers])

  // Tick the "Thinking… 12s" counter while the classic pipeline is working.
  useEffect(() => {
    if (thinkingSince === null) return
    const id = window.setInterval(() => {
      setThinkingSecs(Math.floor((Date.now() - thinkingSince) / 1000))
    }, 500)
    return () => window.clearInterval(id)
  }, [thinkingSince])

  const handleClick = useCallback(() => handleClickClassic(), [handleClickClassic])

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

  const isListening = state === 'listening'
  const isBusy = state === 'starting' || state === 'processing'
  const activeProvider = providers.find((p) => p.id === activeId)

  return (
    <>
      {lastReply && (lastReply.response || lastReply.text) && (
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

      {state === 'processing' && thinkingSecs >= 3 && (
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
        title="Talk to Zero (Ctrl+Shift+J)"
        className={[
          'fixed bottom-6 right-6 z-50',
          'w-14 h-14 rounded-full shadow-lg',
          'flex items-center justify-center',
          'transition-all duration-200',
          'border',
          isListening
            ? 'bg-red-600 hover:bg-red-500 border-red-400 animate-pulse'
            : isBusy
              ? 'bg-zinc-700 border-zinc-600 cursor-wait'
              : 'bg-indigo-600 hover:bg-indigo-500 border-indigo-400',
          'text-white',
        ].join(' ')}
      >
        {isBusy ? (
          <Loader2 className="w-6 h-6 animate-spin" />
        ) : isListening ? (
          <MicOff className="w-6 h-6" />
        ) : (
          <Mic className="w-6 h-6" />
        )}
      </button>

      <ReachyRealtimeSettings
        open={realtimeSettingsOpen}
        onOpenChange={setRealtimeSettingsOpen}
      />
    </>
  )
}
