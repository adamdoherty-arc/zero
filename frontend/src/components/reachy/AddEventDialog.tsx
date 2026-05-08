import { useState } from 'react'
import { Plus, Loader2, X } from 'lucide-react'
import { useCreateCalendarEvent } from '@/hooks/useCalendarApi'
import { useToast } from '@/hooks/use-toast'

interface Props {
  defaultDate?: string // YYYY-MM-DD
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function defaultStartTime(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() + 15)
  d.setSeconds(0, 0)
  // round to next 15
  const m = d.getMinutes()
  const rounded = Math.ceil(m / 15) * 15
  if (rounded === 60) {
    d.setHours(d.getHours() + 1)
    d.setMinutes(0)
  } else {
    d.setMinutes(rounded)
  }
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function plusMinutes(local: string, mins: number): string {
  const d = new Date(local)
  d.setMinutes(d.getMinutes() + mins)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function AddEventDialog({ defaultDate: _defaultDate }: Props) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [start, setStart] = useState(defaultStartTime())
  const [end, setEnd] = useState(plusMinutes(defaultStartTime(), 30))
  const [attendees, setAttendees] = useState('')
  const [location, setLocation] = useState('')

  const create = useCreateCalendarEvent()
  const { toast } = useToast()

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) {
      toast({ title: 'Title required', variant: 'destructive' })
      return
    }
    try {
      await create.mutateAsync({
        summary: title.trim(),
        location: location.trim() || undefined,
        start: { date_time: new Date(start).toISOString(), timezone: tz },
        end: { date_time: new Date(end).toISOString(), timezone: tz },
        attendees: attendees
          .split(',')
          .map((a) => a.trim())
          .filter(Boolean)
          .map((email) => ({ email })),
      })
      toast({ title: 'Event created', description: title })
      setTitle('')
      setLocation('')
      setAttendees('')
      setOpen(false)
    } catch (e) {
      toast({ title: 'Create failed', description: String(e), variant: 'destructive' })
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="text-sm px-3 py-1.5 rounded bg-indigo-500/20 text-indigo-200 hover:bg-indigo-500/30 flex items-center gap-1.5"
      >
        <Plus className="w-4 h-4" /> Add event
      </button>

      {open && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setOpen(false)}>
          <form
            onSubmit={submit}
            onClick={(e) => e.stopPropagation()}
            className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-full max-w-md space-y-3"
          >
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold text-white">New calendar event</h2>
              <button type="button" onClick={() => setOpen(false)} className="text-gray-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            <label className="block">
              <span className="text-xs text-gray-400">Title</span>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                placeholder="Sync with team"
                required
              />
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-gray-400">Start</span>
                <input
                  type="datetime-local"
                  value={start}
                  onChange={(e) => {
                    setStart(e.target.value)
                    setEnd(plusMinutes(e.target.value, 30))
                  }}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                  required
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-400">End</span>
                <input
                  type="datetime-local"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                  required
                />
              </label>
            </div>

            <label className="block">
              <span className="text-xs text-gray-400">Location (optional)</span>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                placeholder="Conference Room A"
              />
            </label>

            <label className="block">
              <span className="text-xs text-gray-400">Attendees (comma-separated emails)</span>
              <input
                type="text"
                value={attendees}
                onChange={(e) => setAttendees(e.target.value)}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                placeholder="alice@example.com, bob@example.com"
              />
            </label>

            <button
              type="submit"
              disabled={create.isPending}
              className="w-full mt-2 px-3 py-2 text-sm font-semibold rounded bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />} Create event
            </button>
          </form>
        </div>
      )}
    </>
  )
}
