import { useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Download, Mic, FileText } from 'lucide-react'
import { toast } from '@/hooks/use-toast'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { getAuthHeaders } from '@/lib/auth'
import {
  useMeeting, useMeetingTranscript, useMeetingSummary,
  useGenerateSummary, useMeetingSpeakers, useUpdateSpeakers,
  useMeetingCost,
} from '@/hooks/useMeetings'
import { MeetingTopicTimeline } from '@/components/meetings/MeetingTopicTimeline'

function MeetingCostFooter({ meetingId }: { meetingId: string }) {
  const { data } = useMeetingCost(meetingId)
  if (!data) return null
  const usd = (data.estimated_cost_usd ?? 0).toFixed(4)
  const audioMin = data.audio_seconds ? Math.round((data.audio_seconds / 60) * 10) / 10 : 0
  return (
    <div className="rounded-md border border-border bg-card/40 px-3 py-2 text-[11px] text-muted-foreground flex flex-wrap gap-x-4 gap-y-1">
      <span>transcribed in <span className="font-mono">{data.transcription_seconds ?? 0}s</span></span>
      <span>audio <span className="font-mono">{audioMin}m</span></span>
      <span>tokens <span className="font-mono">{data.summary_tokens ?? 0}</span></span>
      <span>model <span className="font-mono">{data.summary_model ?? 'n/a'}</span></span>
      <span>est. cost <span className="font-mono">${usd}</span></span>
    </div>
  )
}
import { useMeetingProcessingWS, type ProcessingProgress } from '@/hooks/useMeetingWebSocket'
import { MeetingAudioPlayer } from '@/components/meetings/MeetingAudioPlayer'
import { MeetingTranscriptViewer } from '@/components/meetings/MeetingTranscriptViewer'
import { MeetingSummaryCard } from '@/components/meetings/MeetingSummaryCard'
import { MeetingProcessingProgress } from '@/components/meetings/MeetingProcessingProgress'
import { MeetingChatInterface } from '@/components/meetings/MeetingChatInterface'
import { MeetingSpeakerEditor } from '@/components/meetings/MeetingSpeakerEditor'
export function MeetingDetailPage() {
  const { id } = useParams<{ id: string }>()
  const meetingId = id || ''

  const { data: meeting, isPending: meetingLoading } = useMeeting(meetingId)
  const { data: transcript, isPending: transcriptLoading } = useMeetingTranscript(meetingId)
  const { data: summary } = useMeetingSummary(meetingId)
  const { data: speakers } = useMeetingSpeakers(meetingId)
  const generateSummary = useGenerateSummary()
  const updateSpeakers = useUpdateSpeakers()

  const [processingState, setProcessingState] = useState<ProcessingProgress | null>(null)
  const [speakerEditorOpen, setSpeakerEditorOpen] = useState(false)

  // Listen for processing progress
  useMeetingProcessingWS(
    useCallback((data: ProcessingProgress) => {
      setProcessingState(data)
    }, [])
  )

  // Chat handler - returns data for the chat component to manage its own state
  const handleChatSend = useCallback(async (message: string): Promise<{ answer: string; sources: any[] }> => {
    const res = await fetch('/api/meeting-chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ message, meeting_id: meetingId }),
    })
    if (!res.ok) throw new Error(`Chat request failed: ${res.status}`)
    const data = await res.json()
    return { answer: data.answer, sources: data.sources || [] }
  }, [meetingId])

  // Build speaker map for transcript viewer
  const speakerMap: Record<string, string> = {}
  if (speakers) {
    for (const s of speakers) {
      speakerMap[s.speaker_label] = s.display_name
    }
  }

  if (meetingLoading) {
    return (
      <div className="flex-1 space-y-6 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (!meeting) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center">
          <h2 className="text-xl font-medium">Meeting not found</h2>
          <Link to="/meetings" className="text-primary hover:underline mt-2 inline-block">
            Back to meetings
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Link to="/meetings">
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            </Link>
            <h1 className="text-2xl font-bold">{meeting.title}</h1>
            <Badge variant="outline">{meeting.status}</Badge>
          </div>
          <div className="flex items-center gap-4 text-sm text-muted-foreground ml-10">
            <span>{new Date(meeting.start_time).toLocaleString()}</span>
            {meeting.duration_seconds && (
              <span>{Math.round(meeting.duration_seconds / 60)} minutes</span>
            )}
            {meeting.participants && meeting.participants.length > 0 && (
              <span>{meeting.participants.join(', ')}</span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSpeakerEditorOpen(true)}
          >
            <Mic className="h-4 w-4 mr-1" />
            Speakers
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              try {
                const res = await fetch(`/api/meetings/${meetingId}/vault-write`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                })
                const data = await res.json().catch(() => ({}))
                if (!res.ok) throw new Error(data?.detail || `${res.status}`)
                toast({
                  title: data.private ? 'Private stub written' : 'Vault refreshed',
                  description: data.path ? `Saved to ${data.path}` : 'Re-rendered the meeting markdown.',
                })
              } catch (e) {
                toast({
                  title: 'Vault write failed',
                  description: String(e),
                  variant: 'destructive',
                })
              }
            }}
            title="Re-render the meeting markdown to /vault/Meetings/<YYYY>/<MM>/"
          >
            <FileText className="h-4 w-4 mr-1" />
            Regenerate vault
          </Button>
          <a href={`/api/meetings/${meetingId}/export`} download>
            <Button variant="outline" size="sm">
              <Download className="h-4 w-4 mr-1" />
              Export
            </Button>
          </a>
        </div>
      </div>

      {/* Audio Player */}
      {meeting.status === 'completed' && <MeetingAudioPlayer meetingId={meetingId} />}

      {/* F-83 Topic timeline (only when transcript exists) */}
      {meeting.status === 'completed' && (
        <MeetingTopicTimeline meetingId={meetingId} />
      )}

      {/* F-84 Cost footer (cheap, conditional render in component) */}
      {meeting.status === 'completed' && <MeetingCostFooter meetingId={meetingId} />}

      {/* Processing Progress */}
      {meeting.status === 'processing' && processingState && (
        <MeetingProcessingProgress
          stage={processingState.stage}
          progress={processingState.progress}
          message={processingState.message}
        />
      )}

      {/* Tabs */}
      <Tabs defaultValue="transcript" className="flex-1">
        <TabsList>
          <TabsTrigger value="transcript">
            Transcript
            {transcript && (
              <Badge variant="secondary" className="ml-1.5 text-xs">
                {transcript.total_segments}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
        </TabsList>

        <TabsContent value="transcript" className="mt-4">
          {transcriptLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : transcript && transcript.segments.length > 0 ? (
            <MeetingTranscriptViewer
              segments={transcript.segments}
              speakerMap={speakerMap}
              meetingId={meetingId}
            />
          ) : (
            <div className="text-center text-muted-foreground py-12">
              No transcript available yet.
              {meeting.status === 'scheduled' && ' Start recording to generate a transcript.'}
            </div>
          )}
        </TabsContent>

        <TabsContent value="summary" className="mt-4">
          {summary ? (
            <MeetingSummaryCard
              summary={summary}
              onRegenerate={() => generateSummary.mutate(meetingId)}
              isRegenerating={generateSummary.isPending}
            />
          ) : (
            <div className="text-center text-muted-foreground py-12">
              <p>No summary available yet.</p>
              {meeting.status === 'completed' && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => generateSummary.mutate(meetingId)}
                  disabled={generateSummary.isPending}
                >
                  {generateSummary.isPending ? 'Generating...' : 'Generate Summary'}
                </Button>
              )}
            </div>
          )}
        </TabsContent>

        <TabsContent value="chat" className="mt-4">
          <MeetingChatInterface
            meetingId={meetingId}
            onSend={handleChatSend}
          />
        </TabsContent>
      </Tabs>

      {/* Speaker Editor Dialog */}
      <MeetingSpeakerEditor
        open={speakerEditorOpen}
        onOpenChange={setSpeakerEditorOpen}
        speakers={transcript?.segments
          .map((s) => s.speaker)
          .filter((v, i, a) => v && a.indexOf(v) === i) as string[] || []}
        currentMappings={speakers || []}
        onSave={(mappings) => {
          updateSpeakers.mutate({ id: meetingId, speakers: mappings as any })
          setSpeakerEditorOpen(false)
        }}
      />
    </div>
  )
}
