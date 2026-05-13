/**
 * useMascot — drive the mascot face state and mouth visemes from the
 * realtime voice hook.
 *
 * Three-layer viseme stream (openhuman pattern):
 *
 *   1. Real viseme frames from the TTS backend — preferred. Wire when the
 *      backend gains a `mascot.viseme` event (see backend/app/services/
 *      reachy_realtime/local_handler.py viseme surfacing). Until then it's
 *      a placeholder.
 *   2. Character-level alignment from streaming `textDelta` — we walk the
 *      latest partial assistant transcript at ~16 chars/second and pick a
 *      viseme per character via `visemeForChar`.
 *   3. Procedural fallback when no transcript is available — a gentle
 *      breathing motion so the mouth never freezes during a long pause.
 *
 * Face state machine maps `SessionPhase` from the realtime hook to
 * 'idle' | 'listening' | 'thinking' | 'speaking' | 'concerned'. The mascot
 * renderer picks eye / brow / cheek pose from that.
 */

import { useEffect, useRef, useState } from 'react'

import type {
  SessionPhase,
  VisemeFrame,
  VoiceTranscript,
} from '@/hooks/useRealtimeVoice'

import {
  VISEMES,
  type VisemeId,
  type VisemeShape,
  interpolateViseme,
  visemeForChar,
} from './visemes'

export type MascotFace = 'idle' | 'listening' | 'thinking' | 'speaking' | 'concerned'

export interface MascotState {
  face: MascotFace
  viseme: VisemeShape
  visemeId: VisemeId
  lastSpokenChar: string
}

// Average sustained speech rate, used to walk a streaming transcript at a
// human-ish pace. Real human speech is ~12-18 chars/sec; we pick the middle.
const CHARS_PER_SECOND = 16
const REST_DECAY_MS = 220  // how quickly the mouth returns to REST when idle
// Breathing pulse so an idle / thinking mouth doesn't look frozen.
const BREATH_FREQ_HZ = 0.5

function faceForPhase(phase: SessionPhase): MascotFace {
  switch (phase) {
    case 'listening':
    case 'transcribing':
      return 'listening'
    case 'thinking':
    case 'moving':
      return 'thinking'
    case 'speaking':
      return 'speaking'
    case 'recovering':
    case 'stalled':
      return 'concerned'
    case 'idle':
    default:
      return 'idle'
  }
}

interface UseMascotArgs {
  sessionPhase: SessionPhase
  /** All transcripts. We use only the most recent partial assistant utterance. */
  transcripts: VoiceTranscript[]
  /** Whether the realtime voice session is actively connected. */
  active: boolean
  /** Latest backend-emitted viseme frame. Preferred over text-walking. */
  latestViseme?: VisemeFrame | null
}

const BACKEND_VISEME_TTL_MS = 250

export function useMascot({
  sessionPhase,
  transcripts,
  active,
  latestViseme,
}: UseMascotArgs): MascotState {
  const [face, setFace] = useState<MascotFace>('idle')
  const [viseme, setViseme] = useState<VisemeShape>(VISEMES.REST)
  const [visemeId, setVisemeId] = useState<VisemeId>('REST')
  const [lastSpokenChar, setLastSpokenChar] = useState('')

  // Face is a pure function of the current session phase.
  useEffect(() => {
    setFace(active ? faceForPhase(sessionPhase) : 'idle')
  }, [active, sessionPhase])

  // Layer 1 — backend-emitted viseme frames win when fresh. When the
  // backend stops emitting (i.e. cloud realtime or no speech), the TTL
  // expires and the procedural text-walker (Layer 2) takes over below.
  useEffect(() => {
    if (!latestViseme) return
    if (Date.now() - latestViseme.received_at > BACKEND_VISEME_TTL_MS) return
    const shape: VisemeShape = {
      openness: latestViseme.openness,
      width: latestViseme.width,
    }
    setViseme(shape)
    setVisemeId((latestViseme.viseme_id as VisemeId) ?? 'REST')
    if (latestViseme.char) setLastSpokenChar(latestViseme.char)
  }, [latestViseme])

  const backendVisemeFresh =
    !!latestViseme &&
    Date.now() - latestViseme.received_at < BACKEND_VISEME_TTL_MS

  // Latest partial assistant transcript drives the mouth.
  let latestAssistant: VoiceTranscript | null = null
  for (let i = transcripts.length - 1; i >= 0; i--) {
    const t = transcripts[i]
    if (t.role === 'assistant') {
      latestAssistant = t
      break
    }
  }

  // Animation loop. Walks the latest assistant transcript and interpolates
  // between viseme shapes. When no transcript is fresh, falls back to a
  // small breathing pulse so the face never looks dead.
  const rafRef = useRef<number | null>(null)
  const startedAtRef = useRef<number | null>(null)
  const lastCharIdxRef = useRef(-1)
  const lastShapeRef = useRef<VisemeShape>(VISEMES.REST)
  const lastIdRef = useRef<VisemeId>('REST')

  useEffect(() => {
    const transcriptId = latestAssistant?.id ?? null
    const transcriptText = latestAssistant?.content ?? ''
    const isSpeaking = sessionPhase === 'speaking'

    // If the backend is feeding us fresh visemes, skip the text-walker —
    // the dedicated effect above already updated viseme/visemeId from the
    // backend frame.
    if (backendVisemeFresh) {
      return
    }

    if (!isSpeaking || !transcriptId) {
      // Decay back to REST and keep a tiny breathing motion for life-likeness.
      startedAtRef.current = null
      lastCharIdxRef.current = -1
      const decayStart = performance.now()
      const decayFrom: VisemeShape = lastShapeRef.current
      const tick = (now: number) => {
        const elapsed = now - decayStart
        const t = Math.min(1, elapsed / REST_DECAY_MS)
        const restWithBreath: VisemeShape = {
          ...VISEMES.REST,
          openness:
            VISEMES.REST.openness +
            0.04 * (1 + Math.sin(2 * Math.PI * BREATH_FREQ_HZ * (now / 1000))) / 2,
        }
        const next = interpolateViseme(decayFrom, restWithBreath, t)
        lastShapeRef.current = next
        lastIdRef.current = 'REST'
        setViseme(next)
        setVisemeId('REST')
        if (t < 1 || isSpeaking) {
          rafRef.current = requestAnimationFrame(tick)
        }
      }
      rafRef.current = requestAnimationFrame(tick)
      return () => {
        if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }

    // Speaking — walk the transcript at CHARS_PER_SECOND.
    startedAtRef.current = startedAtRef.current ?? performance.now()
    const startedAt = startedAtRef.current

    const tick = (now: number) => {
      const elapsedSec = (now - startedAt) / 1000
      const targetIdx = Math.min(
        transcriptText.length - 1,
        Math.floor(elapsedSec * CHARS_PER_SECOND),
      )
      if (targetIdx >= 0 && targetIdx !== lastCharIdxRef.current) {
        lastCharIdxRef.current = targetIdx
        const ch = transcriptText[targetIdx] ?? ''
        const id = visemeForChar(ch)
        const target = VISEMES[id]
        // Snap directly to the target — the per-frame interpolation between
        // these will be handled by the SVG transition CSS, which is smoother
        // and cheaper than recomputing each frame here.
        lastShapeRef.current = target
        lastIdRef.current = id
        setViseme(target)
        setVisemeId(id)
        setLastSpokenChar(ch)
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [latestAssistant?.id, latestAssistant?.content, sessionPhase, backendVisemeFresh])

  return { face, viseme, visemeId, lastSpokenChar }
}
