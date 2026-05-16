import { AlertTriangle, Lock } from 'lucide-react'
import { useContentProductionStatus } from '@/hooks/useContentControlApi'

export function ContentProductionPausedBanner({ className = '' }: { className?: string }) {
  const { data } = useContentProductionStatus()

  if (!data?.paused) return null

  return (
    <div
      className={`flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100 ${className}`}
      role="status"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
      <div className="min-w-0">
        <div className="flex items-center gap-2 font-medium text-amber-50">
          <Lock className="h-3.5 w-3.5" />
          Content production paused
        </div>
        <p className="mt-1 text-amber-100/85">
          {data.reason || 'Generate, enhance, reimage, source, seed, and media production actions are locked.'}
        </p>
      </div>
    </div>
  )
}
