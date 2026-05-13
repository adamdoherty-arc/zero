/**
 * MascotDock — floating mascot bubble that pops up while a realtime voice
 * session is active. Mirrors openhuman's desktop-panel behavior but stays
 * inside the browser (the popout route lives at /m/mascot — see T3.2).
 *
 * Bottom-left of the viewport so it stays out of the way of the existing
 * FloatingVoiceButton (which is bottom-right). Hidden when no realtime
 * session is active; auto-fades in/out.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Maximize2 } from 'lucide-react'

import { useSharedRealtimeVoice } from '@/hooks/useSharedRealtimeVoice'

import { MascotSVG } from './MascotSVG'
import { useMascot } from './useMascot'

const MASCOT_CHANNEL = 'zero-mascot'

export function MascotDock() {
  const voice = useSharedRealtimeVoice()
  const { face, viseme, visemeId } = useMascot({
    sessionPhase: voice.sessionPhase,
    transcripts: voice.transcripts,
    active: voice.isActive,
    latestViseme: voice.latestViseme,
  })

  // Broadcast state to any popout windows on every change.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const ch = new BroadcastChannel(MASCOT_CHANNEL)
    ch.postMessage({ type: 'state', face, viseme, visemeId, ts: Date.now() })
    return () => ch.close()
  }, [face, viseme, visemeId])

  // Auto-hide the dock when realtime is not active. Small fade-out so the
  // user doesn't see it pop in/out abruptly during connect handshakes.
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (voice.isActive) {
      setVisible(true)
      return
    }
    const t = window.setTimeout(() => setVisible(false), 600)
    return () => window.clearTimeout(t)
  }, [voice.isActive])

  if (!visible && !voice.isActive) return null

  const opacityClass = voice.isActive ? 'opacity-100' : 'opacity-0'

  return (
    <div
      data-testid="mascot-dock"
      className={[
        'fixed bottom-6 left-6 z-40 transition-opacity duration-500 pointer-events-none',
        opacityClass,
      ].join(' ')}
    >
      <div className="relative pointer-events-auto">
        <div className="rounded-full bg-zinc-900/80 backdrop-blur-sm border border-zinc-700/60 shadow-2xl p-2">
          <MascotSVG face={face} viseme={viseme} size={96} />
        </div>
        <Link
          to="/m/mascot"
          target="_blank"
          rel="noopener noreferrer"
          className="absolute -right-1 -top-1 rounded-full bg-zinc-800 border border-zinc-700 p-1.5 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-700"
          title="Pop out mascot to its own window"
          aria-label="Pop out mascot"
        >
          <Maximize2 className="w-3 h-3" />
        </Link>
      </div>
    </div>
  )
}
