import { useState } from 'react'
import { Disc3, Loader2, X } from 'lucide-react'
import { useCreateMeeting, useStartRecording } from '@/hooks/useMeetings'
import { useToast } from '@/hooks/use-toast'

interface Props {
  onStarted: (meetingId: string) => void
  disabled?: boolean
  disabledReason?: string
}

export function QuickMeetingDialog({ onStarted, disabled, disabledReason }: Props) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [duration, setDuration] = useState(5)

  const createMeeting = useCreateMeeting()
  const startRecording = useStartRecording()
  const { toast } = useToast()

  const busy = createMeeting.isPending || startRecording.isPending

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = title.trim() || 'Quick meeting'
    const start = new Date()
    const end = new Date(start.getTime() + duration * 60_000)
    try {
      const meeting = await createMeeting.mutateAsync({
        title: trimmed,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        participants: [],
      })
      // Call DailyMeetings (via nginx proxy) directly. Bypasses Zero's
      // /meetings/{id}/record-now which routes through the host_agent
      // (repurposed for Reachy daemon supervision and doesn't own the
      // /record/start endpoint any more).
      await startRecording.mutateAsync({
        meeting_id: meeting.id,
        title: trimmed,
        source: 'mixed',
      })
      toast({ title: 'Recording started', description: trimmed })
      onStarted(meeting.id)
      setOpen(false)
      setTitle('')
      setDuration(5)
    } catch (e) {
      toast({
        title: 'Could not start quick meeting',
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  return (
    <>
      <button
        onClick={() => !disabled && setOpen(true)}
        disabled={disabled}
        title={disabled ? disabledReason : 'Start recording a quick meeting now'}
        className="text-sm px-3 py-1.5 rounded bg-red-500/20 text-red-200 hover:bg-red-500/30 flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Disc3 className="w-4 h-4" /> Quick meeting
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
          onClick={() => !busy && setOpen(false)}
        >
          <form
            onSubmit={submit}
            onClick={(e) => e.stopPropagation()}
            className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-full max-w-md space-y-3"
          >
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold text-white">Record a quick meeting</h2>
              <button type="button" onClick={() => setOpen(false)} disabled={busy} className="text-gray-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            <p className="text-xs text-gray-400">
              Starts recording immediately via DailyMeetings. Stop + summarise from the panel that appears on this page.
            </p>

            <label className="block">
              <span className="text-xs text-gray-400">Title</span>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
                placeholder="Zero test meeting"
                autoFocus
              />
            </label>

            <label className="block">
              <span className="text-xs text-gray-400">Expected duration (minutes)</span>
              <input
                type="number"
                min={1}
                max={120}
                value={duration}
                onChange={(e) => setDuration(Math.max(1, Math.min(120, Number(e.target.value) || 5)))}
                className="w-full mt-1 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm"
              />
              <span className="text-[10px] text-gray-500">Used only to set the end time. You can stop any time.</span>
            </label>

            <button
              type="submit"
              disabled={busy}
              className="w-full mt-2 px-3 py-2 text-sm font-semibold rounded bg-red-500/20 text-red-200 hover:bg-red-500/30 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Disc3 className="w-4 h-4" />} Start recording
            </button>
          </form>
        </div>
      )}
    </>
  )
}
