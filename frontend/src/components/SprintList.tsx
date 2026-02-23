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
  return (
    <div>
      <h2 className="text-xl font-bold mb-6">Sprints</h2>

      {/* Sprint list */}
      <div className="space-y-3">
        {sprints.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            No sprints found. Sprints are managed in Legion.
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
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-lg">{sprint.name}</h3>
                      {sprint.project_name && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-300">
                          {sprint.project_name}
                        </span>
                      )}
                    </div>
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
                        {sprint.completed_points}/{sprint.total_points} tasks ({progress}%)
                      </span>
                    </div>
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
