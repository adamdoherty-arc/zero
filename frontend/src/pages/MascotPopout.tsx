/**
 * MascotPopout — full-window mascot.
 *
 * Open this in its own browser window (window.open / target="_blank" /
 * "Open in window" from a Tauri shell later) and you get a focused mascot
 * surface that mirrors the openhuman desktop-panel UX without needing Tauri.
 * Communicates with the parent tab via `BroadcastChannel` so the realtime
 * session state stays in sync without re-opening a WebSocket per window.
 *
 * For a true OS-native window we'd embed this same route in a Tauri or
 * Electron wrapper that opens it borderless and always-on-top.
 */

import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { MascotSVG } from '@/components/reachy/Mascot/MascotSVG'
import {
  VISEMES,
  type VisemeId,
  type VisemeShape,
} from '@/components/reachy/Mascot/visemes'
import type { MascotFace } from '@/components/reachy/Mascot/useMascot'

const CHANNEL = 'zero-mascot'

interface MascotBroadcast {
  type: 'state'
  face: MascotFace
  visemeId: VisemeId
  viseme?: VisemeShape
  ts: number
}

export default function MascotPopout() {
  const [params] = useSearchParams()
  const wantsTransparent = params.get('transparent') === '1'
  const color = params.get('color') ?? undefined

  const [face, setFace] = useState<MascotFace>('idle')
  const [viseme, setViseme] = useState<VisemeShape>(VISEMES.REST)
  const [lastBroadcastAt, setLastBroadcastAt] = useState<number>(0)

  // Listen to the parent tab. If we never hear from it (e.g. the user
  // opened this URL directly without a session), the mascot just idles.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const ch = new BroadcastChannel(CHANNEL)
    const onMessage = (event: MessageEvent<MascotBroadcast>) => {
      const data = event.data
      if (!data || data.type !== 'state') return
      setFace(data.face)
      setViseme(data.viseme ?? VISEMES[data.visemeId] ?? VISEMES.REST)
      setLastBroadcastAt(data.ts)
    }
    ch.addEventListener('message', onMessage)
    return () => {
      ch.removeEventListener('message', onMessage)
      ch.close()
    }
  }, [])

  // If no broadcast arrives within 10 s, show a connection hint so the user
  // knows the parent window needs to be running.
  const stale = useMemo(() => {
    if (lastBroadcastAt === 0) return true
    return Date.now() - lastBroadcastAt > 10_000
  }, [lastBroadcastAt])

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center"
      style={{
        background: wantsTransparent ? 'transparent' : '#0f172a',
        color: '#e2e8f0',
      }}
    >
      <div className="w-[min(420px,80vw)] h-[min(420px,80vw)]">
        <MascotSVG face={face} viseme={viseme} color={color} size="100%" />
      </div>
      <div className="mt-4 text-xs uppercase tracking-widest text-zinc-500">
        {stale ? 'Waiting for Zero session…' : face}
      </div>
    </div>
  )
}
