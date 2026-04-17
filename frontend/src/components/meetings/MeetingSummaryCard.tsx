import { Badge } from '@/components/ui/badge'
import { RefreshCw, CheckCircle2, Circle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { MeetingSummary } from '@/types/meeting'

interface Props {
  summary: MeetingSummary
  onRegenerate?: () => void
  isRegenerating?: boolean
}

export function MeetingSummaryCard({ summary, onRegenerate, isRegenerating }: Props) {
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <p className="text-zinc-300 text-sm leading-relaxed whitespace-pre-wrap">{summary.summary_text}</p>
        {onRegenerate && (
          <Button variant="ghost" size="sm" onClick={onRegenerate} disabled={isRegenerating} className="shrink-0 ml-4">
            <RefreshCw className={`w-4 h-4 ${isRegenerating ? 'animate-spin' : ''}`} />
          </Button>
        )}
      </div>

      {summary.key_topics && summary.key_topics.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">Key Topics</h4>
          <div className="flex gap-2 flex-wrap">
            {summary.key_topics.map((topic, i) => (
              <Badge key={i} variant="secondary" className="text-xs">{topic}</Badge>
            ))}
          </div>
        </div>
      )}

      {summary.action_items && summary.action_items.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">Action Items</h4>
          <div className="space-y-2">
            {summary.action_items.map((item, i) => (
              <div key={i} className="flex items-start gap-2">
                <Circle className="w-4 h-4 text-zinc-500 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm text-zinc-300">{typeof item === 'string' ? item : item.description}</p>
                  {typeof item !== 'string' && item.owner && (
                    <span className="text-xs text-zinc-500">Owner: {item.owner}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary.decisions && summary.decisions.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">Decisions</h4>
          <ul className="space-y-1">
            {summary.decisions.map((decision, i) => (
              <li key={i} className="text-sm text-zinc-300 flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
                {decision}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.model_used && (
        <p className="text-xs text-zinc-600">Generated with {summary.model_used}</p>
      )}
    </div>
  )
}
