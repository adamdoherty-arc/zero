import { useState } from 'react'
import { useCurrentSprint, useSprintBoard } from '@/hooks/useSprintApi'
import { KanbanBoard } from '@/components/KanbanBoard'
import { SprintHeader } from '@/components/SprintHeader'
import { CreateTaskModal } from '@/components/CreateTaskModal'
import { TaskDetailModal } from '@/components/TaskDetailModal'
import type { Task } from '@/types'

export function BoardPage() {
  const [isCreateTaskOpen, setIsCreateTaskOpen] = useState(false)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)

  const { data: currentSprint, isLoading: isLoadingSprint } = useCurrentSprint()
  const { data: board, isLoading: isLoadingBoard } = useSprintBoard(currentSprint?.id || '')

  const handleTaskClick = (task: Task) => {
    setSelectedTask(task)
  }

  return (
    <div className="page-content">
      <div className="flex items-center justify-between mb-6">
        <h1 className="page-title">Sprint Board</h1>
        <button
          onClick={() => setIsCreateTaskOpen(true)}
          className="btn-primary"
        >
          + New Task
        </button>
      </div>

      {isLoadingSprint ? (
        <div className="text-center py-12 text-muted-foreground">Loading sprint...</div>
      ) : currentSprint ? (
        <>
          <SprintHeader sprint={currentSprint} />
          {isLoadingBoard ? (
            <div className="text-center py-12 text-muted-foreground">Loading board...</div>
          ) : board ? (
            <KanbanBoard board={board} onTaskClick={handleTaskClick} />
          ) : (
            <div className="text-center py-12 text-muted-foreground">No board data available</div>
          )}
        </>
      ) : (
        <div className="text-center py-12">
          <h2 className="text-xl text-muted-foreground mb-4">No active sprint</h2>
          <a href="/sprints" className="btn-primary px-6 py-3">
            View Sprints
          </a>
        </div>
      )}

      <CreateTaskModal
        isOpen={isCreateTaskOpen}
        onClose={() => setIsCreateTaskOpen(false)}
        sprintId={currentSprint?.id}
      />

      <TaskDetailModal
        task={selectedTask}
        isOpen={selectedTask !== null}
        onClose={() => setSelectedTask(null)}
      />
    </div>
  )
}
