import { useEcosystemProjectDetail } from '@/hooks/useSprintApi'
import type { EcosystemTimeline, EcosystemProjectTask } from '@/hooks/useSprintApi'
import {
  X,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ChevronRight,
} from 'lucide-react'

interface LegionProjectDetailProps {
  projectId: number
  onClose: () => void
}

function getHealthColor(score: number): string {
  if (score >= 80) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-red-400'
}


function getStatusColor(status: string): string {
  switch (status) {
    case 'active':
      return 'text-blue-400'
    case 'completed':
      return 'text-green-400'
    case 'failed':
    case 'blocked':
      return 'text-red-400'
    default:
      return 'text-muted-foreground'
  }
}

function SprintRow({ sprint }: { sprint: EcosystemTimeline }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-border/50 last:border-0">
      <ChevronRight className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-foreground truncate">{sprint.name}</div>
        <div className="text-[11px] text-muted-foreground">
          {sprint.completed_tasks}/{sprint.total_tasks} tasks
        </div>
      </div>
      <span className={`text-xs capitalize ${getStatusColor(sprint.status)}`}>
        {sprint.status}
      </span>
      <div className="w-20">
        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full ${sprint.status === 'completed' ? 'bg-green-400' : 'bg-indigo-400'}`}
            style={{ width: `${Math.min(sprint.progress, 100)}%` }}
          />
        </div>
        <div className="text-[10px] text-muted-foreground text-right mt-0.5">
          {Math.round(sprint.progress)}%
        </div>
      </div>
    </div>
  )
}

function TaskRow({ task }: { task: EcosystemProjectTask }) {
  const statusIcon = {
    completed: <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />,
    running: <Activity className="w-3.5 h-3.5 text-blue-400" />,
    in_progress: <Activity className="w-3.5 h-3.5 text-blue-400" />,
    failed: <AlertTriangle className="w-3.5 h-3.5 text-red-400" />,
    blocked: <AlertTriangle className="w-3.5 h-3.5 text-red-400" />,
  }[task.status] || <Clock className="w-3.5 h-3.5 text-muted-foreground" />

  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border/30 last:border-0">
      <div className="mt-0.5 flex-shrink-0">{statusIcon}</div>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-foreground truncate">{task.title}</div>
        {task.blocked_reason && (
          <div className="text-[11px] text-red-400 truncate">{task.blocked_reason}</div>
        )}
      </div>
      <span className="text-[11px] text-muted-foreground capitalize flex-shrink-0">
        {task.status}
      </span>
    </div>
  )
}

export function LegionProjectDetail({ projectId, onClose }: LegionProjectDetailProps) {
  const { data, isLoading, error } = useEcosystemProjectDetail(projectId)

  if (isLoading) {
    return (
      <div className="glass-card p-6 animate-pulse">
        <div className="h-6 bg-muted rounded w-1/3 mb-4" />
        <div className="h-4 bg-muted rounded w-2/3 mb-2" />
        <div className="h-4 bg-muted rounded w-1/2" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="glass-card p-6">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-muted-foreground">
            {error ? 'Failed to load project details. Try syncing first.' : 'Project not found in cache.'}
          </p>
          <button type="button" onClick={onClose} className="p-1 hover:bg-muted rounded">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    )
  }

  const { project, sprints, tasks } = data
  const blockedTasks = tasks.filter(
    (t) => t.status === 'failed' || t.status === 'blocked'
  )
  const activeSprints = sprints.filter((s) => s.status === 'active')
  const completedSprints = sprints.filter((s) => s.status === 'completed')

  return (
    <div className="glass-card p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-foreground">{project.name}</h2>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-muted-foreground capitalize">{project.status}</span>
            <span className={`text-sm font-bold ${getHealthColor(project.health_score)}`}>
              Health: {Math.round(project.health_score)}
            </span>
          </div>
        </div>
        <button type="button" onClick={onClose} className="p-1 hover:bg-muted rounded">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Task Summary Bar */}
      {project.task_summary.total > 0 && (
        <div className="mb-5">
          <div className="flex gap-0.5 h-2 rounded-full overflow-hidden bg-muted">
            {project.task_summary.completed > 0 && (
              <div
                className="bg-green-400 h-full"
                style={{
                  width: `${(project.task_summary.completed / project.task_summary.total) * 100}%`,
                }}
              />
            )}
            {project.task_summary.in_progress > 0 && (
              <div
                className="bg-blue-400 h-full"
                style={{
                  width: `${(project.task_summary.in_progress / project.task_summary.total) * 100}%`,
                }}
              />
            )}
            {project.task_summary.blocked > 0 && (
              <div
                className="bg-red-400 h-full"
                style={{
                  width: `${(project.task_summary.blocked / project.task_summary.total) * 100}%`,
                }}
              />
            )}
          </div>
          <div className="flex gap-4 mt-1.5 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-400" />
              {project.task_summary.completed} done
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-blue-400" />
              {project.task_summary.in_progress} active
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-400" />
              {project.task_summary.blocked} blocked
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-muted-foreground/40" />
              {project.task_summary.total - project.task_summary.completed - project.task_summary.in_progress - project.task_summary.blocked} ready
            </span>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Sprints */}
        <div>
          <h3 className="text-sm font-medium text-foreground mb-2">
            Sprints ({sprints.length})
          </h3>
          {sprints.length > 0 ? (
            <div>
              {activeSprints.length > 0 && (
                <div className="mb-2">
                  <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">Active</div>
                  {activeSprints.map((s) => (
                    <SprintRow key={s.id} sprint={s} />
                  ))}
                </div>
              )}
              {completedSprints.length > 0 && (
                <div>
                  <div className="text-[11px] text-muted-foreground uppercase tracking-wide mb-1">Completed</div>
                  {completedSprints.map((s) => (
                    <SprintRow key={s.id} sprint={s} />
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground italic">No sprints cached</p>
          )}
        </div>

        {/* Blocked/Failed Tasks */}
        <div>
          <h3 className="text-sm font-medium text-foreground mb-2">
            Blocked / Failed ({blockedTasks.length})
          </h3>
          {blockedTasks.length > 0 ? (
            <div>
              {blockedTasks.map((t) => (
                <TaskRow key={t.id} task={t} />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground italic">No blocked tasks</p>
          )}
        </div>
      </div>
    </div>
  )
}
