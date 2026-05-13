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
  body_motion?: boolean
  input_source?: 'reachy' | 'browser'
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
export type SessionPhase =
  | 'idle'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'moving'
  | 'recovering'
  | 'stalled'

export interface VoiceInputHealth {
  source: string
  ready: boolean
  rms: number
  peak: number
  empty_stt_count: number
  confidence_state: string
  last_signal_at?: number | null
  last_frame_at?: number | null
  suggested_action?: string | null
  last_error?: string | null
}

export interface VoiceOutputHealth {
  sink: string
  ready: boolean
  queued_ms: number
  last_error?: string | null
}

const INPUT_RATE_BY_BACKEND: Record<VoiceBackend, number> = {
  openai: 24000,
  gemini: 16000,
  local: 16000,  // matches Silero VAD + faster-whisper native rate
}
const BROWSER_MIC_PROMPT_TIMEOUT_MS = 12000
const BROWSER_MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    channelCount: 1,
  },
}

function stopStream(stream: MediaStream | null) {
  try {
    stream?.getTracks().forEach((track) => track.stop())
  } catch {
    // best effort cleanup
  }
}

function requestBrowserMicStream(): Promise<MediaStream> {
  let timedOut = false
  let timeoutId: number | null = null
  const request = navigator.mediaDevices.getUserMedia(BROWSER_MIC_CONSTRAINTS)
  return new Promise((resolve, reject) => {
    timeoutId = window.setTimeout(() => {
      timedOut = true
      reject(
        new Error(
          'Computer microphone permission is still waiting. Allow microphone access in the browser prompt, then press Computer mic again.',
        ),
      )
    }, BROWSER_MIC_PROMPT_TIMEOUT_MS)

    request
      .then((stream) => {
        if (timeoutId !== null) window.clearTimeout(timeoutId)
        if (timedOut) {
          stopStream(stream)
          return
        }
        resolve(stream)
      })
      .catch((error) => {
        if (timeoutId !== null) window.clearTimeout(timeoutId)
        if (timedOut) return
        reject(error)
      })
  })
}

const OUTPUT_RATE_BY_BACKEND: Record<VoiceBackend, number> = {
  openai: 24000,
  gemini: 24000,
  local: 24000,
}

export interface VisemeFrame {
  viseme_id: string
  openness: number
  width: number
  offset_ms?: number
  char?: string
  /** Wall-clock timestamp when this frame was received. Used by the mascot
   * hook to decide whether to fall back to procedural text-walking. */
  received_at: number
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
  bodyMotion: boolean
  inputReady: boolean
  inputSource: 'reachy' | 'browser' | null
  inputDevice: string | null
  outputSink: 'reachy_speaker' | 'unavailable' | null
  outputDevice: string | null
  sessionPhase: SessionPhase
  stalledReason: string | null
  inputHealth: VoiceInputHealth | null
  outputHealth: VoiceOutputHealth | null
  localPlayback: boolean
  /** Most-recent backend-emitted mascot viseme. Null until the first frame. */
  latestViseme: VisemeFrame | null
  start: (overrides?: VoiceStartArgs) => Promise<void>
  stop: () => Promise<void>
  cancel: () => Promise<void>
  swapBackend: (next: VoiceStartArgs) => boolean
  sendText: (text: string) => void
  cancelResponse: () => void
  setBodyMotion: (enabled: boolean) => void
  toggleMute: () => void
  setMuted: (muted: boolean) => void
  switchInputSource: (source: 'reachy' | 'browser') => Promise<void>
  setLocalPlayback: (next: boolean) => void
  isActive: boolean
}

// Hard cap on the "connecting" state. Covers a stalled provider handshake,
// flaky network, or an upstream that accepts the WebSocket but never emits
// the session.ready event. Without this, the UI used to spin forever.
const CONNECT_TIMEOUT_MS = 35_000

