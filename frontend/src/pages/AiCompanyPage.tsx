import { useState } from 'react'
import {
  Users, CheckCircle, DollarSign, Play, Plus, Brain,
  Loader2, ChevronRight, Cpu, Sparkles,
} from 'lucide-react'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import {
  useAgentRoles,
  useAgentTasks,
  useAiCompanyStats,
  useCeoPlan,
  useCreateAgentTask,
  type AgentRole,
  type AgentTask,
  type AiCompanyStats,
} from '@/hooks/useAgentCompanyApi'

// ---------------------------------------------------------------------------
// Status badge helpers
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-500/20 text-green-400',
  in_progress: 'bg-blue-500/20 text-blue-400',
  pending: 'bg-gray-500/20 text-gray-400',
  failed: 'bg-red-500/20 text-red-400',
  delegated: 'bg-yellow-500/20 text-yellow-400',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? 'bg-gray-500/20 text-gray-400'
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

// ---------------------------------------------------------------------------
// Stats Cards
// ---------------------------------------------------------------------------

function StatCard({ icon: Icon, label, value, color }: {
  icon: React.ElementType
  label: string
  value: string | number
  color: string
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div>
          <div className="text-xs text-gray-400">{label}</div>
          <div className="text-2xl font-bold text-gray-100">{value}</div>
        </div>
      </div>
    </div>
  )
}

