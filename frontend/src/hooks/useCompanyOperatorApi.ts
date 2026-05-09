import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAuthHeaders } from '@/lib/auth'
import type { CompanyDashboardReviewSummary, Task, TaskCreate, TaskUpdate } from '@/types'

const API_URL = ''

export interface CompanyOperatorTask {
  id: string
  title: string
  description?: string
  status: string
  priority: string
  category?: string
  source?: string
  project_id?: string
  sprint_id?: string
  blocked_reason?: string
  created_at?: string
  updated_at?: string
  completed_at?: string
  risk?: 'low' | 'high'
  formation?: boolean
}

export interface CompanyOperatorApproval {
  id: string
  tool_name: string
  tier: string
  summary: string
  arguments: Record<string, unknown>
  requested_by: string
  status: string
  decision_reason?: string
  decided_by?: string
  created_at?: string
  decided_at?: string
  executed_at?: string
  expires_at?: string
}

export interface CompanySubagentStatus {
  id: string
  name: string
  description?: string
  capabilities: string[]
  autonomy: string
  agent_status?: string
  active_tasks: number
  running_tasks?: number
  queued_tasks?: number
  waiting_on_adam?: number
  waiting_on_approval?: number
  needs_review_tasks?: number
  question_count?: number
  approval_count?: number
  total_tasks: number
  last_run_at?: string
  next_scheduled_run?: string
  current_assignment?: string
  blocked_reason?: string
  idle_reason?: string
  last_output?: string
  last_task_status?: string
  cost_usd?: number
}

export interface CompanyPromptLabStatus {
  runs_100?: number
  graded_100?: number
  ungraded_100?: number
  avg_quality?: number | null
  latest?: Array<Record<string, unknown>>
}

export interface CompanyFormationStatus {
  total: number
  done: number
  ready: number
  blocked: number
  percent: number
  tasks: CompanyOperatorTask[]
}

export interface CompanyOperatorRun {
  id?: string | null
  run_type: string
  requested_by?: string
  status: string
  summary?: string
  report: Record<string, unknown>
  actions: Array<Record<string, unknown>>
  errors: string[]
  started_at?: string
  completed_at?: string
  created_at?: string
}

export interface CompanyAgentQuestion {
  id: string
  question: string
  context: Record<string, unknown>
  answer_type: string
  options: unknown[]
  priority: string
  status: string
  asked_by_agent: string
  task_id?: string | null
  agent_task_id?: string | null
  operator_run_id?: string | null
  source: string
  answer?: string | null
  answered_by?: string | null
  created_at?: string
  answered_at?: string | null
  dismissed_at?: string | null
  updated_at?: string | null
  recommended_default?: string | null
  why_needed?: string | null
  blocks_progress?: boolean | null
  decision_type?: string | null
}

export interface CompanyAgentQuestionTriage {
  requested_by: string
  reviewed: number
  highlighted: number
  dismissed: number
  max_open?: number
  top_questions: CompanyAgentQuestion[]
  dismissed_questions: CompanyAgentQuestion[]
  summary: string
}

export interface CompanyOperatorToday {
  question: string
  answer: string
  next_tasks: CompanyOperatorTask[]
  approvals: CompanyOperatorApproval[]
  blocked_tasks: CompanyOperatorTask[]
  formation: CompanyFormationStatus
}

export interface CompanyOperatorStatus {
  operator: string
  company: string
  active: boolean
  autonomy: string
  paused: boolean
  overnight_enabled: boolean
  agent_work_enabled?: boolean
  agent_work_interval_minutes?: number
  heartbeat?: CompanyOperatorRun | null
  latest_agent_work?: CompanyOperatorRun | null
  latest_overnight?: CompanyOperatorRun | null
  today: CompanyOperatorToday
  counts: Record<string, number>
  formation: CompanyFormationStatus
  approvals: CompanyOperatorApproval[]
  questions?: CompanyAgentQuestion[]
  blocked_tasks: CompanyOperatorTask[]
  subagents: CompanySubagentStatus[]
  prompt_lab: CompanyPromptLabStatus
  dashboard_review?: CompanyDashboardReviewSummary
}

export interface CompanyOperatorOvernight {
  latest: CompanyOperatorRun
  recent: CompanyOperatorRun[]
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
    ...options,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(detail.detail || response.statusText || `HTTP ${response.status}`))
  }
  return response.json()
}

export const companyOperatorKeys = {
  all: ['companyOperator'] as const,
  status: () => [...companyOperatorKeys.all, 'status'] as const,
  runs: (runType?: string, limit?: number) => [...companyOperatorKeys.all, 'runs', runType, limit] as const,
  today: () => [...companyOperatorKeys.all, 'today'] as const,
  overnight: () => [...companyOperatorKeys.all, 'overnight'] as const,
  report: (reportType?: string) => [...companyOperatorKeys.all, 'report', reportType] as const,
  approvals: (status?: string, limit?: number) => ['agentApprovals', status, limit] as const,
  questions: (status?: string, taskId?: string, agentTaskId?: string, limit?: number) =>
    [...companyOperatorKeys.all, 'questions', status, taskId, agentTaskId, limit] as const,
}

export function useCompanyOperatorStatus() {
  return useQuery({
    queryKey: companyOperatorKeys.status(),
    queryFn: () => fetchJson<CompanyOperatorStatus>('/api/company/operator/status'),
    refetchInterval: 30000,
  })
}

