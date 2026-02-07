import type { EcosystemTimeline } from '@/hooks/useSprintApi'

interface SprintTimelineProps {
  sprints: EcosystemTimeline[]
}

function getProgressColor(progress: number): string {
  if (progress >= 80) return 'bg-green-400'
  if (progress >= 50) return 'bg-yellow-400'
  if (progress >= 20) return 'bg-blue-400'
  return 'bg-muted-foreground'
}

export function SprintTimeline({ sprints }: SprintTimelineProps) {
  if (sprints.length === 0) {
    return (
      <div className="glass-card p-5">
        <h2 className="text-sm font-semibold text-foreground mb-3">Active Sprints Timeline</h2>
        <p className="text-xs text-muted-foreground italic">No active sprints across the ecosystem</p>
      </div>
    )
  }

  return (
    <div className="glass-card p-5">
      <h2 className="text-sm font-semibold text-foreground mb-4">Active Sprints Timeline</h2>
      <div className="space-y-3">
        {sprints.map((sprint) => (
          <div key={sprint.id} className="flex items-center gap-3">
            <div className="w-24 flex-shrink-0 text-right">
              <span className="text-xs text-muted-foreground">{sprint.project_name}</span>
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-foreground truncate max-w-[70%]" title={sprint.name}>
                  {sprint.name}
                </span>
                <span className="text-[11px] text-muted-foreground ml-2 flex-shrink-0">
                  {sprint.completed_tasks}/{sprint.total_tasks}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${getProgressColor(sprint.progress)}`}
                  style={{ width: `${Math.min(sprint.progress, 100)}%` }}
                />
              </div>
            </div>
            <div className="w-12 text-right flex-shrink-0">
              <span className="text-xs font-medium text-foreground">
                {Math.round(sprint.progress)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
