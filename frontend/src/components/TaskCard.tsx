import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Bug, Sparkles, Wrench, FileText, BookOpen, AlertTriangle } from 'lucide-react'
import type { Task } from '../types'

interface TaskCardProps {
  task: Task
  isDragging?: boolean
  onClick?: (task: Task) => void
}

const CATEGORY_ICONS = {
  bug: Bug,
  feature: Sparkles,
  enhancement: Wrench,
  chore: FileText,
  documentation: BookOpen,
}

const PRIORITY_COLORS = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/50',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/50',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
  low: 'bg-gray-500/20 text-gray-400 border-gray-500/50',
}

const SOURCE_BADGES = {
  MANUAL: null,
  QA_DETECTED: { label: 'QA', color: 'bg-purple-500/20 text-purple-400' },
  ERROR_LOG: { label: 'Error', color: 'bg-red-500/20 text-red-400' },
  ENHANCEMENT_ENGINE: { label: 'Auto', color: 'bg-blue-500/20 text-blue-400' },
  USER_REPORTED: { label: 'User', color: 'bg-green-500/20 text-green-400' },
  TODO_SCAN: { label: 'TODO', color: 'bg-yellow-500/20 text-yellow-400' },
}

export function TaskCard({ task, isDragging, onClick }: TaskCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
  } = useSortable({ id: task.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  const CategoryIcon = CATEGORY_ICONS[task.category] || FileText
  const sourceBadge = SOURCE_BADGES[task.source]

  const handleClick = () => {
    if (!isDragging && onClick) {
      onClick(task)
    }
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={handleClick}
      className={`
        task-card cursor-pointer
        ${isDragging ? 'dragging opacity-80 shadow-xl' : ''}
        ${task.status === 'blocked' ? 'border-red-500/50' : ''}
      `}
    >
      {/* Header with category icon and priority */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <CategoryIcon className="w-4 h-4 text-gray-500" />
          <span className={`text-xs px-1.5 py-0.5 rounded border ${PRIORITY_COLORS[task.priority]}`}>
            {task.priority}
          </span>
        </div>

        {task.points && (
          <span className="text-xs bg-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded-full">
            {task.points} pts
          </span>
        )}
      </div>

      {/* Title */}
      <h4 className="font-medium text-gray-200 mb-2 line-clamp-2">{task.title}</h4>

      {/* Blocked reason */}
      {task.status === 'blocked' && task.blocked_reason && (
        <div className="flex items-start gap-1.5 text-xs text-red-400 bg-red-500/10 rounded p-2 mb-2">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span className="line-clamp-2">{task.blocked_reason}</span>
        </div>
      )}

      {/* Footer with ID and source */}
      <div className="flex items-center justify-between text-xs text-gray-500 mt-2">
        <span>{task.id}</span>
        {sourceBadge && (
          <span className={`px-1.5 py-0.5 rounded ${sourceBadge.color}`}>
            {sourceBadge.label}
          </span>
        )}
      </div>
    </div>
  )
}
