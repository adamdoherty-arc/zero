import { Link } from 'react-router-dom'
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ElementType, FormEvent, ReactNode } from 'react'
import {
  Activity,
  AlertTriangle,
  Ban,
  Banknote,
  Bot,
  Briefcase,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock3,
  Columns3,
  Copy,
  Cpu,
  Eye,
  EyeOff,
  ExternalLink,
  FileText,
  Filter,
  Gavel,
  HelpCircle,
  Inbox,
  KeyRound,
  Lightbulb,
  ListChecks,
  Megaphone,
  MessageSquareText,
  PackageCheck,
  Pause,
  PauseCircle,
  Play,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Table2,
  Target,
  Trash2,
  X,
} from 'lucide-react'

import {
  agentProfiles,
  approvals,
  assets,
  companyDocs,
  financeEvidencePackets,
  financeSetupRails,
  companyKpis,
  labJobs,
  opportunities,
  productIdeas,
  subscriptions,
  tasks as seedTasks,
  taxEvents,
  type CompanyTask,
  type CompanyTaskStatus,
  type RiskLevel,
} from '@/data/company-os'
import { allNavItems } from '@/config/navigation'
import {
  useAgentApprovals,
  useAnswerCompanyAgentQuestion,
  useCompanyAgentQuestions,
  useCompanyOperatorOvernight,
  useCompanyOperatorRuns,
  useCompanyOperatorStatus,
  useCompanyOperatorToday,
  useDecideAgentApproval,
  useDismissCompanyAgentQuestion,
  useGenerateCompanyOperatorReport,
  usePauseCompanyOperator,
  useResumeCompanyOperator,
  useRunCompanyPromptEval,
  useRunCompanyOperatorTick,
  useTriageCompanyAgentQuestions,
  type CompanyOperatorApproval,
  type CompanyAgentQuestion,
  type CompanySubagentStatus,
} from '@/hooks/useCompanyOperatorApi'
import {
  useCompanyProgressCheckin,
  useCompanySeedStatus,
  useCompanySetupProgress,
  useCompanyReviewSummary,
  useCompanyTaskEvents,
  useCompanyTaskReview,
  useCompanyWorkItems,
  useCompleteCompanyWorkItem,
  useCreateCompanyWorkItem,
  useDeleteCompanyWorkItem,
  useDuplicateCompanyWorkItem,
  useImportCompanySeedBacklog,
  useReopenCompanyWorkItem,
  useRunCompanyCompletionReview,
  useRunCompanyProgressCheckin,
  useUpdateCompanyWorkItem,
  type CompanySetupTaskSummary,
} from '@/hooks/useCompanyWorkItemsApi'
import {
  useCompanyFacts,
  useDeleteCompanyFact,
  usePatchCompanyFact,
  useUpsertCompanyFact,
} from '@/hooks/useCompanyFactsApi'
import { toast } from '@/hooks/use-toast'
import { maskSensitive } from '@/lib/masking'
import { cn } from '@/lib/utils'
import { TaskNotesPanel } from '@/components/TaskNotesPanel'
import type {
  CompanyFact,
  CompanyWorkItemReview,
  CompletionOutput,
  Task as ZeroTask,
  TaskUpdate as ZeroTaskUpdate,
  WalkthroughCompletionField,
} from '@/types'

export type CompanySection =
  | 'overview'
  | 'operator'
  | 'tasks'
  | 'agents'
  | 'inbox'
  | 'approvals'
  | 'finance'
  | 'legal'
  | 'revenue'
  | 'product'
  | 'robotics'
  | 'marketing'
  | 'docs'

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const sectionLabels: Record<CompanySection, string> = {
  overview: 'Command Center',
  operator: 'Operator',
  tasks: 'Tasks',
  agents: 'Agents',
  inbox: 'Agent Inbox',
  approvals: 'Approvals',
  finance: 'Finance',
  legal: 'Legal / LLC',
  revenue: 'Consulting / CRM',
  product: 'Product Studio',
  robotics: 'Robotics Lab',
  marketing: 'Marketing',
  docs: 'Docs / Sources',
}

const riskClasses: Record<RiskLevel, string> = {
  low: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  medium: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  high: 'border-orange-500/30 bg-orange-500/10 text-orange-300',
  critical: 'border-red-500/30 bg-red-500/10 text-red-300',
}

function scoreClass(score?: number) {
  if (score === undefined) return 'border-gray-700 text-gray-400'
  if (score >= 85) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (score >= 65) return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (score >= 45) return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-red-500/30 bg-red-500/10 text-red-300'
}

const statusColumns: CompanyTaskStatus[] = ['on-hold', 'in-progress', 'blocked', 'done']
const statusColumnLabels: Record<CompanyTaskStatus, string> = {
  backlog: 'Backlog',
  ready: 'Ready',
  'on-hold': 'On Hold',
  'in-progress': 'In Progress',
  blocked: 'Blocked',
  done: 'Completed',
}
const statusColumnClasses: Record<CompanyTaskStatus, string> = {
  backlog: 'border-gray-700',
  ready: 'border-blue-500/40',
  'on-hold': 'border-amber-500/50',
  'in-progress': 'border-emerald-500/50',
  blocked: 'border-red-500/50',
  done: 'border-green-500/50',
}
const companyDomains = ['Formation', 'Finance', 'Consulting', 'Product', 'Robotics', 'Marketing', 'Operations', 'Dashboard', 'Agents', 'Knowledge']
const ownerAgents = [
  'zero-company-operator',
  'chief_of_staff',
  'finance_cpa',
  'legal_compliance',
  'procurement_asset',
  'consulting_revenue',
  'delivery',
  'product',
  'engineering',
  'llm_ops',
  'knowledge_second_brain',
  'marketing_content',
  'robotics_lab',
  'security_risk',
]
const zeroStatusOptions: Array<{ label: string; value: ZeroTask['status']; company: CompanyTaskStatus }> = [
  { label: 'On Hold', value: 'on_hold', company: 'on-hold' },
  { label: 'In progress', value: 'in_progress', company: 'in-progress' },
  { label: 'Blocked', value: 'blocked', company: 'blocked' },
  { label: 'Done', value: 'done', company: 'done' },
]
const priorityOptions: ZeroTask['priority'][] = ['critical', 'high', 'medium', 'low']

const highRiskTaskPattern = /sunbiz|file florida llc|ein|registered agent|operating agreement|ip assignment|software\/ip|bank account|credit card|asset transfer|equipment transfer|fair market value|fmv|robot purchase|robot transfer|home office|duval|cpa|attorney|stripe|tax|liability|website/i

type CompanyTaskCard = CompanyTask & {
  zeroStatus?: ZeroTask['status']
  zeroPriority?: ZeroTask['priority']
  zeroDescription?: string
  zeroBlockedReason?: string
  zeroTask?: ZeroTask
  review?: CompanyWorkItemReview
}

function taskStatusToCompany(status: ZeroTask['status']): CompanyTaskStatus {
  if (status === 'on_hold') return 'on-hold'
  if (status === 'blocked') return 'blocked'
  if (status === 'done') return 'done'
  return 'in-progress'
}

function companyStatusToZero(status: CompanyTaskStatus): ZeroTask['status'] {
  if (status === 'on-hold') return 'on_hold'
  if (status === 'in-progress') return 'in_progress'
  if (status === 'blocked') return 'blocked'
  if (status === 'done') return 'done'
  return 'in_progress'
}

function zeroStatusForCompanyTask(task: CompanyTaskCard): ZeroTask['status'] {
  return zeroStatusOptions.find((item) => item.company === task.status)?.value ?? companyStatusToZero(task.status)
}

function taskDomain(task: ZeroTask): string {
  const match = task.description?.match(/\(([^)]+ Sprint)\)/)
  if (match?.[1]) return match[1].replace(' Sprint', '')
  return task.category.replace(/_/g, ' ')
}

function zeroTaskToCompanyTask(task: ZeroTask): CompanyTaskCard {
  const risk: RiskLevel = (task.risk_level as RiskLevel | undefined) ?? (highRiskTaskPattern.test(`${task.title} ${task.description ?? ''}`) ? 'high' : 'medium')
  return {
    id: task.id,
    title: task.title,
    domain: task.domain ?? taskDomain(task),
    sprint: task.domain ? `${task.domain} Sprint` : taskDomain(task),
    status: taskStatusToCompany(task.status),
    owner: task.owner_agent ?? 'zero-company-operator',
    priority: task.priority === 'critical' ? 1 : task.priority === 'high' ? 2 : task.priority === 'medium' ? 3 : 4,
    due: task.due_at ? formatDateTime(task.due_at) : 'unscheduled',
    risk,
    requiresApproval: task.approval_state === 'pending' || Boolean(task.blocked_reason?.toLowerCase().includes('approval')) || risk === 'high' || risk === 'critical',
    sourceSystem: 'zero',
    nextAction: taskStatusToCompany(task.status) === 'in-progress' && ['critical', 'high'].includes(task.priority),
    zeroStatus: task.status,
    zeroPriority: task.priority,
    zeroDescription: task.description,
    zeroBlockedReason: task.blocked_reason,
    zeroTask: task,
  }
}

function useCompanyTaskCards() {
  const query = useCompanyWorkItems({ limit: 500 })
  const { data: reviewSummary } = useCompanyReviewSummary()
  const reviewsByTask = new Map((reviewSummary?.reviews ?? []).map((review) => [review.task_id, review]))
  const liveTasks = (query.data ?? []).map((task) => {
    const card = zeroTaskToCompanyTask(task)
    card.review = reviewsByTask.get(task.id)
    return card
  })
  return {
    tasks: liveTasks,
    seedPreviewTasks: seedTasks,
    isLoading: query.isLoading,
    error: query.error,
    isLive: liveTasks.length > 0,
    reviewSummary,
  }
}

interface TaskDrawerContextValue {
  openTaskById: (taskId: string) => void
  openTask: (task: CompanyTaskCard) => void
  openTaskForCompletion: (task: CompanyTaskCard) => void
}

const TaskDrawerContext = createContext<TaskDrawerContextValue | null>(null)

function useTaskDrawer() {
  return useContext(TaskDrawerContext)
}

function ClickableTaskCard({ task, editable = false }: { task: CompanyTaskCard; editable?: boolean }) {
  const drawer = useTaskDrawer()
  return (
    <div className="relative">
      <TaskCard task={task} editable={editable} />
      {drawer && (
        <button
          type="button"
          onClick={() => drawer.openTask(task)}
          className="mt-1 inline-flex items-center gap-1 text-[11px] text-blue-300 hover:text-blue-200"
        >
          <ChevronRight className="h-3 w-3" />
          Open walkthrough
        </button>
      )}
    </div>
  )
}

function priorityBadge(priority?: string) {
  if (!priority) return riskClasses.medium
  if (priority === 'critical') return riskClasses.critical
  if (priority === 'high') return riskClasses.high
  if (priority === 'low') return riskClasses.low
  return riskClasses.medium
}

function OperatorTodayTaskList({ tasks }: { tasks: Array<{ id: string; title: string; status: string; priority: string; risk?: string }> }) {
  const drawer = useTaskDrawer()
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      {tasks.map((task) => (
        <button
          key={task.id}
          type="button"
          onClick={() => drawer?.openTaskById(task.id)}
          className="rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-left hover:border-blue-500/50 hover:bg-gray-900"
        >
          <div className="text-sm font-medium text-gray-100">{task.title}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge className={statusBadgeClass(task.status)}>{task.status}</Badge>
            <Badge className="border-gray-700 text-gray-300">{task.priority}</Badge>
            {task.risk === 'high' && <Badge className={riskClasses.high}>approval gate</Badge>}
          </div>
        </button>
      ))}
    </div>
  )
}

function SetupTaskRow({ task }: { task: CompanySetupTaskSummary }) {
  const drawer = useTaskDrawer()
  return (
    <button
      type="button"
      onClick={() => drawer?.openTaskById(task.id)}
      className="flex w-full items-center justify-between gap-3 rounded-md border border-gray-800 bg-gray-950/60 px-3 py-2 text-left text-sm hover:border-blue-500/50 hover:bg-gray-900"
    >
      <span className="min-w-0 flex-1 truncate text-gray-100">{task.title}</span>
      <span className="flex shrink-0 items-center gap-1.5">
        <Badge className="border-gray-700 text-gray-300">{task.domain}</Badge>
        <Badge className={priorityBadge(task.priority)}>{task.priority}</Badge>
        <ChevronRight className="h-3.5 w-3.5 text-gray-500" />
      </span>
    </button>
  )
}

function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium', className)}>
      {children}
    </span>
  )
}