export function useCompanyOperatorRuns(runType?: string, limit = 20) {
  return useQuery({
    queryKey: companyOperatorKeys.runs(runType, limit),
    queryFn: () => {
      const params = new URLSearchParams()
      if (runType) params.set('run_type', runType)
      params.set('limit', String(limit))
      return fetchJson<CompanyOperatorRun[]>(`/api/company/operator/runs?${params.toString()}`)
    },
    refetchInterval: 30000,
  })
}

export function useCompanyOperatorToday() {
  return useQuery({
    queryKey: companyOperatorKeys.today(),
    queryFn: () => fetchJson<CompanyOperatorToday>('/api/company/operator/today'),
    refetchInterval: 30000,
  })
}

export function useCompanyOperatorOvernight() {
  return useQuery({
    queryKey: companyOperatorKeys.overnight(),
    queryFn: () => fetchJson<CompanyOperatorOvernight>('/api/company/operator/overnight'),
    refetchInterval: 60000,
  })
}

export function useCompanyOperatorLatestReport(reportType?: string) {
  return useQuery({
    queryKey: companyOperatorKeys.report(reportType),
    queryFn: () => {
      const params = reportType ? `?report_type=${encodeURIComponent(reportType)}` : ''
      return fetchJson<CompanyOperatorRun>(`/api/company/operator/report/latest${params}`)
    },
    refetchInterval: 60000,
  })
}

export function useAgentApprovals(status?: string, limit = 50) {
  return useQuery({
    queryKey: companyOperatorKeys.approvals(status, limit),
    queryFn: () => {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      params.set('limit', String(limit))
      return fetchJson<CompanyOperatorApproval[]>(`/api/agent-approvals?${params.toString()}`)
    },
    refetchInterval: 30000,
  })
}

export function useCompanyAgentQuestions(status = 'open', taskId?: string, agentTaskId?: string, limit = 50) {
  return useQuery({
    queryKey: companyOperatorKeys.questions(status, taskId, agentTaskId, limit),
    queryFn: () => {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      if (taskId) params.set('task_id', taskId)
      if (agentTaskId) params.set('agent_task_id', agentTaskId)
      params.set('limit', String(limit))
      return fetchJson<CompanyAgentQuestion[]>(`/api/company/operator/questions?${params.toString()}`)
    },
    refetchInterval: 30000,
  })
}

export function useDecideAgentApproval() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: 'approved' | 'rejected'; reason?: string }) =>
      fetchJson<CompanyOperatorApproval>(`/api/agent-approvals/${id}/decide`, {
        method: 'POST',
        body: JSON.stringify({ status, reason, decided_by: 'dashboard' }),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useAnswerCompanyAgentQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) =>
      fetchJson<CompanyAgentQuestion>(`/api/company/operator/questions/${id}/answer`, {
        method: 'POST',
        body: JSON.stringify({ answer, answered_by: 'dashboard' }),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useDismissCompanyAgentQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      fetchJson<CompanyAgentQuestion>(`/api/company/operator/questions/${id}/dismiss`, {
        method: 'POST',
        body: JSON.stringify({ answered_by: 'dashboard' }),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useTriageCompanyAgentQuestions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { requested_by?: string; limit?: number; max_open?: number } = {}) =>
      fetchJson<CompanyAgentQuestionTriage>('/api/company/operator/questions/triage', {
        method: 'POST',
        body: JSON.stringify({
          requested_by: data.requested_by ?? 'dashboard',
          limit: data.limit ?? 200,
          max_open: data.max_open ?? 25,
        }),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useRunCompanyPromptEval() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { limit?: number } = {}) =>
      fetchJson<CompanyOperatorRun>('/api/company/operator/prompt-eval', {
        method: 'POST',
        body: JSON.stringify({ limit: data.limit ?? 20 }),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

function invalidateOperator(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: companyOperatorKeys.all })
  qc.invalidateQueries({ queryKey: ['companyWorkItems'] })
  qc.invalidateQueries({ queryKey: ['tasks'] })
  qc.invalidateQueries({ queryKey: ['agentCompany'] })
  qc.invalidateQueries({ queryKey: ['agentApprovals'] })
  qc.invalidateQueries({ queryKey: companyOperatorKeys.questions() })
}

export function useRunCompanyOperatorTick() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { run_type?: string; requested_by?: string; force?: boolean; target_agent_id?: string } = {}) =>
      fetchJson<CompanyOperatorRun>('/api/company/operator/tick', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useGenerateCompanyOperatorReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { report_type?: string; requested_by?: string } = {}) =>
      fetchJson<CompanyOperatorRun>('/api/company/operator/report', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function usePauseCompanyOperator() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchJson<Record<string, unknown>>('/api/company/operator/pause', { method: 'POST' }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useResumeCompanyOperator() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchJson<Record<string, unknown>>('/api/company/operator/resume', { method: 'POST' }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useCreateCompanyOperatorTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskCreate) =>
      fetchJson<Task>('/api/company/operator/tasks', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useUpdateCompanyOperatorTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: TaskUpdate }) =>
      fetchJson<Task>(`/api/company/operator/tasks/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}

export function useAssignCompanyTaskToSubagent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { task_id: string; role_id: string; requested_by?: string }) =>
      fetchJson<Record<string, unknown>>('/api/company/operator/assign', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidateOperator(qc),
  })
}
