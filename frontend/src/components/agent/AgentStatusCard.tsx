import { Cpu, Pause, Play, Square, Clock, Loader2 } from 'lucide-react'
import { useAgentStatus, useStopExecution, usePauseAgent, useResumeAgent } from '@/hooks/useAgentApi'

function timeAgo(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = Math.floor((now - then) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function AgentStatusCard() {
  const { data: status, isLoading } = useAgentStatus()
  const stopExecution = useStopExecution()
  const pauseAgent = usePauseAgent()
  const resumeAgent = useResumeAgent()

  if (isLoading) {
    return (
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading agent status...</span>
        </div>
      </div>
    )
  }

  if (!status) return null

  const task = status.current_task
  const isWorking = status.running && task

  return (
    <div className="glass-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Cpu className={`w-5 h-5 ${isWorking ? 'text-green-400' : 'text-muted-foreground'}`} />
          <h3 className="text-sm font-semibold text-foreground">Zero Agent</h3>
          {isWorking ? (
            <span className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              Working
            </span>
          ) : status.paused ? (
            <span className="flex items-center gap-1.5 text-xs text-yellow-400">
              <span className="w-2 h-2 rounded-full bg-yellow-400" />
              Paused
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="w-2 h-2 rounded-full bg-gray-500" />
              Idle
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {isWorking && (
            <button
              onClick={() => stopExecution.mutate()}
              className="btn-icon text-red-400 hover:text-red-300"
              title="Stop current task"
            >
              <Square className="w-4 h-4" />
            </button>
          )}
          {status.paused ? (
            <button
              onClick={() => resumeAgent.mutate()}
              className="btn-icon text-green-400 hover:text-green-300"
              title="Resume worker"
            >
              <Play className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={() => pauseAgent.mutate()}
              className="btn-icon text-yellow-400 hover:text-yellow-300"
              title="Pause worker"
            >
              <Pause className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {isWorking && task ? (
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium text-foreground">{task.title}</p>
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
              {task.description}
            </p>
          </div>

          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span>Step {task.current_step} of {task.total_steps}</span>
              <span>{task.progress_percent}%</span>
            </div>
            <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all duration-500"
                style={{ width: `${task.progress_percent}%` }}
              />
            </div>
          </div>

          {task.current_file && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="w-3 h-3" />
              <span className="truncate">{task.current_file}</span>
            </div>
          )}

          {task.started_at && (
            <p className="text-xs text-muted-foreground">
              Started {timeAgo(task.started_at)}
            </p>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {status.paused
            ? 'Worker is paused. Resume to pick up queued tasks.'
            : 'Waiting for tasks. Submit a task above to get started.'}
        </p>
      )}

      {status.queue_depth > 0 && (
        <div className="mt-3 pt-3 border-t border-border">
          <p className="text-xs text-muted-foreground">
            {status.queue_depth} task{status.queue_depth !== 1 ? 's' : ''} in queue
          </p>
        </div>
      )}
    </div>
  )
}
