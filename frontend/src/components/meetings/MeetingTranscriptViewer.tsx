import { ScrollArea } from '@/components/ui/scroll-area'
import type { TranscriptSegment } from '@/types/meeting'

interface Props {
  segments: TranscriptSegment[]
  speakerMap?: Record<string, string>
  onTimestampClick?: (time: number) => void
}

const SPEAKER_COLORS = [
  'text-blue-400', 'text-emerald-400', 'text-amber-400', 'text-purple-400',
  'text-pink-400', 'text-cyan-400', 'text-orange-400', 'text-rose-400',
]

export function MeetingTranscriptViewer({ segments, speakerMap = {}, onTimestampClick }: Props) {
  const speakerColorMap: Record<string, string> = {}
  let colorIdx = 0

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

  if (!segments.length) {
    return <p className="text-zinc-500 text-sm">No transcript available.</p>
  }

  return (
    <ScrollArea className="h-[500px]">
      <div className="space-y-3 pr-4">
        {segments.map((seg) => {
          const speaker = speakerMap[seg.speaker || ''] || seg.speaker || 'Speaker'
          return (
            <div key={seg.id} className="flex gap-3 group">
              <button
                onClick={() => onTimestampClick?.(seg.start_time)}
                className="text-xs text-zinc-500 hover:text-blue-400 font-mono mt-1 shrink-0 w-12"
              >
                {formatTime(seg.start_time)}
              </button>
              <div className="flex-1">
                <span className={`text-xs font-medium ${getSpeakerColor(speaker)}`}>
                  {speaker}
                </span>
                <p className="text-sm text-zinc-300 mt-0.5">{seg.text}</p>
              </div>
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )
}
