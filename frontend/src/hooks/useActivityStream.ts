import { useCallback, useEffect, useRef, useState } from 'react'
import { getAuthHeaders } from '@/lib/auth'
import type { OrchestratorActivityEvent } from '../types'

const SSE_URL = '/api/orchestrator/activity/stream'
const MAX_EVENTS = 100

export function useActivityStream() {
  const [events, setEvents] = useState<OrchestratorActivityEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const retryRef = useRef(0)

  const connect = useCallback(() => {
    // Close existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const headers = getAuthHeaders()
    const token = headers?.Authorization?.replace('Bearer ', '') ?? ''
    const url = `${SSE_URL}${token ? `?token=${token}` : ''}`

    const es = new EventSource(url)
    eventSourceRef.current = es

    es.onopen = () => {
      setIsConnected(true)
      retryRef.current = 0
    }

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.event_type === 'connected') return // Skip initial handshake

        setEvents((prev) => {
          const next = [data as OrchestratorActivityEvent, ...prev]
          return next.slice(0, MAX_EVENTS)
        })
      } catch {
        // Skip malformed events
      }
    }

    es.onerror = () => {
      setIsConnected(false)
      es.close()

      // Exponential backoff reconnect
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000)
      retryRef.current += 1
      setTimeout(connect, delay)
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      eventSourceRef.current?.close()
    }
  }, [connect])

  const reconnect = useCallback(() => {
    retryRef.current = 0
    connect()
  }, [connect])

  return { events, isConnected, reconnect }
}
