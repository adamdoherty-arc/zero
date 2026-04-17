import { Badge } from '@/components/ui/badge'
import { Loader2, Check } from 'lucide-react'

interface Props {
  stage: string
  progress: number
  message: string
}

const STAGES = ['transcribing', 'diarizing', 'storing', 'summarizing', 'embedding', 'complete']

export function MeetingProcessingProgress({ stage, progress: _progress, message }: Props) {
  const currentIdx = STAGES.indexOf(stage)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {stage !== 'complete' && <Loader2 className="w-4 h-4 animate-spin text-blue-400" />}
        {stage === 'complete' && <Check className="w-4 h-4 text-emerald-400" />}
        <span className="text-sm text-zinc-300">{message}</span>
      </div>
      <div className="w-full bg-zinc-700 rounded-full h-2">
        <div
          className="bg-blue-500 h-2 rounded-full transition-all duration-500"
          style={{ width: `${(currentIdx / (STAGES.length - 1)) * 100}%` }}
        />
      </div>
      <div className="flex gap-2 flex-wrap">
        {STAGES.filter(s => s !== 'complete').map((s, i) => (
          <Badge
            key={s}
            variant={i < currentIdx ? 'default' : i === currentIdx ? 'secondary' : 'outline'}
            className={`text-xs ${i < currentIdx ? 'bg-emerald-600' : i === currentIdx ? 'bg-blue-600' : 'opacity-50'}`}
          >
            {s}
          </Badge>
        ))}
      </div>
    </div>
  )
}
