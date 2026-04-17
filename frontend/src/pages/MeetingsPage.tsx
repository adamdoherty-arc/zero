import { useState, useCallback, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Mic, Search, Trash2, Clock, Users, ChevronRight, Radio } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useMeetings, useStartRecording, useStopRecording, useDeleteMeeting,
} from '@/hooks/useMeetings'
import { useMeetingRecordingWS, useMeetingLiveTranscriptWS } from '@/hooks/useMeetingWebSocket'
import { useMeetingRecordingStore } from '@/store/meetingRecordingStore'
import { MeetingRecordingControls } from '@/components/meetings/MeetingRecordingControls'
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
  const startRecording = useStartRecording()
  const stopRecording = useStopRecording()
  const deleteMeeting = useDeleteMeeting()
  // Connect WebSocket for live recording status
  useMeetingRecordingWS()
  const { isRecording, liveSegments } = useMeetingRecordingStore()
  // Connect live transcript WS only while recording
  const { isConnected: liveTranscriptConnected } = useMeetingLiveTranscriptWS(isRecording)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new segments arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [liveSegments.length])

  const handleStart = useCallback(() => {
    startRecording.mutate(
      { title: `Meeting ${new Date().toLocaleString()}` },
      {
        onError: (error) => {
          toast({
            variant: 'destructive',
            title: 'Recording failed',
            description: error instanceof Error ? error.message : 'Could not start recording',
          })
        },
      }
    )
  }, [startRecording])

  const handleStop = useCallback(() => {
    stopRecording.mutate()
  }, [stopRecording])

  const meetings = data?.meetings ?? []
  const filteredMeetings = search
    ? meetings.filter((m) => m.title.toLowerCase().includes(search.toLowerCase()))
    : meetings

  const statusFilters: { label: string; value: string | undefined }[] = [
    { label: 'All', value: undefined },
    { label: 'Scheduled', value: 'scheduled' },
    { label: 'Recording', value: 'recording' },
    { label: 'Processing', value: 'processing' },
    { label: 'Completed', value: 'completed' },
  ]

  return (
    <div className="flex-1 space-y-6 p-6">
      <div className="flex items-center justify-end">
        <MeetingRecordingControls onStart={handleStart} onStop={handleStop} />
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
                  <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
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
