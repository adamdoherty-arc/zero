import { Calendar, Target, TrendingUp } from 'lucide-react'
import type { Sprint } from '../types'

interface SprintHeaderProps {
  sprint: Sprint
}

export function SprintHeader({ sprint }: SprintHeaderProps) {
  const progress = sprint.total_points > 0
    ? Math.round((sprint.completed_points / sprint.total_points) * 100)
    : 0

  const endDate = sprint.end_date ? new Date(sprint.end_date) : null
  const daysRemaining = endDate
    ? Math.max(0, Math.ceil((endDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24)))
    : null

  return (
    <div className="glass-card p-6 mb-6">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="badge badge-success uppercase">
              {sprint.status}
            </span>
            <span className="text-gray-500">Sprint {sprint.number}</span>
          </div>
          <h1 className="text-2xl font-bold">{sprint.name}</h1>
          {sprint.description && (
            <p className="text-gray-400 mt-1">{sprint.description}</p>
          )}
        </div>

        {/* Stats */}
        <div className="flex gap-6 text-sm">
          <div className="text-center">
            <div className="flex items-center gap-1 text-gray-400 mb-1">
              <Calendar className="w-4 h-4" />
              Days Left
            </div>
            <div className="text-2xl font-bold text-primary">
              {daysRemaining ?? '-'}
            </div>
          </div>

          <div className="text-center">
            <div className="flex items-center gap-1 text-gray-400 mb-1">
              <Target className="w-4 h-4" />
              Points
            </div>
            <div className="text-2xl font-bold">
              <span className="text-accent">{sprint.completed_points}</span>
              <span className="text-gray-500">/{sprint.total_points}</span>
            </div>
          </div>

          <div className="text-center">
            <div className="flex items-center gap-1 text-gray-400 mb-1">
              <TrendingUp className="w-4 h-4" />
              Progress
            </div>
            <div className="text-2xl font-bold text-primary">{progress}%</div>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="progress-bar">
        <div
          className="progress-bar-fill"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Goals */}
      {sprint.goals.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-medium text-gray-400 mb-2">Sprint Goals</h3>
          <ul className="space-y-1">
            {sprint.goals.map((goal, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                <span className="text-primary mt-0.5">•</span>
                {goal}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
