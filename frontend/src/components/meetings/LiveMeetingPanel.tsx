import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AudioLines, CheckCircle2, Loader2, Square, X, ListTodo } from 'lucide-react'
import {
  useCreateTasksFromActionItems,
  useLiveTick,
  useMeeting,
  useMeetingSummary,
  useMeetingTranscript,
  useStopRecording,
  type ActionItemTaskLink,
} from '@/hooks/useMeetings'
import {
  useMeetingLiveTranscriptWS,
  useMeetingProcessingWS,
  type ProcessingProgress,
} from '@/hooks/useMeetingWebSocket'
import { useMeetingRecordingStore } from '@/store/meetingRecordingStore'
import { useToast } from '@/hooks/use-toast'

interface Props {
  meetingId: string
  onDone: () => void
}

type Phase = 'recording' | 'processing' | 'done' | 'error'

function formatClock(s: number): string {
  const mm = Math.floor(s / 60).toString().padStart(2, '0')
  const ss = Math.floor(s % 60).toString().padStart(2, '0')
  return `${mm}:${ss}`
}

export function LiveMeetingPanel({ meetingId, onDone }: Props) {
  const { toast } = useToast()
  const [phase, setPhase] = useState<Phase>('recording')
  const [elapsed, setElapsed] = useState(0)
  const [progress, setProgress] = useState<ProcessingProgress | null>(null)
  const startedAt = useRef(Date.now())
  const scrollRef = useRef<HTMLDivElement>(null)

  const stopRecording = useStopRecording()
  const createTasks = useCreateTasksFromActionItems()
  const liveTick = useLiveTick()
  const [taskLinks, setTaskLinks] = useState<Record<number, ActionItemTaskLink>>({})
  const [runningNotes, setRunningNotes] = useState<string[]>([])
  const [liveActionCount, setLiveActionCount] = useState(0)
  const lastTickedSegRef = useRef(0)
  const { liveSegments, clearLiveSegments } = useMeetingRecordingStore()
  useMeetingLiveTranscriptWS(phase === 'recording')
  useMeetingProcessingWS(
    useCallback((p: ProcessingProgress) => {
      setProgress(p)
      if (p.stage === 'complete') setPhase('done')
    }, []),
  )

  const meeting = useMeeting(meetingId)
  const transcript = useMeetingTranscript(phase === 'done' ? meetingId : '')
  const summary = useMeetingSummary(phase === 'done' ? meetingId : '')

  useEffect(() => {
    clearLiveSegments()
    const timer = window.setInterval(() => {
      setElapsed((Date.now() - startedAt.current) / 1000)
    }, 500)
    return () => window.clearInterval(timer)
  }, [clearLiveSegments])

  // Phase 4: live running-notes tick — every 60 sec while recording, send the
  // segments since the last tick to the live-tick endpoint and append the
  // delta. Stateless on the backend; we keep the running notes here.
  useEffect(() => {
    if (phase !== 'recording') return
    const id = window.setInterval(async () => {
      const fresh = liveSegments.slice(lastTickedSegRef.current)
      if (fresh.length === 0) return
      lastTickedSegRef.current = liveSegments.length
      const chunk = fresh.map((s) => s.text).join(' ').trim()
      if (!chunk) return
      try {
        const result = await liveTick.mutateAsync({
          chunk_text: chunk,
          running_notes: runningNotes,
          meeting_title: meeting.data?.title ?? '',
        })
        if (result.running_notes_delta.length > 0) {
          setRunningNotes((prev) => [...prev, ...result.running_notes_delta].slice(-50))
        }
        if (result.new_action_items.length > 0) {
          setLiveActionCount((c) => c + result.new_action_items.length)
        }
      } catch {
        // best-effort: ignore tick failures
      }
    }, 60_000)
    return () => window.clearInterval(id)
  }, [phase, liveSegments, runningNotes, liveTick, meeting.data?.title])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [liveSegments.length])

  // Fallback poll in case the processing WS drops and we miss the "complete" frame.
  useEffect(() => {
    if (phase !== 'processing') return
    const id = window.setInterval(() => {
      meeting.refetch()
    }, 3000)
    return () => window.clearInterval(id)
  }, [phase, meeting])

  useEffect(() => {
    if (phase === 'processing' && meeting.data?.status === 'completed') {
      setPhase('done')
    }
    if (phase === 'processing' && meeting.data?.status === 'failed') {
      setPhase('error')
    }
  }, [phase, meeting.data?.status])

  async function handleCreateTasks(filter: 'all' | 'me') {
    try {
      const resp = await createTasks.mutateAsync({
        meeting_id: meetingId,
        owner_filter: filter,
      })
      const merged: Record<number, ActionItemTaskLink> = { ...taskLinks }
      for (const link of resp.created) merged[link.index] = link
      for (const link of resp.skipped) {
        if (!merged[link.index]) merged[link.index] = link
      }
      setTaskLinks(merged)
      toast({
        title: `Created ${resp.created.length} task${resp.created.length === 1 ? '' : 's'}`,
        description: resp.skipped.length
          ? `${resp.skipped.length} skipped`
          : undefined,
      })
    } catch (e) {
      toast({ title: 'Task creation failed', description: String(e), variant: 'destructive' })
    }
  }

  async function handleStop() {
    try {
      await stopRecording.mutateAsync()
      setPhase('processing')
      setProgress({ stage: 'transcribing', progress: 0, message: 'Starting…' })
      toast({ title: 'Recording stopped', description: 'Transcribing + summarising…' })
    } catch (e) {
      toast({ title: 'Stop failed', description: String(e), variant: 'destructive' })
      setPhase('error')
    }
  }

  const transcriptLines = useMemo(
    () => transcript.data?.segments ?? [],
    [transcript.data],
  )

  return (
    <div className="glass-card p-4 mb-6 border border-red-500/30">
      <div className="flex items-center gap-2 mb-3">
        {phase === 'recording' && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-300">
            <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
            RECORDING · {formatClock(elapsed)}
          </span>
        )}
        {phase === 'processing' && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-300">
            <Loader2 className="w-3 h-3 animate-spin" /> {progress?.stage ?? 'processing'}
          </span>
        )}
        {phase === 'done' && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-300">
            <CheckCircle2 className="w-3 h-3" /> Done
          </span>
        )}
        {phase === 'error' && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-400">
            <X className="w-3 h-3" /> Failed
          </span>
        )}
        <span className="text-sm text-gray-300 font-medium truncate">
          {meeting.data?.title ?? 'Quick meeting'}
        </span>
        <button
          onClick={onDone}
          className="ml-auto text-xs text-gray-400 hover:text-white flex items-center gap-1"
          title="Close panel"
        >
          <X className="w-3 h-3" /> Close
        </button>
      </div>

      {phase === 'recording' && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                Live transcript
              </div>
              <div
                ref={scrollRef}
                className="bg-gray-900/60 rounded border border-gray-700 max-h-48 overflow-y-auto p-3"
              >
                {liveSegments.length === 0 ? (
                  <div className="text-xs text-gray-500 flex items-center gap-2">
                    <AudioLines className="w-3 h-3 animate-pulse" /> Listening… transcript streams here.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {liveSegments.map((seg) => (
                      <div key={seg.id} className="text-sm text-gray-200">
                        <span className="text-[10px] text-gray-500 font-mono mr-2">
                          {formatClock(seg.start)}
                        </span>
                        {seg.text}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1 flex items-center justify-between">
                <span>Running notes</span>
                {liveActionCount > 0 && (
                  <span className="text-emerald-300 normal-case tracking-normal">
                    {liveActionCount} action item{liveActionCount === 1 ? '' : 's'}
                  </span>
                )}
              </div>
              <div className="bg-gray-900/60 rounded border border-gray-700 max-h-48 overflow-y-auto p-3">
                {runningNotes.length === 0 ? (
                  <div className="text-xs text-gray-500">
                    Notes will appear here every minute.
                  </div>
                ) : (
                  <ul className="text-sm text-gray-200 list-disc ml-4 space-y-1">
                    {runningNotes.map((note, i) => (
                      <li key={i}>{note}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={handleStop}
            disabled={stopRecording.isPending}
            className="px-3 py-2 text-sm font-semibold rounded bg-red-500/25 text-red-200 hover:bg-red-500/35 disabled:opacity-50 flex items-center gap-2"
          >
            {stopRecording.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
            Stop & summarise
          </button>
        </>
      )}

      {phase === 'processing' && (
        <div className="space-y-2">
          <p className="text-xs text-gray-400">{progress?.message ?? 'Running pipeline…'}</p>
          <div className="w-full h-1.5 bg-gray-800 rounded overflow-hidden">
            <div
              className="h-full bg-amber-400 transition-all"
              style={{ width: `${Math.round((progress?.progress ?? 0) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {phase === 'done' && (
        <div className="space-y-3">
          {summary.data?.summary_text ? (
            <div>
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Summary</h3>
              <p className="text-sm text-gray-100 whitespace-pre-wrap">{summary.data.summary_text}</p>
              {summary.data.action_items && summary.data.action_items.length > 0 && (
                <>
                  <div className="flex items-center gap-2 mt-3 mb-1">
                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide flex-1">
                      Action items
                    </h4>
                    <button
                      onClick={() => handleCreateTasks('me')}
                      disabled={createTasks.isPending}
                      className="text-[11px] px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50 flex items-center gap-1"
                    >
                      <ListTodo className="w-3 h-3" /> Mine → tasks
                    </button>
                    <button
                      onClick={() => handleCreateTasks('all')}
                      disabled={createTasks.isPending}
                      className="text-[11px] px-2 py-0.5 rounded bg-indigo-500/15 text-indigo-300 hover:bg-indigo-500/25 disabled:opacity-50 flex items-center gap-1"
                    >
                      <ListTodo className="w-3 h-3" /> All → tasks
                    </button>
                  </div>
                  <ul className="text-sm text-gray-200 list-disc ml-5 space-y-0.5">
                    {summary.data.action_items.map((a, i) => {
                      const link = taskLinks[i]
                      return (
                        <li key={i}>
                          <span className="text-emerald-300">{a.owner}</span>: {a.description}
                          {a.due && <span className="text-gray-500"> (due {a.due})</span>}
                          {link?.task_id && (
                            <a
                              href={`/sprints?task=${link.task_id}`}
                              className="ml-2 text-[11px] text-emerald-400 hover:text-emerald-300"
                            >
                              → {link.task_id}
                            </a>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </>
              )}
              {summary.data.decisions && summary.data.decisions.length > 0 && (
                <>
                  <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-3 mb-1">
                    Decisions
                  </h4>
                  <ul className="text-sm text-gray-200 list-disc ml-5 space-y-0.5">
                    {summary.data.decisions.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          ) : summary.isLoading ? (
            <p className="text-xs text-gray-400 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> Loading summary…
            </p>
          ) : (
            <p className="text-xs text-amber-400">No summary was produced (pipeline may have skipped it).</p>
          )}

          <details className="text-xs">
            <summary className="cursor-pointer text-gray-400 hover:text-gray-200">
              Full transcript ({transcriptLines.length} segments)
            </summary>
            <div className="mt-2 bg-gray-900/60 rounded border border-gray-700 max-h-48 overflow-y-auto p-2">
              {transcriptLines.map((seg) => (
                <div key={seg.id} className="text-sm text-gray-200 mb-0.5">
                  <span className="text-[10px] text-gray-500 font-mono mr-2">
                    {formatClock(seg.start_time)}
                  </span>
                  {seg.speaker && <span className="text-indigo-300 mr-1">[{seg.speaker}]</span>}
                  {seg.text}
                </div>
              ))}
            </div>
          </details>

          <div className="flex items-center gap-2 pt-1">
            <a
              href={`/meetings/${meetingId}`}
              className="text-xs text-indigo-400 hover:text-indigo-300"
            >
              Open full meeting →
            </a>
            <button
              onClick={onDone}
              className="ml-auto text-xs px-2.5 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {phase === 'error' && (
        <div className="text-sm text-red-300">
          Pipeline failed. Check DailyMeetings logs.
          <button
            onClick={onDone}
            className="ml-3 text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600"
          >
            Close
          </button>
        </div>
      )}
    </div>
  )
}
