import { useState, useEffect } from 'react'
import { X, Save, Trash2, AlertTriangle } from 'lucide-react'
import { useUpdateTask, useDeleteTask, useMoveTask } from '../hooks/useSprintApi'
import type { Task, TaskStatus, TaskCategory, TaskPriority } from '../types'

interface TaskDetailModalProps {
  task: Task | null
  isOpen: boolean
  onClose: () => void
}

const STATUS_OPTIONS: TaskStatus[] = ['backlog', 'todo', 'in_progress', 'review', 'testing', 'done', 'blocked']
const CATEGORY_OPTIONS: TaskCategory[] = ['bug', 'feature', 'enhancement', 'chore', 'documentation']
const PRIORITY_OPTIONS: TaskPriority[] = ['critical', 'high', 'medium', 'low']

const STATUS_COLORS: Record<TaskStatus, string> = {
  backlog: 'bg-gray-500',
  todo: 'bg-blue-500',
  in_progress: 'bg-yellow-500',
  review: 'bg-purple-500',
  testing: 'bg-orange-500',
  done: 'bg-green-500',
  blocked: 'bg-red-500',
}

export function TaskDetailModal({ task, isOpen, onClose }: TaskDetailModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<TaskStatus>('backlog')
  const [category, setCategory] = useState<TaskCategory>('feature')
  const [priority, setPriority] = useState<TaskPriority>('medium')
  const [points, setPoints] = useState<string>('')
  const [blockedReason, setBlockedReason] = useState('')

  const updateTask = useUpdateTask()
  const deleteTask = useDeleteTask()
  const moveTask = useMoveTask()

  // Sync state with task prop
  useEffect(() => {
    if (task) {
      setTitle(task.title)
      setDescription(task.description || '')
      setStatus(task.status)
      setCategory(task.category)
      setPriority(task.priority)
      setPoints(task.points?.toString() || '')
      setBlockedReason(task.blocked_reason || '')
    }
  }, [task])

  if (!isOpen || !task) return null

  const handleSave = () => {
    updateTask.mutate(
      {
        id: task.id,
        data: {
          title,
          description: description || undefined,
          category,
          priority,
          points: points ? parseInt(points, 10) : undefined,
          blocked_reason: status === 'blocked' ? blockedReason : undefined,
        },
      },
      { onSuccess: onClose }
    )
  }

  const handleStatusChange = (newStatus: TaskStatus) => {
    setStatus(newStatus)
    moveTask.mutate(
      {
        id: task.id,
        move: {
          status: newStatus,
          reason: newStatus === 'blocked' ? blockedReason : undefined,
        },
      }
    )
  }

  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete this task?')) {
      deleteTask.mutate(task.id, { onSuccess: onClose })
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-50 p-4">
      <div className="modal-content w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700/50 sticky top-0 bg-surface/95 backdrop-blur-sm rounded-t-2xl">
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">{task.id}</span>
            <div className={`w-2 h-2 rounded-full ${STATUS_COLORS[status]}`} />
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDelete}
              className="p-2 text-red-400 hover:bg-red-400/10 rounded transition-colors"
              title="Delete task"
            >
              <Trash2 className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-700 rounded transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Title */}
          <div>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              className="w-full text-xl font-semibold bg-transparent border-none focus:outline-none focus:ring-2 focus:ring-primary/50 rounded px-2 py-1 -mx-2"
              placeholder="Task title..."
            />
          </div>

          {/* Status buttons */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-2">Status</label>
            <div className="flex flex-wrap gap-2">
              {STATUS_OPTIONS.map(s => (
                <button
                  key={s}
                  onClick={() => handleStatusChange(s)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    status === s
                      ? `${STATUS_COLORS[s]} text-white`
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {s.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>

          {/* Blocked reason */}
          {status === 'blocked' && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <div className="flex items-center gap-2 text-red-400 mb-2">
                <AlertTriangle className="w-4 h-4" />
                <span className="text-sm font-medium">Blocked Reason</span>
              </div>
              <input
                type="text"
                value={blockedReason}
                onChange={e => setBlockedReason(e.target.value)}
                placeholder="Why is this task blocked?"
                className="input-field focus:border-red-500"
              />
            </div>
          )}

          {/* Category, Priority, Points */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Category</label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value as TaskCategory)}
                className="input-field"
              >
                {CATEGORY_OPTIONS.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Priority</label>
              <select
                value={priority}
                onChange={e => setPriority(e.target.value as TaskPriority)}
                className="input-field"
              >
                {PRIORITY_OPTIONS.map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">Points</label>
              <input
                type="number"
                value={points}
                onChange={e => setPoints(e.target.value)}
                min="0"
                max="100"
                className="input-field"
              />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={6}
              placeholder="Add a description..."
              className="input-field resize-none font-mono text-sm"
            />
          </div>

          {/* Metadata */}
          <div className="grid grid-cols-2 gap-4 text-sm text-gray-400 stat-card">
            <div>
              <span className="text-gray-500">Source:</span>{' '}
              <span className={task.source === 'MANUAL' ? '' : 'text-primary'}>
                {task.source}
              </span>
            </div>
            <div>
              <span className="text-gray-500">Created:</span>{' '}
              {new Date(task.created_at).toLocaleDateString()}
            </div>
            {task.started_at && (
              <div>
                <span className="text-gray-500">Started:</span>{' '}
                {new Date(task.started_at).toLocaleDateString()}
              </div>
            )}
            {task.completed_at && (
              <div>
                <span className="text-gray-500">Completed:</span>{' '}
                {new Date(task.completed_at).toLocaleDateString()}
              </div>
            )}
            {task.source_reference && (
              <div className="col-span-2">
                <span className="text-gray-500">Reference:</span>{' '}
                <span className="text-primary">{task.source_reference}</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-4 border-t border-gray-700/50 sticky bottom-0 bg-surface/95 backdrop-blur-sm rounded-b-2xl">
          <button
            onClick={onClose}
            className="btn-secondary"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!title.trim() || updateTask.isPending}
            className="btn-primary gap-2"
          >
            <Save className="w-4 h-4" />
            {updateTask.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
