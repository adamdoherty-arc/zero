import { useCallback, useEffect, useRef, useState } from 'react'
import { useMeetingRecordingStore } from '@/store/meetingRecordingStore'
import type { LiveTranscriptSegment } from '@/types/meeting'

// WebSocket connects to DailyMeetings (standalone host app on port 18793)
// which handles audio recording since Docker can't access Windows audio APIs.
function getWsBaseUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.hostname}:18793`
}

// ---- Recording Status WebSocket ----
export function useMeetingRecordingWS() {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const mountedRef = useRef(true)
  const [isConnected, setIsConnected] = useState(false)

  const connect = useCallback(() => {
    if (!mountedRef.current) return

    if (wsRef.current) {
      wsRef.current.close()
    }

    const ws = new WebSocket(`${getWsBaseUrl()}/ws/meeting-recording`)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      retryRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const s = useMeetingRecordingStore.getState()
        s.setRecording(data.is_recording, data.meeting_id)
        s.setDuration(data.duration_seconds || 0)
        s.setAudioLevels(data.audio_levels || null)
      } catch {
        // Skip malformed messages
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      if (!mountedRef.current) return
      // Exponential backoff reconnect
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000)
      retryRef.current += 1
      setTimeout(connect, delay)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      wsRef.current?.close()
    }
  }, [connect])

  const reconnect = useCallback(() => {
    retryRef.current = 0
    connect()
  }, [connect])

  return { isConnected, reconnect }
}

// ---- Processing Progress WebSocket ----
export interface ProcessingProgress {
  stage: string
  progress: number
  message: string
}

export function useMeetingProcessingWS(
  onProgress: (data: ProcessingProgress) => void
) {
  const wsRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  // Stable ref for the callback to avoid reconnects when onProgress changes
  const onProgressRef = useRef(onProgress)
  onProgressRef.current = onProgress

  useEffect(() => {
    const ws = new WebSocket(`${getWsBaseUrl()}/ws/meeting-processing`)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ProcessingProgress
        onProgressRef.current(data)
      } catch {
        // Skip malformed messages
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
    }

    ws.onerror = () => {
      ws.close()
    }

    return () => {
      ws.close()
    }
  }, [])

  return { isConnected }
}

// ---- Live Transcript WebSocket ----
export function useMeetingLiveTranscriptWS(enabled: boolean) {
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const mountedRef = useRef(true)
  const [isConnected, setIsConnected] = useState(false)

  const connect = useCallback(() => {
    if (!mountedRef.current) return

    if (wsRef.current) {
      wsRef.current.close()
    }

    const ws = new WebSocket(`${getWsBaseUrl()}/ws/meeting-live-transcript`)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      retryRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'segment') {
          const segment: LiveTranscriptSegment = {
            type: 'segment',
            id: data.id,
            start: data.start,
            end: data.end,
            text: data.text,
          }
          useMeetingRecordingStore.getState().addLiveSegment(segment)
        }
      } catch {
        // Skip malformed messages
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      if (!mountedRef.current) return
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000)
      retryRef.current += 1
      setTimeout(connect, delay)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    if (enabled) {
      connect()
    }
    return () => {
      mountedRef.current = false
      wsRef.current?.close()
    }
  }, [enabled, connect])

  return { isConnected }
}
