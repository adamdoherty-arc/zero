import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Mic,
  Search,
  Trash2,
  Clock,
  Users,
  ChevronRight,
  Radio,
  CalendarClock,
  CheckCircle2,
  RefreshCw,
  Loader2,
  ListTodo,
  FileText,
  MessageSquare,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useMeetings,
  useStopRecording,
  useDeleteMeeting,
  useMeetingPreferences,
  useUpdateMeetingPreferences,
  useVoiceprints,
  useRecordingCapabilities,
  useMeetingArtifactStats,
  type MeetingArtifactStats,
} from '@/hooks/useMeetings'
import {
  useCalendarStatus,
  useSyncCalendar,
  fetchCalendarAuthUrl,
} from '@/hooks/useCalendarApi'
import { useMeetingRecordingWS, useMeetingLiveTranscriptWS } from '@/hooks/useMeetingWebSocket'
import { useMeetingRecordingStore } from '@/store/meetingRecordingStore'
import { MeetingRecordingControls } from '@/components/meetings/MeetingRecordingControls'
import { LLMTaskPicker } from '@/components/meetings/LLMTaskPicker'
import { LiveTranscriptModelPicker } from '@/components/meetings/LiveTranscriptModelPicker'
import { toast } from '@/hooks/use-toast'
import type { MeetingStatus } from '@/types/meeting'

const STATUS_COLORS: Record<MeetingStatus, string> = {
  scheduled: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  recording: 'bg-red-500/20 text-red-400 border-red-500/30',
  processing: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  completed: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  failed: 'bg-red-500/20 text-red-400 border-red-500/30',
}

