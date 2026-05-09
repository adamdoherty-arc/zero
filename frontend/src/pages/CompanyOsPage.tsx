import { Link } from 'react-router-dom'
import { useState } from 'react'
import type { ElementType, FormEvent, ReactNode } from 'react'
import {
  Activity,
  AlertTriangle,
  Banknote,
  Bot,
  Briefcase,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Columns3,
  Copy,
  Cpu,
  ExternalLink,
  FileText,
  Filter,
  Gavel,
  HelpCircle,
  Inbox,
  Megaphone,
  MessageSquareText,
  PackageCheck,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  Table2,
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
  useCompanySeedStatus,
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
  useUpdateCompanyWorkItem,
} from '@/hooks/useCompanyWorkItemsApi'
import { toast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import type { CompanyWorkItemReview, Task as ZeroTask, TaskUpdate as ZeroTaskUpdate } from '@/types'

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
  done: 'Done',
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
          <div className="col-span-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={busy}
              onClick={() => completeTask.mutate(task.id, {
                onSuccess: (result) => toast({
                  title: result.status === 'blocked' ? 'Approval gate queued' : 'Task completed',
                  description: result.blocked_reason,
                }),
                onError: (error) => toast({ title: 'Complete failed', description: error.message }),
              })}
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

function OverviewSection() {
  const { tasks, isLive } = useCompanyTaskCards()
  const { data: liveApprovals, isLoading: approvalsLoading } = useAgentApprovals('pending', 4)
  const nextTasks = tasks.filter((task) => task.nextAction)
  const pendingApprovals = approvals.filter((approval) => approval.status === 'pending').slice(0, 4)
  const hasLiveApprovals = Boolean(liveApprovals?.length)

  return (
    <div className="space-y-6">
      <OperatorStatusStrip />
      <DashboardReviewPanel />

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
            {nextTasks.map((task) => <TaskCard key={task.id} task={task} />)}
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
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {topToday.next_tasks.slice(0, 4).map((task) => (
              <div key={task.id} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
                <div className="text-sm font-medium text-gray-100">{task.title}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge className={statusBadgeClass(task.status)}>{task.status}</Badge>
                  <Badge className="border-gray-700 text-gray-300">{task.priority}</Badge>
                  {task.risk === 'high' && <Badge className={riskClasses.high}>approval gate</Badge>}
                </div>
              </div>
            ))}
          </div>
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

function TaskDetailDrawer({ task, onClose }: { task: CompanyTaskCard | null; onClose: () => void }) {
  const updateTask = useUpdateCompanyWorkItem()
  const completeTask = useCompleteCompanyWorkItem()
  const reopenTask = useReopenCompanyWorkItem()
  const { data: events } = useCompanyTaskEvents(task?.id)
  const { data: review } = useCompanyTaskReview(task?.id)
  const { data: taskQuestions } = useCompanyAgentQuestions('open', task?.id, undefined, 10)

  if (!task?.zeroTask) return null
  const zero = task.zeroTask
  const busy = updateTask.isPending || completeTask.isPending || reopenTask.isPending
  const update = (data: ZeroTaskUpdate) => {
    updateTask.mutate(
      { id: task.id, data },
      {
        onSuccess: () => toast({ title: 'Task saved' }),
        onError: (error) => toast({ title: 'Task save failed', description: error.message }),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60">
      <aside className="ml-auto flex h-full w-full max-w-2xl flex-col border-l border-gray-800 bg-gray-950 shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-gray-800 p-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-blue-300">Company Work Item</div>
            <h2 className="mt-2 text-lg font-semibold text-white">{task.title}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-gray-400 hover:bg-gray-900 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <label className="grid gap-1 text-xs text-gray-500">
            Title
            <input
              defaultValue={zero.title}
              onBlur={(event) => event.target.value !== zero.title && update({ title: event.target.value })}
              className="h-9 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm text-gray-100 outline-none focus:border-blue-500"
            />
          </label>
          <label className="grid gap-1 text-xs text-gray-500">
            Description
            <textarea
              defaultValue={zero.description ?? ''}
              onBlur={(event) => event.target.value !== (zero.description ?? '') && update({ description: event.target.value })}
              className="min-h-28 rounded-md border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-100 outline-none focus:border-blue-500"
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
              disabled={busy}
              onClick={() => completeTask.mutate(task.id, {
                onSuccess: (result) => toast({ title: result.status === 'blocked' ? 'Approval gate queued' : 'Task completed', description: result.blocked_reason }),
                onError: (error) => toast({ title: 'Complete failed', description: error.message }),
              })}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-emerald-600 px-3 text-sm font-medium text-white disabled:opacity-60"
            >
              <CheckCircle2 className="h-4 w-4" />
              Complete
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => reopenTask.mutate(task.id, {
                onSuccess: () => toast({ title: 'Task reopened' }),
                onError: (error) => toast({ title: 'Reopen failed', description: error.message }),
              })}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-gray-800 bg-gray-900 px-3 text-sm font-medium text-gray-200 disabled:opacity-60"
            >
              <RotateCcw className="h-4 w-4" />
              Reopen
            </button>
          </div>
          <section>
            <h3 className="mb-2 text-sm font-semibold text-gray-100">Audit Trail</h3>
            <div className="space-y-2">
              {(events ?? []).slice(0, 12).map((event) => (
                <div key={event.id} className="rounded-md border border-gray-800 bg-gray-900/60 p-2 text-xs text-gray-400">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-gray-200">{event.event_type}</span>
                    <span>{formatDateTime(event.created_at)}</span>
                  </div>
                  {event.summary && <div className="mt-1">{event.summary}</div>}
                  <div className="mt-1 text-gray-600">{event.actor}</div>
                </div>
              ))}
              {!events?.length && <div className="text-xs text-gray-500">No task events recorded yet.</div>}
            </div>
          </section>
        </div>
      </aside>
    </div>
  )
}

function TasksSection() {
  const { tasks, seedPreviewTasks, isLoading, isLive, error, reviewSummary } = useCompanyTaskCards()
  const createTask = useCreateCompanyWorkItem()
  const updateTask = useUpdateCompanyWorkItem()
  const importSeed = useImportCompanySeedBacklog()
  const { data: seedStatus } = useCompanySeedStatus()
  const [title, setTitle] = useState('')
  const [domain, setDomain] = useState('Formation')
  const [priority, setPriority] = useState<ZeroTask['priority']>('high')
  const [view, setView] = useState<'kanban' | 'table'>('kanban')
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [selectedTask, setSelectedTask] = useState<CompanyTaskCard | null>(null)
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null)

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
      <TaskDetailDrawer task={selectedTask} onClose={() => setSelectedTask(null)} />
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

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Finance Setup Rails" icon={ClipboardList}>
        <div className="space-y-2">
          {financeSetupRails.map((item) => (
            <div key={item.rail} className="rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-gray-100">{item.rail}</div>
                  <div className="mt-1 text-xs leading-relaxed text-gray-400">{item.next}</div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Badge className={riskClasses[item.risk]}>{item.risk}</Badge>
                  <Badge className={statusBadgeClass(item.status)}>{item.status}</Badge>
                </div>
              </div>
              <div className="mt-2 text-xs text-gray-500">{item.owner}</div>
            </div>
          ))}
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
  )
}

function LegalSection() {
  return (
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
          {taxEvents.map((event) => (
            <div key={event.title} className="flex items-center justify-between rounded-lg bg-gray-950/60 p-3 text-sm">
              <div><span className="text-gray-100">{event.title}</span><span className="ml-2 text-xs text-gray-500">{event.owner}</span></div>
              <span className="text-xs text-gray-400">{event.date}</span>
            </div>
          ))}
        </div>
      </Panel>
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

export function CompanyOsPage({ section = 'overview' }: { section?: CompanySection }) {
  return (
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
  )
}
