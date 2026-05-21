import { useEffect, useRef, useState } from 'react'
import { Captions, Move, X } from 'lucide-react'
import {
  useReachyCompanionStatus,
} from '@/hooks/useReachyApi'

interface CaptionLine {
  text: string
  speaker?: string | null
  ts: number
}

const LS_KEY = 'zero.live_captions.position'

/**
 * F-77 — floating draggable overlay that streams the live meeting
 * transcript while companion.meeting_active=true.
 *
 * Auto-shows when meeting_active flips True and auto-hides on False.
 * Connects to ``/ws/meeting-live-transcript`` (host_agent owns this
 * socket — see frontend/nginx.conf). Persists its (x,y) to localStorage
 * so it lands in the same spot across sessions.
 */
export function LiveCaptionsOverlay() {
  const status = useReachyCompanionStatus()
  const meetingActive = Boolean(status.data?.policy?.meeting_active)
  const [open, setOpen] = useState(true)
  const [pos, setPos] = useState<{ x: number; y: number }>(() => {
    try {
      const raw = localStorage.getItem(LS_KEY)
      if (raw) return JSON.parse(raw)
    } catch {
      // ignore
    }
    return { x: 24, y: 24 }
  })
  const [lines, setLines] = useState<CaptionLine[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(pos))
    } catch {
      // storage unavailable
    }
  }, [pos])

  useEffect(() => {
    if (!meetingActive || !open) {
      if (wsRef.current) {
        try {
          wsRef.current.close()
        } catch {
          // ignore
        }
        wsRef.current = null
      }
      return
    }
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${scheme}://${window.location.host}/ws/meeting-live-transcript`
    let cancelled = false
    let backoff = 500

    const connect = () => {
      if (cancelled) return
      try {
        const ws = new WebSocket(url)
        wsRef.current = ws
        ws.onopen = () => {
          backoff = 500
        }
        ws.onmessage = (ev) => {
          let parsed: Record<string, unknown> | null = null
          try {
            parsed = JSON.parse(ev.data)
          } catch {
            return
          }
          if (!parsed || typeof parsed !== 'object') return
          const text = String(parsed.text ?? parsed.transcript ?? '').trim()
          if (!text) return
          const speaker = (parsed.speaker ?? null) as string | null
          setLines((prev) => {
            const next = [...prev, { text, speaker, ts: Date.now() }]
            return next.slice(-5)
          })
        }
        ws.onclose = () => {
          wsRef.current = null
          if (cancelled || !meetingActive) return
          const delay = Math.min(backoff, 8000)
          backoff = Math.min(backoff * 2, 8000)
          window.setTimeout(connect, delay)
        }
        ws.onerror = () => {
          try {
            ws.close()
          } catch {
            // ignore
          }
        }
      } catch {
        const delay = Math.min(backoff, 8000)
        backoff = Math.min(backoff * 2, 8000)
        window.setTimeout(connect, delay)
      }
    }
    connect()
    return () => {
      cancelled = true
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
  }, [meetingActive, open])

  // Auto-clear stale lines when meeting ends.
  useEffect(() => {
    if (!meetingActive) setLines([])
  }, [meetingActive])

  if (!meetingActive || !open) return null

  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      baseX: pos.x,
      baseY: pos.y,
    }
    const onMove = (mv: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      setPos({
        x: Math.max(0, d.baseX + (mv.clientX - d.startX)),
        y: Math.max(0, d.baseY + (mv.clientY - d.startY)),
      })
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div
      className="fixed z-[60] w-[420px] max-w-[95vw] glass-card border border-sky-500/40 bg-sky-500/5 shadow-xl"
      style={{ left: pos.x, top: pos.y }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b border-sky-500/30 cursor-grab active:cursor-grabbing select-none"
        onMouseDown={onMouseDown}
      >
        <Captions className="w-4 h-4 text-sky-300" />
        <span className="text-xs uppercase tracking-wide text-sky-200">
          Live captions
        </span>
        <span className="text-[10px] text-sky-400/70 ml-1">
          meeting · "Hey Zero" to ask
        </span>
        <span className="flex-1" />
        <Move className="w-3.5 h-3.5 text-sky-300/60" />
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded p-0.5 text-sky-300 hover:bg-sky-500/20"
          title="Close (re-opens automatically on the next meeting)"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="px-3 py-2 space-y-1 max-h-48 overflow-y-auto">
        {lines.length === 0 ? (
          <div className="text-xs text-gray-400 italic">listening…</div>
        ) : (
          lines.map((line, i) => (
            <div key={`${line.ts}-${i}`} className="text-sm leading-snug">
              {line.speaker && (
                <span className="font-semibold text-sky-200 mr-1.5">
                  {line.speaker}:
                </span>
              )}
              <span className="text-gray-100">{line.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
