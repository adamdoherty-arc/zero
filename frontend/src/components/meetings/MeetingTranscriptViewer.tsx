import { useEffect, useRef, useState } from 'react'
import { Mic, Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import type { TranscriptSegment } from '@/types/meeting'

interface Props {
  segments: TranscriptSegment[]
  speakerMap?: Record<string, string>
  meetingId?: string
  onTimestampClick?: (time: number) => void
  /** F-90 — when set, smooth-scroll the segment whose ``start`` is the
   * closest match into view + briefly flash a highlight. Changing the
   * value re-fires the scroll (use ``Date.now()`` or a wrapper). */
  scrollToSeconds?: number | null
  /** F-90 — fired with the currently-on-screen segment's start so the
   * parent (topic timeline) can highlight the active topic block. */
  onActiveSecondsChange?: (seconds: number) => void
}

const SPEAKER_COLORS = [
  'text-blue-400', 'text-emerald-400', 'text-amber-400', 'text-purple-400',
  'text-pink-400', 'text-cyan-400', 'text-orange-400', 'text-rose-400',
]

interface EnrollDialogState {
  segmentId: number
  start: number
  end: number
  displayName: string
}

export function MeetingTranscriptViewer({
  segments,
  speakerMap = {},
  meetingId,
  onTimestampClick,
  scrollToSeconds,
  onActiveSecondsChange,
}: Props) {
  const speakerColorMap: Record<string, string> = {}
  let colorIdx = 0
  const [enrollDialog, setEnrollDialog] = useState<EnrollDialogState | null>(null)
  const [enrolling, setEnrolling] = useState(false)
  const [flashId, setFlashId] = useState<number | null>(null)
  const segmentRefs = useRef<Map<number, HTMLDivElement>>(new Map())

  // F-90 — react to scrollToSeconds: find the nearest segment and scroll
  useEffect(() => {
    if (scrollToSeconds == null || !segments?.length) return
    let nearest = segments[0]
    let nearestDelta = Math.abs((segments[0].start_time ?? 0) - scrollToSeconds)
    for (const s of segments) {
      const d = Math.abs((s.start_time ?? 0) - scrollToSeconds)
      if (d < nearestDelta) {
        nearest = s
        nearestDelta = d
      }
    }
    if (nearest?.id == null) return
    const el = segmentRefs.current.get(nearest.id)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setFlashId(nearest.id)
    const t = window.setTimeout(() => setFlashId(null), 1200)
    return () => window.clearTimeout(t)
  }, [scrollToSeconds, segments])

  // F-90 — observe which segment is centered + emit its start
  useEffect(() => {
    if (!onActiveSecondsChange || !segments?.length) return
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (!visible.length) return
        const center = window.innerHeight / 2
        const best = visible.reduce((acc, cur) => {
          const accMid = (acc.boundingClientRect.top + acc.boundingClientRect.bottom) / 2
          const curMid = (cur.boundingClientRect.top + cur.boundingClientRect.bottom) / 2
          return Math.abs(curMid - center) < Math.abs(accMid - center) ? cur : acc
        })
        const segId = Number(best.target.getAttribute('data-segment-id') ?? -1)
        const seg = segments.find((s) => s.id === segId)
        if (seg?.start_time != null) onActiveSecondsChange(seg.start_time)
      },
      { threshold: 0.4 },
    )
    segmentRefs.current.forEach((el) => obs.observe(el))
    return () => obs.disconnect()
  }, [segments, onActiveSecondsChange])

  const getSpeakerColor = (speaker: string) => {
    if (!speakerColorMap[speaker]) {
      speakerColorMap[speaker] = SPEAKER_COLORS[colorIdx % SPEAKER_COLORS.length]
      colorIdx++
    }
    return speakerColorMap[speaker]
  }

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  async function handleEnroll() {
    if (!enrollDialog || !meetingId) return
    const name = enrollDialog.displayName.trim()
    if (!name) {
      toast({ title: 'Name required', variant: 'destructive' })
      return
    }
    setEnrolling(true)
    try {
      const res = await fetch('/api/voiceprints/enroll-from-segment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          meeting_id: meetingId,
          start_seconds: enrollDialog.start,
          end_seconds: enrollDialog.end,
          display_name: name,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      toast({
        title: data.replaced_existing ? `Updated voice for ${name}` : `Enrolled ${name}`,
        description: `${(enrollDialog.end - enrollDialog.start).toFixed(1)}s sample from this meeting.`,
      })
      setEnrollDialog(null)
    } catch (e) {
      toast({ title: 'Enrollment failed', description: String(e), variant: 'destructive' })
    } finally {
      setEnrolling(false)
    }
  }

  if (!segments.length) {
    return <p className="text-zinc-500 text-sm">No transcript available.</p>
  }

  return (
    <>
      <ScrollArea className="h-[500px]">
        <div className="space-y-3 pr-4">
          {segments.map((seg) => {
            const speaker = speakerMap[seg.speaker || ''] || seg.speaker || 'Speaker'
            const duration = seg.end_time - seg.start_time
            const canEnroll = !!meetingId && duration >= 0.8
            return (
              <div
                key={seg.id}
                data-segment-id={seg.id}
                ref={(el) => {
                  if (el) segmentRefs.current.set(seg.id, el)
                  else segmentRefs.current.delete(seg.id)
                }}
                className={`flex gap-3 group rounded-md px-2 -mx-2 transition-colors ${
                  flashId === seg.id ? 'bg-indigo-500/15 ring-1 ring-indigo-400/40' : ''
                }`}
              >
                <button
                  onClick={() => onTimestampClick?.(seg.start_time)}
                  className="text-xs text-zinc-500 hover:text-blue-400 font-mono mt-1 shrink-0 w-12"
                >
                  {formatTime(seg.start_time)}
                </button>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium ${getSpeakerColor(speaker)}`}>
                      {speaker}
                    </span>
                    {canEnroll && (
                      <button
                        onClick={() =>
                          setEnrollDialog({
                            segmentId: seg.id,
                            start: seg.start_time,
                            end: seg.end_time,
                            displayName: speakerMap[seg.speaker || ''] || '',
                          })
                        }
                        className="opacity-0 group-hover:opacity-100 transition text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 flex items-center gap-1"
                        title={`Enroll this ${duration.toFixed(1)}s slice as a voiceprint`}
                      >
                        <Mic className="w-2.5 h-2.5" />
                        Enroll voice
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-zinc-300 mt-0.5">{seg.text}</p>
                </div>
              </div>
            )
          })}
        </div>
      </ScrollArea>

      {enrollDialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={() => !enrolling && setEnrollDialog(null)}
        >
          <div
            className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-[420px] max-w-[90vw]"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-white mb-1 flex items-center gap-2">
              <Mic className="w-4 h-4 text-emerald-300" /> Enroll voiceprint
            </h3>
            <div className="text-xs text-gray-400 mb-3">
              Segment {formatTime(enrollDialog.start)}–{formatTime(enrollDialog.end)} ({(enrollDialog.end - enrollDialog.start).toFixed(1)}s)
            </div>
            <label className="block text-xs text-gray-400 mb-1">Display name</label>
            <input
              autoFocus
              type="text"
              value={enrollDialog.displayName}
              onChange={(e) => setEnrollDialog({ ...enrollDialog, displayName: e.target.value })}
              placeholder="e.g. Alice Wong"
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500"
              disabled={enrolling}
            />
            <div className="text-[11px] text-gray-500 mt-2">
              The embedding is computed from this slice of the meeting recording. Re-enrolling with the same name replaces the prior sample.
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setEnrollDialog(null)}
                disabled={enrolling}
                className="text-sm px-3 py-1.5 rounded bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleEnroll}
                disabled={enrolling || !enrollDialog.displayName.trim()}
                className="text-sm px-4 py-1.5 rounded bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50 flex items-center gap-1.5"
              >
                {enrolling && <Loader2 className="w-3 h-3 animate-spin" />}
                Enroll
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
