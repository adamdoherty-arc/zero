import { useState } from 'react'
import { X } from 'lucide-react'
import { useCreateTask, useProjects } from '../hooks/useSprintApi'
import type { TaskCategory, TaskPriority } from '../types'

interface CreateTaskModalProps {
  isOpen: boolean
  onClose: () => void
  sprintId?: string
}

export function CreateTaskModal({ isOpen, onClose, sprintId }: CreateTaskModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState<TaskCategory>('feature')
  const [priority, setPriority] = useState<TaskPriority>('medium')
  const [points, setPoints] = useState<string>('')
  const [projectId, setProjectId] = useState<string>('')

  const createTask = useCreateTask()
  const { data: projects } = useProjects()

  if (!isOpen) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return

    createTask.mutate(
      {
        title: title.trim(),
        description: description.trim() || undefined,
        sprint_id: sprintId,
        project_id: projectId || undefined,
        category,
        priority,
        points: points ? parseInt(points, 10) : undefined,
      },
      {
        onSuccess: () => {
          setTitle('')
          setDescription('')
          setCategory('feature')
          setPriority('medium')
          setPoints('')
          setProjectId('')
          onClose()
        },
      }
    )
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-50">
      <div className="modal-content w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700/50">
          <h2 className="text-lg font-semibold">Create Task</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-700 rounded transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Title *
            </label>
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="Task title..."
              className="input-field"
              autoFocus
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Task description..."
              rows={3}
              className="input-field resize-none"
            />
          </div>

          {/* Project */}
          {projects && projects.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Project
              </label>
              <select
                value={projectId}
                onChange={e => setProjectId(e.target.value)}
                className="input-field"
              >
                <option value="">No project</option>
                {projects.map(project => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Category & Priority */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Category
              </label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value as TaskCategory)}
                className="input-field"
              >
                <option value="feature">Feature</option>
                <option value="bug">Bug</option>
                <option value="enhancement">Enhancement</option>
                <option value="chore">Chore</option>
                <option value="documentation">Documentation</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Priority
              </label>
              <select
                value={priority}
                onChange={e => setPriority(e.target.value as TaskPriority)}
                className="input-field"
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>

          {/* Points */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Story Points
            </label>
            <input
              type="number"
              value={points}
              onChange={e => setPoints(e.target.value)}
              placeholder="Optional..."
              min="0"
              max="100"
              className="input-field"
            />
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || createTask.isPending}
              className="btn-primary"
            >
              {createTask.isPending ? 'Creating...' : 'Create Task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