function Panel({ title, icon: Icon, children, action }: {
  title: string
  icon: ElementType
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900/80">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-100">
          <Icon className="h-4 w-4 text-blue-400" />
          {title}
        </h2>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

function formatDateTime(value?: string | null) {
  if (!value) return 'not yet'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

function formatDateInput(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

function statusBadgeClass(status?: string) {
  if (status === 'completed' || status === 'ok' || status === 'done') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed' || status === 'blocked') return 'border-red-500/30 bg-red-500/10 text-red-300'
  if (status === 'pending' || status === 'in_progress') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-gray-700 text-gray-300'
}

function agentStatusClass(status?: string) {
  if (status === 'Running now') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'Waiting on Adam') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'Waiting on approval') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (status === 'Needs review') return 'border-red-500/30 bg-red-500/10 text-red-300'
  if (status === 'Queued') return 'border-sky-500/30 bg-sky-500/10 text-sky-300'
  return 'border-gray-700 text-gray-300'
}

function priorityBadgeClass(priority?: string) {
  if (priority === 'critical') return riskClasses.critical
  if (priority === 'high') return riskClasses.high
  if (priority === 'low') return riskClasses.low
  return riskClasses.medium
}

function TaskCard({ task, editable = false }: { task: CompanyTaskCard; editable?: boolean }) {
  const drawer = useTaskDrawer()
  const updateTask = useUpdateCompanyWorkItem()
  const completeTask = useCompleteCompanyWorkItem()
  const reopenTask = useReopenCompanyWorkItem()
  const duplicateTask = useDuplicateCompanyWorkItem()
  const deleteTask = useDeleteCompanyWorkItem()
  const canEdit = editable && task.sourceSystem === 'zero'
  const zeroStatus = zeroStatusForCompanyTask(task)
  const zeroPriority = task.zeroPriority ?? (task.priority <= 1 ? 'critical' : task.priority === 2 ? 'high' : task.priority === 3 ? 'medium' : 'low')
  const busy = updateTask.isPending || completeTask.isPending || reopenTask.isPending || duplicateTask.isPending || deleteTask.isPending

  const mutateWithToast = (fn: () => void, label: string) => {
    try {
      fn()
      toast({ title: label })
    } catch (error) {
      toast({ title: 'Task update failed', description: error instanceof Error ? error.message : String(error) })
    }
  }

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
      <div className="mb-2 flex items-start justify-between gap-3">
        <h3 className="text-sm font-medium leading-snug text-gray-100">{task.title}</h3>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {task.review && <Badge className={scoreClass(task.review.score)}>{task.review.score}/100</Badge>}
          {task.nextAction && <Badge className="border-blue-500/30 bg-blue-500/10 text-blue-300">next</Badge>}
        </div>
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        <Badge className="border-gray-700 text-gray-300">{task.domain}</Badge>
        <Badge className={riskClasses[task.risk]}>{task.risk}</Badge>
        {task.requiresApproval && <Badge className="border-red-500/30 bg-red-500/10 text-red-300">approval</Badge>}
        {task.review?.recommendation && <Badge className="border-gray-700 text-gray-400">{task.review.recommendation}</Badge>}
        {(() => {
          const outs = (task.zeroTask?.completion_outputs as { outputs?: unknown[] } | undefined)?.outputs ?? []
          return outs.length > 0 ? (
            <Badge className="border-emerald-500/40 bg-emerald-500/10 text-emerald-200">
              <CheckCircle2 className="mr-1 inline h-3 w-3" />
              {outs.length} deliverable{outs.length === 1 ? '' : 's'}
            </Badge>
          ) : null
        })()}
      </div>
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{task.owner}</span>
        <span>{task.due}</span>
      </div>
      {canEdit && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <label className="grid gap-1 text-[11px] text-gray-500">
            Status
            <select
              value={zeroStatus}
              disabled={busy}
              onChange={(event) => mutateWithToast(
                () => updateTask.mutate({ id: task.id, data: { status: event.target.value as ZeroTask['status'] } }),
                'Task status updated',
              )}
              className="h-8 rounded-md border border-gray-800 bg-gray-900 px-2 text-xs text-gray-200 outline-none focus:border-blue-500"
            >
              {zeroStatusOptions.map((item) => (
                <option key={item.value} value={item.value} disabled={task.requiresApproval && item.value === 'done'}>
                  {item.label}{task.requiresApproval && item.value === 'done' ? ' (approval)' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[11px] text-gray-500">
            Priority
            <select
              value={zeroPriority}
              disabled={busy}
              onChange={(event) => mutateWithToast(
                () => updateTask.mutate({ id: task.id, data: { priority: event.target.value as ZeroTask['priority'] } }),
                'Task priority updated',
              )}
              className="h-8 rounded-md border border-gray-800 bg-gray-900 px-2 text-xs text-gray-200 outline-none focus:border-blue-500"
            >
              {priorityOptions.map((priority) => (
                <option key={priority} value={priority}>{priority}</option>
              ))}
            </select>
          </label>
          {task.requiresApproval && (
            <div className="col-span-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
              Done is blocked until the approval gate is cleared.
            </div>
          )}
          {zeroStatus !== 'done' && (
            <div className="col-span-2 flex flex-wrap gap-1.5">
              {zeroStatus === 'in_progress' && (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => updateTask.mutate(
                      { id: task.id, data: { status: 'on_hold' } },
                      {
                        onSuccess: () => toast({ title: 'Task placed on hold' }),
                        onError: (error) => toast({ title: 'Hold failed', description: error.message }),
                      },
                    )}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 text-[11px] text-amber-200 disabled:opacity-50"
                  >
                    <Pause className="h-3 w-3" />
                    Hold
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      const reason = task.zeroBlockedReason?.trim() || window.prompt('Why is this task blocked?', 'Waiting on external dependency') || ''
                      updateTask.mutate(
                        { id: task.id, data: { status: 'blocked', blocked_reason: reason || 'Manual block from board' } },
                        {
                          onSuccess: () => toast({ title: 'Task marked blocked' }),
                          onError: (error) => toast({ title: 'Block failed', description: error.message }),
                        },
                      )
                    }}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-red-500/30 bg-red-500/10 px-2 text-[11px] text-red-300 disabled:opacity-50"
                  >
                    <Ban className="h-3 w-3" />
                    Block
                  </button>
                </>
              )}
              {zeroStatus === 'on_hold' && (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => updateTask.mutate(
                      { id: task.id, data: { status: 'in_progress' } },
                      {
                        onSuccess: () => toast({ title: 'Task resumed' }),
                        onError: (error) => toast({ title: 'Resume failed', description: error.message }),
                      },
                    )}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 text-[11px] text-blue-200 disabled:opacity-50"
                  >
                    <Play className="h-3 w-3" />
                    Resume
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      const reason = task.zeroBlockedReason?.trim() || window.prompt('Why is this task blocked?', 'Waiting on external dependency') || ''
                      updateTask.mutate(
                        { id: task.id, data: { status: 'blocked', blocked_reason: reason || 'Manual block from board' } },
                        {
                          onSuccess: () => toast({ title: 'Task marked blocked' }),
                          onError: (error) => toast({ title: 'Block failed', description: error.message }),
                        },
                      )
                    }}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-red-500/30 bg-red-500/10 px-2 text-[11px] text-red-300 disabled:opacity-50"
                  >
                    <Ban className="h-3 w-3" />
                    Block
                  </button>
                </>
              )}
              {zeroStatus === 'blocked' && (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => updateTask.mutate(
                      { id: task.id, data: { status: 'in_progress', blocked_reason: '' } },
                      {
                        onSuccess: () => toast({ title: 'Task unblocked - back in progress' }),
                        onError: (error) => toast({ title: 'Unblock failed', description: error.message }),
                      },
                    )}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 text-[11px] text-blue-200 disabled:opacity-50"
                  >
                    <Play className="h-3 w-3" />
                    Resume
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => updateTask.mutate(
                      { id: task.id, data: { status: 'on_hold', blocked_reason: '' } },
                      {
                        onSuccess: () => toast({ title: 'Task placed on hold' }),
                        onError: (error) => toast({ title: 'Hold failed', description: error.message }),
                      },
                    )}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 text-[11px] text-amber-200 disabled:opacity-50"
                  >
                    <Pause className="h-3 w-3" />
                    Hold
                  </button>
                </>
              )}
            </div>
          )}
          <div className="col-span-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={busy}
              onClick={() => drawer?.openTaskForCompletion(task)}
              title="Open completion modal to record deliverables"
              className="inline-flex h-7 items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 text-[11px] text-emerald-200 disabled:opacity-50"
            >
              <CheckCircle2 className="h-3 w-3" />
              Complete
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => reopenTask.mutate(task.id, {
                onSuccess: () => toast({ title: 'Task reopened' }),
                onError: (error) => toast({ title: 'Reopen failed', description: error.message }),
              })}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 text-[11px] text-blue-200 disabled:opacity-50"
            >
              <RotateCcw className="h-3 w-3" />
              Reopen
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => duplicateTask.mutate(task.id, {
                onSuccess: () => toast({ title: 'Task duplicated' }),
                onError: (error) => toast({ title: 'Duplicate failed', description: error.message }),
              })}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-gray-700 bg-gray-900 px-2 text-[11px] text-gray-200 disabled:opacity-50"
            >
              <Copy className="h-3 w-3" />
              Copy
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => deleteTask.mutate(task.id, {
                onSuccess: () => toast({ title: 'Task deleted' }),
                onError: (error) => toast({ title: 'Delete failed', description: error.message }),
              })}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-red-500/30 bg-red-500/10 px-2 text-[11px] text-red-200 disabled:opacity-50"
            >
              <Trash2 className="h-3 w-3" />
              Delete
            </button>
          </div>
          {updateTask.error && <div className="col-span-2 text-[11px] text-red-300">{updateTask.error.message}</div>}
        </div>
      )}
    </div>
  )
}

function CompanySubnav({ active }: { active: CompanySection }) {
  const companyLinks = allNavItems.filter((item) => item.group === 'Company OS')

  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {companyLinks.map((item) => {
        const isActive =
          (active === 'overview' && item.href === '/company') ||
          item.href.endsWith(`/${active}`)
        return (
          <Link
            key={item.href}
            to={item.href}
            className={cn(
              'inline-flex h-8 shrink-0 items-center gap-2 rounded-md px-3 text-xs font-medium transition-colors',
              isActive
                ? 'bg-blue-600 text-white'
                : 'border border-gray-800 bg-gray-900 text-gray-400 hover:text-white',
            )}
          >
            <item.icon className="h-3.5 w-3.5" />
            {item.label}
          </Link>
        )
      })}
    </div>
  )
}

function Header({ section }: { section: CompanySection }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-blue-300">ADA AI LLC Company OS</p>
          <h1 className="mt-2 text-3xl font-bold text-white">{sectionLabels[section]}</h1>
          <p className="mt-2 max-w-3xl text-sm text-gray-400">
            Zero is now the single personal and company operating surface. It reads the migrated company docs,
            manages the internal task cockpit, and routes high-risk actions through approval gates.
          </p>
        </div>
        <Link
          to="/ask-zero"
          className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-500"
        >
          <Bot className="h-4 w-4" />
          Ask Zero
        </Link>
      </div>
      <CompanySubnav active={section} />
    </div>
  )
}

