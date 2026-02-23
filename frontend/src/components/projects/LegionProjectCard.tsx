import type { EcosystemProject } from '@/hooks/useSprintApi'
import { Activity, CheckCircle2, AlertTriangle, Clock } from 'lucide-react'

interface LegionProjectCardProps {
  project: EcosystemProject
  isSelected: boolean
  onSelect: (id: number) => void
}

function getHealthColor(score: number): string {
  if (score >= 80) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-red-400'
}

function getHealthBg(score: number): string {
  if (score >= 80) return 'bg-green-400'
  if (score >= 50) return 'bg-yellow-400'
  return 'bg-red-400'
}

export function LegionProjectCard({ project, isSelected, onSelect }: LegionProjectCardProps) {
  const { task_summary: ts, current_sprint: sprint, health_score } = project
  const progress = ts.total > 0 ? (ts.completed / ts.total) * 100 : 0

  return (
    <button
      type="button"
      onClick={() => onSelect(project.id)}
      className={`glass-card p-5 text-left w-full transition-all cursor-pointer hover:ring-1 hover:ring-indigo-500/50 ${
        isSelected ? 'ring-2 ring-indigo-500' : ''
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-base font-semibold text-foreground">{project.name}</h3>
          <p className="text-xs text-muted-foreground capitalize">{project.status}</p>
        </div>
        <div className={`text-right ${getHealthColor(health_score)}`}>
          <div className="text-lg font-bold">{Math.round(health_score)}</div>
          <div className="text-[10px] uppercase tracking-wide">Health</div>
        </div>
      </div>

      {sprint ? (
        <div className="mb-3">
          <div className="text-xs text-muted-foreground mb-1 truncate" title={sprint.name}>
            {sprint.name}
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${getHealthBg(health_score)}`}
              style={{ width: `${Math.min(progress, 100)}%` }}
            />
          </div>
          <div className="text-[11px] text-muted-foreground mt-1">
            {ts.completed}/{ts.total} tasks ({Math.round(progress)}%)
          </div>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground mb-3 italic">No active sprint</div>
      )}

      <div className="grid grid-cols-4 gap-1 text-center">
        <div className="flex flex-col items-center">
          <Clock className="w-3.5 h-3.5 text-muted-foreground mb-0.5" />
          <span className="text-xs font-medium text-foreground">
            {ts.total - ts.completed - ts.in_progress - ts.blocked}
          </span>
          <span className="text-[10px] text-muted-foreground">Ready</span>
        </div>
        <div className="flex flex-col items-center">
          <Activity className="w-3.5 h-3.5 text-blue-400 mb-0.5" />
          <span className="text-xs font-medium text-foreground">{ts.in_progress}</span>
          <span className="text-[10px] text-muted-foreground">Active</span>
        </div>
        <div className="flex flex-col items-center">
          <CheckCircle2 className="w-3.5 h-3.5 text-green-400 mb-0.5" />
          <span className="text-xs font-medium text-foreground">{ts.completed}</span>
          <span className="text-[10px] text-muted-foreground">Done</span>
        </div>
        <div className="flex flex-col items-center">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 mb-0.5" />
          <span className="text-xs font-medium text-foreground">{ts.blocked}</span>
          <span className="text-[10px] text-muted-foreground">Blocked</span>
        </div>
      </div>
    </button>
  )
}
