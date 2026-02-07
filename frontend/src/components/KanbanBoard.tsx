import { useState } from 'react'
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { TaskCard } from './TaskCard'
import { KanbanColumn } from './KanbanColumn'
import { useMoveTask } from '../hooks/useSprintApi'
import type { SprintBoard, Task, TaskStatus } from '../types'

interface KanbanBoardProps {
  board: SprintBoard
  onTaskClick?: (task: Task) => void
}

const COLUMN_ORDER: TaskStatus[] = [
  'backlog',
  'todo',
  'in_progress',
  'review',
  'testing',
  'done',
  'blocked',
]

const COLUMN_LABELS: Record<TaskStatus, string> = {
  backlog: 'Backlog',
  todo: 'To Do',
  in_progress: 'In Progress',
  review: 'Review',
  testing: 'Testing',
  done: 'Done',
  blocked: 'Blocked',
}

const COLUMN_COLORS: Record<TaskStatus, string> = {
  backlog: 'border-gray-600',
  todo: 'border-blue-600',
  in_progress: 'border-yellow-600',
  review: 'border-purple-600',
  testing: 'border-orange-600',
  done: 'border-green-600',
  blocked: 'border-red-600',
}

export function KanbanBoard({ board, onTaskClick }: KanbanBoardProps) {
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const moveTask = useMoveTask()

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor)
  )

  const handleDragStart = (event: DragStartEvent) => {
    const { active } = event
    const taskId = active.id as string

    // Find the task across all columns
    for (const status of COLUMN_ORDER) {
      const task = board.columns[status]?.find(t => t.id === taskId)
      if (task) {
        setActiveTask(task)
        break
      }
    }
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    setActiveTask(null)

    if (!over) return

    const taskId = active.id as string
    const newStatus = over.id as TaskStatus

    // Only move if dropped on a valid column
    if (COLUMN_ORDER.includes(newStatus)) {
      // Find current status
      let currentStatus: TaskStatus | null = null
      for (const status of COLUMN_ORDER) {
        if (board.columns[status]?.some(t => t.id === taskId)) {
          currentStatus = status
          break
        }
      }

      // Only call API if status changed
      if (currentStatus && currentStatus !== newStatus) {
        moveTask.mutate({ id: taskId, move: { status: newStatus } })
      }
    }
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex gap-4 overflow-x-auto pb-4">
        {COLUMN_ORDER.map(status => {
          const tasks = board.columns[status] || []
          const taskIds = tasks.map(t => t.id)

          return (
            <KanbanColumn
              key={status}
              id={status}
              title={COLUMN_LABELS[status]}
              count={tasks.length}
              colorClass={COLUMN_COLORS[status]}
            >
              <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
                {tasks.map(task => (
                  <TaskCard key={task.id} task={task} onClick={onTaskClick} />
                ))}
              </SortableContext>
            </KanbanColumn>
          )
        })}
      </div>

      <DragOverlay>
        {activeTask ? <TaskCard task={activeTask} isDragging /> : null}
      </DragOverlay>
    </DndContext>
  )
}
