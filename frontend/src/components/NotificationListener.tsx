import { useEffect, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'

/**
 * NotificationListener — subscribes to /api/notifications/ws and dispatches
 * Radix toasts for events published by the backend notification bus.
 *
 * Mount once at the top of App so the WS lives for the lifetime of the
 * dashboard tab. Reconnects with exponential backoff if the socket dies.
 */
export function NotificationListener() {
  const { toast } = useToast()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectMs = useRef<number>(500)
  const cancelledRef = useRef<boolean>(false)

  useEffect(() => {
    cancelledRef.current = false

    const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${wsScheme}://${window.location.host}/api/notifications/ws`

    const connect = () => {
      if (cancelledRef.current) return
      try {
        const ws = new WebSocket(wsUrl)
        wsRef.current = ws

        ws.onopen = () => {
          reconnectMs.current = 500
        }

        ws.onmessage = (ev) => {
          let event: Record<string, unknown> | null = null
          try {
            event = JSON.parse(ev.data)
          } catch {
            return
          }
          if (!event || typeof event !== 'object') return
          const type = String(event.type ?? '')
          if (type === 'ping') return

          // Meeting toast branches removed 2026-06-20 (meetings concept retired;
          // no publisher remains, stale persisted events are ignored here).
          // Generic notice fallback.
          const summary = String(event.summary ?? event.message ?? '')
          if (summary) {
            toast({
              title: String(event.title ?? 'Zero'),
              description: summary,
            })
          }
        }

        ws.onclose = () => {
          wsRef.current = null
          if (cancelledRef.current) return
          const delay = Math.min(reconnectMs.current, 15000)
          reconnectMs.current = Math.min(delay * 2, 15000)
          window.setTimeout(connect, delay)
        }

        ws.onerror = () => {
          try {
            ws.close()
          } catch {
            // swallow — onclose will handle reconnect
          }
        }
      } catch {
        const delay = Math.min(reconnectMs.current, 15000)
        reconnectMs.current = Math.min(delay * 2, 15000)
        window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelledRef.current = true
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        try {
          ws.close()
        } catch {
          // ignore
        }
      }
    }
  }, [toast])

  return null
}