export function MeetingsPage() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [search, setSearch] = useState('')

  const { data, isPending } = useMeetings({ status: statusFilter, limit: 50 })
  const stopRecording = useStopRecording()
  const deleteMeeting = useDeleteMeeting()
  const calendarStatus = useCalendarStatus()
  const calendarSync = useSyncCalendar()
  const capabilities = useRecordingCapabilities()
  const prefs = useMeetingPreferences()
  const updatePrefs = useUpdateMeetingPreferences()
  const voiceprints = useVoiceprints()
  const autoSyncFiredRef = useRef(false)
  // Connect WebSocket for live recording status
  useMeetingRecordingWS()
  const { isRecording, liveSegments } = useMeetingRecordingStore()
  // Connect live transcript WS only while recording
  const { isConnected: liveTranscriptConnected } = useMeetingLiveTranscriptWS(isRecording)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-sync calendar once on mount when connected but stale.
  useEffect(() => {
    if (autoSyncFiredRef.current) return
    if (!calendarStatus.data?.connected) return
    const ls = calendarStatus.data.last_sync
    const stale = !ls || Date.now() - new Date(ls).getTime() > 10 * 60_000
    if (!stale) return
    autoSyncFiredRef.current = true
    calendarSync.mutate(undefined, {
      onSuccess: () => toast({ title: 'Calendar auto-synced' }),
    })
  }, [calendarStatus.data, calendarSync])

  async function handleConnectCalendar() {
    try {
      const url = await fetchCalendarAuthUrl()
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch (e) {
      toast({ title: 'OAuth failed', description: String(e), variant: 'destructive' })
    }
  }

  async function handleSync() {
    try {
      await calendarSync.mutateAsync()
      toast({ title: 'Calendar synced' })
    } catch (e) {
      toast({ title: 'Sync failed', description: String(e), variant: 'destructive' })
    }
  }

  async function toggleAutoTasks() {
    const next = !(prefs.data?.auto_create_tasks_from_meetings ?? false)
    try {
      await updatePrefs.mutateAsync({ auto_create_tasks_from_meetings: next })
      toast({ title: next ? 'Auto-create tasks: ON' : 'Auto-create tasks: OFF' })
    } catch (e) {
      toast({ title: 'Could not update', description: String(e), variant: 'destructive' })
    }
  }

  async function toggleAutoRecordAll() {
    const next = !(prefs.data?.auto_record_all ?? false)
    if (next) {
      const ok = confirm(
        'Auto-record every calendar event with attendees? This will start the recorder for every meeting on your calendar.',
      )
      if (!ok) return
    }
    try {
      await updatePrefs.mutateAsync({ auto_record_all: next })
      toast({ title: next ? 'Auto-record all: ON' : 'Auto-record all: OFF' })
    } catch (e) {
      toast({ title: 'Could not update', description: String(e), variant: 'destructive' })
    }
  }

  const isCalendarConnected = calendarStatus.data?.connected === true
  const lastSync = calendarStatus.data?.last_sync ?? null
  const lastSyncLabel = useMemo(() => {
    if (!lastSync) return 'never'
    const ms = Date.now() - new Date(lastSync).getTime()
    const min = Math.round(ms / 60_000)
    if (min < 1) return 'just now'
    if (min < 60) return `${min} min ago`
    const hr = Math.round(min / 60)
    if (hr < 24) return `${hr} h ago`
    return `${Math.round(hr / 24)} d ago`
  }, [lastSync])

  // Auto-scroll to bottom when new segments arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [liveSegments.length])

  const handleStop = useCallback(() => {
    stopRecording.mutate()
  }, [stopRecording])

  const meetings = data?.meetings ?? []
  const filteredMeetings = search
    ? meetings.filter((m) => m.title.toLowerCase().includes(search.toLowerCase()))
    : meetings
  const artifactStats = useMeetingArtifactStats(filteredMeetings.map((m) => m.id))
  const statsByMeeting = useMemo(() => {
    const map = new Map<string, MeetingArtifactStats>()
    for (const s of artifactStats.data ?? []) {
      map.set(s.meeting_id, s)
    }
    return map
  }, [artifactStats.data])

  const statusFilters: { label: string; value: string | undefined }[] = [
    { label: 'All', value: undefined },
    { label: 'Scheduled', value: 'scheduled' },
    { label: 'Recording', value: 'recording' },
    { label: 'Processing', value: 'processing' },
    { label: 'Completed', value: 'completed' },
  ]

  const primaryVoice = voiceprints.data?.find((v) => v.is_primary) ?? null
  const totalVoiceprints = voiceprints.data?.length ?? 0

  return (
    <div className="flex-1 space-y-6 p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Meetings</h1>
          <p className="text-sm text-gray-400">
            Record, transcribe, summarise, and turn action items into tasks. Audio captures from the Reachy mic by default.
          </p>
        </div>
        <MeetingRecordingControls onStop={handleStop} />
      </div>

      {/* Status + preferences strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Calendar</div>
          {isCalendarConnected ? (
            <div className="text-sm text-emerald-300 truncate flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              {calendarStatus.data?.email_address || 'connected'}
            </div>
          ) : (
            <button
              onClick={handleConnectCalendar}
              className="text-sm text-amber-300 hover:text-amber-200 underline-offset-2 hover:underline"
            >
              Connect Google Calendar
            </button>
          )}
        </div>
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500 flex items-center justify-between">
            <span>Last sync</span>
            <button
              onClick={handleSync}
              disabled={calendarSync.isPending || !isCalendarConnected}
              className="text-gray-400 hover:text-gray-200 disabled:opacity-40"
              title="Sync now"
            >
              {calendarSync.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3" />
              )}
            </button>
          </div>
          <div className="text-sm text-gray-200">{lastSyncLabel}</div>
        </div>
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Voice enrolled</div>
          {primaryVoice ? (
            <div className="text-sm text-emerald-300 truncate flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              {primaryVoice.display_name}
              {totalVoiceprints > 1 && (
                <span className="text-[10px] text-gray-500"> +{totalVoiceprints - 1}</span>
              )}
            </div>
          ) : (
            <Link
              to="/reachy/voice"
              className="text-sm text-amber-300 hover:text-amber-200 underline-offset-2 hover:underline"
            >
              Enroll yourself →
            </Link>
          )}
        </div>
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Recording</div>
          <div className="text-sm">
            {capabilities.data?.can_record ? (
              <span className="text-emerald-300">
                Ready · {capabilities.data.via ?? 'host'}
              </span>
            ) : (
              <span className="text-amber-300">Audio offline</span>
            )}
          </div>
        </div>
      </div>

      {/* Preferences toggle row */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={toggleAutoRecordAll}
          disabled={updatePrefs.isPending}
          className={`text-xs px-2.5 py-1.5 rounded flex items-center gap-1 disabled:opacity-50 ${
            prefs.data?.auto_record_all
              ? 'bg-emerald-500/25 text-emerald-200 hover:bg-emerald-500/35'
              : 'bg-gray-700/50 text-gray-300 hover:bg-gray-600/60'
          }`}
          title="Auto-record every calendar event with attendees"
        >
          <CalendarClock className="w-3 h-3" />
          Auto-record all: {prefs.data?.auto_record_all ? 'ON' : 'OFF'}
        </button>
        <button
          onClick={toggleAutoTasks}
          disabled={updatePrefs.isPending}
          className={`text-xs px-2.5 py-1.5 rounded flex items-center gap-1 disabled:opacity-50 ${
            prefs.data?.auto_create_tasks_from_meetings
              ? 'bg-indigo-500/25 text-indigo-200 hover:bg-indigo-500/35'
              : 'bg-gray-700/50 text-gray-300 hover:bg-gray-600/60'
          }`}
          title="Auto-create Zero tasks from action items assigned to me"
        >
          <ListTodo className="w-3 h-3" />
          Auto-tasks: {prefs.data?.auto_create_tasks_from_meetings ? 'ON' : 'OFF'}
        </button>
        <LLMTaskPicker task="summary" label="Summary LLM" />
        <LiveTranscriptModelPicker />
      </div>

      {/* Live Transcript Panel — visible during recording */}
      {isRecording && (
        <Card className="border-red-500/30 bg-red-500/5">
          <div className="flex items-center gap-2 px-4 pt-3 pb-2">
            <Radio className="h-4 w-4 text-red-400 animate-pulse" />
            <span className="text-sm font-medium text-red-400">Live Transcription</span>
            {liveTranscriptConnected && (
              <Badge variant="outline" className="text-xs bg-emerald-500/20 text-emerald-400 border-emerald-500/30">
                Connected
              </Badge>
            )}
          </div>
          <div ref={scrollRef} className="px-4 pb-3 max-h-64 overflow-y-auto">
            {liveSegments.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                Listening... transcript will appear as you speak
              </p>
            ) : (
              <div className="space-y-2">
                {liveSegments.map((seg) => (
                  <div key={seg.id} className="flex gap-3">
                    <span className="text-xs text-zinc-500 font-mono mt-0.5 shrink-0 w-12">
                      {Math.floor(seg.start / 60).toString().padStart(2, '0')}:
                      {Math.floor(seg.start % 60).toString().padStart(2, '0')}
                    </span>
                    <p className="text-sm text-zinc-300">{seg.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search meetings..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
        <div className="flex gap-1">
          {statusFilters.map((f) => (
            <Button
              key={f.label}
              variant={statusFilter === f.value ? 'secondary' : 'ghost'}
              size="sm"
              onClick={() => setStatusFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Meeting List */}
      {isPending ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : filteredMeetings.length === 0 ? (
        <Card className="flex flex-col items-center justify-center p-12 text-center">
          <Mic className="h-12 w-12 text-muted-foreground mb-4" />
          <h3 className="text-lg font-medium">No meetings yet</h3>
          <p className="text-muted-foreground mt-1">
            Click "Start Recording" to begin capturing your first meeting
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {filteredMeetings.map((meeting) => (
            <Link key={meeting.id} to={`/meetings/${meeting.id}`}>
              <Card className="flex items-center justify-between p-4 hover:bg-accent/50 transition-colors cursor-pointer">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium truncate">{meeting.title}</span>
                    <Badge
                      variant="outline"
                      className={STATUS_COLORS[meeting.status as MeetingStatus] || ''}
                    >
                      {meeting.status}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground flex-wrap">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" />
                      {new Date(meeting.start_time).toLocaleDateString(undefined, {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                      })}
                    </span>
                    {meeting.duration_seconds && (
                      <span>{Math.round(meeting.duration_seconds / 60)}m</span>
                    )}
                    {meeting.participants && meeting.participants.length > 0 && (
                      <span className="flex items-center gap-1">
                        <Users className="h-3.5 w-3.5" />
                        {meeting.participants.length}
                      </span>
                    )}
                    {(() => {
                      const s = statsByMeeting.get(meeting.id)
                      if (!s) return null
                      return (
                        <>
                          {s.transcript_segments > 0 && (
                            <span
                              className="flex items-center gap-1 text-emerald-400"
                              title={`${s.transcript_segments} transcript segments`}
                            >
                              <FileText className="h-3.5 w-3.5" />
                              {s.transcript_segments}
                            </span>
                          )}
                          {s.has_summary && (
                            <span
                              className="flex items-center gap-1 text-indigo-300"
                              title="Summary generated"
                            >
                              <MessageSquare className="h-3.5 w-3.5" />
                              summary
                            </span>
                          )}
                          {s.action_items_count > 0 && (
                            <span
                              className="flex items-center gap-1 text-amber-300"
                              title={`${s.action_items_count} action items`}
                            >
                              <ListTodo className="h-3.5 w-3.5" />
                              {s.action_items_count}
                            </span>
                          )}
                          {s.speaker_count > 0 && (
                            <span
                              className="flex items-center gap-1 text-cyan-300"
                              title={`${s.speaker_count} distinct speakers`}
                            >
                              <Users className="h-3.5 w-3.5" />
                              {s.speaker_count} spk
                            </span>
                          )}
                        </>
                      )
                    })()}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      if (confirm('Delete this meeting?')) {
                        deleteMeeting.mutate(meeting.id)
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
