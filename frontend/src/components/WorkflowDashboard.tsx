import { useState } from 'react'
import {
  useWorkflows,
  useActiveExecutions,
  useExecutionHistory,
  useTriggerWorkflow,
  useCancelExecution,
  type WorkflowSummary,
  type WorkflowExecution,
} from '../hooks/useWorkflowApi'
import { Play, Square, Clock, CheckCircle, XCircle, AlertCircle, Workflow } from 'lucide-react'

const STATUS_ICONS: Record<string, React.ReactNode> = {
  completed: <CheckCircle className="w-4 h-4 text-green-400" />,
  running: <Clock className="w-4 h-4 text-blue-400 animate-spin" />,
  failed: <XCircle className="w-4 h-4 text-red-400" />,
  cancelled: <AlertCircle className="w-4 h-4 text-yellow-400" />,
  skipped: <AlertCircle className="w-4 h-4 text-gray-400" />,
}

export function WorkflowDashboard() {
  const [selectedExecution, setSelectedExecution] = useState<WorkflowExecution | null>(null)
  const { data: workflowData, isLoading: loadingWorkflows } = useWorkflows()
  const { data: activeData } = useActiveExecutions()
  const { data: historyData } = useExecutionHistory()
  const triggerMutation = useTriggerWorkflow()
  const cancelMutation = useCancelExecution()

  const workflows: WorkflowSummary[] = workflowData?.workflows || []
  const activeExecutions: WorkflowExecution[] = activeData?.executions || []
  const history: WorkflowExecution[] = historyData?.history || []

  const handleTrigger = (name: string) => {
    triggerMutation.mutate({ name, trigger: { type: 'manual' } })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Workflow className="w-6 h-6 text-indigo-400" />
          Workflows
        </h1>
        <div className="text-sm text-gray-400">
          {workflows.length} available &middot; {activeExecutions.length} running
        </div>
      </div>

      {/* Active Executions */}
      {activeExecutions.length > 0 && (
        <div className="card-glass p-4">
          <h2 className="text-lg font-semibold mb-3 text-blue-400">Running</h2>
          <div className="space-y-2">
            {activeExecutions.map((exec) => (
              <div
                key={exec.execution_id}
                className="flex items-center justify-between p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10"
                onClick={() => setSelectedExecution(exec)}
              >
                <div className="flex items-center gap-3">
                  <Clock className="w-4 h-4 text-blue-400 animate-spin" />
                  <span className="font-medium">{exec.workflow_id}</span>
                  <span className="text-xs text-gray-400">{exec.execution_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">
                    {Object.values(exec.steps || {}).filter((s) => s.status === 'completed').length}/
                    {Object.keys(exec.steps || {}).length} steps
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      cancelMutation.mutate(exec.execution_id)
                    }}
                    className="text-red-400 hover:text-red-300 p-1"
                    title="Cancel"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Available Workflows */}
      <div className="card-glass p-4">
        <h2 className="text-lg font-semibold mb-3">Available Workflows</h2>
        {loadingWorkflows ? (
          <div className="text-gray-400 text-center py-4">Loading...</div>
        ) : workflows.length === 0 ? (
          <div className="text-gray-400 text-center py-4">No workflows defined</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {workflows.map((wf) => (
              <div key={wf.name} className="p-4 bg-white/5 rounded-lg border border-white/10">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold">{wf.name}</h3>
                  <button
                    onClick={() => handleTrigger(wf.name)}
                    disabled={triggerMutation.isPending}
                    className="btn-primary flex items-center gap-1 text-sm px-3 py-1"
                  >
                    <Play className="w-3 h-3" /> Run
                  </button>
                </div>
                <p className="text-sm text-gray-400 mb-2">{wf.description}</p>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span>{wf.steps} steps</span>
                  <span>v{wf.version}</span>
                  {wf.triggers.map((t) => (
                    <span key={t} className="px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded-full">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Execution History */}
      <div className="card-glass p-4">
        <h2 className="text-lg font-semibold mb-3">Recent Executions</h2>
        {history.length === 0 ? (
          <div className="text-gray-400 text-center py-4">No execution history</div>
        ) : (
          <div className="space-y-2">
            {history.map((exec) => (
              <div
                key={exec.execution_id}
                className="flex items-center justify-between p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10"
                onClick={() => setSelectedExecution(exec)}
              >
                <div className="flex items-center gap-3">
                  {STATUS_ICONS[exec.status] || STATUS_ICONS.failed}
                  <span className="font-medium">{exec.workflow_id}</span>
                  <span className="text-xs text-gray-400">{exec.execution_id}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <span>{exec.completed_at ? new Date(exec.completed_at).toLocaleString() : ''}</span>
                  <span className={
                    exec.status === 'completed' ? 'text-green-400' :
                    exec.status === 'failed' ? 'text-red-400' : 'text-gray-400'
                  }>
                    {exec.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Execution Detail Modal */}
      {selectedExecution && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="card-glass p-6 max-w-2xl w-full max-h-[80vh] overflow-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold">{selectedExecution.workflow_id}</h3>
              <button
                onClick={() => setSelectedExecution(null)}
                className="text-gray-400 hover:text-white"
              >
                &times;
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-4 text-sm">
              <div>
                <span className="text-gray-400">Execution ID:</span>{' '}
                <span className="font-mono">{selectedExecution.execution_id}</span>
              </div>
              <div>
                <span className="text-gray-400">Status:</span>{' '}
                <span className={
                  selectedExecution.status === 'completed' ? 'text-green-400' :
                  selectedExecution.status === 'failed' ? 'text-red-400' : 'text-blue-400'
                }>{selectedExecution.status}</span>
              </div>
              {selectedExecution.started_at && (
                <div>
                  <span className="text-gray-400">Started:</span>{' '}
                  {new Date(selectedExecution.started_at).toLocaleString()}
                </div>
              )}
              {selectedExecution.completed_at && (
                <div>
                  <span className="text-gray-400">Completed:</span>{' '}
                  {new Date(selectedExecution.completed_at).toLocaleString()}
                </div>
              )}
            </div>

            {selectedExecution.error && (
              <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg mb-4 text-sm text-red-400">
                {selectedExecution.error}
              </div>
            )}

            <h4 className="font-semibold mb-2">Steps</h4>
            <div className="space-y-2">
              {Object.entries(selectedExecution.steps || {}).map(([stepId, step]) => (
                <div key={stepId} className="flex items-center justify-between p-2 bg-white/5 rounded">
                  <div className="flex items-center gap-2">
                    {STATUS_ICONS[step.status] || STATUS_ICONS.failed}
                    <span className="font-mono text-sm">{stepId}</span>
                  </div>
                  <span className="text-xs text-gray-400">{step.status}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
