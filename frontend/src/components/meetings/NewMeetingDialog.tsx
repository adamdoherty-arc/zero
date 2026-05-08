import { useMemo, useState } from 'react'
import { CalendarClock, Loader2, Mic } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useCalendarEvents, useMeetingFromEvent } from '@/hooks/useCalendarApi'
import { useStartRecording } from '@/hooks/useMeetings'
import { toast } from '@/hooks/use-toast'

interface Props {
  micDeviceIndex?: number
  disabled?: boolean
  disabledReason?: string
}

export function NewMeetingDialog({ micDeviceIndex, disabled, disabledReason }: Props) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [eventId, setEventId] = useState<string | ''>('')

  const range = useMemo(() => {
    const now = new Date()
    const end = new Date(now)
    end.setDate(end.getDate() + 7)
    return {
      start_date: now.toISOString(),
      end_date: end.toISOString(),
      limit: 50,
    }
  }, [])

  const events = useCalendarEvents(range)
  const fromEvent = useMeetingFromEvent()
  const startRecording = useStartRecording()

  const busy = fromEvent.isPending || startRecording.isPending

  function reset() {
    setTitle('')
    setEventId('')
  }

  async function handleStart() {
    try {
      let meetingId: string | undefined
      let resolvedTitle = title.trim() || undefined

      if (eventId) {
        const m = await fromEvent.mutateAsync(eventId)
        meetingId = m.id
        if (!resolvedTitle) resolvedTitle = m.title
      }

      if (!meetingId && !resolvedTitle) {
        resolvedTitle = `Meeting ${new Date().toLocaleString()}`
      }

      await startRecording.mutateAsync({
        meeting_id: meetingId,
        title: resolvedTitle,
        source: 'mic',
        mic_device_index: micDeviceIndex,
      })

      toast({
        title: 'Recording started',
        description: resolvedTitle,
      })
      reset()
      setOpen(false)
    } catch (e) {
      toast({
        title: 'Could not start',
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset() }}>
      <DialogTrigger asChild>
        <Button
          variant="default"
          className="gap-2"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
        >
          <Mic className="w-4 h-4" />
          New Meeting
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Start a new meeting</DialogTitle>
          <DialogDescription>
            Give it a title or link a calendar event. Audio captures from{' '}
            <span className="font-mono text-xs">{micDeviceIndex !== undefined ? `mic #${micDeviceIndex}` : 'default mic'}</span>.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
              Title
            </label>
            <Input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Quick sync, 1:1 with Bob, …"
              disabled={busy}
            />
          </div>

          <div>
            <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1">
              <CalendarClock className="w-3 h-3" /> Link to calendar event (optional)
            </label>
            <select
              value={eventId}
              onChange={(e) => {
                setEventId(e.target.value)
                if (e.target.value && !title) {
                  const ev = events.data?.find((x) => x.id === e.target.value)
                  if (ev?.summary) setTitle(ev.summary)
                }
              }}
              disabled={busy}
              className="w-full bg-gray-900/60 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 disabled:opacity-50"
            >
              <option value="">— None —</option>
              {(events.data ?? []).map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.summary || 'Untitled'} ·{' '}
                  {ev.start?.date_time
                    ? new Date(ev.start.date_time).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: 'numeric',
                        minute: '2-digit',
                      })
                    : ev.start?.date || ''}
                </option>
              ))}
            </select>
            {events.isLoading && (
              <div className="text-[10px] text-gray-500 mt-1">
                <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                Loading events…
              </div>
            )}
            {!events.isLoading && (events.data ?? []).length === 0 && (
              <div className="text-[10px] text-gray-500 mt-1">
                No events in the next 7 days. Connect Google Calendar from the page header.
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button onClick={handleStart} disabled={busy} className="gap-2">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mic className="w-4 h-4" />}
            Start recording
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