function OperatorStatusStrip() {
  const { data: status } = useCompanyOperatorStatus()
  if (!status) return null

  return (
    <div className="grid gap-3 md:grid-cols-4">
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Zero Operator</span>
          <Badge className={status.active ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}>
            {status.active ? 'active' : 'paused'}
          </Badge>
        </div>
        <div className="mt-2 text-xl font-semibold text-white">{status.autonomy}</div>
        <div className="mt-1 text-xs text-gray-500">Heartbeat only {formatDateTime(status.heartbeat?.created_at)}</div>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
        <div className="text-xs text-gray-500">Agent Work Loop</div>
        <div className="mt-2 text-xl font-semibold text-white">{status.latest_agent_work?.status ?? 'not run yet'}</div>
        <div className="mt-1 text-xs text-gray-500">
          Every {status.agent_work_interval_minutes ?? 15} min, last {formatDateTime(status.latest_agent_work?.created_at)}
        </div>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
        <div className="text-xs text-gray-500">Adam Queue</div>
        <div className="mt-2 text-xl font-semibold text-white">{status.counts.questions_open ?? 0} questions</div>
        <div className="mt-1 text-xs text-gray-500">{status.counts.approvals_pending ?? 0} approvals waiting</div>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
        <div className="text-xs text-gray-500">Agents</div>
        <div className="mt-2 text-xl font-semibold text-white">{status.counts.agent_tasks_running ?? 0} running</div>
        <div className="mt-1 text-xs text-gray-500">{status.counts.agent_tasks_queued ?? 0} queued, {status.counts.agent_tasks_needs_review ?? 0} need review</div>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4 md:col-span-2">
        <div className="text-xs text-gray-500">Formation Sprint</div>
        <div className="mt-2 text-xl font-semibold text-white">{status.formation.percent}%</div>
        <div className="mt-2 h-2 rounded-full bg-gray-800">
          <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.min(100, status.formation.percent)}%` }} />
        </div>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4 md:col-span-2">
        <div className="text-xs text-gray-500">Subagents</div>
        <div className="mt-2 text-xl font-semibold text-white">{status.counts.subagents ?? status.subagents.length}</div>
        <div className="mt-1 text-xs text-gray-500">Pending work is queued, not shown as running</div>
      </div>
    </div>
  )
}

function DashboardReviewPanel() {
  const { data: review } = useCompanyReviewSummary()
  const runReview = useRunCompanyOperatorTick()

  if (!review) {
    return (
      <Panel title="Company Dashboard Review" icon={Activity}>
        <div className="text-sm text-gray-400">No dashboard review has been generated yet.</div>
      </Panel>
    )
  }

  const categories = Object.entries(review.category_scores ?? {}).sort((a, b) => a[0].localeCompare(b[0]))
  return (
    <Panel
      title="Company Dashboard Review"
      icon={Activity}
      action={
        <button
          type="button"
          onClick={() => runReview.mutate({ run_type: 'dashboard_review', requested_by: 'dashboard', force: true }, {
            onSuccess: () => toast({ title: 'Company dashboard review completed' }),
            onError: (error) => toast({ title: 'Review failed', description: error.message }),
          })}
          disabled={runReview.isPending}
          className="inline-flex h-8 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-medium text-white disabled:opacity-60"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', runReview.isPending && 'animate-spin')} />
          Run review
        </button>
      }
    >
      <div className="grid gap-3 lg:grid-cols-[220px_1fr]">
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
          <div className="text-xs text-gray-500">Launch Readiness Grade</div>
          <div className="mt-2 flex items-end gap-2">
            <span className="text-4xl font-bold text-white">{review.overall_score}</span>
            <span className="pb-1 text-sm text-gray-500">/100</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-gray-800">
            <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.min(100, review.overall_score)}%` }} />
          </div>
          <div className="mt-3 text-xs text-gray-500">
            Last review {formatDateTime(String(review.last_run?.created_at ?? ''))}
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded-lg bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Reviewed</div>
            <div className="mt-1 text-xl font-semibold text-white">{review.tasks_reviewed}</div>
          </div>
          <div className="rounded-lg bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Critical blockers</div>
            <div className="mt-1 text-xl font-semibold text-red-300">{review.critical_blockers}</div>
          </div>
          <div className="rounded-lg bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Missing info</div>
            <div className="mt-1 text-xl font-semibold text-amber-300">{review.missing_info_count}</div>
          </div>
          <div className="rounded-lg bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Archived</div>
            <div className="mt-1 text-xl font-semibold text-gray-200">{review.archived_count}</div>
          </div>
          <div className="md:col-span-2">
            <div className="mb-2 text-xs font-medium text-gray-400">Category grades</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {categories.slice(0, 8).map(([category, score]) => (
                <div key={category} className="flex items-center justify-between rounded-md border border-gray-800 bg-gray-950/60 px-3 py-2 text-xs">
                  <span className="text-gray-300">{category}</span>
                  <Badge className={scoreClass(score)}>{score}</Badge>
                </div>
              ))}
            </div>
          </div>
          <div className="md:col-span-2">
            <div className="mb-2 text-xs font-medium text-gray-400">Weakest tasks</div>
            <div className="space-y-2">
              {(review.weakest_tasks ?? []).slice(0, 4).map((item) => (
                <div key={String(item.task_id)} className="rounded-md border border-gray-800 bg-gray-950/60 px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-gray-300">{String(item.title ?? item.task_id)}</span>
                    <Badge className={scoreClass(Number(item.score))}>{String(item.score)}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {review.what_zero_did_last?.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs font-medium text-gray-400">What Zero did last</div>
          <div className="grid gap-2 md:grid-cols-2">
            {review.what_zero_did_last.slice(0, 6).map((action, index) => (
              <div key={`${String(action.type)}-${index}`} className="rounded-md border border-gray-800 bg-gray-950/60 p-2 text-xs text-gray-400">
                <span className="font-medium text-gray-200">{String(action.type ?? 'action')}</span>
                {action.title ? ` - ${String(action.title)}` : ''}
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}

function SetupProgressPanel() {
  const { data: progress, isLoading } = useCompanySetupProgress()

  if (isLoading && !progress) {
    return (
      <Panel title="Initial Company Setup" icon={Target}>
        <div className="text-sm text-gray-400">Loading setup progress...</div>
      </Panel>
    )
  }
  if (!progress) {
    return (
      <Panel title="Initial Company Setup" icon={Target}>
        <div className="text-sm text-amber-200">Setup progress unavailable.</div>
      </Panel>
    )
  }

  const domains = Object.entries(progress.by_domain).sort((a, b) => b[1].total - a[1].total)
  return (
    <Panel
      title="Initial Company Setup"
      icon={Target}
      action={
        <span className="text-xs text-gray-400">
          {progress.done} of {progress.total} launch-critical tasks done
        </span>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <div className="rounded-lg border border-blue-500/40 bg-blue-500/5 p-4">
          <div className="text-xs uppercase tracking-wider text-blue-300">Setup Complete</div>
          <div className="mt-2 flex items-end gap-2">
            <span className="text-5xl font-bold text-white">{progress.percent}</span>
            <span className="pb-2 text-base text-gray-400">%</span>
          </div>
          <div className="mt-3 h-3 rounded-full bg-gray-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-400 transition-all"
              style={{ width: `${Math.min(100, progress.percent)}%` }}
            />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <div className="text-base font-semibold text-emerald-300">{progress.done}</div>
              <div className="text-gray-500">done</div>
            </div>
            <div>
              <div className="text-base font-semibold text-amber-300">{progress.in_progress}</div>
              <div className="text-gray-500">active</div>
            </div>
            <div>
              <div className="text-base font-semibold text-red-300">{progress.blocked}</div>
              <div className="text-gray-500">blocked</div>
            </div>
          </div>
        </div>
        <div className="space-y-3">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">By Domain</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {domains.map(([domain, entry]) => (
                <div key={domain} className="rounded-md border border-gray-800 bg-gray-950/60 px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-gray-200">{domain}</span>
                    <span className="text-gray-400">{entry.done}/{entry.total}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-gray-800">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        entry.percent >= 80 ? 'bg-emerald-500' : entry.percent >= 40 ? 'bg-blue-500' : 'bg-amber-500',
                      )}
                      style={{ width: `${entry.percent}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
          {progress.next_unblocked.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
                <Sparkles className="h-3.5 w-3.5 text-blue-400" />
                Do This Next
              </div>
              <div className="space-y-1.5">
                {progress.next_unblocked.slice(0, 5).map((task) => (
                  <SetupTaskRow key={task.id} task={task} />
                ))}
              </div>
            </div>
          )}
          {progress.critical_blocked.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-red-300">
                <AlertTriangle className="h-3.5 w-3.5" />
                Blocked - Needs You
              </div>
              <div className="space-y-1.5">
                {progress.critical_blocked.slice(0, 4).map((task) => (
                  <SetupTaskRow key={task.id} task={task} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Panel>
  )
}

function ZeroCheckinPanel() {
  const { data: checkin, isLoading } = useCompanyProgressCheckin()
  const runCheckin = useRunCompanyProgressCheckin()

  return (
    <Panel
      title="Zero Check-In"
      icon={Bot}
      action={
        <button
          type="button"
          onClick={() =>
            runCheckin.mutate(undefined, {
              onSuccess: () => toast({ title: 'Zero refreshed the check-in' }),
              onError: (error) => toast({ title: 'Check-in failed', description: error.message }),
            })
          }
          disabled={runCheckin.isPending}
          className="inline-flex h-8 items-center gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-medium text-blue-100 disabled:opacity-60"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', runCheckin.isPending && 'animate-spin')} />
          Refresh
        </button>
      }
    >
      {isLoading && !checkin && <div className="text-sm text-gray-400">Loading the latest check-in...</div>}
      {checkin && (
        <div className="space-y-3 text-sm">
          <p className="text-gray-200">{checkin.summary}</p>
          <div className="grid gap-2 md:grid-cols-3">
            <div className="rounded-md border border-gray-800 bg-gray-950/60 p-3">
              <div className="text-xs text-gray-500">Stalled (3+ days)</div>
              <div className="mt-1 text-xl font-semibold text-amber-300">{checkin.stalled_count}</div>
            </div>
            <div className="rounded-md border border-gray-800 bg-gray-950/60 p-3">
              <div className="text-xs text-gray-500">Overdue</div>
              <div className="mt-1 text-xl font-semibold text-red-300">{checkin.overdue_count}</div>
            </div>
            <div className="rounded-md border border-gray-800 bg-gray-950/60 p-3">
              <div className="text-xs text-gray-500">Moved last 24h</div>
              <div className="mt-1 text-xl font-semibold text-emerald-300">{checkin.moved_recently_count}</div>
            </div>
          </div>
          {checkin.stalled.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-amber-300">Stalled</div>
              <div className="space-y-1.5">
                {checkin.stalled.slice(0, 4).map((task) => (
                  <SetupTaskRow
                    key={task.id}
                    task={{ id: task.id, title: task.title, domain: task.domain, status: 'stalled', priority: task.priority }}
                  />
                ))}
              </div>
            </div>
          )}
          {checkin.overdue.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-red-300">Overdue</div>
              <div className="space-y-1.5">
                {checkin.overdue.slice(0, 4).map((task) => (
                  <SetupTaskRow
                    key={task.id}
                    task={{ id: task.id, title: task.title, domain: task.domain, status: 'overdue', priority: task.priority, due_at: task.due_at }}
                  />
                ))}
              </div>
            </div>
          )}
          <div className="text-[11px] text-gray-500">Last check-in {formatDateTime(checkin.computed_at)} - {checkin.requested_by}</div>
        </div>
      )}
    </Panel>
  )
}

function CompanyFactsPanel() {
  const [search, setSearch] = useState('')
  const [domain, setDomain] = useState<string>('all')
  const { data: facts, isLoading } = useCompanyFacts()
  const [revealedFactIds, setRevealedFactIds] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const upsertFact = useUpsertCompanyFact()
  const patchFact = usePatchCompanyFact()
  const deleteFact = useDeleteCompanyFact()

  const filtered = useMemo(() => {
    let rows = facts ?? []
    if (domain !== 'all') rows = rows.filter((f) => (f.domain ?? 'Uncategorized') === domain)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      rows = rows.filter((f) =>
        f.key.toLowerCase().includes(q) || f.label.toLowerCase().includes(q) || f.value.toLowerCase().includes(q),
      )
    }
    return rows
  }, [facts, domain, search])

  const grouped = useMemo(() => {
    const map = new Map<string, CompanyFact[]>()
    for (const fact of filtered) {
      const key = fact.domain ?? 'Uncategorized'
      const list = map.get(key) ?? []
      list.push(fact)
      map.set(key, list)
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]))
  }, [filtered])

  const domainOptions = useMemo(() => {
    const set = new Set<string>()
    for (const fact of facts ?? []) set.add(fact.domain ?? 'Uncategorized')
    return Array.from(set).sort()
  }, [facts])

  const toggleReveal = (id: string) =>
    setRevealedFactIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const startEdit = (fact: CompanyFact) => {
    setEditingId(fact.id)
    setEditValue(fact.value)
  }

  const saveEdit = (fact: CompanyFact) => {
    if (!editValue.trim() || editValue === fact.value) {
      setEditingId(null)
      return
    }
    patchFact.mutate(
      { id: fact.id, data: { value: editValue.trim() } },
      {
        onSuccess: () => {
          toast({ title: 'Fact updated' })
          setEditingId(null)
        },
        onError: (error) => toast({ title: 'Update failed', description: error.message }),
      },
    )
  }

  const handleDelete = (fact: CompanyFact) => {
    if (!window.confirm(`Delete fact "${fact.label}"?`)) return
    deleteFact.mutate(fact.id, {
      onSuccess: () => toast({ title: 'Fact deleted' }),
      onError: (error) => toast({ title: 'Delete failed', description: error.message }),
    })
  }

  return (
    <Panel
      title="Company Facts"
      icon={KeyRound}
      action={<span className="text-xs text-gray-500">{(facts ?? []).length} recorded</span>}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-500" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search facts"
            className="h-8 w-full rounded-md border border-gray-800 bg-gray-950 pl-7 pr-3 text-xs text-gray-200 outline-none focus:border-blue-500"
          />
        </div>
        <select
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          className="h-8 rounded-md border border-gray-800 bg-gray-950 px-2 text-xs text-gray-200"
        >
          <option value="all">All domains</option>
          {domainOptions.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <NewFactInline onCreated={() => setSearch('')} upsert={upsertFact} />
      </div>
      {isLoading ? (
        <div className="text-xs text-gray-500">Loading facts...</div>
      ) : grouped.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-800 p-4 text-xs text-gray-400">
          No company facts yet. Complete a setup task with structured outputs to populate this registry.
        </div>
      ) : (
        <div className="space-y-4">
          {grouped.map(([groupDomain, items]) => (
            <div key={groupDomain}>
              <div className="mb-2 text-xs uppercase tracking-wider text-blue-300">{groupDomain}</div>
              <div className="grid gap-2 md:grid-cols-2">
                {items.map((fact) => {
                  const revealed = revealedFactIds.has(fact.id)
                  const displayValue = fact.sensitive && !revealed ? maskSensitive(fact.value) : fact.value
                  const isEditing = editingId === fact.id
                  return (
                    <div key={fact.id} className="rounded-md border border-gray-800 bg-gray-950/60 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-gray-100">{fact.label}</div>
                          <div className="mt-0.5 text-[10px] uppercase tracking-wider text-gray-500">
                            key: <code className="text-gray-400">{fact.key}</code>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          {fact.sensitive && (
                            <button
                              type="button"
                              onClick={() => toggleReveal(fact.id)}
                              title={revealed ? 'Hide' : 'Reveal'}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-700 text-gray-300 hover:text-white"
                            >
                              {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => (isEditing ? saveEdit(fact) : startEdit(fact))}
                            title={isEditing ? 'Save' : 'Edit'}
                            className="inline-flex h-7 items-center gap-1 rounded-md border border-gray-700 px-2 text-[11px] text-gray-300 hover:text-white"
                          >
                            {isEditing ? 'Save' : 'Edit'}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(fact)}
                            title="Delete"
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-700 text-gray-400 hover:border-red-500/40 hover:text-red-300"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                      {isEditing ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={(event) => setEditValue(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') saveEdit(fact)
                            else if (event.key === 'Escape') setEditingId(null)
                          }}
                          className="mt-2 h-9 w-full rounded-md border border-gray-800 bg-gray-950 px-3 text-sm text-gray-100"
                        />
                      ) : (
                        <div className="mt-2 break-all text-sm text-gray-100">{displayValue}</div>
                      )}
                      {fact.evidence_url && (
                        <a
                          href={fact.evidence_url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-flex items-center gap-1 text-[11px] text-blue-300 hover:text-blue-200"
                        >
                          <ExternalLink className="h-3 w-3" /> evidence
                        </a>
                      )}
                      {fact.source_task_id && (
                        <div className="mt-1 text-[10px] text-gray-500">from task <code>{fact.source_task_id}</code></div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function NewFactInline({ onCreated, upsert }: { onCreated: () => void; upsert: ReturnType<typeof useUpsertCompanyFact> }) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [value, setValue] = useState('')
  const [factDomain, setFactDomain] = useState('')
  const [sensitive, setSensitive] = useState(false)

  const reset = () => {
    setKey(''); setLabel(''); setValue(''); setFactDomain(''); setSensitive(false)
  }

  const submit = () => {
    if (!key.trim() || !label.trim() || !value.trim()) {
      toast({ title: 'Need key, label, and value' })
      return
    }
    upsert.mutate(
      {
        key: key.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'),
        label: label.trim(),
        value: value.trim(),
        domain: factDomain.trim() || undefined,
        sensitive,
      },
      {
        onSuccess: () => {
          toast({ title: 'Fact recorded' })
          reset()
          setOpen(false)
          onCreated()
        },
        onError: (error) => toast({ title: 'Save failed', description: error.message }),
      },
    )
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex h-8 items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 text-xs text-blue-200"
      >
        + Add fact
      </button>
    )
  }
  return (
    <div className="flex w-full flex-wrap items-center gap-2 rounded-md border border-gray-800 bg-gray-900/60 p-2">
      <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="key" className="h-8 w-28 rounded-md border border-gray-800 bg-gray-950 px-2 text-xs text-gray-200" />
      <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="label" className="h-8 w-36 rounded-md border border-gray-800 bg-gray-950 px-2 text-xs text-gray-200" />
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" className="h-8 w-40 rounded-md border border-gray-800 bg-gray-950 px-2 text-xs text-gray-200" />
      <input value={factDomain} onChange={(e) => setFactDomain(e.target.value)} placeholder="domain" className="h-8 w-28 rounded-md border border-gray-800 bg-gray-950 px-2 text-xs text-gray-200" />
      <label className="flex items-center gap-1 text-[11px] text-gray-300">
        <input type="checkbox" checked={sensitive} onChange={(e) => setSensitive(e.target.checked)} />
        sensitive
      </label>
      <button type="button" onClick={submit} disabled={upsert.isPending} className="inline-flex h-8 items-center rounded-md bg-emerald-600 px-3 text-xs text-white disabled:opacity-60">Save</button>
      <button type="button" onClick={() => { reset(); setOpen(false) }} className="inline-flex h-8 items-center rounded-md border border-gray-700 px-3 text-xs text-gray-300">Cancel</button>
    </div>
  )
}

function OverviewSection() {
  const { tasks, isLive } = useCompanyTaskCards()
  const { data: liveApprovals, isLoading: approvalsLoading } = useAgentApprovals('pending', 4)
  const nextTasks = tasks.filter((task) => task.nextAction)
  const pendingApprovals = approvals.filter((approval) => approval.status === 'pending').slice(0, 4)
  const hasLiveApprovals = Boolean(liveApprovals?.length)

  return (
    <div className="space-y-6">
      <SetupProgressPanel />
      <OperatorStatusStrip />
      <ZeroCheckinPanel />
      <DashboardReviewPanel />
      <CompanyFactsPanel />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {companyKpis.map((kpi) => (
          <div key={kpi.label} className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
            <div className="text-xs text-gray-500">{kpi.label}</div>
            <div className="mt-2 text-2xl font-semibold text-white">{kpi.value}</div>
            <div className="mt-1 text-xs text-gray-400">{kpi.detail}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.9fr]">
        <Panel title={isLive ? 'Next Tasks - Zero DB' : 'Next Tasks - Seed'} icon={ClipboardList} action={<Link to="/company/tasks" className="text-xs text-blue-300">Open tasks</Link>}>
          <div className="grid gap-3 md:grid-cols-2">
            {nextTasks.map((task) => <ClickableTaskCard key={task.id} task={task} />)}
          </div>
        </Panel>
        <Panel title="Approvals Waiting" icon={ShieldCheck} action={<Link to="/company/approvals" className="text-xs text-blue-300">Review</Link>}>
          <div className="space-y-3">
            {approvalsLoading && <div className="text-xs text-gray-500">Loading live approval gates...</div>}
            {hasLiveApprovals ? liveApprovals?.map((approval) => (
              <div key={approval.id} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
                <div className="text-sm font-medium text-gray-100">{approval.summary}</div>
                <div className="mt-2 flex items-center justify-between gap-3 text-xs text-gray-500">
                  <span className="truncate">{approval.requested_by}</span>
                  <Badge className={approval.tier === 'financial' ? riskClasses.critical : riskClasses.high}>{approval.tier}</Badge>
                </div>
              </div>
            )) : pendingApprovals.map((approval) => (
              <div key={approval.id} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
                <div className="text-sm font-medium text-gray-100">{approval.action}</div>
                <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                  <span>{approval.owner}</span>
                  <Badge className={riskClasses[approval.risk]}>{approval.risk}</Badge>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Zero Company Brief" icon={Bot}>
        <div className="grid gap-3 md:grid-cols-3">
          {[
            'What should I work on today?',
            'What is blocked?',
            'Prepare a CPA readiness summary.',
            'What subscriptions or assets need review?',
            'What approvals need me?',
            'Prepare the weekly company brief.',
          ].map((prompt) => (
            <Link
              key={prompt}
              to="/ask-zero"
              className="rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-sm text-gray-300 hover:border-blue-500/60 hover:text-white"
            >
              {prompt}
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  )
}

function OperatorSection() {
  const { data: status, isLoading } = useCompanyOperatorStatus()
  const { data: today } = useCompanyOperatorToday()
  const { data: overnight } = useCompanyOperatorOvernight()
  const { data: runs } = useCompanyOperatorRuns(undefined, 12)
  const runTick = useRunCompanyOperatorTick()
  const generateReport = useGenerateCompanyOperatorReport()
  const pauseOperator = usePauseCompanyOperator()
  const resumeOperator = useResumeCompanyOperator()

  if (isLoading && !status) {
    return <Panel title="Zero Company Operator" icon={Activity}><div className="text-sm text-gray-400">Loading operator state...</div></Panel>
  }

  if (!status) {
    return (
      <Panel title="Zero Company Operator" icon={Activity}>
        <div className="text-sm text-red-300">The operator API did not return a status yet.</div>
      </Panel>
    )
  }

  const latestOvernight = overnight?.latest ?? status.latest_overnight
  const latestAgentWork = status.latest_agent_work
  const topToday = today ?? status.today

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">Heartbeat</span>
            <Badge className={status.active ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}>
              {status.active ? 'active' : 'paused'}
            </Badge>
          </div>
          <div className="mt-2 text-lg font-semibold text-white">{formatDateTime(status.heartbeat?.created_at)}</div>
          <div className="mt-1 text-xs text-gray-500">{status.autonomy}</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
          <div className="text-xs text-gray-500">Agent Work</div>
          <div className="mt-2 text-lg font-semibold text-white">{latestAgentWork?.status ?? 'not run yet'}</div>
          <div className="mt-1 text-xs text-gray-500">{status.counts.agent_tasks_running ?? 0} running, {status.counts.agent_tasks_queued ?? 0} queued</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
          <div className="text-xs text-gray-500">Formation</div>
          <div className="mt-2 text-lg font-semibold text-white">{status.formation.percent}% complete</div>
          <div className="mt-1 text-xs text-gray-500">{status.formation.ready} ready, {status.formation.blocked} gated</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
          <div className="text-xs text-gray-500">Adam Queue</div>
          <div className="mt-2 text-lg font-semibold text-white">{status.counts.questions_open ?? 0} questions</div>
          <div className="mt-1 text-xs text-gray-500">{status.counts.approvals_pending ?? 0} approvals waiting</div>
        </div>
      </div>
      <DashboardReviewPanel />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => runTick.mutate({ run_type: 'agent_work', requested_by: 'dashboard', force: true })}
          disabled={runTick.isPending}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-60"
        >
          <RefreshCw className={cn('h-4 w-4', runTick.isPending && 'animate-spin')} />
          Run Agent Work Now
        </button>
        <button
          type="button"
          onClick={() => runTick.mutate({ run_type: 'manual', requested_by: 'dashboard', force: true })}
          disabled={runTick.isPending}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm font-medium text-gray-200 hover:text-white disabled:opacity-60"
        >
          <Activity className="h-4 w-4" />
          Run Full Operator
        </button>
        <button
          type="button"
          onClick={() => generateReport.mutate({ report_type: 'morning_brief', requested_by: 'dashboard' })}
          disabled={generateReport.isPending}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm font-medium text-gray-200 hover:text-white disabled:opacity-60"
        >
          <FileText className="h-4 w-4" />
          Generate Brief
        </button>
        {status.paused ? (
          <button
            type="button"
            onClick={() => resumeOperator.mutate()}
            disabled={resumeOperator.isPending}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 text-sm font-medium text-emerald-200 disabled:opacity-60"
          >
            <PlayCircle className="h-4 w-4" />
            Resume Overnight
          </button>
        ) : (
          <button
            type="button"
            onClick={() => pauseOperator.mutate()}
            disabled={pauseOperator.isPending}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 text-sm font-medium text-amber-200 disabled:opacity-60"
          >
            <PauseCircle className="h-4 w-4" />
            Pause Overnight
          </button>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Panel title="What Adam Should Do Today" icon={ClipboardList} action={<Link to="/company/tasks" className="text-xs text-blue-300">Edit board</Link>}>
          <p className="text-sm text-gray-200">{topToday.answer}</p>
          <OperatorTodayTaskList tasks={topToday.next_tasks.slice(0, 4)} />
        </Panel>
        <Panel title="Overnight Report" icon={Clock3}>
          <div className="text-sm text-gray-200">{latestOvernight?.summary ?? 'No overnight report has run yet.'}</div>
          <div className="mt-3 space-y-2">
            {((latestOvernight?.actions as Array<Record<string, unknown>> | undefined) ?? []).slice(0, 4).map((action, index) => (
              <div key={`${action.type}-${index}`} className="rounded-md bg-gray-950/60 p-2 text-xs text-gray-400">
                {String(action.type ?? 'action')} {action.title ? `- ${String(action.title)}` : ''}
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Active Subagents" icon={Bot}>
          <div className="grid gap-3 md:grid-cols-2">
            {status.subagents.map((agent) => (
              <div key={agent.id} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-gray-100">{agent.name}</div>
                    <div className="mt-1 text-xs text-gray-500">{agent.autonomy} - {agent.total_tasks} tasks</div>
                  </div>
                  <Badge className={agentStatusClass(agent.agent_status)}>
                    {agent.agent_status ?? (agent.active_tasks > 0 ? 'Running now' : 'Idle')}
                  </Badge>
                </div>
                <div className="mt-3 text-xs text-gray-400">{agent.current_assignment ?? agent.idle_reason ?? 'No active assignment'}</div>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                  <Badge className="border-gray-700 text-gray-300">{agent.running_tasks ?? agent.active_tasks} running</Badge>
                  <Badge className="border-gray-700 text-gray-300">{agent.queued_tasks ?? 0} queued</Badge>
                  <Badge className="border-blue-500/30 bg-blue-500/10 text-blue-300">{agent.question_count ?? 0} questions</Badge>
                  <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-300">{agent.approval_count ?? 0} approvals</Badge>
                </div>
                {agent.last_output && <div className="mt-2 rounded-md bg-gray-900 p-2 text-xs text-gray-500">{agent.last_output}</div>}
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Questions, Approvals, And Blockers" icon={Inbox} action={<Link to="/company/inbox" className="text-xs text-blue-300">Open inbox</Link>}>
          <div className="space-y-3">
            {[...(status.questions ?? []).slice(0, 3).map((question) => ({
              id: question.id,
              label: question.question,
              meta: `${question.asked_by_agent} - ${formatDateTime(question.created_at)}`,
              status: question.status,
            })), ...status.approvals.slice(0, 3).map((approval) => ({
              id: approval.id,
              label: approval.summary,
              meta: `${approval.tier} - ${formatDateTime(approval.expires_at)}`,
              status: approval.status,
            })), ...status.blocked_tasks.slice(0, 3).map((task) => ({
              id: task.id,
              label: task.title,
              meta: task.blocked_reason ?? 'blocked',
              status: task.status,
            }))].map((item) => (
              <div key={item.id} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
                <div className="text-sm font-medium text-gray-100">{item.label}</div>
                <div className="mt-2 flex items-center justify-between gap-3 text-xs text-gray-500">
                  <span className="truncate">{item.meta}</span>
                  <Badge className={statusBadgeClass(item.status)}>{item.status}</Badge>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Recent Operator Runs" icon={Activity}>
        <div className="grid gap-2">
          {(runs ?? []).map((run) => (
            <div key={run.id ?? `${run.run_type}-${run.created_at}`} className="grid gap-2 rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-sm md:grid-cols-[140px_110px_1fr_140px] md:items-center">
              <span className="font-medium text-gray-100">{run.run_type}</span>
              <Badge className={statusBadgeClass(run.status)}>{run.status}</Badge>
              <span className="text-gray-400">{run.summary ?? 'No summary'}</span>
              <span className="text-xs text-gray-500">{formatDateTime(run.created_at)}</span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}

type WalkthroughT = NonNullable<CompanyWorkItemReview['walkthrough']>

function TaskWalkthroughSection({ walkthrough }: { walkthrough: WalkthroughT }) {
  return (
    <section className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-blue-300">
            <ListChecks className="h-4 w-4" />
            How To Complete This
          </div>
          <h3 className="mt-1 text-base font-semibold text-white">{walkthrough.title}</h3>
        </div>
        <div className="flex flex-col items-end gap-1 text-[11px] text-gray-400">
          {walkthrough.time_required && <Badge className="border-gray-700 text-gray-300">{walkthrough.time_required}</Badge>}
          {walkthrough.cost && <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-200">{walkthrough.cost}</Badge>}
        </div>
      </div>
      {walkthrough.best_time && (
        <div className="mt-2 text-xs text-blue-200">Best time: {walkthrough.best_time}</div>
      )}
      {walkthrough.prerequisites && walkthrough.prerequisites.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-amber-200">Before you start</div>
          <ul className="space-y-1 text-sm text-gray-200">
            {walkthrough.prerequisites.map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4 space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-gray-400">Step-by-step</div>
        {walkthrough.steps.map((step, index) => (
          <div key={`${step.title}-${index}`} className="rounded-md border border-gray-800 bg-gray-950/80 p-3 text-sm">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1 space-y-2">
                <div className="text-base font-medium text-gray-100">{step.title}</div>
                <div className="text-sm leading-relaxed text-gray-300 whitespace-pre-wrap">{step.instruction}</div>
                {step.url && (
                  <a
                    href={step.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-200 hover:bg-blue-500/20"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    {step.url.length > 60 ? `${step.url.slice(0, 60)}...` : step.url}
                  </a>
                )}
                {step.button && (
                  <div className="text-xs text-gray-400">
                    Click the button labeled <span className="rounded-md bg-gray-800 px-2 py-0.5 text-gray-100">{step.button}</span>
                  </div>
                )}
                {step.fields && step.fields.length > 0 && (
                  <div className="rounded-md border border-gray-800 bg-gray-900/60 p-2.5">
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-500">Fill in</div>
                    <div className="space-y-1">
                      {step.fields.map((field) => (
                        <div key={field.label} className="grid grid-cols-[160px_1fr] gap-2 text-xs">
                          <span className="text-gray-400">{field.label}</span>
                          <span className="text-gray-100">{field.value ?? '(your value)'}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {step.gotcha && (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-100">
                    <span className="font-semibold">Gotcha:</span> {step.gotcha}
                  </div>
                )}
                {step.completion_check && (
                  <div className="flex items-start gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs text-emerald-200">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{step.completion_check}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {walkthrough.evidence_to_archive && walkthrough.evidence_to_archive.length > 0 && (
          <div className="rounded-md border border-gray-800 bg-gray-900/40 p-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-gray-400">Evidence to archive</div>
            <ul className="mt-2 space-y-1 text-sm text-gray-300">
              {walkthrough.evidence_to_archive.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-500" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {walkthrough.what_this_unlocks && walkthrough.what_this_unlocks.length > 0 && (
          <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-emerald-300">What this unlocks</div>
            <ul className="mt-2 space-y-1 text-sm text-emerald-100/90">
              {walkthrough.what_this_unlocks.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {walkthrough.common_mistakes && walkthrough.common_mistakes.length > 0 && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 md:col-span-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-amber-300">Common mistakes</div>
            <ul className="mt-2 space-y-1 text-sm text-amber-100/90">
              {walkthrough.common_mistakes.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {walkthrough.if_something_goes_wrong && walkthrough.if_something_goes_wrong.length > 0 && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 md:col-span-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-red-300">If something goes wrong</div>
            <ul className="mt-2 space-y-1 text-sm text-red-100/90">
              {walkthrough.if_something_goes_wrong.map((item) => (
                <li key={item} className="flex items-start gap-2">
                  <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}

type CompletionVerdictT = NonNullable<CompanyWorkItemReview['completion_review']>

function CompletionVerdictPanel({ verdict }: { verdict: CompletionVerdictT }) {
  return (
    <section className="rounded-lg border border-purple-500/30 bg-purple-500/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-purple-300">
            <Bot className="h-4 w-4" />
            Zero's Completion Review
          </div>
          <p className="mt-2 text-sm text-gray-200">{verdict.summary}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge className={scoreClass(verdict.quality_score)}>{verdict.quality_score}/100</Badge>
          <Badge className={verdict.looks_complete ? riskClasses.low : riskClasses.high}>
            {verdict.looks_complete ? 'looks complete' : 'incomplete'}
          </Badge>
          {verdict.fallback && <Badge className="border-gray-700 text-gray-400">fallback</Badge>}
        </div>
      </div>
      {verdict.concerns.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-amber-300">Concerns</div>
          <ul className="space-y-1 text-sm text-amber-100/90">
            {verdict.concerns.map((item, index) => (
              <li key={`${item}-${index}`} className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {verdict.missing_followups.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-blue-300">Follow-up tasks Zero recommends</div>
          <div className="space-y-2">
            {verdict.missing_followups.map((item, index) => (
              <div key={`${item.title}-${index}`} className="rounded-md border border-gray-800 bg-gray-950/60 p-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-medium text-gray-100">{item.title}</div>
                  <div className="flex shrink-0 gap-1">
                    <Badge className="border-gray-700 text-gray-300">{item.domain}</Badge>
                    <Badge className={priorityBadge(item.priority)}>{item.priority}</Badge>
                  </div>
                </div>
                <div className="mt-1 text-xs text-gray-400">{item.why}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {verdict.created_followups && verdict.created_followups.length > 0 && (
        <div className="mt-3 rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs text-emerald-200">
          Zero auto-created {verdict.created_followups.length} follow-up task(s): {verdict.created_followups.map((f) => f.title).join('; ')}
        </div>
      )}
      {verdict.infrastructure_suggestions.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-purple-300">
            <Lightbulb className="h-3.5 w-3.5" />
            Infrastructure suggestions for the command center
          </div>
          <div className="space-y-2">
            {verdict.infrastructure_suggestions.map((item, index) => (
              <div key={`${item.name}-${index}`} className="rounded-md border border-gray-800 bg-gray-950/60 p-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-medium text-gray-100">{item.name}</div>
                  <Badge className="border-purple-500/30 bg-purple-500/10 text-purple-200">{item.surface}</Badge>
                </div>
                <div className="mt-1 text-xs text-gray-400">{item.rationale}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {verdict.reviewed_at && (
        <div className="mt-3 text-[11px] text-gray-500">
          Reviewed {formatDateTime(verdict.reviewed_at)} - {verdict.reviewed_by ?? 'zero-completion-review'}
        </div>
      )}
    </section>
  )
}

function TaskDetailDrawer({ task, autoCompleteToken, onClose }: { task: CompanyTaskCard | null; autoCompleteToken?: number; onClose: () => void }) {
  const updateTask = useUpdateCompanyWorkItem()
  const completeTask = useCompleteCompanyWorkItem()
  const reopenTask = useReopenCompanyWorkItem()
  const runCompletionReview = useRunCompanyCompletionReview()
  const { data: events } = useCompanyTaskEvents(task?.id)
  const { data: review } = useCompanyTaskReview(task?.id)
  const { data: taskQuestions } = useCompanyAgentQuestions('open', task?.id, undefined, 10)
  const [completionVerdict, setCompletionVerdict] = useState<CompletionVerdictT | null>(null)
  const [completionModalOpen, setCompletionModalOpen] = useState(false)
  const lastConsumedToken = useRef(0)

  useEffect(() => {
    if (autoCompleteToken && autoCompleteToken !== lastConsumedToken.current && task) {
      lastConsumedToken.current = autoCompleteToken
      setCompletionModalOpen(true)
    }
  }, [autoCompleteToken, task?.id])

  if (!task?.zeroTask) return null
  const zero = task.zeroTask
  const busy = updateTask.isPending || completeTask.isPending || reopenTask.isPending
  const walkthrough = review?.walkthrough as WalkthroughT | undefined
  const completionFields: WalkthroughCompletionField[] = (walkthrough as unknown as { completion_fields?: WalkthroughCompletionField[] } | undefined)?.completion_fields ?? []
  const completionOutputsRecord = (zero.completion_outputs ?? {}) as { outputs?: CompletionOutput[]; note?: string; recorded_at?: string; recorded_by?: string }
  const lastCompletionReview: CompletionVerdictT | null =
    (review?.completion_review as CompletionVerdictT | null | undefined) ?? completionVerdict
  const update = (data: ZeroTaskUpdate) => {
    updateTask.mutate(
      { id: task.id, data },
      {
        onSuccess: () => toast({ title: 'Task saved' }),
        onError: (error) => toast({ title: 'Task save failed', description: error.message }),
      },
    )
  }

  const submitCompletion = (outputs: CompletionOutput[], note: string) => {
    completeTask.mutate(
      { id: task.id, completion_note: note || undefined, outputs, actor: 'dashboard' },
      {
        onSuccess: (result) => {
          setCompletionModalOpen(false)
          toast({
            title: result.status === 'blocked' ? 'Approval gate queued' : 'Task completed - running Zero review',
            description: result.blocked_reason,
          })
          if (result.status === 'done') {
            runCompletionReview.mutate(
              { id: task.id, auto_create_followups: true },
              {
                onSuccess: (verdict) => {
                  setCompletionVerdict(verdict as unknown as CompletionVerdictT)
                  toast({
                    title: 'Zero completion review done',
                    description: verdict.summary?.slice(0, 140),
                  })
                },
                onError: (error) => toast({ title: 'Completion review failed', description: error.message }),
              },
            )
          }
        },
        onError: (error) => toast({ title: 'Complete failed', description: error.message }),
      },
    )
  }

  const handleCompleteAndReview = () => setCompletionModalOpen(true)

  return (
    <div className="fixed inset-0 z-50 bg-black/60">
      <aside className="ml-auto flex h-full w-full max-w-3xl flex-col border-l border-gray-800 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-blue-300">Company Work Item</div>
            <h2 className="mt-2 text-xl font-semibold text-white">{task.title}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-gray-400 hover:bg-gray-900 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {walkthrough && <TaskWalkthroughSection walkthrough={walkthrough} />}
          <TaskCompletionOutputsSection outputs={completionOutputsRecord} />
          <label className="grid gap-1 text-xs text-gray-500">
            Title
            <input
              defaultValue={zero.title}
              onBlur={(event) => event.target.value !== zero.title && update({ title: event.target.value })}
              className="h-10 rounded-md border border-gray-800 bg-gray-900 px-3 text-base text-gray-100 outline-none focus:border-blue-500"
            />
          </label>
          <label className="grid gap-1 text-xs text-gray-500">
            Description
            <textarea
              defaultValue={zero.description ?? ''}
              onBlur={(event) => event.target.value !== (zero.description ?? '') && update({ description: event.target.value })}
              className="min-h-72 rounded-md border border-gray-800 bg-gray-900 px-4 py-3 text-base leading-relaxed text-gray-100 outline-none focus:border-blue-500"
            />
          </label>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-xs text-gray-500">
              Status
              <select value={zero.status} disabled={busy} onChange={(event) => update({ status: event.target.value as ZeroTask['status'] })} className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100">
                {zeroStatusOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-gray-500">
              Priority
              <select value={zero.priority} disabled={busy} onChange={(event) => update({ priority: event.target.value as ZeroTask['priority'] })} className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100">
                {priorityOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-gray-500">
              Domain
              <select value={zero.domain ?? 'Operations'} disabled={busy} onChange={(event) => update({ domain: event.target.value })} className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100">
                {companyDomains.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-gray-500">
              Owner Agent
              <select value={zero.owner_agent ?? 'zero-company-operator'} disabled={busy} onChange={(event) => update({ owner_agent: event.target.value })} className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100">
                {ownerAgents.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-gray-500">
              Due Date
              <input
                type="date"
                value={formatDateInput(zero.due_at)}
                disabled={busy}
                onChange={(event) => update({ due_at: event.target.value ? `${event.target.value}T12:00:00Z` : undefined })}
                className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100"
              />
            </label>
            <label className="grid gap-1 text-xs text-gray-500">
              Risk
              <select value={zero.risk_level ?? 'medium'} disabled={busy} onChange={(event) => update({ risk_level: event.target.value as ZeroTask['risk_level'] })} className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100">
                {['low', 'medium', 'high', 'critical'].map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
          </div>
          {zero.blocked_reason && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
              {zero.blocked_reason}
            </div>
          )}
          {review && (
            <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-gray-100">Zero Review</h3>
                <div className="flex gap-2">
                  <Badge className={scoreClass(review.score)}>{review.score}/100</Badge>
                  <Badge className="border-gray-700 text-gray-300">{review.recommendation}</Badge>
                </div>
              </div>
              {review.summary && <p className="mt-2 text-sm text-gray-300">{review.summary}</p>}
              {review.missing_info.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-xs font-medium text-amber-200">Missing information</div>
                  <div className="flex flex-wrap gap-1.5">
                    {review.missing_info.map((item) => <Badge key={item} className="border-amber-500/30 bg-amber-500/10 text-amber-200">{item.replace(/_/g, ' ')}</Badge>)}
                  </div>
                </div>
              )}
            </section>
          )}
          {review?.action_steps?.length ? (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-gray-100">Steps To Completion</h3>
              <ol className="space-y-2">
                {review.action_steps.map((step, index) => (
                  <li key={`${step}-${index}`} className="rounded-md border border-gray-800 bg-gray-900/60 p-2 text-sm text-gray-300">
                    <span className="mr-2 text-xs text-blue-300">{index + 1}</span>{step}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {review?.acceptance_criteria?.length ? (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-gray-100">Acceptance Criteria</h3>
              <div className="space-y-2">
                {review.acceptance_criteria.map((item) => (
                  <div key={item} className="flex gap-2 rounded-md border border-gray-800 bg-gray-900/60 p-2 text-sm text-gray-300">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {review?.automation_plan && Object.keys(review.automation_plan).length > 0 && (
            <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
              <h3 className="text-sm font-semibold text-gray-100">Automation And Guardrails</h3>
              <div className="mt-2 grid gap-2 text-xs text-gray-400 md:grid-cols-2">
                <div>Owner: <span className="text-gray-200">{String(review.automation_plan.owner_agent ?? zero.owner_agent ?? 'zero-company-operator')}</span></div>
                <div>Scope: <span className="text-gray-200">{String(review.automation_plan.scope ?? 'internal preparation')}</span></div>
              </div>
              <div className="mt-2 text-xs text-gray-500">
                Approval remains required for filings, purchases, tax/legal decisions, client or public messages, and account changes.
              </div>
            </section>
          )}
          {taskQuestions?.length ? (
            <section className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-blue-100">
                <HelpCircle className="h-4 w-4" />
                Agent Questions
              </h3>
              <div className="mt-2 space-y-2">
                {taskQuestions.map((question) => (
                  <div key={question.id} className="rounded-md border border-blue-500/20 bg-gray-950/60 p-2 text-sm text-gray-200">
                    <div>{question.question}</div>
                    <div className="mt-1 text-xs text-blue-200">{question.asked_by_agent} - {formatDateTime(question.created_at)}</div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {(review?.source_links?.length || zero.links?.length) ? (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-gray-100">Evidence And Sources</h3>
              <div className="space-y-2">
                {[...(review?.source_links ?? []), ...(zero.links ?? [])].map((link, index) => {
                  const url = String(link.url ?? '')
                  const label = String((link.label ?? link.title ?? url) || 'Source')
                  return (
                    <a
                      key={`${label}-${index}`}
                      href={url || undefined}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-between gap-3 rounded-md border border-gray-800 bg-gray-900/60 p-2 text-xs text-blue-300 hover:border-blue-500/50"
                    >
                      <span>{label}</span>
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )
                })}
              </div>
            </section>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || runCompletionReview.isPending}
              onClick={handleCompleteAndReview}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-emerald-600 px-4 text-sm font-medium text-white disabled:opacity-60"
            >
              <CheckCircle2 className="h-4 w-4" />
              Complete + Zero Review
            </button>
            <button
              type="button"
              disabled={runCompletionReview.isPending}
              onClick={() => runCompletionReview.mutate(
                { id: task.id, auto_create_followups: true },
                {
                  onSuccess: (verdict) => {
                    setCompletionVerdict(verdict as unknown as CompletionVerdictT)
                    toast({ title: 'Zero completion review done' })
                  },
                  onError: (error) => toast({ title: 'Review failed', description: error.message }),
                },
              )}
              className="inline-flex h-10 items-center gap-2 rounded-md border border-blue-500/40 bg-blue-500/10 px-3 text-sm font-medium text-blue-100 disabled:opacity-60"
            >
              <Sparkles className={cn('h-4 w-4', runCompletionReview.isPending && 'animate-pulse')} />
              Re-run Zero Review
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => reopenTask.mutate(task.id, {
                onSuccess: () => toast({ title: 'Task reopened' }),
                onError: (error) => toast({ title: 'Reopen failed', description: error.message }),
              })}
              className="inline-flex h-10 items-center gap-2 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm font-medium text-gray-200 disabled:opacity-60"
            >
              <RotateCcw className="h-4 w-4" />
              Reopen
            </button>
          </div>
          {lastCompletionReview && <CompletionVerdictPanel verdict={lastCompletionReview} />}
          <TaskNotesPanel taskId={task.id} scope="company" />
          <section>
            <h3 className="mb-2 text-sm font-semibold text-gray-100">Audit Trail</h3>
            <div className="space-y-2">
              {(events ?? []).filter((e) => e.event_type !== 'note').slice(0, 12).map((event) => (
                <div key={event.id} className="rounded-md border border-gray-800 bg-gray-900/60 p-2 text-xs text-gray-400">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-gray-200">{event.event_type}</span>
                    <span>{formatDateTime(event.created_at)}</span>
                  </div>
                  {event.summary && <div className="mt-1">{event.summary}</div>}
                  <div className="mt-1 text-gray-600">{event.actor}</div>
                </div>
              ))}
              {!(events ?? []).filter((e) => e.event_type !== 'note').length && (
                <div className="text-xs text-gray-500">No task events recorded yet.</div>
              )}
            </div>
          </section>
        </div>
      </aside>
      {completionModalOpen && (
        <TaskCompletionModal
          taskTitle={zero.title}
          fields={completionFields}
          existingOutputs={completionOutputsRecord.outputs ?? []}
          existingNote={completionOutputsRecord.note ?? ''}
          taskDomain={zero.domain ?? null}
          submitting={completeTask.isPending}
          onCancel={() => setCompletionModalOpen(false)}
          onSubmit={submitCompletion}
        />
      )}
    </div>
  )
}

function TaskCompletionOutputsSection({
  outputs,
}: {
  outputs: { outputs?: CompletionOutput[]; note?: string; recorded_at?: string; recorded_by?: string }
}) {
  const items = outputs.outputs ?? []
  const note = outputs.note ?? ''
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set())
  const toggle = (key: string) =>
    setRevealedKeys((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  if (items.length === 0 && !note) return null

  return (
    <section className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
        <CheckCircle2 className="h-3.5 w-3.5" />
        Completion outputs
        {outputs.recorded_at && (
          <span className="ml-2 text-[10px] font-normal normal-case text-gray-500">
            recorded {formatDateTime(outputs.recorded_at)}{outputs.recorded_by ? ` by ${outputs.recorded_by}` : ''}
          </span>
        )}
      </div>
      {items.length > 0 && (
        <div className="grid gap-2 md:grid-cols-2">
          {items.map((item, idx) => {
            const revealed = revealedKeys.has(item.key)
            const display = item.sensitive && !revealed ? maskSensitive(item.value) : item.value
            return (
              <div key={`${item.key}-${idx}`} className="rounded-md border border-gray-800 bg-gray-950/60 p-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-xs font-medium text-gray-200">{item.label}</div>
                  {item.sensitive && (
                    <button
                      type="button"
                      onClick={() => toggle(item.key)}
                      className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-gray-700 text-gray-300 hover:text-white"
                      title={revealed ? 'Hide' : 'Reveal'}
                    >
                      {revealed ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                    </button>
                  )}
                </div>
                <div className="mt-1 break-all text-sm text-gray-100">{display}</div>
                <div className="mt-0.5 text-[10px] uppercase tracking-wider text-gray-500">
                  <code>{item.key}</code>{item.domain && ` - ${item.domain}`}
                </div>
              </div>
            )
          })}
        </div>
      )}
      {note && (
        <div className="mt-2 rounded-md border border-gray-800 bg-gray-900/60 p-2 text-xs text-gray-300 whitespace-pre-wrap">{note}</div>
      )}
    </section>
  )
}

function TaskCompletionModal({
  taskTitle,
  fields,
  existingOutputs,
  existingNote,
  taskDomain,
  submitting,
  onCancel,
  onSubmit,
}: {
  taskTitle: string
  fields: WalkthroughCompletionField[]
  existingOutputs: CompletionOutput[]
  existingNote: string
  taskDomain: string | null
  submitting: boolean
  onCancel: () => void
  onSubmit: (outputs: CompletionOutput[], note: string) => void
}) {
  const existingByKey = useMemo(() => {
    const map = new Map<string, CompletionOutput>()
    for (const item of existingOutputs) map.set(item.key, item)
    return map
  }, [existingOutputs])

  type Row = {
    key: string
    label: string
    placeholder?: string
    sensitive: boolean
    required: boolean
    domain?: string
    value: string
    revealed: boolean
    fromWalkthrough: boolean
  }

  const initial: Row[] = useMemo(() => {
    const rows: Row[] = []
    const seenKeys = new Set<string>()
    for (const field of fields) {
      const existing = existingByKey.get(field.key)
      rows.push({
        key: field.key,
        label: field.label,
        placeholder: field.placeholder,
        sensitive: Boolean(field.sensitive),
        required: Boolean(field.required),
        domain: field.domain,
        value: existing?.value ?? '',
        revealed: !field.sensitive,
        fromWalkthrough: true,
      })
      seenKeys.add(field.key)
    }
    for (const item of existingOutputs) {
      if (seenKeys.has(item.key)) continue
      rows.push({
        key: item.key,
        label: item.label || item.key,
        placeholder: undefined,
        sensitive: Boolean(item.sensitive),
        required: false,
        domain: item.domain ?? undefined,
        value: item.value,
        revealed: !item.sensitive,
        fromWalkthrough: false,
      })
    }
    return rows
  }, [fields, existingOutputs, existingByKey])

  const [rows, setRows] = useState<Row[]>(initial)
  const [note, setNote] = useState<string>(existingNote)
  const [customKey, setCustomKey] = useState('')
  const [customLabel, setCustomLabel] = useState('')

  useEffect(() => {
    setRows(initial)
  }, [initial])
  useEffect(() => {
    setNote(existingNote)
  }, [existingNote])

  const setRowValue = (index: number, value: string) =>
    setRows((current) => current.map((row, idx) => (idx === index ? { ...row, value } : row)))

  const toggleReveal = (index: number) =>
    setRows((current) => current.map((row, idx) => (idx === index ? { ...row, revealed: !row.revealed } : row)))

  const toggleSensitive = (index: number) =>
    setRows((current) => current.map((row, idx) => (idx === index ? { ...row, sensitive: !row.sensitive, revealed: row.sensitive ? row.revealed : false } : row)))

  const addCustomRow = () => {
    const key = customKey.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_')
    if (!key) return
    if (rows.some((row) => row.key === key)) {
      toast({ title: 'Key already used on this task', description: key })
      return
    }
    setRows((current) => [
      ...current,
      {
        key,
        label: customLabel.trim() || key,
        placeholder: undefined,
        sensitive: false,
        required: false,
        domain: taskDomain ?? undefined,
        value: '',
        revealed: true,
        fromWalkthrough: false,
      },
    ])
    setCustomKey('')
    setCustomLabel('')
  }

  const removeRow = (index: number) =>
    setRows((current) => current.filter((_, idx) => idx !== index))

  const handleSubmit = () => {
    const missingRequired = rows.filter((row) => row.required && !row.value.trim())
    if (missingRequired.length) {
      toast({
        title: 'Fill in the required outputs first',
        description: missingRequired.map((row) => row.label).join(', '),
      })
      return
    }
    const outputs: CompletionOutput[] = rows
      .filter((row) => row.value.trim())
      .map((row) => ({
        key: row.key,
        label: row.label,
        value: row.value.trim(),
        domain: row.domain ?? taskDomain ?? undefined,
        sensitive: row.sensitive,
      }))
    onSubmit(outputs, note.trim())
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-6">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-lg border border-gray-800 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-emerald-300">Record outputs</div>
            <h2 className="mt-2 text-lg font-semibold text-white">{taskTitle}</h2>
            <p className="mt-1 text-xs text-gray-400">Capture the structured outputs this task produced. Sensitive values are masked in the dashboard.</p>
          </div>
          <button type="button" onClick={onCancel} className="rounded-md p-2 text-gray-400 hover:bg-gray-900 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {rows.length === 0 ? (
            <div className="rounded-md border border-dashed border-gray-800 p-4 text-xs text-gray-400">
              No structured outputs are required for this task. Add a free-text note below, or attach custom key/value outputs.
            </div>
          ) : (
            <div className="space-y-3">
              {rows.map((row, index) => (
                <div key={`${row.key}-${index}`} className="rounded-md border border-gray-800 bg-gray-900/60 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-xs font-medium text-gray-200">
                      {row.label}
                      {row.required && <span className="ml-1 text-red-400">*</span>}
                      <div className="mt-0.5 text-[10px] uppercase tracking-wider text-gray-500">
                        key: <code className="text-gray-400">{row.key}</code>
                        {row.domain && <span className="ml-2">domain: {row.domain}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => toggleSensitive(index)}
                        title={row.sensitive ? 'Mark not sensitive' : 'Mark sensitive'}
                        className={cn(
                          'inline-flex h-7 w-7 items-center justify-center rounded-md border',
                          row.sensitive ? 'border-amber-500/40 bg-amber-500/10 text-amber-200' : 'border-gray-700 text-gray-400 hover:text-white',
                        )}
                      >
                        <KeyRound className="h-3.5 w-3.5" />
                      </button>
                      {!row.fromWalkthrough && (
                        <button
                          type="button"
                          onClick={() => removeRow(index)}
                          title="Remove this output"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-700 text-gray-400 hover:border-red-500/40 hover:text-red-300"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      type={row.sensitive && !row.revealed ? 'password' : 'text'}
                      value={row.value}
                      placeholder={row.placeholder}
                      onChange={(event) => setRowValue(index, event.target.value)}
                      className="h-9 flex-1 rounded-md border border-gray-800 bg-gray-950 px-3 text-sm text-gray-100 outline-none focus:border-blue-500"
                    />
                    {row.sensitive && (
                      <button
                        type="button"
                        onClick={() => toggleReveal(index)}
                        title={row.revealed ? 'Hide value' : 'Reveal value'}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-700 text-gray-300 hover:text-white"
                      >
                        {row.revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="rounded-md border border-dashed border-gray-800 p-3">
            <div className="mb-2 text-xs uppercase tracking-wider text-gray-500">Add custom output</div>
            <div className="flex gap-2">
              <input
                type="text"
                value={customKey}
                placeholder="key (e.g. cpa_email)"
                onChange={(event) => setCustomKey(event.target.value)}
                className="h-9 flex-1 rounded-md border border-gray-800 bg-gray-950 px-3 text-sm text-gray-100 outline-none focus:border-blue-500"
              />
              <input
                type="text"
                value={customLabel}
                placeholder="label (e.g. CPA email)"
                onChange={(event) => setCustomLabel(event.target.value)}
                className="h-9 flex-1 rounded-md border border-gray-800 bg-gray-950 px-3 text-sm text-gray-100 outline-none focus:border-blue-500"
              />
              <button
                type="button"
                onClick={addCustomRow}
                className="inline-flex h-9 items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 text-xs text-blue-200"
              >
                Add
              </button>
            </div>
          </div>

          <label className="grid gap-1 text-xs text-gray-500">
            Completion note (appended to the task description)
            <textarea
              value={note}
              placeholder="What did you do, anything Zero should know about how this got done"
              onChange={(event) => setNote(event.target.value)}
              className="min-h-24 rounded-md border border-gray-800 bg-gray-900 px-3 py-2 text-sm leading-relaxed text-gray-100 outline-none focus:border-blue-500"
            />
          </label>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-gray-800 p-4">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-9 items-center rounded-md border border-gray-700 bg-gray-900 px-4 text-sm text-gray-200"
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-4 text-sm font-medium text-white disabled:opacity-60"
          >
            <CheckCircle2 className="h-4 w-4" />
            {submitting ? 'Recording...' : 'Complete + Run Zero Review'}
          </button>
        </div>
      </div>
    </div>
  )
}

function TasksSection() {
  const { tasks, seedPreviewTasks, isLoading, isLive, error, reviewSummary } = useCompanyTaskCards()
  const createTask = useCreateCompanyWorkItem()
  const updateTask = useUpdateCompanyWorkItem()
  const importSeed = useImportCompanySeedBacklog()
  const { data: seedStatus } = useCompanySeedStatus()
  const drawer = useTaskDrawer()
  const [title, setTitle] = useState('')
  const [domain, setDomain] = useState('Formation')
  const [priority, setPriority] = useState<ZeroTask['priority']>('high')
  const [view, setView] = useState<'kanban' | 'table'>('kanban')
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null)
  const setSelectedTask = (task: CompanyTaskCard | null) => {
    if (task && drawer) drawer.openTask(task)
  }

  const submitTask = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) return
    createTask.mutate(
      {
        title: trimmed,
        description: `(${domain} Sprint) Created from the Company OS task board.`,
        project_id: 'company',
        category: 'chore',
        priority,
        source: 'MANUAL',
        domain,
        owner_agent: ownerAgentsByDomain(domain),
        tags: [domain.toLowerCase().replace(/\s+/g, '-')],
      },
      {
        onSuccess: (created) => {
          setTitle('')
          toast({ title: created.status === 'blocked' ? 'Task created behind approval gate' : 'Task created', description: created.blocked_reason })
        },
        onError: (err) => toast({ title: 'Could not create task', description: err.message }),
      },
    )
  }

  const visibleTasks = tasks.filter((task) => {
    if (filter !== 'all') {
      if (filter === 'today' && !task.nextAction && task.status !== 'in-progress') return false
      if (filter === 'blocked' && task.status !== 'blocked') return false
      if (filter === 'approval' && !task.requiresApproval) return false
      if (filter !== 'today' && filter !== 'blocked' && filter !== 'approval' && task.domain !== filter) return false
    }
    if (search.trim()) {
      const needle = search.toLowerCase()
      return `${task.title} ${task.domain} ${task.owner} ${task.zeroDescription ?? ''}`.toLowerCase().includes(needle)
    }
    return true
  })
  const nextSortOrder = () => Math.max(0, ...tasks.map((task) => task.zeroTask?.sort_order ?? 0)) + 1
  const moveTaskToStatus = (taskId: string, status: CompanyTaskStatus) => {
    updateTask.mutate(
      { id: taskId, data: { status: companyStatusToZero(status), sort_order: nextSortOrder() } },
      {
        onSuccess: (result) => toast({
          title: result.status === 'blocked' && status === 'done' ? 'Approval gate queued' : 'Task moved',
          description: result.blocked_reason,
        }),
        onError: (err) => toast({ title: 'Move failed', description: err.message }),
      },
    )
  }

  return (
    <Panel
      title={isLive ? 'Task Suite - Zero DB' : 'Task Suite - Import Required'}
      icon={ClipboardList}
      action={
        <div className="flex gap-2">
          <button type="button" onClick={() => setView('kanban')} className={cn('inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs', view === 'kanban' ? 'bg-blue-600 text-white' : 'border border-gray-800 text-gray-300')}>
            <Columns3 className="h-3.5 w-3.5" /> Kanban
          </button>
          <button type="button" onClick={() => setView('table')} className={cn('inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs', view === 'table' ? 'bg-blue-600 text-white' : 'border border-gray-800 text-gray-300')}>
            <Table2 className="h-3.5 w-3.5" /> Table
          </button>
        </div>
      }
    >
      {reviewSummary && (
        <div className="mb-4 grid gap-3 md:grid-cols-4">
          <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Company grade</div>
            <div className="mt-1 text-2xl font-semibold text-white">{reviewSummary.overall_score}/100</div>
          </div>
          <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Reviewed</div>
            <div className="mt-1 text-2xl font-semibold text-gray-100">{reviewSummary.tasks_reviewed}</div>
          </div>
          <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Critical blockers</div>
            <div className="mt-1 text-2xl font-semibold text-red-300">{reviewSummary.critical_blockers}</div>
          </div>
          <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
            <div className="text-xs text-gray-500">Missing info</div>
            <div className="mt-1 text-2xl font-semibold text-amber-300">{reviewSummary.missing_info_count}</div>
          </div>
        </div>
      )}
      {!isLive && !isLoading && (
        <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
          <div className="text-sm font-semibold text-amber-100">No live editable company tasks yet.</div>
          <p className="mt-1 text-sm text-amber-200/80">{seedStatus?.message ?? 'Import the seed backlog to convert the docs plan into editable Zero tasks.'}</p>
          <button
            type="button"
            disabled={importSeed.isPending}
            onClick={() => importSeed.mutate(undefined, {
              onSuccess: (result) => toast({ title: 'Seed backlog imported', description: `${result.created} created, ${result.skipped} skipped.` }),
              onError: (err) => toast({ title: 'Seed import failed', description: err.message }),
            })}
            className="mt-3 inline-flex h-9 items-center gap-2 rounded-md bg-amber-500 px-3 text-sm font-medium text-gray-950 disabled:opacity-60"
          >
            <Send className="h-4 w-4" />
            Import Seed Backlog
          </button>
          <div className="mt-3 text-xs text-amber-200/70">Seed preview below is read-only until imported.</div>
        </div>
      )}
      {error && <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">Task API error: {error.message}</div>}
      <form onSubmit={submitTask} className="mb-4 grid gap-2 rounded-lg border border-gray-800 bg-gray-950/60 p-3 md:grid-cols-[1fr_170px_130px_auto]">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Add a company task..."
          className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-blue-500"
        />
        <select
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-200 outline-none focus:border-blue-500"
        >
          {companyDomains.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <select
          value={priority}
          onChange={(event) => setPriority(event.target.value as ZeroTask['priority'])}
          className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-200 outline-none focus:border-blue-500"
        >
          {priorityOptions.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <button
          type="submit"
          disabled={createTask.isPending || !title.trim()}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-60"
        >
          <Send className="h-4 w-4" />
          Add
        </button>
      </form>
      <div className="mb-4 grid gap-2 lg:grid-cols-[220px_1fr]">
        <select value={filter} onChange={(event) => setFilter(event.target.value)} className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-200">
          <option value="all">All work</option>
          <option value="today">Today / next</option>
          <option value="blocked">Blocked</option>
          <option value="approval">Approval-gated</option>
          {companyDomains.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <label className="relative">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-600" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tasks, owners, domains..." className="h-9 w-full rounded-md border border-gray-800 bg-gray-900 pl-9 pr-3 text-sm text-gray-100 outline-none focus:border-blue-500" />
        </label>
      </div>
      {isLoading && <div className="mb-3 text-xs text-gray-500">Loading live company tasks...</div>}
      {view === 'kanban' ? (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-4">
          {statusColumns.map((status) => (
            <div
              key={status}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                if (draggedTaskId) {
                  moveTaskToStatus(draggedTaskId, status)
                  setDraggedTaskId(null)
                }
              }}
              className={cn(
                'min-h-[520px] rounded-lg border bg-gray-950/40 p-3 transition-colors',
                statusColumnClasses[status],
                draggedTaskId && 'border-blue-500/40 bg-blue-500/5',
              )}
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-200">{statusColumnLabels[status]}</h3>
                <Badge className="border-gray-700 text-gray-400">{visibleTasks.filter((task) => task.status === status).length}</Badge>
              </div>
              <div className="space-y-3">
                {visibleTasks.filter((task) => task.status === status).map((task) => (
                  <div
                    key={task.id}
                    draggable={task.sourceSystem === 'zero'}
                    onDragStart={() => setDraggedTaskId(task.id)}
                    onDragEnd={() => setDraggedTaskId(null)}
                    onDoubleClick={() => setSelectedTask(task)}
                    className="cursor-grab active:cursor-grabbing"
                  >
                    <TaskCard task={task} editable />
                    <button type="button" onClick={() => setSelectedTask(task)} className="mt-1 text-[11px] text-blue-300">Open details</button>
                  </div>
                ))}
                {visibleTasks.filter((task) => task.status === status).length === 0 && (
                  <div className="flex min-h-32 items-center justify-center rounded-md border border-dashed border-gray-800 text-xs text-gray-600">
                    Drop tasks here
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="min-w-full divide-y divide-gray-800 text-sm">
            <thead className="bg-gray-950/80 text-left text-xs text-gray-500">
              <tr>
                <th className="px-3 py-2">Task</th>
                <th className="px-3 py-2">Grade</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Priority</th>
                <th className="px-3 py-2">Domain</th>
                <th className="px-3 py-2">Owner</th>
                <th className="px-3 py-2">Due</th>
                <th className="px-3 py-2">Risk</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-900">
              {visibleTasks.map((task) => (
                <tr key={task.id} className="bg-gray-950/40 hover:bg-gray-900/80">
                  <td className="max-w-sm px-3 py-2">
                    <button type="button" onClick={() => setSelectedTask(task)} className="text-left font-medium text-gray-100 hover:text-blue-300">{task.title}</button>
                    {task.zeroBlockedReason && <div className="mt-1 truncate text-xs text-amber-300">{task.zeroBlockedReason}</div>}
                  </td>
                  <td className="px-3 py-2">
                    {task.review ? <Badge className={scoreClass(task.review.score)}>{task.review.score}/100</Badge> : <Badge className="border-gray-700 text-gray-500">unreviewed</Badge>}
                  </td>
                  <td className="px-3 py-2">
                    <select
                      value={zeroStatusForCompanyTask(task)}
                      onChange={(event) => updateTask.mutate({ id: task.id, data: { status: event.target.value as ZeroTask['status'] } })}
                      className="h-8 rounded-md border border-gray-800 bg-gray-900 px-2 text-xs text-gray-200"
                    >
                      {zeroStatusOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      value={task.zeroPriority}
                      onChange={(event) => updateTask.mutate({ id: task.id, data: { priority: event.target.value as ZeroTask['priority'] } })}
                      className="h-8 rounded-md border border-gray-800 bg-gray-900 px-2 text-xs text-gray-200"
                    >
                      {priorityOptions.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select
                      value={task.domain}
                      onChange={(event) => updateTask.mutate({ id: task.id, data: { domain: event.target.value } })}
                      className="h-8 rounded-md border border-gray-800 bg-gray-900 px-2 text-xs text-gray-200"
                    >
                      {companyDomains.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2 text-gray-400">{task.owner}</td>
                  <td className="px-3 py-2 text-gray-400">{task.due}</td>
                  <td className="px-3 py-2"><Badge className={riskClasses[task.risk]}>{task.risk}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!isLive && seedPreviewTasks.length > 0 && (
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {seedPreviewTasks.slice(0, 9).map((task) => <TaskCard key={task.id} task={task} />)}
        </div>
      )}
    </Panel>
  )
}

function ownerAgentsByDomain(domain: string) {
  return {
    Formation: 'legal_compliance',
    Finance: 'finance_cpa',
    Consulting: 'consulting_revenue',
    Product: 'product',
    Robotics: 'robotics_lab',
    Marketing: 'marketing_content',
    Dashboard: 'engineering',
    Agents: 'chief_of_staff',
    Knowledge: 'knowledge_second_brain',
    Operations: 'zero-company-operator',
  }[domain] ?? 'zero-company-operator'
}

function ApprovalDetailDrawer({ approval, linkedTask, onClose }: {
  approval: CompanyOperatorApproval | null
  linkedTask?: ZeroTask
  onClose: () => void
}) {
  const decide = useDecideAgentApproval()
  if (!approval) return null
  const args = approval.arguments ?? {}

  const decideWithToast = (status: 'approved' | 'rejected') => {
    decide.mutate(
      { id: approval.id, status, reason: status === 'approved' ? 'Approved from Company OS dashboard.' : 'Rejected from Company OS dashboard.' },
      {
        onSuccess: () => {
          toast({ title: status === 'approved' ? 'Approval recorded' : 'Approval rejected' })
          onClose()
        },
        onError: (error) => toast({ title: 'Approval update failed', description: error.message }),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60">
      <aside className="ml-auto flex h-full w-full max-w-2xl flex-col border-l border-gray-800 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-blue-300">Approval Gate</div>
            <h2 className="mt-2 text-lg font-semibold text-white">{approval.summary}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-gray-400 hover:bg-gray-900 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="flex flex-wrap gap-2">
            <Badge className={approval.tier === 'financial' ? riskClasses.critical : riskClasses.high}>{approval.tier}</Badge>
            <Badge className={statusBadgeClass(approval.status)}>{approval.status}</Badge>
            <Badge className="border-gray-700 text-gray-300">{approval.tool_name}</Badge>
          </div>
          <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
            <h3 className="text-sm font-semibold text-gray-100">What Adam Must Decide</h3>
            <p className="mt-2 text-sm text-gray-300">{String(args.guardrail ?? 'Review this approval before any external action is treated as complete.')}</p>
            {linkedTask && (
              <div className="mt-3 rounded-md border border-gray-800 bg-gray-950/60 p-3 text-sm">
                <div className="text-gray-100">{linkedTask.title}</div>
                <div className="mt-1 text-xs text-gray-500">{linkedTask.domain ?? linkedTask.category} - {linkedTask.priority} - {linkedTask.status}</div>
              </div>
            )}
          </section>
          <section>
            <h3 className="mb-2 text-sm font-semibold text-gray-100">Approval Arguments</h3>
            <div className="space-y-2">
              {Object.entries(args).map(([key, value]) => (
                <div key={key} className="rounded-md border border-gray-800 bg-gray-900/60 p-2 text-xs">
                  <div className="font-medium text-gray-200">{key}</div>
                  <div className="mt-1 break-words text-gray-400">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</div>
                </div>
              ))}
            </div>
          </section>
          <section className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-100">
            Approving this records your decision. Zero still does not file, purchase, open accounts, send client/public messages, or change credentials by itself.
          </section>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={decide.isPending || approval.status !== 'pending'}
              onClick={() => decideWithToast('approved')}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-3 text-sm font-medium text-white disabled:opacity-60"
            >
              <CheckCircle2 className="h-4 w-4" />
              Approve
            </button>
            <button
              type="button"
              disabled={decide.isPending || approval.status !== 'pending'}
              onClick={() => decideWithToast('rejected')}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 text-sm font-medium text-red-200 disabled:opacity-60"
            >
              <X className="h-4 w-4" />
              Reject
            </button>
          </div>
        </div>
      </aside>
    </div>
  )
}

function QuestionDetailDrawer({ question, linkedTask, onClose }: {
  question: CompanyAgentQuestion | null
  linkedTask?: ZeroTask
  onClose: () => void
}) {
  const [answer, setAnswer] = useState('')
  const answerQuestion = useAnswerCompanyAgentQuestion()
  const dismissQuestion = useDismissCompanyAgentQuestion()
  if (!question) return null

  const submitAnswer = () => {
    const trimmed = answer.trim()
    if (!trimmed) return
    answerQuestion.mutate(
      { id: question.id, answer: trimmed },
      {
        onSuccess: () => {
          toast({ title: 'Agent question answered' })
          setAnswer('')
          onClose()
        },
        onError: (error) => toast({ title: 'Answer failed', description: error.message }),
      },
    )
  }

  const dismiss = () => {
    dismissQuestion.mutate(
      { id: question.id },
      {
        onSuccess: () => {
          toast({ title: 'Agent question dismissed' })
          onClose()
        },
        onError: (error) => toast({ title: 'Dismiss failed', description: error.message }),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60">
      <aside className="ml-auto flex h-full w-full max-w-2xl flex-col border-l border-gray-800 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-blue-300">Agent Question</div>
            <h2 className="mt-2 text-lg font-semibold text-white">{question.question}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-gray-400 hover:bg-gray-900 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="flex flex-wrap gap-2">
            <Badge className={statusBadgeClass(question.status)}>{question.status}</Badge>
            <Badge className={priorityBadgeClass(question.priority)}>{question.priority}</Badge>
            <Badge className="border-gray-700 text-gray-300">{String(question.asked_by_agent ?? 'unknown')}</Badge>
          </div>
          {linkedTask && (
            <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
              <h3 className="text-sm font-semibold text-gray-100">Linked Company Task</h3>
              <div className="mt-2 text-sm text-gray-100">{linkedTask.title}</div>
              <div className="mt-1 text-xs text-gray-500">{linkedTask.domain ?? linkedTask.category} - {linkedTask.priority} - {linkedTask.status}</div>
            </section>
          )}
          <section className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-3">
            <h3 className="text-sm font-semibold text-blue-100">Why The Agent Is Asking</h3>
            <div className="mt-2 space-y-2 text-xs text-blue-100/90">
              <div>Agent task: <span className="text-gray-100">{String(question.context?.['agent_task_title'] ?? question.agent_task_id ?? 'unknown')}</span></div>
              {Boolean(question.context?.['result_summary']) && <div>Last output: <span className="text-gray-100">{String(question.context['result_summary'])}</span></div>}
              {Boolean(question.why_needed || question.context?.['why_needed']) && <div>Why needed: <span className="text-gray-100">{String(question.why_needed ?? question.context['why_needed'])}</span></div>}
              {Boolean(question.recommended_default || question.context?.['recommended_default']) && <div>Recommended default: <span className="text-gray-100">{String(question.recommended_default ?? question.context['recommended_default'])}</span></div>}
              {Boolean(question.decision_type || question.context?.['decision_type']) && <div>Decision type: <span className="text-gray-100">{String(question.decision_type ?? question.context['decision_type'])}</span></div>}
              <div>Blocks progress: <span className="text-gray-100">{(question.blocks_progress ?? question.context?.['blocks_progress']) ? 'yes' : 'no'}</span></div>
              <div>Created: <span className="text-gray-100">{formatDateTime(question.created_at)}</span></div>
            </div>
          </section>
          <label className="grid gap-2 text-xs text-gray-500">
            Answer for the agent
            <textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="Give the agent the missing fact, decision, constraint, or next instruction..."
              className="min-h-32 rounded-md border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-100 outline-none focus:border-blue-500"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!answer.trim() || answerQuestion.isPending}
              onClick={submitAnswer}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-medium text-white disabled:opacity-60"
            >
              <Send className="h-4 w-4" />
              Send Answer
            </button>
            <button
              type="button"
              disabled={dismissQuestion.isPending}
              onClick={dismiss}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm font-medium text-gray-200 disabled:opacity-60"
            >
              <X className="h-4 w-4" />
              Dismiss
            </button>
          </div>
        </div>
      </aside>
    </div>
  )
}

function AgentDetailDrawer({ agent, onClose }: { agent: CompanySubagentStatus | null; onClose: () => void }) {
  const runTick = useRunCompanyOperatorTick()
  if (!agent) return null
  return (
    <div className="fixed inset-0 z-50 bg-black/60">
      <aside className="ml-auto flex h-full w-full max-w-2xl flex-col border-l border-gray-800 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-blue-300">Company Agent</div>
            <h2 className="mt-2 text-lg font-semibold text-white">{agent.name}</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => runTick.mutate({ run_type: 'agent_work', requested_by: 'dashboard', force: true, target_agent_id: agent.id })}
              disabled={runTick.isPending}
              className="inline-flex h-8 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-medium text-white disabled:opacity-60"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', runTick.isPending && 'animate-spin')} />
              Run Now
            </button>
            <button type="button" onClick={onClose} className="rounded-md p-2 text-gray-400 hover:bg-gray-900 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-lg bg-gray-900 p-3 text-center">
              <div className="text-xl font-semibold text-white">{agent.total_tasks}</div>
              <div className="text-xs text-gray-500">tasks</div>
            </div>
            <div className="rounded-lg bg-gray-900 p-3 text-center">
              <div className="text-xl font-semibold text-white">{agent.running_tasks ?? agent.active_tasks}</div>
              <div className="text-xs text-gray-500">running</div>
            </div>
            <div className="rounded-lg bg-gray-900 p-3 text-center">
              <div className="text-xl font-semibold text-white">{formatDateTime(agent.last_run_at)}</div>
              <div className="text-xs text-gray-500">last run</div>
            </div>
          </div>
          <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
            <h3 className="text-sm font-semibold text-gray-100">Current State</h3>
            <div className="mt-2 space-y-2 text-sm text-gray-300">
              <div>Autonomy: <span className="text-gray-100">{agent.autonomy}</span></div>
              <div>Status: <span className="text-gray-100">{agent.agent_status ?? (agent.active_tasks > 0 ? 'Running now' : 'Idle')}</span></div>
              <div>Reason: <span className="text-gray-100">{agent.current_assignment ?? agent.idle_reason ?? 'No active assignment'}</span></div>
              <div>Next scheduled run: <span className="text-gray-100">{agent.next_scheduled_run ?? 'Every 15 minutes'}</span></div>
              {agent.blocked_reason && <div className="text-amber-200">Blocked: {agent.blocked_reason}</div>}
            </div>
          </section>
          <section className="grid gap-2 md:grid-cols-4">
            <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-center">
              <div className="text-lg font-semibold text-white">{agent.queued_tasks ?? 0}</div>
              <div className="text-xs text-gray-500">queued</div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-center">
              <div className="text-lg font-semibold text-white">{agent.question_count ?? 0}</div>
              <div className="text-xs text-gray-500">questions</div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-center">
              <div className="text-lg font-semibold text-white">{agent.approval_count ?? 0}</div>
              <div className="text-xs text-gray-500">approvals</div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/60 p-3 text-center">
              <div className="text-lg font-semibold text-white">{agent.needs_review_tasks ?? 0}</div>
              <div className="text-xs text-gray-500">needs review</div>
            </div>
          </section>
          {agent.last_output && (
            <section className="rounded-lg border border-gray-800 bg-gray-900/60 p-3">
              <h3 className="text-sm font-semibold text-gray-100">Last Output</h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-300">{agent.last_output}</p>
            </section>
          )}
          {agent.capabilities?.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-gray-100">Capabilities</h3>
              <div className="flex flex-wrap gap-2">
                {agent.capabilities.map((capability) => <Badge key={capability} className="border-gray-700 text-gray-300">{capability}</Badge>)}
              </div>
            </section>
          )}
        </div>
      </aside>
    </div>
  )
}

function AgentsSection() {
  const { data: status, isLoading, error } = useCompanyOperatorStatus()
  const runTick = useRunCompanyOperatorTick()
  const liveAgents = status?.subagents ?? []
  const [selectedAgent, setSelectedAgent] = useState<CompanySubagentStatus | null>(null)

  if (isLoading && !status) {
    return <Panel title="Agent Company Structure" icon={Bot}><div className="text-sm text-gray-400">Loading live company agents...</div></Panel>
  }

  if (!status) {
    return (
      <Panel title="Agent Company Structure" icon={Bot} action={<Link to="/login" className="text-xs text-blue-300">Connect API</Link>}>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
          <div className="text-sm font-semibold text-amber-100">Live agent state is unavailable.</div>
          <p className="mt-1 text-sm text-amber-200/80">
            The dashboard is not showing seed agent profiles here because that can make idle placeholders look like real 24/7 work. Connect the Zero API token to see running, queued, waiting-on-Adam, approval, and review states.
          </p>
          {error && <p className="mt-2 text-xs text-amber-200/70">{error.message}</p>}
        </div>
      </Panel>
    )
  }

  return (
    <Panel title="Agent Company Structure" icon={Bot}>
      {liveAgents.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {liveAgents.map((agent) => (
            <div
              key={agent.id}
              role="button"
              tabIndex={0}
              onClick={() => setSelectedAgent(agent)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') setSelectedAgent(agent)
              }}
              className="cursor-pointer rounded-lg border border-gray-800 bg-gray-950/60 p-4 text-left hover:border-blue-500/50"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-gray-100">{agent.name}</h3>
                  <p className="mt-1 text-xs text-gray-500">{agent.autonomy}</p>
                </div>
                <Badge className={agentStatusClass(agent.agent_status)}>
                  {agent.agent_status ?? (agent.active_tasks > 0 ? 'Running now' : 'Idle')}
                </Badge>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.total_tasks}</div><div className="text-gray-500">tasks</div></div>
                <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.queued_tasks ?? 0}</div><div className="text-gray-500">queued</div></div>
                <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.question_count ?? 0}</div><div className="text-gray-500">questions</div></div>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.running_tasks ?? agent.active_tasks}</div><div className="text-gray-500">running</div></div>
                <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.approval_count ?? 0}</div><div className="text-gray-500">gates</div></div>
                <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">${agent.cost_usd ?? 0}</div><div className="text-gray-500">cost</div></div>
              </div>
              <div className="mt-3 flex items-start justify-between gap-3">
                <div className="min-w-0 text-xs text-gray-400">{agent.current_assignment ?? agent.idle_reason ?? 'No active assignment'}</div>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    runTick.mutate({ run_type: 'agent_work', requested_by: 'dashboard', force: true, target_agent_id: agent.id })
                  }}
                  disabled={runTick.isPending}
                  className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-blue-600 px-2.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-60"
                >
                  <RefreshCw className={cn('h-3.5 w-3.5', runTick.isPending && 'animate-spin')} />
                  Run Now
                </button>
              </div>
              {agent.last_output && <div className="mt-2 rounded-md bg-gray-900 p-2 text-xs text-gray-500">{agent.last_output}</div>}
            </div>
          ))}
          <AgentDetailDrawer agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {agentProfiles.map((agent) => (
          <div key={agent.key} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-100">{agent.name}</h3>
                <p className="mt-1 text-xs text-gray-500">{agent.owner}</p>
              </div>
              <Badge className="border-blue-500/30 bg-blue-500/10 text-blue-300">{agent.level}</Badge>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
              <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.openTasks}</div><div className="text-gray-500">tasks</div></div>
              <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.runs7d}</div><div className="text-gray-500">runs</div></div>
              <div className="rounded-md bg-gray-900 p-2"><div className="text-gray-100">{agent.approvalsWaiting}</div><div className="text-gray-500">gates</div></div>
            </div>
          </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function AgentInboxSection({ defaultTab = 'questions' }: { defaultTab?: 'questions' | 'approvals' | 'outputs' | 'runs' }) {
  const [tab, setTab] = useState(defaultTab)
  const { data: questions, isLoading: questionsLoading } = useCompanyAgentQuestions('open', undefined, undefined, 200)
  const { data: liveApprovals, isLoading } = useAgentApprovals('pending', 50)
  const { data: liveTasks } = useCompanyWorkItems({ limit: 500 })
  const { data: status } = useCompanyOperatorStatus()
  const { data: runs } = useCompanyOperatorRuns(undefined, 30)
  const runTick = useRunCompanyOperatorTick()
  const triageQuestions = useTriageCompanyAgentQuestions()
  const promptEval = useRunCompanyPromptEval()
  const [selectedQuestion, setSelectedQuestion] = useState<CompanyAgentQuestion | null>(null)
  const [selectedApproval, setSelectedApproval] = useState<CompanyOperatorApproval | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<CompanySubagentStatus | null>(null)
  const hasLiveApprovals = Boolean(liveApprovals?.length)
  const hasQuestions = Boolean(questions?.length)
  const linkedQuestionTask = selectedQuestion
    ? liveTasks?.find((task) => task.id === String(selectedQuestion.task_id ?? ''))
    : undefined
  const linkedTask = selectedApproval
    ? liveTasks?.find((task) => task.id === String(selectedApproval.arguments?.task_id ?? ''))
    : undefined

  return (
    <Panel
      title="Agent Inbox"
      icon={Inbox}
      action={
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => triageQuestions.mutate(
              { requested_by: 'dashboard', limit: 200, max_open: 25 },
              {
                onSuccess: (result) => toast({ title: 'Agent questions triaged', description: result.summary }),
                onError: (error) => toast({ title: 'Question triage failed', description: error.message }),
              },
            )}
            disabled={triageQuestions.isPending}
            className="inline-flex h-8 items-center gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 text-xs font-medium text-blue-100 disabled:opacity-60"
          >
            <Filter className="h-3.5 w-3.5" />
            Triage Questions
          </button>
          <button
            type="button"
            onClick={() => promptEval.mutate(
              { limit: 20 },
              {
                onSuccess: (result) => toast({ title: 'Prompt evaluation queued', description: result.summary }),
                onError: (error) => toast({ title: 'Prompt evaluation failed', description: error.message }),
              },
            )}
            disabled={promptEval.isPending}
            className="inline-flex h-8 items-center gap-2 rounded-md border border-purple-500/30 bg-purple-500/10 px-3 text-xs font-medium text-purple-100 disabled:opacity-60"
          >
            <Activity className={cn('h-3.5 w-3.5', promptEval.isPending && 'animate-pulse')} />
            Improve Prompts
          </button>
          <button
            type="button"
            onClick={() => runTick.mutate({ run_type: 'agent_work', requested_by: 'dashboard', force: true })}
            disabled={runTick.isPending}
            className="inline-flex h-8 items-center gap-2 rounded-md bg-blue-600 px-3 text-xs font-medium text-white disabled:opacity-60"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', runTick.isPending && 'animate-spin')} />
            Run Agent Work
          </button>
        </div>
      }
    >
      <div className="mb-4 grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          <div className="text-xs text-gray-500">Questions</div>
          <div className="mt-1 text-2xl font-semibold text-white">{status?.counts.questions_open ?? questions?.length ?? 0}</div>
          <div className="mt-1 text-[11px] text-gray-500">{questions?.length ?? 0} loaded for review</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          <div className="text-xs text-gray-500">Approvals</div>
          <div className="mt-1 text-2xl font-semibold text-white">{liveApprovals?.length ?? 0}</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          <div className="text-xs text-gray-500">Queued Agent Work</div>
          <div className="mt-1 text-2xl font-semibold text-white">{status?.counts.agent_tasks_queued ?? 0}</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          <div className="text-xs text-gray-500">Running Now</div>
          <div className="mt-1 text-2xl font-semibold text-white">{status?.counts.agent_tasks_running ?? 0}</div>
        </div>
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        {[
          { key: 'questions', label: 'Questions', icon: HelpCircle },
          { key: 'approvals', label: 'Approvals', icon: ShieldCheck },
          { key: 'outputs', label: 'Outputs', icon: MessageSquareText },
          { key: 'runs', label: 'Run Log', icon: Activity },
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key as typeof tab)}
            className={cn(
              'inline-flex h-8 items-center gap-2 rounded-md px-3 text-xs font-medium',
              tab === item.key ? 'bg-blue-600 text-white' : 'border border-gray-800 bg-gray-900 text-gray-300 hover:text-white',
            )}
          >
            <item.icon className="h-3.5 w-3.5" />
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'questions' && (
        <div className="space-y-3">
          {questionsLoading && <div className="text-xs text-gray-500">Loading agent questions...</div>}
          {hasQuestions ? questions?.map((question) => (
            <button key={question.id} type="button" onClick={() => setSelectedQuestion(question)} className="flex w-full flex-col gap-3 rounded-lg border border-gray-800 bg-gray-950/60 p-4 text-left hover:border-blue-500/50 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="text-sm font-medium text-gray-100">{question.question}</div>
                <div className="mt-1 text-xs text-gray-500">{question.asked_by_agent} - {formatDateTime(question.created_at)}</div>
                {Boolean(question.recommended_default || question.context?.['recommended_default']) && (
                  <div className="mt-2 text-xs text-emerald-200">Default: {String(question.recommended_default ?? question.context['recommended_default'])}</div>
                )}
                {question.task_id && <div className="mt-1 text-xs text-blue-300">Linked task: {question.task_id}</div>}
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge className={statusBadgeClass(question.status)}>{question.status}</Badge>
                <Badge className="border-blue-500/30 bg-blue-500/10 text-blue-300">{question.priority}</Badge>
              </div>
            </button>
          )) : <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-4 text-sm text-gray-400">No open agent questions. Agent work can still run and will create questions when it needs Adam.</div>}
        </div>
      )}

      {tab === 'approvals' && (
        <div className="space-y-3">
          {isLoading && <div className="text-xs text-gray-500">Loading live approval gates...</div>}
          {hasLiveApprovals ? liveApprovals?.map((approval) => (
            <button key={approval.id} type="button" onClick={() => setSelectedApproval(approval)} className="flex w-full flex-col gap-3 rounded-lg border border-gray-800 bg-gray-950/60 p-4 text-left hover:border-blue-500/50 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="text-sm font-medium text-gray-100">{approval.summary}</div>
                <div className="mt-1 text-xs text-gray-500">{approval.requested_by} - {approval.tool_name} - expires {formatDateTime(approval.expires_at)}</div>
                {Boolean(approval.arguments?.task_id) && <div className="mt-1 text-xs text-blue-300">Linked task: {String(approval.arguments.task_id)}</div>}
              </div>
              <div className="flex gap-2">
                <Badge className={approval.tier === 'financial' ? riskClasses.critical : riskClasses.high}>{approval.tier}</Badge>
                <Badge className={statusBadgeClass(approval.status)}>{approval.status}</Badge>
              </div>
            </button>
          )) : approvals.map((approval) => (
            <div key={approval.id} className="flex flex-col gap-3 rounded-lg border border-gray-800 bg-gray-950/60 p-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="text-sm font-medium text-gray-100">{approval.action}</div>
                <div className="mt-1 text-xs text-gray-500">{approval.owner} - {approval.source} - due {approval.due}</div>
              </div>
              <div className="flex gap-2">
                <Badge className={riskClasses[approval.risk]}>{approval.risk}</Badge>
                <Badge className="border-gray-700 text-gray-300">{approval.status}</Badge>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'outputs' && (
        <div className="grid gap-3 md:grid-cols-2">
          {(status?.subagents ?? []).map((agent) => (
            <button key={agent.id} type="button" onClick={() => setSelectedAgent(agent)} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4 text-left hover:border-blue-500/50">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-gray-100">{agent.name}</div>
                  <div className="mt-1 text-xs text-gray-500">Last run {formatDateTime(agent.last_run_at)}</div>
                </div>
                <Badge className={agentStatusClass(agent.agent_status)}>{agent.agent_status ?? 'Idle'}</Badge>
              </div>
              <div className="mt-3 text-xs text-gray-400">{agent.last_output || agent.idle_reason || 'No output recorded yet.'}</div>
              <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
                <Badge className="border-gray-700 text-gray-300">{agent.queued_tasks ?? 0} queued</Badge>
                <Badge className="border-blue-500/30 bg-blue-500/10 text-blue-300">{agent.question_count ?? 0} questions</Badge>
                <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-300">{agent.approval_count ?? 0} approvals</Badge>
              </div>
            </button>
          ))}
        </div>
      )}

      {tab === 'runs' && (
        <div className="space-y-2">
          {(runs ?? []).map((run) => (
            <div key={run.id ?? `${run.run_type}-${run.created_at}`} className="grid gap-2 rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-sm md:grid-cols-[150px_100px_90px_1fr_140px] md:items-center">
              <span className="font-medium text-gray-100">{run.run_type}</span>
              <Badge className={statusBadgeClass(run.status)}>{run.status}</Badge>
              <span className="text-xs text-gray-400">{run.actions?.length ?? 0} actions</span>
              <span className="text-gray-400">{run.summary ?? 'No summary'}</span>
              <span className="text-xs text-gray-500">{formatDateTime(run.created_at)}</span>
            </div>
          ))}
        </div>
      )}

      <QuestionDetailDrawer question={selectedQuestion} linkedTask={linkedQuestionTask} onClose={() => setSelectedQuestion(null)} />
      <ApprovalDetailDrawer approval={selectedApproval} linkedTask={linkedTask} onClose={() => setSelectedApproval(null)} />
      <AgentDetailDrawer agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </Panel>
  )
}

function ApprovalsSection() {
  return <AgentInboxSection defaultTab="approvals" />
}

function InboxSection() {
  return <AgentInboxSection defaultTab="questions" />
}

function FinanceSection() {
  const monthly = subscriptions.reduce((sum, item) => sum + item.monthlyCost, 0)
  const assetTotal = assets.reduce((sum, item) => sum + item.cost, 0)
  const { tasks } = useCompanyTaskCards()
  const drawer = useTaskDrawer()
  const findTaskByRail = (rail: string) => {
    const lower = rail.toLowerCase()
    return tasks.find((task) => task.title.toLowerCase().includes(lower) || task.domain.toLowerCase() === lower)
  }

  return (
    <div className="space-y-6">
      <SetupProgressPanel />
      <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Finance Setup Rails" icon={ClipboardList}>
        <div className="space-y-2">
          {financeSetupRails.map((item) => {
            const linked = findTaskByRail(item.rail)
            return (
              <button
                key={item.rail}
                type="button"
                onClick={() => linked && drawer?.openTask(linked)}
                disabled={!linked}
                className={cn(
                  'w-full rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-left text-sm',
                  linked ? 'hover:border-blue-500/50 hover:bg-gray-900 cursor-pointer' : 'opacity-80 cursor-default',
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 font-medium text-gray-100">
                      {item.rail}
                      {linked && <ChevronRight className="h-3.5 w-3.5 text-blue-300" />}
                    </div>
                    <div className="mt-1 text-xs leading-relaxed text-gray-400">{item.next}</div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <Badge className={riskClasses[item.risk]}>{item.risk}</Badge>
                    <Badge className={statusBadgeClass(item.status)}>{item.status}</Badge>
                  </div>
                </div>
                <div className="mt-2 text-xs text-gray-500">{item.owner}</div>
                {linked && (
                  <div className="mt-2 text-[11px] text-blue-300">Open walkthrough: {linked.title}</div>
                )}
              </button>
            )
          })}
        </div>
      </Panel>
      <Panel title="Evidence Packets" icon={ShieldCheck}>
        <div className="space-y-2">
          {financeEvidencePackets.map((item) => (
            <div key={item.item} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-gray-100">{item.item}</div>
                  <div className="mt-1 text-xs text-blue-300">{item.artifact}</div>
                  <div className="mt-2 text-xs leading-relaxed text-gray-400">{item.next}</div>
                </div>
                <Badge className={statusBadgeClass(item.status)}>{item.status}</Badge>
              </div>
              <div className="mt-2 text-xs text-gray-500">{item.owner}</div>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title={`Subscriptions - ${currency.format(monthly)}/mo tracked`} icon={Banknote}>
        <div className="space-y-2">
          {subscriptions.map((item) => (
            <div key={item.vendor} className="flex items-center justify-between rounded-lg bg-gray-950/60 p-3 text-sm">
              <div><span className="text-gray-100">{item.vendor}</span><span className="ml-2 text-xs text-gray-500">{item.category}</span></div>
              <Badge className="border-gray-700 text-gray-300">{item.evidence}</Badge>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title={`Assets - ${assetTotal > 0 ? `${currency.format(assetTotal)} tracked` : 'FMV pending'}`} icon={PackageCheck}>
        <div className="space-y-2">
          {assets.map((item) => (
            <div key={item.name} className="rounded-lg bg-gray-950/60 p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-gray-100">{item.name}</span>
                <span className="text-gray-400">{item.cost > 0 ? currency.format(item.cost) : 'FMV TBD'}</span>
              </div>
              <div className="mt-1 text-xs text-gray-500">{item.type} - {item.businessUse}% business use - evidence {item.evidence}</div>
            </div>
          ))}
        </div>
      </Panel>
      </div>
    </div>
  )
}

function LegalSection() {
  const { tasks } = useCompanyTaskCards()
  const drawer = useTaskDrawer()
  const findTask = (title: string) => {
    const lower = title.toLowerCase()
    return tasks.find((task) => lower.includes(task.title.toLowerCase().slice(0, 12)) || task.title.toLowerCase().includes(lower.slice(0, 12)))
  }

  return (
    <div className="space-y-6">
      <SetupProgressPanel />
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="LLC Formation Stance" icon={Gavel}>
          <div className="space-y-3 text-sm text-gray-300">
            <p>Recommended 2026 structure: Florida single-member LLC taxed as a disregarded entity.</p>
            <p>S-Corp election is deferred until sustained profit justifies payroll and filing overhead.</p>
            <p>Options trading stays outside the operating LLC unless a trader-tax CPA designs a separate structure.</p>
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-amber-200">
              Attorney and CPA review are required before public fintech claims, client contracts, tax elections, or legal filings.
            </div>
          </div>
        </Panel>
        <Panel title="Tax And Legal Calendar" icon={AlertTriangle}>
          <div className="space-y-2">
            {taxEvents.map((event) => {
              const linked = findTask(event.title)
              return (
                <button
                  key={event.title}
                  type="button"
                  onClick={() => linked && drawer?.openTask(linked)}
                  disabled={!linked}
                  className={cn(
                    'flex w-full items-center justify-between rounded-lg bg-gray-950/60 p-3 text-left text-sm',
                    linked ? 'hover:bg-gray-900 cursor-pointer' : 'opacity-80 cursor-default',
                  )}
                >
                  <div>
                    <span className="text-gray-100">{event.title}</span>
                    <span className="ml-2 text-xs text-gray-500">{event.owner}</span>
                    {linked && <span className="ml-2 text-[11px] text-blue-300">walkthrough</span>}
                  </div>
                  <span className="text-xs text-gray-400">{event.date}</span>
                </button>
              )
            })}
          </div>
        </Panel>
      </div>
    </div>
  )
}

function RevenueSection() {
  return (
    <Panel title="Consulting Pipeline" icon={Briefcase}>
      <div className="grid gap-3 md:grid-cols-3">
        {opportunities.map((opportunity) => (
          <div key={opportunity.account} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
            <div className="text-sm font-semibold text-gray-100">{opportunity.account}</div>
            <div className="mt-1 text-xs text-gray-500">{opportunity.offer}</div>
            <div className="mt-3 flex items-center justify-between text-xs">
              <Badge className="border-blue-500/30 bg-blue-500/10 text-blue-300">{opportunity.stage}</Badge>
              <span className="text-gray-300">{currency.format(opportunity.value)}</span>
            </div>
            <div className="mt-3 text-xs text-gray-400">{opportunity.nextStep}</div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function ProductSection() {
  return (
    <Panel title="Product Studio" icon={PackageCheck}>
      <div className="grid gap-3 md:grid-cols-3">
        {productIdeas.map((idea) => (
          <div key={idea.name} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
            <div className="text-sm font-semibold text-gray-100">{idea.name}</div>
            <p className="mt-2 text-xs leading-relaxed text-gray-400">{idea.thesis}</p>
            <div className="mt-3 flex items-center justify-between text-xs">
              <Badge className="border-gray-700 text-gray-300">{idea.stage}</Badge>
              <span className="text-blue-300">{idea.confidence}%</span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function RoboticsSection() {
  return (
    <Panel title="Robotics And 3D Print Lab" icon={Cpu}>
      <div className="grid gap-3 md:grid-cols-3">
        {labJobs.map((job) => (
          <div key={job.item} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
            <div className="text-sm font-semibold text-gray-100">{job.item}</div>
            <div className="mt-1 text-xs text-gray-500">{job.material} - {job.stage}</div>
            <Badge className={job.safety === 'clear' ? riskClasses.low : riskClasses.high}>
              {job.safety}
            </Badge>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function MarketingSection() {
  return (
    <Panel title="Marketing And Public Surface" icon={Megaphone}>
      <div className="grid gap-3 md:grid-cols-3">
        {[
          'Update adamdoherty.com with approved AI adoption consulting positioning.',
          'Draft LinkedIn posts from company operating lessons after approval.',
          'Convert successful internal workflows into case-study candidates.',
        ].map((item) => (
          <div key={item} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4 text-sm text-gray-300">
            {item}
          </div>
        ))}
      </div>
    </Panel>
  )
}

function DocsSection() {
  return (
    <Panel title="Company Docs And Sources" icon={FileText}>
      <div className="grid gap-3 lg:grid-cols-2">
        {companyDocs.map((doc) => (
          <div key={doc.path} className="rounded-lg border border-gray-800 bg-gray-950/60 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-100">{doc.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-gray-400">{doc.purpose}</p>
              </div>
              <ExternalLink className="h-4 w-4 shrink-0 text-gray-600" />
            </div>
            <div className="mt-3 grid gap-1 text-xs text-gray-500">
              <span>{doc.path}</span>
              <span>{doc.owner} - {doc.agent}</span>
              <span>UI: {doc.route} - reviewed {doc.reviewed}</span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function renderSection(section: CompanySection) {
  switch (section) {
    case 'operator': return <OperatorSection />
    case 'tasks': return <TasksSection />
    case 'agents': return <AgentsSection />
    case 'inbox': return <InboxSection />
    case 'approvals': return <ApprovalsSection />
    case 'finance': return <FinanceSection />
    case 'legal': return <LegalSection />
    case 'revenue': return <RevenueSection />
    case 'product': return <ProductSection />
    case 'robotics': return <RoboticsSection />
    case 'marketing': return <MarketingSection />
    case 'docs': return <DocsSection />
    case 'overview':
    default: return <OverviewSection />
  }
}

function GlobalTaskDrawer({ children }: { children: ReactNode }) {
  const [selectedTask, setSelectedTask] = useState<CompanyTaskCard | null>(null)
  const [pendingTaskId, setPendingTaskId] = useState<string | null>(null)
  const [autoCompleteToken, setAutoCompleteToken] = useState(0)
  const { data: liveTasks } = useCompanyWorkItems({ limit: 500 })
  const taskById = useMemo(() => new Map((liveTasks ?? []).map((task) => [task.id, task])), [liveTasks])

  useEffect(() => {
    if (!pendingTaskId) return
    const live = taskById.get(pendingTaskId)
    if (live) {
      setSelectedTask(zeroTaskToCompanyTask(live))
      setPendingTaskId(null)
    }
  }, [pendingTaskId, taskById])

  const value: TaskDrawerContextValue = {
    openTask: (task) => setSelectedTask(task),
    openTaskById: (taskId: string) => {
      const live = taskById.get(taskId)
      if (live) {
        setSelectedTask(zeroTaskToCompanyTask(live))
      } else {
        setPendingTaskId(taskId)
      }
    },
    openTaskForCompletion: (task) => {
      setSelectedTask(task)
      setAutoCompleteToken((value) => value + 1)
    },
  }

  return (
    <TaskDrawerContext.Provider value={value}>
      {children}
      <TaskDetailDrawer task={selectedTask} autoCompleteToken={autoCompleteToken} onClose={() => setSelectedTask(null)} />
    </TaskDrawerContext.Provider>
  )
}

export function CompanyOsPage({ section = 'overview' }: { section?: CompanySection }) {
  return (
    <GlobalTaskDrawer>
      <div className="mx-auto max-w-7xl space-y-6">
        <Header section={section} />
        {renderSection(section)}
        <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4 text-xs text-gray-500">
          <div className="flex items-center gap-2 text-gray-300">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            Guardrail active
          </div>
          <p className="mt-2">
            Zero may summarize, draft, classify, create internal tasks, and prepare reports. Purchases, filings,
            tax elections, legal actions, client communications, public website changes, and account changes stay
            behind approval gates.
          </p>
        </div>
      </div>
    </GlobalTaskDrawer>
  )
}
