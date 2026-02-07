import { create } from 'zustand'
import type { Sprint, Task, SprintBoard } from '../types'

interface SprintState {
  // Data
  sprints: Sprint[]
  currentSprint: Sprint | null
  tasks: Task[]
  board: SprintBoard | null

  // Loading states
  isLoading: boolean
  error: string | null

  // Actions
  setSprints: (sprints: Sprint[]) => void
  setCurrentSprint: (sprint: Sprint | null) => void
  setTasks: (tasks: Task[]) => void
  setBoard: (board: SprintBoard | null) => void
  setLoading: (isLoading: boolean) => void
  setError: (error: string | null) => void

  // Task actions
  updateTaskStatus: (taskId: string, newStatus: string) => void
  addTask: (task: Task) => void
  removeTask: (taskId: string) => void
  updateTask: (taskId: string, updates: Partial<Task>) => void
}

export const useSprintStore = create<SprintState>((set) => ({
  // Initial state
  sprints: [],
  currentSprint: null,
  tasks: [],
  board: null,
  isLoading: false,
  error: null,

  // Actions
  setSprints: (sprints) => set({ sprints }),
  setCurrentSprint: (sprint) => set({ currentSprint: sprint }),
  setTasks: (tasks) => set({ tasks }),
  setBoard: (board) => set({ board }),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),

  // Task mutations (optimistic updates)
  updateTaskStatus: (taskId, newStatus) => set((state) => {
    const tasks = state.tasks.map(task =>
      task.id === taskId ? { ...task, status: newStatus as Task['status'] } : task
    )

    // Also update board if it exists
    let board = state.board
    if (board) {
      const columns = { ...board.columns }
      // Find and remove task from old column
      for (const status in columns) {
        const taskIndex = columns[status].findIndex(t => t.id === taskId)
        if (taskIndex !== -1) {
          const [task] = columns[status].splice(taskIndex, 1)
          // Add to new column
          if (!columns[newStatus]) columns[newStatus] = []
          columns[newStatus].push({ ...task, status: newStatus as Task['status'] })
          break
        }
      }
      board = { ...board, columns }
    }

    return { tasks, board }
  }),

  addTask: (task) => set((state) => ({
    tasks: [...state.tasks, task]
  })),

  removeTask: (taskId) => set((state) => ({
    tasks: state.tasks.filter(t => t.id !== taskId)
  })),

  updateTask: (taskId, updates) => set((state) => ({
    tasks: state.tasks.map(task =>
      task.id === taskId ? { ...task, ...updates } : task
    )
  }))
}))
