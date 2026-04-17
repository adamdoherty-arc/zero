import { create } from 'zustand'
import type { AudioLevels, LiveTranscriptSegment } from '../types/meeting'

interface MeetingRecordingState {
  // Data
  isRecording: boolean
  meetingId: string | null
  durationSeconds: number
  audioLevels: AudioLevels | null
  liveSegments: LiveTranscriptSegment[]

  // Actions
  setRecording: (isRecording: boolean, meetingId?: string | null) => void
  setDuration: (seconds: number) => void
  setAudioLevels: (levels: AudioLevels | null) => void
  addLiveSegment: (segment: LiveTranscriptSegment) => void
  clearLiveSegments: () => void
  reset: () => void
}

export const useMeetingRecordingStore = create<MeetingRecordingState>((set) => ({
  // Initial state
  isRecording: false,
  meetingId: null,
  durationSeconds: 0,
  audioLevels: null,
  liveSegments: [],

  // Actions
  setRecording: (isRecording, meetingId = null) => set((state) => ({
    isRecording,
    meetingId,
    liveSegments: isRecording ? state.liveSegments : [],
  })),
  setDuration: (durationSeconds) => set({ durationSeconds }),
  setAudioLevels: (audioLevels) => set({ audioLevels }),
  addLiveSegment: (segment) => set((state) => ({
    liveSegments: [...state.liveSegments, segment],
  })),
  clearLiveSegments: () => set({ liveSegments: [] }),
  reset: () => set({ isRecording: false, meetingId: null, durationSeconds: 0, audioLevels: null, liveSegments: [] }),
}))
