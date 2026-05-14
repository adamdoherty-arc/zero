/**
 * Mascot — composite component that wires `useMascot` to `MascotSVG`.
 *
 * Reads the shared realtime voice context so any sibling component (the
 * InteractiveModeBar, a popout window, the mobile PWA) can mount the same
 * mascot and they'll all share state.
 */

import { useSharedRealtimeVoice } from '@/hooks/useSharedRealtimeVoice'

import { MascotSVG } from './MascotSVG'
import { useMascot } from './useMascot'

export interface MascotProps {
  size?: number | string
  className?: string
  animateAntennas?: boolean
  color?: string
}

export function Mascot({
  size = 120,
  className,
  animateAntennas = true,
  color,
}: MascotProps) {
  const voice = useSharedRealtimeVoice()
  const { face, viseme } = useMascot({
    sessionPhase: voice.sessionPhase,
    transcripts: voice.transcripts,
    active: voice.isActive,
    latestViseme: voice.latestViseme,
  })

  return (
    <MascotSVG
      face={face}
      viseme={viseme}
      animateAntennas={animateAntennas}
      color={color}
      size={size}
      className={className}
    />
  )
}
