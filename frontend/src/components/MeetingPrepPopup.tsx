import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { CalendarClock } from 'lucide-react'

/**
 * Feature-59 — MeetingPrepPopup
 *
 * Subscribes to /api/notifications/ws and surfaces the full prep brief
 * as a dialog when a `meeting.prep` event lands. NotificationListener
 * already shows the short toast; this is the "click to expand" surface.
 *
 * State machine: only one popup at a time. New prep events while a
 * popup is open update the in-flight brief instead of stacking modals.
 */

interface PrepEvent {
  type: 'meeting.prep'
  event_id?: string
  title?: string
  starts_at?: string
  summary?: string
  markdown?: string
}

function formatWhen(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const now = Date.now()
  const minsAway = Math.round((d.getTime() - now) / 60_000)
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (minsAway > 0 && minsAway < 60) return `${time} (in ${minsAway} min)`
  return time
}

export function MeetingPrepPopup() {
  const [event, setEvent] = useState<PrepEvent | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectMs = useRef<number>(500)
  const cancelledRef = useRef<boolean>(false)
  const seenIds = useRef<Set<string>>(new Set())

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
          let payload: Record<string, unknown> | null = null
          try {
            payload = JSON.parse(ev.data)
          } catch {
            return
          }
          if (!payload || typeof payload !== 'object') return
          if (payload.type !== 'meeting.prep') return

          const eid = String(payload.event_id ?? '')
          if (eid && seenIds.current.has(eid)) return
          if (eid) seenIds.current.add(eid)

          setEvent({
            type: 'meeting.prep',
            event_id: eid || undefined,
            title: typeof payload.title === 'string' ? payload.title : undefined,
            starts_at: typeof payload.starts_at === 'string' ? payload.starts_at : undefined,
            summary: typeof payload.summary === 'string' ? payload.summary : undefined,
            markdown: typeof payload.markdown === 'string' ? payload.markdown : undefined,
          })
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
            /* swallow */
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
          /* ignore */
        }
      }
    }
  }, [])

  if (!event) return null

  const when = formatWhen(event.starts_at)

  return (
    <Dialog open={event != null} onOpenChange={(open) => !open && setEvent(null)}>
      <DialogContent className="max-w-2xl bg-gray-900 border-gray-800 text-gray-100">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-emerald-300">
            <CalendarClock className="w-5 h-5" />
            Prep brief — {event.title || 'Upcoming meeting'}
          </DialogTitle>
          {when && <div className="text-xs text-gray-400 mt-1">{when}</div>}
        </DialogHeader>
        {event.summary && (
          <div className="text-sm text-gray-300 mb-2 italic">{event.summary}</div>
        )}
        {event.markdown ? (
          <pre className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed max-h-[60vh] overflow-y-auto font-sans bg-gray-950 rounded p-3 border border-gray-800">
            {event.markdown}
          </pre>
        ) : (
          <div className="text-sm text-gray-400">No additional context for this event.</div>
        )}
      </DialogContent>
    </Dialog>
  )
}
