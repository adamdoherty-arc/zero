import { useMemo, useState } from 'react'
import { CalendarClock, Disc3, Loader2, MapPin, Users, Zap } from 'lucide-react'
import {
  type CalendarEventSummary,
  useMeetingFromEvent,
  useRecordNow,
  useToggleAutoRecord,
  useAutoRecordList,
} from '@/hooks/useCalendarApi'
import { useToast } from '@/hooks/use-toast'

interface Props {
  event: CalendarEventSummary
}

function eventStartDate(e: CalendarEventSummary): Date | null {
  if (e.start?.date_time) return new Date(e.start.date_time)
  if (e.start?.date) return new Date(e.start.date)
  return null
}

function eventEndDate(e: CalendarEventSummary): Date | null {
  if (e.end?.date_time) return new Date(e.end.date_time)
  if (e.end?.date) return new Date(e.end.date)
  return null
}

function formatTimeRange(start: Date | null, end: Date | null, allDay?: boolean): string {
  if (!start) return 'Unknown time'
  if (allDay) return start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  const d = start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  const s = start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  if (!end) return `${d} · ${s}`
  const e = end.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${d} · ${s} – ${e}`
}

function relativeStartLabel(start: Date | null): string | null {
  if (!start) return null
  const ms = start.getTime() - Date.now()
  const min = Math.round(ms / 60000)
  if (min < -60) return null
  if (min < -1) return `${Math.abs(min)} min ago`
  if (min < 1) return 'starting now'
  if (min < 60) return `in ${min} min`
  const hr = Math.round(min / 60)
  if (hr < 24) return `in ${hr} h`
  return null
}

export function MeetingCard({ event }: Props) {
  const { toast } = useToast()
  const fromEvent = useMeetingFromEvent()
  const recordNow = useRecordNow()
  const toggleAutoRecord = useToggleAutoRecord()
  const autoRecordList = useAutoRecordList()

  const [meetingId, setMeetingId] = useState<string | null>(null)
  const start = useMemo(() => eventStartDate(event), [event])
  const end = useMemo(() => eventEndDate(event), [event])
  const relative = relativeStartLabel(start)

  const autoEntry = autoRecordList.data?.entries.find((e) => e.calendar_event_id === event.id)
  const isAutoRecord = Boolean(autoEntry)

  async function ensureMeeting(): Promise<string | null> {
    if (meetingId) return meetingId
    if (autoEntry?.meeting_id) {
      setMeetingId(autoEntry.meeting_id)
      return autoEntry.meeting_id
    }
    try {
      const m = await fromEvent.mutateAsync(event.id)
      setMeetingId(m.id)
      return m.id
    } catch (e) {
      toast({ title: 'Could not create meeting', description: String(e), variant: 'destructive' })
      return null
    }
  }

  async function handleRecordNow() {
    const id = await ensureMeeting()
    if (!id) return
    try {
      await recordNow.mutateAsync(id)
      toast({ title: 'Recording started', description: event.summary })
    } catch (e) {
      toast({ title: 'Start failed', description: String(e), variant: 'destructive' })
    }
  }

  async function handleToggleAutoRecord() {
    const id = await ensureMeeting()
    if (!id) return
    try {
      const res = await toggleAutoRecord.mutateAsync({ meeting_id: id, enabled: !isAutoRecord })
      toast({
        title: res.auto_record ? 'Auto-record ON' : 'Auto-record OFF',
        description: event.summary,
      })
    } catch (e) {
      toast({ title: 'Toggle failed', description: String(e), variant: 'destructive' })
    }
  }

  const busy = fromEvent.isPending || recordNow.isPending || toggleAutoRecord.isPending

  return (
    <div className="glass-card p-4 hover:border-emerald-500/30 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <CalendarClock className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            <h3 className="text-sm font-semibold text-white truncate">{event.summary || 'Untitled'}</h3>
            {relative && (
              <span className="text-[10px] uppercase tracking-wide bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded">
                {relative}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400">{formatTimeRange(start, end, event.is_all_day)}</p>
          {event.location && (
            <p className="text-xs text-gray-500 mt-1 flex items-center gap-1">
              <MapPin className="w-3 h-3" /> {event.location}
            </p>
          )}
          {event.has_attendees && (
            <p className="text-xs text-gray-500 mt-1 flex items-center gap-1">
              <Users className="w-3 h-3" /> with attendees
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-700/40">
        <button
          onClick={handleRecordNow}
          disabled={busy}
          className="text-xs px-2.5 py-1.5 rounded bg-red-500/15 text-red-300 hover:bg-red-500/25 flex items-center gap-1 disabled:opacity-50"
        >
          {recordNow.isPending ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Disc3 className="w-3 h-3" />
          )}
          Record now
        </button>
        <button
          onClick={handleToggleAutoRecord}
          disabled={busy || event.is_all_day}
          className={`text-xs px-2.5 py-1.5 rounded flex items-center gap-1 disabled:opacity-50 ${
            isAutoRecord
              ? 'bg-emerald-500/25 text-emerald-200 hover:bg-emerald-500/35'
              : 'bg-gray-700/50 text-gray-300 hover:bg-gray-600/60'
          }`}
        >
          <Zap className="w-3 h-3" />
          {isAutoRecord ? 'Auto-record ON' : 'Auto-record'}
        </button>
        {event.html_link && (
          <a
            href={event.html_link}
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-xs text-indigo-400 hover:text-indigo-300"
          >
            Open in Calendar →
          </a>
        )}
      </div>
    </div>
  )
}
