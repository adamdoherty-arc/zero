import { useState } from 'react'
import { useCurrentSprint, useSprintBoard } from '@/hooks/useSprintApi'
import { KanbanBoard } from '@/components/KanbanBoard'
import { SprintHeader } from '@/components/SprintHeader'
import { TaskDetailModal } from '@/components/TaskDetailModal'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import type { Task } from '@/types'

export function BoardPage() {
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
      </div>

      {isLoadingSprint ? (
        <LoadingSkeleton variant="inline" message="Loading sprint..." />
      ) : currentSprint ? (
        <>
          <SprintHeader sprint={currentSprint} />
          {isLoadingBoard ? (
            <LoadingSkeleton variant="page" message="Loading board..." />
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

      <TaskDetailModal
        task={selectedTask}
        isOpen={selectedTask !== null}
        onClose={() => setSelectedTask(null)}
      />
    </div>
  )
}