export function useRealtimeVoice(defaults: VoiceStartArgs = {}): UseRealtimeVoice {
  const [state, setState] = useState<VoiceState>('idle')
  const [transcripts, setTranscripts] = useState<VoiceTranscript[]>([])
  const [tools, setTools] = useState<VoiceToolEvent[]>([])
  const [cost, setCost] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [voice, setVoice] = useState<string | null>(null)
  const [muted, setMutedState] = useState(false)
  const [bodyMotion, setBodyMotionState] = useState(false)
  const [inputReady, setInputReady] = useState(false)
  const [inputSource, setInputSource] = useState<'reachy' | 'browser' | null>(null)
  const [inputDevice, setInputDevice] = useState<string | null>(null)
  const [outputSink, setOutputSink] = useState<'reachy_speaker' | 'unavailable' | null>(
    null,
  )
  const [outputDevice, setOutputDevice] = useState<string | null>(null)
  const [sessionPhase, setSessionPhase] = useState<SessionPhase>('idle')
  const [stalledReason, setStalledReason] = useState<string | null>(null)
  const [inputHealth, setInputHealth] = useState<VoiceInputHealth | null>(null)
  const [outputHealth, setOutputHealth] = useState<VoiceOutputHealth | null>(null)
  const [latestViseme, setLatestViseme] = useState<VisemeFrame | null>(null)
  // Reachy should speak through its own USB speaker by default. Browser
  // playback is a manual fallback so we do not get double audio or route the
  // assistant through the computer without making that explicit.
  // Default ON — most users want to hear the assistant on their computer
  // speaker, not exclusively through Reachy's USB speaker. Turn off via the
  // "Computer on / Computer muted" toggle in the management panel or TopBar.
  const [localPlayback, setLocalPlaybackState] = useState(true)

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const playbackTimeRef = useRef<number>(0)
  const backendRef = useRef<VoiceBackend>('openai')
  const partialIdRef = useRef(0)
  const mutedRef = useRef(false)
  const bodyMotionRef = useRef(false)
  const localPlaybackRef = useRef(true)
  const sessionReadyRef = useRef(false)
  const inputReadyRef = useRef(false)
  const inputSourceRef = useRef<'reachy' | 'browser'>('browser')
  const connectTimerRef = useRef<number | null>(null)
  // Scheduled BufferSource nodes for assistant playback. Kept so we can
  // stop-and-flush them when the user barges in mid-reply.
  const pendingSpeakerNodesRef = useRef<AudioBufferSourceNode[]>([])
  const intentionalCloseRef = useRef(false)
  const autoMicFallbackRef = useRef(false)
  const browserMicRequestSeqRef = useRef(0)
  const browserMicBlockedRef = useRef(false)
  const switchInputSourceRef = useRef<((source: 'reachy' | 'browser') => Promise<void>) | null>(
    null,
  )

  // Pre-fetch the audio worklet script on mount so the first `addModule` on
  // connect is a browser-cache hit (saves 150-250ms of perceived latency on
  // "click button → robot hears me"). Harmless if the fetch fails.
  useEffect(() => {
    fetch('/reachy-mic-worklet.js', { cache: 'force-cache' }).catch(() => {
      /* non-fatal; addModule will fetch on connect */
    })
  }, [])

  const cleanupEverything = useCallback(async () => {
    browserMicRequestSeqRef.current += 1
    browserMicBlockedRef.current = false
    if (connectTimerRef.current !== null) {
      window.clearTimeout(connectTimerRef.current)
      connectTimerRef.current = null
    }
    try {
      if (wsRef.current) {
        intentionalCloseRef.current = true
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
    setSessionPhase('idle')
    setStalledReason(null)
  }, [])

  const scheduleSpeakerFrame = useCallback(
    (samples: Float32Array, sampleRate: number) => {
      let ctx = audioCtxRef.current
      if (!ctx) {
        ctx = new AudioContext()
        audioCtxRef.current = ctx
      }
      if (!ctx) return
      // Browsers (Chrome/Firefox/Safari) start AudioContexts in 'suspended'
      // state. Without an explicit resume after a user gesture, scheduled
      // BufferSource nodes silently produce no audio.
      if (ctx.state === 'suspended') {
        void ctx.resume()
      }
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

  const markConnectedAfterMicChange = useCallback(() => {
    if (!sessionReadyRef.current) return
    if (connectTimerRef.current !== null) {
      window.clearTimeout(connectTimerRef.current)
      connectTimerRef.current = null
    }
    setState('connected')
  }, [])

  const markBrowserMicUnavailable = useCallback(
    (message: string) => {
      inputSourceRef.current = 'browser'
      // Browser input is logically selected even if capture is degraded; do
      // not let a permission prompt block the realtime model/text session.
      inputReadyRef.current = true
      setInputSource('browser')
      setInputReady(true)
      setInputDevice('Computer microphone unavailable')
      setInputHealth({
        source: 'browser_mic',
        ready: false,
        rms: 0,
        peak: 0,
        empty_stt_count: 0,
        confidence_state: 'no_signal',
        last_signal_at: null,
        last_frame_at: null,
        suggested_action: 'allow_browser_mic',
        last_error: message,
      })
      setSessionPhase('stalled')
      setStalledReason('browser microphone unavailable')
      setError(message)
      browserMicBlockedRef.current = true
      markConnectedAfterMicChange()
    },
    [markConnectedAfterMicChange],
  )

  const beginBrowserMicCapture = useCallback(
    (inputRate: number) => {
      const requestSeq = ++browserMicRequestSeqRef.current
      browserMicBlockedRef.current = false
      inputSourceRef.current = 'browser'
      inputReadyRef.current = true
      setInputSource('browser')
      setInputReady(true)
      setInputDevice('Computer microphone opening')
      setInputHealth({
        source: 'browser_mic',
        ready: false,
        rms: 0,
        peak: 0,
        empty_stt_count: 0,
        confidence_state: 'waiting_for_signal',
        last_signal_at: null,
        last_frame_at: null,
        suggested_action: null,
        last_error: null,
      })

      void (async () => {
        let stream: MediaStream
        try {
          stream = await requestBrowserMicStream()
        } catch (e) {
          if (requestSeq !== browserMicRequestSeqRef.current || inputSourceRef.current !== 'browser') {
            return
          }
          markBrowserMicUnavailable(`Computer microphone unavailable: ${String(e)}`)
          return
        }

        if (requestSeq !== browserMicRequestSeqRef.current || inputSourceRef.current !== 'browser') {
          stopStream(stream)
          return
        }

        micStreamRef.current = stream
        let ctx = audioCtxRef.current
        if (!ctx || ctx.state === 'closed') {
          ctx = new AudioContext()
          audioCtxRef.current = ctx
        }
        // AudioContext starts suspended on Chrome/Firefox/Safari and silently
        // produces no audio frames until explicitly resumed. The click that
        // started the session is the user gesture, so resume is allowed.
        if (ctx.state === 'suspended') {
          try { await ctx.resume() } catch { /* best effort */ }
        }
        try {
          await ctx.audioWorklet.addModule('/reachy-mic-worklet.js')
        } catch (e) {
          if (requestSeq !== browserMicRequestSeqRef.current) {
            stopStream(stream)
            return
          }
          stopStream(stream)
          micStreamRef.current = null
          markBrowserMicUnavailable(`Audio worklet failed to load: ${String(e)}`)
          return
        }

        if (requestSeq !== browserMicRequestSeqRef.current || inputSourceRef.current !== 'browser') {
          stopStream(stream)
          return
        }

        const mediaSource = ctx.createMediaStreamSource(stream)
        const worklet = new AudioWorkletNode(ctx, 'reachy-mic-processor', {
          processorOptions: { framesPerChunk: 960 },
        })
        workletNodeRef.current = worklet
        worklet.port.onmessage = (msg: MessageEvent<Float32Array>) => {
          if (mutedRef.current) return
          const frame = msg.data
          const currentWs = wsRef.current
          if (!currentWs || currentWs.readyState !== WebSocket.OPEN) return
          const b64 = encodeMicFrame(frame, ctx.sampleRate, inputRate)
          currentWs.send(JSON.stringify({ type: 'audio', audio_b64: b64, rate: inputRate }))
        }
        mediaSource.connect(worklet)
        inputReadyRef.current = true
        setInputReady(true)
        setInputDevice('Browser microphone')
        setInputHealth({
          source: 'browser_mic',
          ready: true,
          rms: 0,
          peak: 0,
          empty_stt_count: 0,
          confidence_state: 'waiting_for_signal',
          last_signal_at: null,
          last_frame_at: null,
          suggested_action: null,
          last_error: null,
        })
        setSessionPhase('listening')
        setStalledReason(null)
        setError(null)
        browserMicBlockedRef.current = false
        markConnectedAfterMicChange()
      })()
    },
    [markBrowserMicUnavailable, markConnectedAfterMicChange],
  )

  const handleServerEvent = useCallback(
    (evt: Record<string, unknown>) => {
      const type = evt.type as string | undefined
      const markConnectedIfReady = () => {
        if (!sessionReadyRef.current || !inputReadyRef.current) return
        if (connectTimerRef.current !== null) {
          window.clearTimeout(connectTimerRef.current)
          connectTimerRef.current = null
        }
        setState('connected')
      }
      switch (type) {
        case 'mascot.viseme': {
          const id = typeof evt.viseme_id === 'string' ? evt.viseme_id : 'REST'
          const openness = typeof evt.openness === 'number' ? evt.openness : 0
          const width = typeof evt.width === 'number' ? evt.width : 0.3
          setLatestViseme({
            viseme_id: id,
            openness,
            width,
            offset_ms: typeof evt.offset_ms === 'number' ? evt.offset_ms : undefined,
            char: typeof evt.char === 'string' ? evt.char : undefined,
            received_at: Date.now(),
          })
          break
        }
        case 'session.phase': {
          const phase = evt.phase as SessionPhase
          if (phase) setSessionPhase(phase)
          if (typeof evt.reason === 'string') setStalledReason(evt.reason)
          break
        }
        case 'session.health': {
          const phase = evt.session_phase as SessionPhase
          if (phase) setSessionPhase(phase)
          setStalledReason((evt.stalled_reason as string | null) ?? null)
          if (evt.input_health && typeof evt.input_health === 'object') {
            const health = evt.input_health as VoiceInputHealth
            setInputHealth(health)
            if (health.ready) {
              inputReadyRef.current = true
              setInputReady(true)
              if (typeof health.source === 'string' && health.source.includes('browser')) {
                setInputSource('browser')
              } else if (typeof health.source === 'string' && health.source !== 'unknown') {
                setInputSource('reachy')
              }
            }
          }
          if (evt.output_health && typeof evt.output_health === 'object') {
            setOutputHealth(evt.output_health as VoiceOutputHealth)
          }
          if (phase && phase !== 'idle' && phase !== 'stalled') {
            sessionReadyRef.current = true
          }
          markConnectedIfReady()
          break
        }
        case 'session.ready':
          sessionReadyRef.current = true
          setModel((evt.model as string) ?? null)
          setVoice((evt.voice as string) ?? null)
          if (browserMicBlockedRef.current) {
            setSessionPhase('stalled')
            setStalledReason('browser microphone unavailable')
          } else {
            setSessionPhase('listening')
          }
          markConnectedIfReady()
          break
        case 'input.ready':
          inputReadyRef.current = true
          setInputReady(true)
          setInputSource(inputSourceRef.current)
          setInputDevice((evt.device_name as string) ?? null)
          setInputHealth({
            source: (evt.source as string) || inputSourceRef.current,
            ready: true,
            rms: 0,
            peak: 0,
            empty_stt_count: 0,
            confidence_state: 'waiting_for_signal',
            last_signal_at: null,
            last_frame_at: null,
            suggested_action: null,
            last_error: null,
          })
          markConnectedIfReady()
          break
        case 'input.source': {
          const source = evt.source === 'browser' ? 'browser' : 'reachy'
          inputSourceRef.current = source
          setInputSource(source)
          break
        }
        case 'body_motion':
          if (typeof evt.enabled === 'boolean') {
            bodyMotionRef.current = evt.enabled
            setBodyMotionState(evt.enabled)
          }
          break
        case 'output.ready': {
          const sink = evt.sink === 'reachy_speaker' ? 'reachy_speaker' : null
          setOutputSink(sink)
          setOutputDevice((evt.device_name as string) ?? null)
          setOutputHealth({
            sink: sink || 'unknown',
            ready: sink === 'reachy_speaker',
            queued_ms: 0,
            last_error: null,
          })
          // Don't auto-disable computer playback when Reachy speaker is
          // ready — playing from both is fine, and many users sit far from
          // the robot. The user can mute computer audio explicitly via the
          // "Computer muted" toggle.
          break
        }
        case 'output.unavailable':
          setOutputSink('unavailable')
          setOutputDevice(null)
          setOutputHealth({
            sink: 'reachy_speaker',
            ready: false,
            queued_ms: 0,
            last_error:
              (evt.message as string) || 'Reachy speaker is unavailable.',
          })
          // Reachy speaker failed — make sure computer playback is on so
          // the user can still hear the assistant.
          if (!localPlaybackRef.current) {
            localPlaybackRef.current = true
            setLocalPlaybackState(true)
          }
          setError(
            (evt.message as string) ||
              'Reachy speaker is unavailable. Routing audio to computer speaker.',
          )
          break
        case 'input.warning':
          {
            const nextHealth: VoiceInputHealth = {
              source: inputSourceRef.current,
              ready: true,
              rms: Number(evt.rms ?? 0),
              peak: Number(evt.peak ?? 0),
              empty_stt_count: Number(evt.empty_stt_count ?? 0),
              confidence_state: String(evt.confidence_state ?? 'low_confidence'),
              suggested_action: (evt.suggested_action as string) || null,
              last_error: (evt.message as string) || null,
            }
            setInputHealth(nextHealth)
            setError((evt.message as string) || 'Reachy microphone input is degraded.')
            const needsBrowserFallback =
              nextHealth.confidence_state === 'no_signal' &&
              nextHealth.suggested_action === 'switch_to_browser_mic' &&
              inputSourceRef.current !== 'browser'
            if (needsBrowserFallback && !autoMicFallbackRef.current) {
              autoMicFallbackRef.current = true
              inputReadyRef.current = false
              setInputReady(false)
              setSessionPhase('listening')
              setStalledReason(null)
              void switchInputSourceRef.current?.('browser')
            }
          }
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
          // Skip browser playback unless the user explicitly enables the
          // computer speaker fallback.
          if (!localPlaybackRef.current) break
          const b64 = (evt.audio_b64 as string) || ''
          const rate =
            (evt.rate as number) || OUTPUT_RATE_BY_BACKEND[backendRef.current]
          if (b64) scheduleSpeakerFrame(decodeSpeakerFrame(b64), rate)
          break
        }
        case 'audio.done':
          // Caller can use this to toggle "assistant finished speaking" UI.
          setSessionPhase('listening')
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
          // A real turn means a prior mic/STT warning is stale. Keep the
          // transcript focused on conversation, not old capture diagnostics.
          setError(null)
          setTranscripts((prev) => [
            ...prev.filter((t) => !t.partial),
            { id: `${Date.now()}-${Math.random()}`, role, content },
          ])
          setSessionPhase(role === 'user' ? 'thinking' : 'speaking')
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
          setSessionPhase('moving')
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
          if (evt.code === 'input_unavailable' && inputSourceRef.current !== 'browser') {
            const message =
              (evt.message as string) ||
              'Reachy microphone is unavailable; switching to computer mic.'
            setError(message)
            autoMicFallbackRef.current = true
            inputReadyRef.current = true
            setInputReady(true)
            setInputHealth({
              source: 'reachy_mic',
              ready: false,
              rms: 0,
              peak: 0,
              empty_stt_count: 0,
              confidence_state: 'no_signal',
              suggested_action: 'switch_to_browser_mic',
              last_error: message,
            })
            setSessionPhase('stalled')
            setStalledReason('reachy_mic_no_signal')
            markConnectedIfReady()
            void switchInputSourceRef.current?.('browser')
            break
          }
          if (evt.code === 'stt_timeout' || evt.code === 'llm_timeout') {
            setSessionPhase('stalled')
            setStalledReason((evt.message as string) || String(evt.code))
          }
          if (
            evt.code === 'tts_timeout' ||
            evt.code === 'speaker_backpressure' ||
            evt.code === 'tool_timeout' ||
            evt.code === 'websocket_closed'
          ) {
            setSessionPhase('stalled')
            setStalledReason((evt.message as string) || String(evt.code))
          }
          setError((evt.message as string) || 'unknown error')
          if (
            evt.code === 'input_unavailable' ||
            String(evt.message ?? '').toLowerCase().includes('microphone stream failed')
          ) {
            setState('error')
            void cleanupEverything()
          }
          break
        case 'session.closed':
          setState('closed')
          break
      }
    },
    [cleanupEverything, scheduleSpeakerFrame],
  )

  const start = useCallback(
    async (overrides: VoiceStartArgs = {}) => {
      if (state === 'connecting' || state === 'connected') return
      setError(null)
      setTranscripts([])
      setTools([])
      setCost(0)
      setState('connecting')
      setSessionPhase('idle')
      setStalledReason(null)
      setInputHealth(null)
      setOutputHealth(null)
      intentionalCloseRef.current = false
      autoMicFallbackRef.current = false

      // Arm the connect-timeout watchdog. If session.ready doesn't arrive
      // within CONNECT_TIMEOUT_MS we tear everything down and surface an
      // actionable error instead of leaving the UI stuck on "Connecting…".
      if (connectTimerRef.current !== null) {
        window.clearTimeout(connectTimerRef.current)
      }
      connectTimerRef.current = window.setTimeout(() => {
        connectTimerRef.current = null
        setError(
          'Connection timed out while opening the model, Reachy mic, or Reachy speaker. Try again or switch backend.',
        )
        setState('error')
        void cleanupEverything()
      }, CONNECT_TIMEOUT_MS)

      const merged: VoiceStartArgs = { ...defaults, ...overrides }
      const backend: VoiceBackend = (merged.backend as VoiceBackend) || 'openai'
      const inputSource = merged.input_source ?? 'browser'
      backendRef.current = backend
      inputSourceRef.current = inputSource
      sessionReadyRef.current = false
      inputReadyRef.current = inputSource === 'browser'
      setInputReady(inputSource === 'browser')
      setInputSource(inputSource)
      setInputDevice(inputSource === 'browser' ? 'Browser microphone' : null)

      const inputRate = INPUT_RATE_BY_BACKEND[backend]

      // 1. Mic + AudioContext + Worklet. Browser capture is intentionally
      // async and non-blocking; OpenAI/Gemini session readiness should not be
      // held hostage by a permission prompt or a flaky local microphone.
      if (inputSource === 'browser') {
        beginBrowserMicCapture(inputRate)
      }

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
            enable_body_motion: merged.body_motion ?? false,
            input_source: inputSource,
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
        const expected = intentionalCloseRef.current
        setState((current) => (current === 'error' ? current : 'closed'))
        void cleanupEverything().finally(() => {
          if (!expected) {
            setSessionPhase('stalled')
            setStalledReason('WebSocket closed')
            setError('WebSocket closed')
          }
          intentionalCloseRef.current = false
        })
      }
    },
    [beginBrowserMicCapture, cleanupEverything, defaults, handleServerEvent, state],
  )

  const stop = useCallback(async () => {
    await cleanupEverything()
    setMutedState(false)
    mutedRef.current = false
    setBodyMotionState(false)
    bodyMotionRef.current = false
    sessionReadyRef.current = false
    inputReadyRef.current = false
    setInputReady(false)
    setInputSource(null)
    setInputDevice(null)
    setOutputSink(null)
    setOutputDevice(null)
    autoMicFallbackRef.current = false
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

  const setBodyMotion = useCallback((enabled: boolean) => {
    bodyMotionRef.current = enabled
    setBodyMotionState(enabled)
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'set_body_motion', enabled }))
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
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'set_input_muted', muted: next }))
  }, [])

  const toggleMute = useCallback(() => {
    setMuted(!mutedRef.current)
  }, [setMuted])

  const switchInputSource = useCallback(
    async (source: 'reachy' | 'browser') => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        setError('Cannot switch microphone because the live voice socket is closed.')
        setSessionPhase('stalled')
        setStalledReason('voice socket closed')
        return
      }
      const inputRate = INPUT_RATE_BY_BACKEND[backendRef.current]

      try {
        workletNodeRef.current?.disconnect()
      } catch {
        /* ignore */
      }
      workletNodeRef.current = null
      try {
        micStreamRef.current?.getTracks().forEach((t) => t.stop())
      } catch {
        /* ignore */
      }
      micStreamRef.current = null

      if (source === 'browser') {
        ws.send(JSON.stringify({ type: 'set_input_source', source }))
        beginBrowserMicCapture(inputRate)
        markConnectedAfterMicChange()
        autoMicFallbackRef.current = false
        return
      }

      browserMicRequestSeqRef.current += 1
      browserMicBlockedRef.current = false
      inputSourceRef.current = source
      setInputSource(source)
      setInputReady(false)
      inputReadyRef.current = false
      setInputDevice(null)
      ws.send(JSON.stringify({ type: 'set_input_source', source }))
    },
    [beginBrowserMicCapture, markConnectedAfterMicChange],
  )

  switchInputSourceRef.current = switchInputSource

  useEffect(() => {
    if (state !== 'connected') return
    if (inputSource !== 'reachy') return
    if (autoMicFallbackRef.current) return
    if (!inputHealth) return
    const needsFallback =
      inputHealth.confidence_state === 'no_signal' &&
      inputHealth.suggested_action === 'switch_to_browser_mic'
    if (!needsFallback) return
    autoMicFallbackRef.current = true
    setError(inputHealth.last_error || 'Reachy microphone is silent; switching to computer mic.')
    void switchInputSource('browser')
  }, [
    inputHealth?.confidence_state,
    inputHealth?.last_error,
    inputHealth?.suggested_action,
    inputSource,
    state,
    switchInputSource,
  ])

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
    bodyMotion,
    inputReady,
    inputSource,
    inputDevice,
    outputSink,
    outputDevice,
    sessionPhase,
    stalledReason,
    inputHealth,
    outputHealth,
    localPlayback,
    latestViseme,
    start,
    stop,
    cancel,
    swapBackend,
    sendText,
    cancelResponse,
    setBodyMotion,
    toggleMute,
    setMuted,
    switchInputSource,
    setLocalPlayback,
    isActive: state === 'connected' || state === 'connecting',
  }
}
