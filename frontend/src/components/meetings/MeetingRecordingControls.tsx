import { Mic, Square, Circle, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMeetingRecordingStore } from '@/store/meetingRecordingStore'
import { useRecordingCapabilities } from '@/hooks/useMeetings'

interface Props {
  onStart: (source?: string) => void
  onStop: () => void
}

export function MeetingRecordingControls({ onStart, onStop }: Props) {
  const { isRecording, durationSeconds, audioLevels } = useMeetingRecordingStore()
  const { data: capabilities } = useRecordingCapabilities()

  const formatDuration = (secs: number) => {
    const h = Math.floor(secs / 3600)
    const m = Math.floor((secs % 3600) / 60)
    const s = Math.floor(secs % 60)
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const canRecord = capabilities?.can_record ?? true

  return (
    <div className="flex items-center gap-4">
      {isRecording ? (
        <>
          <Button onClick={onStop} variant="destructive" className="gap-2">
            <Square className="w-4 h-4" />
            Stop Recording
          </Button>
          <div className="flex items-center gap-2">
            <Circle className="w-3 h-3 text-red-500 animate-pulse fill-red-500" />
            <span className="text-red-400 font-mono text-sm">{formatDuration(durationSeconds)}</span>
          </div>
          {audioLevels && (
            <div className="flex items-end gap-1 h-6">
              {[audioLevels.system, audioLevels.mic, audioLevels.mixed].map((level, i) => (
                <div
                  key={i}
                  className="w-1.5 bg-emerald-500 rounded-full transition-all duration-100"
                  style={{ height: `${Math.min(100, level * 400)}%`, minHeight: '2px' }}
                />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="flex items-center gap-3">
          <Button
            onClick={() => onStart()}
            className="gap-2"
            disabled={!canRecord}
          >
            <Mic className="w-4 h-4" />
            Start Recording
          </Button>
          {capabilities && !capabilities.can_record && (
            <span className="flex items-center gap-1.5 text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              {capabilities.message || 'Audio recording unavailable in this environment'}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
