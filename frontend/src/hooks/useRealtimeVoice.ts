import { useCallback, useEffect, useRef, useState } from 'react'
import {
  decodeSpeakerFrame,
  encodeMicFrame,
} from '@/lib/reachy-realtime-audio'
import { getToken } from '@/lib/auth'

/**
 * Client for the Reachy realtime voice bridge.
 *
 * Lifecycle:
 *   const voice = useRealtimeVoice({ backend: 'openai', profile: 'companion' })
 *   voice.start()   // opens mic + WebSocket; enters state === 'connected'
 *   voice.stop()    // tears everything down
 *
 * Audio:
 *   - Mic is captured via AudioWorklet, resampled to the provider's input
 *     rate (OpenAI 24 kHz, Gemini 16 kHz), and streamed frame-by-frame.
 *   - Incoming audio.delta frames are buffered into a Web Audio playback
 *     queue so playback is smooth regardless of network jitter.
 *
 * Events the caller can consume:
 *   - transcripts: rolling list of {role, content}
 *   - tools: rolling list of {tool_name, call_id, status, result}
 *   - cost: cumulative USD (OpenAI only; Gemini surfaces no cost field today)
 *   - error: last error string, if any
 */

export type VoiceBackend = 'openai' | 'gemini' | 'local'

export interface VoiceStartArgs {
  backend?: VoiceBackend
  profile?: string | null
  voice?: string | null
  model?: string | null
  api_key?: string | null
}

export interface VoiceTranscript {
  id: string
  role: 'user' | 'assistant'
  content: string
  partial?: boolean
}

export interface VoiceToolEvent {
  call_id: string
  tool_name: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  args?: string
  result?: unknown
}

type VoiceState = 'idle' | 'connecting' | 'connected' | 'error' | 'closed'

const INPUT_RATE_BY_BACKEND: Record<VoiceBackend, number> = {
  openai: 24000,
  gemini: 16000,
  local: 16000,  // matches Silero VAD + faster-whisper native rate
}

const OUTPUT_RATE_BY_BACKEND: Record<VoiceBackend, number> = {
  openai: 24000,
  gemini: 24000,
  local: 24000,
}

export interface UseRealtimeVoice {
  state: VoiceState
  transcripts: VoiceTranscript[]
  tools: VoiceToolEvent[]
  cost: number
  error: string | null
  model: string | null
  voice: string | null
  muted: boolean
  localPlayback: boolean
  start: (overrides?: VoiceStartArgs) => Promise<void>
  stop: () => Promise<void>
  cancel: () => Promise<void>
  swapBackend: (next: VoiceStartArgs) => boolean
  sendText: (text: string) => void
  cancelResponse: () => void
  toggleMute: () => void
  setMuted: (muted: boolean) => void
  setLocalPlayback: (next: boolean) => void
  isActive: boolean
}

// Hard cap on the "connecting" state. Covers a stalled provider handshake,
// flaky network, or an upstream that accepts the WebSocket but never emits
// the session.ready event. Without this, the UI used to spin forever.
const CONNECT_TIMEOUT_MS = 12_000