function StatsRow({ stats }: { stats: AiCompanyStats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <StatCard
        icon={Users}
        label="Total Roles"
        value={stats.total_roles}
        color="bg-indigo-500/20 text-indigo-400"
      />
      <StatCard
        icon={Play}
        label="Active Tasks"
        value={stats.tasks_in_progress}
        color="bg-blue-500/20 text-blue-400"
      />
      <StatCard
        icon={CheckCircle}
        label="Completed"
        value={stats.tasks_completed}
        color="bg-green-500/20 text-green-400"
      />
      <StatCard
        icon={DollarSign}
        label="Total Cost"
        value={`$${stats.total_cost_usd.toFixed(2)}`}
        color="bg-emerald-500/20 text-emerald-400"
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Roles Grid
// ---------------------------------------------------------------------------

function RoleCard({ role }: { role: AgentRole }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 hover:border-indigo-500/50 transition-colors">
      <div className="flex items-start gap-3 mb-3">
        <div className="p-2 rounded-lg bg-indigo-500/20 text-indigo-400 shrink-0">
          <Cpu className="w-4 h-4" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-gray-100 truncate">{role.name}</h3>
          <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{role.description}</p>
        </div>
      </div>

      <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-3">
        <Sparkles className="w-3 h-3" />
        <span className="truncate">{role.llm_provider}/{role.llm_model}</span>
      </div>

      {role.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {role.capabilities.map((cap) => (
            <span
              key={cap}
              className="inline-flex items-center rounded-md bg-gray-700/60 px-2 py-0.5 text-[10px] font-medium text-gray-300"
            >
              {cap}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function RolesSection({ roles }: { roles: AgentRole[] }) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-100 mb-3 flex items-center gap-2">
        <Users className="w-5 h-5 text-indigo-400" />
        Agent Roles
        <span className="text-sm font-normal text-gray-500">({roles.length})</span>
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {roles.map((role) => (
          <RoleCard key={role.id} role={role} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recent Tasks
// ---------------------------------------------------------------------------

function TaskRow({ task }: { task: AgentTask }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 hover:bg-gray-800/50 transition-colors">
      <StatusBadge status={task.status} />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-gray-200 truncate">{task.title}</div>
        {task.assigned_role && (
          <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-1">
            <ChevronRight className="w-3 h-3" />
            {task.assigned_role}
          </div>
        )}
      </div>
      {task.cost_usd !== null && task.cost_usd !== undefined && task.cost_usd > 0 && (
        <span className="text-xs text-emerald-400 font-mono shrink-0">
          ${task.cost_usd.toFixed(4)}
        </span>
      )}
      <span className="text-xs text-gray-500 shrink-0">
        {timeAgo(task.created_at)}
      </span>
    </div>
  )
}

function RecentTasksSection({ tasks }: { tasks: AgentTask[] }) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-100 mb-3 flex items-center gap-2">
        <Play className="w-5 h-5 text-blue-400" />
        Recent Tasks
        <span className="text-sm font-normal text-gray-500">({tasks.length})</span>
      </h2>
      <div className="bg-gray-800 rounded-lg border border-gray-700 divide-y divide-gray-700/50">
        {tasks.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-500 text-sm">
            No tasks yet. Use CEO Plan or New Task to get started.
          </div>
        ) : (
          tasks.map((task) => <TaskRow key={task.id} task={task} />)
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// CEO Plan Dialog
// ---------------------------------------------------------------------------

function CeoPlanDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [description, setDescription] = useState('')
  const ceoPlan = useCeoPlan()

  const handleSubmit = () => {
    if (!description.trim()) return
    ceoPlan.mutate({ description: description.trim() }, {
      onSuccess: () => {
        setDescription('')
        onOpenChange(false)
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-gray-900 border-gray-700">
        <DialogHeader>
          <DialogTitle className="text-gray-100 flex items-center gap-2">
            <Brain className="w-5 h-5 text-indigo-400" />
            CEO Plan
          </DialogTitle>
          <DialogDescription className="text-gray-400">
            Describe a high-level objective. The CEO agent will decompose it into tasks
            and delegate to the appropriate roles.
          </DialogDescription>
        </DialogHeader>

        <textarea
          className="w-full h-32 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
          placeholder="e.g. Research top 5 competitors in the AI agent space and draft a comparison report..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        <DialogFooter>
          <button
            onClick={() => onOpenChange(false)}
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!description.trim() || ceoPlan.isPending}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {ceoPlan.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Planning...
              </>
            ) : (
              <>
                <Brain className="w-4 h-4" />
                Submit Plan
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// New Task Dialog
// ---------------------------------------------------------------------------

function NewTaskDialog({ open, onOpenChange, roles }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  roles: AgentRole[]
}) {
  const [title, setTitle] = useState('')
  const [roleId, setRoleId] = useState('')
  const createTask = useCreateAgentTask()

  const handleSubmit = () => {
    if (!title.trim()) return
    createTask.mutate(
      { title: title.trim(), description: title.trim(), assigned_role: roleId || undefined },
      {
        onSuccess: () => {
          setTitle('')
          setRoleId('')
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-gray-900 border-gray-700">
        <DialogHeader>
          <DialogTitle className="text-gray-100 flex items-center gap-2">
            <Plus className="w-5 h-5 text-blue-400" />
            New Task
          </DialogTitle>
          <DialogDescription className="text-gray-400">
            Create a task and optionally assign it to a specific agent role.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <input
            type="text"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            placeholder="Task title..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />

          <select
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            value={roleId}
            onChange={(e) => setRoleId(e.target.value)}
          >
            <option value="">Auto-assign</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>

        <DialogFooter>
          <button
            onClick={() => onOpenChange(false)}
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!title.trim() || createTask.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
          >
            {createTask.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                Create Task
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function AiCompanyPage() {
  const [ceoPlanOpen, setCeoPlanOpen] = useState(false)
  const [newTaskOpen, setNewTaskOpen] = useState(false)

  const { data: stats, isLoading: statsLoading } = useAiCompanyStats()
  const { data: roles, isLoading: rolesLoading } = useAgentRoles()
  const { data: tasks, isLoading: tasksLoading } = useAgentTasks()

  return (
    <div className="min-h-screen bg-gray-900 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Action buttons */}
        <div className="flex items-center justify-end">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCeoPlanOpen(true)}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
            >
              <Brain className="w-4 h-4" />
              CEO Plan
            </button>
            <button
              onClick={() => setNewTaskOpen(true)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              New Task
            </button>
          </div>
        </div>

        {/* Stats */}
        {statsLoading ? (
          <LoadingSkeleton variant="cards" count={4} />
        ) : stats ? (
          <StatsRow stats={stats} />
        ) : null}

        {/* Agent Roles */}
        {rolesLoading ? (
          <LoadingSkeleton variant="cards" count={6} message="Loading agent roles..." />
        ) : roles && roles.length > 0 ? (
          <RolesSection roles={roles} />
        ) : (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-8 text-center">
            <Users className="w-10 h-10 text-gray-600 mx-auto mb-2" />
            <p className="text-gray-400 text-sm">No agent roles configured yet.</p>
          </div>
        )}

        {/* Recent Tasks */}
        {tasksLoading ? (
          <LoadingSkeleton variant="page" message="Loading tasks..." />
        ) : (
          <RecentTasksSection tasks={tasks ?? []} />
        )}
      </div>

      {/* Dialogs */}
      <CeoPlanDialog open={ceoPlanOpen} onOpenChange={setCeoPlanOpen} />
      <NewTaskDialog open={newTaskOpen} onOpenChange={setNewTaskOpen} roles={roles ?? []} />
    </div>
  )
}
