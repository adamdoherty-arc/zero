import { useEffect, useRef } from 'react'
import { useToast } from '@/hooks/use-toast'

/**
 * NotificationListener — subscribes to /api/notifications/ws and dispatches
 * Radix toasts for meeting nudges, meeting start/stop, and any other event
 * published by the backend notification bus.
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

          if (type === 'meeting.nudge') {
            const bucket = Number(event.bucket_min ?? 0)
            const title = String(event.title ?? 'an event')
            toast({
              title: `Meeting in ${bucket} min`,
              description: title,
            })
            return
          }
          if (type === 'meeting.starting') {
            const title = String(event.title ?? 'this meeting')
            toast({
              title: 'Recording meeting',
              description: `Capturing ${title}. Reachy is listening silently — say "Hey Zero" to ask a question.`,
            })
            return
          }
          if (type === 'meeting.stopped') {
            const title = String(event.title ?? 'meeting')
            toast({
              title: 'Meeting captured',
              description: `Transcript and summary for ${title} saved to the vault.`,
            })
            return
          }
          if (type === 'meeting.prep') {
            const title = String(event.title ?? 'an upcoming meeting')
            const summary = String(event.summary ?? '')
            toast({
              title: `Prep brief — ${title}`,
              description: summary || 'Tap to view full prep context.',
            })
            return
          }
          if (type === 'meeting.consent_needed') {
            const title = String(event.title ?? 'meeting')
            const reason = String(event.reason ?? '')
            toast({
              title: `Confirm recording — ${title}`,
              description: `Auto-record paused (${reason}). Click record-now if you still want to capture this meeting.`,
              variant: 'destructive',
            })
            return
          }
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
