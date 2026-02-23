import { useState } from 'react'
import { History, ChevronDown, ChevronRight, CheckCircle, XCircle, FileCode, Clock } from 'lucide-react'
import { useAgentHistory } from '@/hooks/useAgentApi'
import type { AgentHistoryItem } from '@/types'

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function TaskHistoryEntry({ task }: { task: AgentHistoryItem }) {
  const [expanded, setExpanded] = useState(false)
  const isSuccess = task.status === 'complete'
  const result = task.result

  return (
    <div className="border border-border rounded-md overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-accent/30 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
        )}

        {isSuccess ? (
          <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />
        ) : (
          <XCircle className="w-4 h-4 text-red-400 shrink-0" />
        )}

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{task.title}</p>
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
            {result?.files_modified !== undefined && (
              <span className="flex items-center gap-1">
                <FileCode className="w-3 h-3" />
                {result.files_modified} files
              </span>
            )}
            {result?.duration_seconds !== undefined && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatDuration(result.duration_seconds)}
              </span>
            )}
            {result && (
              <span>{result.completed}/{result.total_steps} steps</span>
            )}
          </div>
        </div>

        {task.completed_at && (
          <span className="text-xs text-muted-foreground shrink-0">
            {new Date(task.completed_at).toLocaleDateString()}
          </span>
        )}
      </button>

      {expanded && task.execution_log && (
        <div className="border-t border-border bg-background/30 p-3 space-y-1.5">
          {task.execution_log.map((step, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              {step.status === 'success' ? (
                <CheckCircle className="w-3 h-3 text-green-400 mt-0.5 shrink-0" />
              ) : step.status === 'failed' ? (
                <XCircle className="w-3 h-3 text-red-400 mt-0.5 shrink-0" />
              ) : (
                <div className="w-3 h-3 rounded-full border border-muted-foreground mt-0.5 shrink-0" />
              )}
              <div className="min-w-0">
                <span className="text-muted-foreground">Step {step.step}:</span>{' '}
                <span className="text-foreground">{step.description}</span>
                {step.file && (
                  <span className="text-muted-foreground"> — {step.file}</span>
                )}
                {step.result_message && step.status === 'failed' && (
                  <p className="text-red-400 mt-0.5">{step.result_message}</p>
                )}
              </div>
            </div>
          ))}

          {result?.error && (
            <p className="text-xs text-red-400 mt-2 pt-2 border-t border-border">
              Error: {result.error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function TaskHistory() {
  const { data: history, isLoading } = useAgentHistory(10)

  if (isLoading) return null
  if (!history || history.length === 0) return null

  return (
    <div className="glass-card p-5">
      <div className="flex items-center gap-2 mb-4">
        <History className="w-5 h-5 text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground">Recent Agent Activity</h3>
      </div>

      <div className="space-y-2">
        {history.slice().reverse().map((task) => (
          <TaskHistoryEntry key={task.task_id} task={task} />
        ))}
      </div>
    </div>
  )
}
