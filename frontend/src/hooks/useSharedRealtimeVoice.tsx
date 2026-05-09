import { createContext, type ReactNode, useContext } from 'react'
import { useRealtimeVoice, type UseRealtimeVoice, type VoiceStartArgs } from '@/hooks/useRealtimeVoice'

export type { SessionPhase } from '@/hooks/useRealtimeVoice'

const RealtimeVoiceContext = createContext<UseRealtimeVoice | null>(null)

export function RealtimeVoiceProvider({
  children,
  defaults,
}: {
  children: ReactNode
  defaults?: VoiceStartArgs
}) {
  const voice = useRealtimeVoice(defaults)
  return (
    <RealtimeVoiceContext.Provider value={voice}>
      {children}
    </RealtimeVoiceContext.Provider>
  )
}

export function useSharedRealtimeVoice(): UseRealtimeVoice {
  const voice = useContext(RealtimeVoiceContext)
  if (!voice) {
    throw new Error('useSharedRealtimeVoice must be used inside RealtimeVoiceProvider')
  }
  return voice
}
