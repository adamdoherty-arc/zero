import { useState } from 'react'
import { Play, CheckCircle, PauseCircle, Plus } from 'lucide-react'
import { useStartSprint, useCompleteSprint, useCreateSprint } from '../hooks/useSprintApi'
import type { Sprint, SprintStatus } from '../types'

interface SprintListProps {
  sprints: Sprint[]
}

const STATUS_COLORS: Record<SprintStatus, string> = {
  planning: 'badge-info',
  active: 'badge-success',
  paused: 'badge-warning',
  completed: 'badge-neutral',
  cancelled: 'badge-danger',
}

export function SprintList({ sprints }: SprintListProps) {
  const [isCreating, setIsCreating] = useState(false)
  const [newSprintName, setNewSprintName] = useState('')

  const startSprint = useStartSprint()
  const completeSprint = useCompleteSprint()
  const createSprint = useCreateSprint()

  const handleCreate = () => {
    if (!newSprintName.trim()) return
    createSprint.mutate(
      { name: newSprintName.trim() },
      {
        onSuccess: () => {
          setNewSprintName('')
          setIsCreating(false)
        },
      }
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">Sprints</h2>
        {!isCreating && (
          <button
            onClick={() => setIsCreating(true)}
            className="btn-primary gap-2"
          >
            <Plus className="w-4 h-4" />
            New Sprint
          </button>
        )}
      </div>

      {/* Create sprint form */}
      {isCreating && (
        <div className="glass-card p-4 mb-4">
          <h3 className="font-medium mb-3">Create New Sprint</h3>
          <div className="flex gap-3">
            <input
              type="text"
              value={newSprintName}
              onChange={e => setNewSprintName(e.target.value)}
              placeholder="Sprint name..."
              className="flex-1 input-field"
              autoFocus
            />
            <button
              onClick={handleCreate}
              disabled={!newSprintName.trim() || createSprint.isPending}
              className="btn-primary"
            >
              {createSprint.isPending ? 'Creating...' : 'Create'}
            </button>
            <button
              onClick={() => {
                setIsCreating(false)
                setNewSprintName('')
              }}
              className="btn-secondary"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Sprint list */}
      <div className="space-y-3">
        {sprints.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            No sprints yet. Create your first sprint to get started.
          </div>
        ) : (
          sprints.map(sprint => {
            const progress = sprint.total_points > 0
              ? Math.round((sprint.completed_points / sprint.total_points) * 100)
              : 0

            return (
              <div
                key={sprint.id}
                className="glass-card-hover p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`badge ${STATUS_COLORS[sprint.status]}`}>
                        {sprint.status}
                      </span>
                      <span className="text-gray-500 text-sm">Sprint {sprint.number}</span>
                    </div>
                    <h3 className="font-semibold text-lg">{sprint.name}</h3>
                    {sprint.description && (
                      <p className="text-gray-400 text-sm mt-1">{sprint.description}</p>
                    )}

                    {/* Progress */}
                    <div className="flex items-center gap-4 mt-3">
                      <div className="flex-1 progress-bar max-w-xs">
                        <div
                          className="progress-bar-fill"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <span className="text-sm text-gray-400">
                        {sprint.completed_points}/{sprint.total_points} pts ({progress}%)
                      </span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 ml-4">
                    {sprint.status === 'planning' && (
                      <button
                        onClick={() => startSprint.mutate(sprint.id)}
                        disabled={startSprint.isPending}
                        className="p-2 text-green-400 hover:bg-green-400/10 rounded-lg transition-colors"
                        title="Start Sprint"
                      >
                        <Play className="w-5 h-5" />
                      </button>
                    )}
                    {sprint.status === 'active' && (
                      <button
                        onClick={() => completeSprint.mutate(sprint.id)}
                        disabled={completeSprint.isPending}
                        className="p-2 text-blue-400 hover:bg-blue-400/10 rounded-lg transition-colors"
                        title="Complete Sprint"
                      >
                        <CheckCircle className="w-5 h-5" />
                      </button>
                    )}
                    {sprint.status === 'paused' && (
                      <button
                        onClick={() => startSprint.mutate(sprint.id)}
                        disabled={startSprint.isPending}
                        className="p-2 text-yellow-400 hover:bg-yellow-400/10 rounded-lg transition-colors"
                        title="Resume Sprint"
                      >
                        <PauseCircle className="w-5 h-5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
