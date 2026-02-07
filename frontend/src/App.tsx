import { useState } from 'react'
import { useCurrentSprint, useSprintBoard, useSprints } from './hooks/useSprintApi'
import { KanbanBoard } from './components/KanbanBoard'
import { SprintHeader } from './components/SprintHeader'
import { SprintList } from './components/SprintList'
import { CreateTaskModal } from './components/CreateTaskModal'
import { TaskDetailModal } from './components/TaskDetailModal'
import { OrchestratorPanel } from './components/OrchestratorPanel'
import { ProjectList } from './components/ProjectList'
import { WorkflowDashboard } from './components/WorkflowDashboard'
import { LayoutDashboard, ListTodo, Settings, Zap, FolderGit2, Workflow } from 'lucide-react'
import type { Task } from './types'

type View = 'board' | 'sprints' | 'projects' | 'workflows' | 'orchestrator'

function App() {
  const [view, setView] = useState<View>('board')
  const [isCreateTaskOpen, setIsCreateTaskOpen] = useState(false)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)

  const { data: currentSprint, isLoading: isLoadingSprint } = useCurrentSprint()
  const { data: board, isLoading: isLoadingBoard } = useSprintBoard(currentSprint?.id || '')
  const { data: sprints } = useSprints()

  const handleTaskClick = (task: Task) => {
    setSelectedTask(task)
  }

  return (
    <div className="min-h-screen bg-background text-gray-100">
      {/* Navigation */}
      <nav className="nav-glass">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-2">
              <Zap className="w-6 h-6 text-indigo-400" />
              <span className="text-lg font-semibold">ZERO</span>
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={() => setView('board')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${
                  view === 'board'
                    ? 'nav-tab-active'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <LayoutDashboard className="w-4 h-4" />
                Board
              </button>
              <button
                onClick={() => setView('sprints')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${
                  view === 'sprints'
                    ? 'nav-tab-active'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <ListTodo className="w-4 h-4" />
                Sprints
              </button>
              <button
                onClick={() => setView('projects')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${
                  view === 'projects'
                    ? 'nav-tab-active'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <FolderGit2 className="w-4 h-4" />
                Projects
              </button>
              <button
                onClick={() => setView('workflows')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${
                  view === 'workflows'
                    ? 'nav-tab-active'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Workflow className="w-4 h-4" />
                Workflows
              </button>
              <button
                onClick={() => setView('orchestrator')}
                className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-all ${
                  view === 'orchestrator'
                    ? 'nav-tab-active'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Settings className="w-4 h-4" />
                Orchestrator
              </button>
            </div>

            <button
              onClick={() => setIsCreateTaskOpen(true)}
              className="btn-primary"
            >
              + New Task
            </button>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {view === 'board' && (
          <>
            {isLoadingSprint ? (
              <div className="text-center py-12 text-gray-400">Loading sprint...</div>
            ) : currentSprint ? (
              <>
                <SprintHeader sprint={currentSprint} />
                {isLoadingBoard ? (
                  <div className="text-center py-12 text-gray-400">Loading board...</div>
                ) : board ? (
                  <KanbanBoard board={board} onTaskClick={handleTaskClick} />
                ) : (
                  <div className="text-center py-12 text-gray-400">No board data available</div>
                )}
              </>
            ) : (
              <div className="text-center py-12">
                <h2 className="text-xl text-gray-400 mb-4">No active sprint</h2>
                <button
                  onClick={() => setView('sprints')}
                  className="btn-primary px-6 py-3"
                >
                  View Sprints
                </button>
              </div>
            )}
          </>
        )}

        {view === 'sprints' && <SprintList sprints={sprints || []} />}

        {view === 'projects' && <ProjectList />}

        {view === 'workflows' && <WorkflowDashboard />}

        {view === 'orchestrator' && <OrchestratorPanel />}
      </main>

      {/* Create Task Modal */}
      <CreateTaskModal
        isOpen={isCreateTaskOpen}
        onClose={() => setIsCreateTaskOpen(false)}
        sprintId={currentSprint?.id}
      />

      {/* Task Detail Modal */}
      <TaskDetailModal
        task={selectedTask}
        isOpen={selectedTask !== null}
        onClose={() => setSelectedTask(null)}
      />
    </div>
  )
}

export default App
