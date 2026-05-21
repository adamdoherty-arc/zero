import { useMemo, useState } from 'react'
import { Hash, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from '@/hooks/use-toast'
import { useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { useMeetingTopics } from '@/hooks/useMeetings'

interface Props {
  meetingId: string
  /** Optional click handler — typically scroll the transcript to start_time. */
  onJumpTo?: (startSeconds: number) => void
}

function formatTs(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

const TONE_PALETTE = [
  'border-sky-500/40 bg-sky-500/10 text-sky-200',
  'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  'border-violet-500/40 bg-violet-500/10 text-violet-200',
  'border-amber-500/40 bg-amber-500/10 text-amber-200',
  'border-rose-500/40 bg-rose-500/10 text-rose-200',
  'border-indigo-500/40 bg-indigo-500/10 text-indigo-200',
]

/**
 * F-83 — clickable strip showing the F-76 segmenter's topic boundaries.
 *
 * Each block is sized proportionally to its duration. Hovering shows the
 * full label + timestamp range; clicking calls ``onJumpTo`` so the parent
 * can scroll the transcript viewer to the topic's start.
 */
export function MeetingTopicTimeline({ meetingId, onJumpTo }: Props) {
  const { data, isPending, isError } = useMeetingTopics(meetingId)
  const qc = useQueryClient()
  const [selected, setSelected] = useState<number | null>(null)

  const totalDuration = useMemo(() => {
    if (!data?.topics?.length) return 0
    const first = data.topics[0]
    const last = data.topics[data.topics.length - 1]
    return Math.max(1, last.end_time - first.start_time)
  }, [data])

  if (isPending) {
    return <div className="text-xs text-muted-foreground">Loading topic timeline…</div>
  }
  if (isError || !data || !data.topics?.length) {
    return null
  }

  const onClick = (topic: { topic_id: number; start_time: number }) => {
    setSelected(topic.topic_id)
    onJumpTo?.(topic.start_time)
  }

  const onRegenerate = async () => {
    try {
      const r = await fetch(`/api/meetings/${meetingId}/topics/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      })
      if (!r.ok) throw new Error(`${r.status}`)
      const fresh = await r.json()
      toast({
        title: 'Topic timeline regenerated',
        description: `${fresh.topic_count} topic${fresh.topic_count === 1 ? '' : 's'}`,
      })
      qc.invalidateQueries({ queryKey: ['meetings', meetingId, 'topics'] })
    } catch (e) {
      toast({
        title: 'Regenerate failed',
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Hash className="w-3.5 h-3.5" /> {data.topics.length} topic{data.topics.length === 1 ? '' : 's'}
        </div>
        <Button variant="ghost" size="sm" onClick={onRegenerate}>
          <RotateCcw className="w-3 h-3 mr-1" /> Regenerate
        </Button>
      </div>
      <div className="flex w-full overflow-x-auto rounded-md border border-border bg-card/40">
        {data.topics.map((topic, i) => {
          const duration = Math.max(5, topic.end_time - topic.start_time)
          const widthPct = (duration / totalDuration) * 100
          const tone = TONE_PALETTE[i % TONE_PALETTE.length]
          const active = selected === topic.topic_id
          return (
            <button
              key={topic.topic_id}
              type="button"
              onClick={() => onClick(topic)}
              className={`group relative h-14 shrink-0 border-r last:border-r-0 border-gray-800 ${tone} hover:brightness-125 transition px-2 py-1 text-left ${active ? 'ring-2 ring-white/30' : ''}`}
              style={{ width: `${widthPct}%`, minWidth: '64px' }}
              title={`${topic.label} · ${formatTs(topic.start_time)} → ${formatTs(topic.end_time)} (${topic.segment_count} segments)`}
            >
              <div className="text-[10px] font-mono opacity-70">
                {formatTs(topic.start_time)}
              </div>
              <div className="text-[11px] truncate font-semibold leading-tight">
                {topic.label}
              </div>
            </button>
          )
        })}
      </div>
      {selected !== null && (
        <div className="text-[11px] text-muted-foreground">
          Selected topic #{selected} — click another to navigate.
        </div>
      )}
    </div>
  )
}