export function useRealtimeVoice(defaults: VoiceStartArgs = {}): UseRealtimeVoice {
  const [state, setState] = useState<VoiceState>('idle')
  const [transcripts, setTranscripts] = useState<VoiceTranscript[]>([])
  const [tools, setTools] = useState<VoiceToolEvent[]>([])
  const [cost, setCost] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [voice, setVoice] = useState<string | null>(null)
  const [muted, setMutedState] = useState(false)
  // Default false — the assistant voice should come out of the Reachy
  // speaker (host_agent does that), not the user's PC. Users can opt-in to
  // hear it locally too via the cockpit toggle.
  const [localPlayback, setLocalPlaybackState] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const playbackTimeRef = useRef<number>(0)
  const backendRef = useRef<VoiceBackend>('openai')
  const partialIdRef = useRef(0)
  const mutedRef = useRef(false)
  const localPlaybackRef = useRef(false)
  const connectTimerRef = useRef<number | null>(null)
  // Scheduled BufferSource nodes for assistant playback. Kept so we can
  // stop-and-flush them when the user barges in mid-reply.
  const pendingSpeakerNodesRef = useRef<AudioBufferSourceNode[]>([])

  // Pre-fetch the audio worklet script on mount so the first `addModule` on
  // connect is a browser-cache hit (saves 150-250ms of perceived latency on
  // "click button → robot hears me"). Harmless if the fetch fails.
  useEffect(() => {
    fetch('/reachy-mic-worklet.js', { cache: 'force-cache' }).catch(() => {
      /* non-fatal; addModule will fetch on connect */
    })
  }, [])

  const cleanupEverything = useCallback(async () => {
    if (connectTimerRef.current !== null) {
      window.clearTimeout(connectTimerRef.current)
      connectTimerRef.current = null
    }
    try {
      if (wsRef.current) {
        try {
          wsRef.current.send(JSON.stringify({ type: 'stop' }))
        } catch {
          /* ignore */
        }
        wsRef.current.close()
        wsRef.current = null
      }
    } catch {
      /* ignore */
    }
    try {
      workletNodeRef.current?.disconnect()
      workletNodeRef.current = null
    } catch {
      /* ignore */
    }
    try {
      micStreamRef.current?.getTracks().forEach((t) => t.stop())
      micStreamRef.current = null
    } catch {
      /* ignore */
    }
    try {
      await audioCtxRef.current?.close()
      audioCtxRef.current = null
    } catch {
      /* ignore */
    }
    playbackTimeRef.current = 0
  }, [])

  const scheduleSpeakerFrame = useCallback(
    (samples: Float32Array, sampleRate: number) => {
      const ctx = audioCtxRef.current
      if (!ctx) return
      if (samples.length === 0) return
      const buffer = ctx.createBuffer(1, samples.length, sampleRate)
      buffer.copyToChannel(samples, 0)
      const node = ctx.createBufferSource()
      node.buffer = buffer
      node.connect(ctx.destination)
      const now = ctx.currentTime
      const startAt = Math.max(now, playbackTimeRef.current)
      node.start(startAt)
      playbackTimeRef.current = startAt + buffer.duration
      // Track so we can cut it off if the user interrupts (barge-in).
      pendingSpeakerNodesRef.current.push(node)
      node.onended = () => {
        pendingSpeakerNodesRef.current = pendingSpeakerNodesRef.current.filter(
          (n) => n !== node,
        )
      }
    },
    [],
  )

  // Barge-in: user started speaking while the assistant was still talking.
  // Stop every pending/playing speaker node and reset the scheduling cursor
  // so the next assistant turn starts at "now", not at the end of the
  // already-cancelled reply.
  const cancelPlayback = useCallback(() => {
    const nodes = pendingSpeakerNodesRef.current
    pendingSpeakerNodesRef.current = []
    for (const n of nodes) {
      try {
        n.stop()
      } catch {
        /* node may have ended already */
      }
      try {
        n.disconnect()
      } catch {
        /* ignore */
      }
    }
    const ctx = audioCtxRef.current
    playbackTimeRef.current = ctx ? ctx.currentTime : 0
  }, [])

  const handleServerEvent = useCallback(
    (evt: Record<string, unknown>) => {
      const type = evt.type as string | undefined
      switch (type) {
        case 'session.ready':
          if (connectTimerRef.current !== null) {
            window.clearTimeout(connectTimerRef.current)
            connectTimerRef.current = null
          }
          setState('connected')
          setModel((evt.model as string) ?? null)
          setVoice((evt.voice as string) ?? null)
          break
        case 'backend_swapped':
          // Hot-swap completed on the backend. Update the chips, flush
          // any in-flight assistant audio so the new provider's first reply
          // doesn't overlap the old one's tail.
          cancelPlayback()
          if (typeof evt.model === 'string') setModel(evt.model)
          if (typeof evt.voice === 'string') setVoice(evt.voice)
          if (typeof evt.backend === 'string') {
            backendRef.current = evt.backend as VoiceBackend
          }
          break
        case 'audio.delta': {
          // Skip browser playback unless the user opted in. By default the
          // assistant audio comes out of the Reachy USB speaker via
          // host_agent's /speaker/stream — playing locally too would echo.
          if (!localPlaybackRef.current) break
          const b64 = (evt.audio_b64 as string) || ''
          const rate =
            (evt.rate as number) || OUTPUT_RATE_BY_BACKEND[backendRef.current]
          if (b64) scheduleSpeakerFrame(decodeSpeakerFrame(b64), rate)
          break
        }
        case 'audio.done':
          // Caller can use this to toggle "assistant finished speaking" UI.
          break
        case 'audio.cancelled':
        case 'user.speech_started':
          // User barged in — stop whatever the assistant is currently saying
          // instead of letting the tail of the reply bleed over the new turn.
          cancelPlayback()
          break
        case 'transcript': {
          const role = (evt.role as 'user' | 'assistant') || 'assistant'
          const content = (evt.content as string) || ''
          if (!content.trim()) break
          setTranscripts((prev) => [
            ...prev.filter((t) => !t.partial),
            { id: `${Date.now()}-${Math.random()}`, role, content },
          ])
          break
        }
        case 'transcript.partial': {
          const role = (evt.role as 'user' | 'assistant') || 'user'
          const content = (evt.content as string) || ''
          const partialId = `partial-${partialIdRef.current++}`
          setTranscripts((prev) => [
            ...prev.filter((t) => !t.partial),
            { id: partialId, role, content, partial: true },
          ])
          break
        }
        case 'tool.start': {
          const call_id = (evt.call_id as string) || ''
          const tool_name = (evt.tool_name as string) || ''
          setTools((prev) => [
            ...prev,
            {
              call_id,
              tool_name,
              status: 'running',
              args: (evt.args as string) || '',
            },
          ])
          break
        }
        case 'tool.end': {
          const call_id = (evt.call_id as string) || ''
          const status = (evt.status as VoiceToolEvent['status']) || 'completed'
          const result = evt.result
          setTools((prev) =>
            prev.map((t) =>
              t.call_id === call_id ? { ...t, status, result } : t,
            ),
          )
          break
        }
        case 'usage':
          if (typeof evt.cumulative_usd === 'number') setCost(evt.cumulative_usd)
          break
        case 'error':
          setError((evt.message as string) || 'unknown error')
          break
        case 'session.closed':
          setState('closed')
          break
      }
    },
    [scheduleSpeakerFrame],
  )

  const start = useCallback(
    async (overrides: VoiceStartArgs = {}) => {
      if (state === 'connecting' || state === 'connected') return
      setError(null)
      setTranscripts([])
      setTools([])
      setCost(0)
      setState('connecting')

      // Arm the connect-timeout watchdog. If session.ready doesn't arrive
      // within CONNECT_TIMEOUT_MS we tear everything down and surface an
      // actionable error instead of leaving the UI stuck on "Connecting…".
      if (connectTimerRef.current !== null) {
        window.clearTimeout(connectTimerRef.current)
      }
      connectTimerRef.current = window.setTimeout(() => {
        connectTimerRef.current = null
        setError(
          'Connection timed out. Check your API key, network, or try the other backend.',
        )
        setState('error')
        void cleanupEverything()
      }, CONNECT_TIMEOUT_MS)

      const merged: VoiceStartArgs = { ...defaults, ...overrides }
      const backend: VoiceBackend = (merged.backend as VoiceBackend) || 'openai'
      backendRef.current = backend

      const inputRate = INPUT_RATE_BY_BACKEND[backend]

      // 1. Mic + AudioContext + Worklet
      let stream: MediaStream
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            channelCount: 1,
          },
        })
      } catch (e) {
        setError(`Microphone permission denied: ${String(e)}`)
        setState('error')
        return
      }
      micStreamRef.current = stream

      const ctx = new AudioContext()
      audioCtxRef.current = ctx
      try {
        await ctx.audioWorklet.addModule('/reachy-mic-worklet.js')
      } catch (e) {
        await cleanupEverything()
        setError(`Audio worklet failed to load: ${String(e)}`)
        setState('error')
        return
      }

      const source = ctx.createMediaStreamSource(stream)
      const worklet = new AudioWorkletNode(ctx, 'reachy-mic-processor', {
        processorOptions: { framesPerChunk: 960 },
      })
      workletNodeRef.current = worklet

      worklet.port.onmessage = (msg: MessageEvent<Float32Array>) => {
        if (mutedRef.current) return
        const frame = msg.data
        const ws = wsRef.current
        if (!ws || ws.readyState !== WebSocket.OPEN) return
        const b64 = encodeMicFrame(frame, ctx.sampleRate, inputRate)
        ws.send(JSON.stringify({ type: 'audio', audio_b64: b64, rate: inputRate }))
      }
      source.connect(worklet)

      // 2. WebSocket
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const token = getToken() || ''
      // Zero's API lives on the same origin; the WS is under /api/reachy/realtime/ws.
      const wsUrl = `${proto}//${window.location.host}/api/reachy/realtime/ws${
        token ? `?token=${encodeURIComponent(token)}` : ''
      }`

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            type: 'start',
            backend,
            profile: merged.profile ?? null,
            voice: merged.voice ?? null,
            model: merged.model ?? null,
            api_key: merged.api_key ?? null,
          }),
        )
      }
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(String(ev.data))
          handleServerEvent(data)
        } catch {
          // ignore malformed frames
        }
      }
      ws.onerror = () => {
        setError('WebSocket error')
        setState('error')
      }
      ws.onclose = () => {
        setState((current) => (current === 'error' ? current : 'closed'))
        cleanupEverything()
      }
    },
    [cleanupEverything, defaults, handleServerEvent, state],
  )

  const stop = useCallback(async () => {
    await cleanupEverything()
    setMutedState(false)
    mutedRef.current = false
    setState('idle')
  }, [cleanupEverything])

  // Alias so call sites can read `voice.cancel()` when aborting a hung
  // connect, even though it's the same code path as ending a live session.
  const cancel = useCallback(async () => {
    await stop()
  }, [stop])

  const sendText = useCallback((text: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'text', text }))
  }, [])

  // Barge-in / interrupt the assistant's current reply. Sends the WS frame
  // the backend session loop forwards to the provider as response.cancel.
  const cancelResponse = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'cancel_response' }))
  }, [])

  // Hot-swap to a different backend / voice / model / persona while keeping
  // the WS, mic stream, and Reachy speaker sink alive. Returns true if the
  // swap frame was sent. The backend tears down the old handler, builds a
  // new one, and emits a ``backend_swapped`` event we surface as a transcript
  // status. Conversation history (in the provider's working context) is
  // not carried across handlers — but tier-2 vector memory persists, so the
  // companion still recalls prior turns when the persona is unchanged.
  const swapBackend = useCallback((next: VoiceStartArgs): boolean => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    const payload: Record<string, unknown> = { type: 'swap_backend' }
    if (next.backend) {
      payload.backend = next.backend
      backendRef.current = next.backend
    }
    if (next.voice) payload.voice = next.voice
    if (next.model) payload.model = next.model
    if (next.profile) payload.profile = next.profile
    ws.send(JSON.stringify(payload))
    return true
  }, [])

  const setMuted = useCallback((next: boolean) => {
    mutedRef.current = next
    setMutedState(next)
  }, [])

  const toggleMute = useCallback(() => {
    setMuted(!mutedRef.current)
  }, [setMuted])

  const setLocalPlayback = useCallback((next: boolean) => {
    localPlaybackRef.current = next
    setLocalPlaybackState(next)
  }, [])

  // Auto-cleanup on unmount.
  useEffect(() => {
    return () => {
      cleanupEverything()
    }
  }, [cleanupEverything])

  return {
    state,
    transcripts,
    tools,
    cost,
    error,
    model,
    voice,
    muted,
    localPlayback,
    start,
    stop,
    cancel,
    swapBackend,
    sendText,
    cancelResponse,
    toggleMute,
    setMuted,
    setLocalPlayback,
    isActive: state === 'connected' || state === 'connecting',
  }
}
