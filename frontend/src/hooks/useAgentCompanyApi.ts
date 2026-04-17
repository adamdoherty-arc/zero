import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// Types

export interface AgentRole {
  id: string
  name: string
  description: string
  capabilities: string[]
  system_prompt: string
  llm_provider: string
  llm_model: string
  execution_llm_provider?: string
  execution_llm_model?: string
  delegation_rules: Record<string, unknown>
  is_active: boolean
  created_at: string
}

export interface AgentTask {
  id: string
  project_id?: string
  title: string
  description: string
  task_type: string
  assigned_role: string
  status: string
  priority: number
  dependencies: string[]
  context: Record<string, unknown>
  result?: Record<string, unknown>
  parent_task_id?: string
  cost_usd: number
  created_at: string
  started_at?: string
  completed_at?: string
}

export interface AgentTaskCreate {
  title: string
  description: string
  task_type?: string
  assigned_role?: string
  priority?: number
  context?: Record<string, unknown>
}

export interface AiCompanyStats {
  total_roles: number
  active_roles: number
  total_tasks: number
  tasks_completed: number
  tasks_failed: number
  tasks_in_progress: number
  total_cost_usd: number
  tasks_by_role: Record<string, number>
  tasks_by_type: Record<string, number>
}

export interface TaskFilters {
  status?: string
  role?: string
  task_type?: string
  limit?: number
}

// Query key factory

const companyKeys = {
  all: ['agentCompany'] as const,
  roles: () => [...companyKeys.all, 'roles'] as const,
  tasks: () => [...companyKeys.all, 'tasks'] as const,
  taskList: (filters?: TaskFilters) => [...companyKeys.tasks(), filters] as const,
  task: (id: string) => [...companyKeys.tasks(), id] as const,
  stats: () => [...companyKeys.all, 'stats'] as const,
}

// Hooks

export function useAgentRoles() {
  return useQuery({
    queryKey: companyKeys.roles(),
    queryFn: async (): Promise<AgentRole[]> => {
      const res = await fetch(`${API_URL}/api/company/roles`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch roles')
      return res.json()
    },
    staleTime: 30000,
  })
}

export function useAgentTasks(filters?: TaskFilters) {
  return useQuery({
    queryKey: companyKeys.taskList(filters),
    queryFn: async (): Promise<AgentTask[]> => {
      const params = new URLSearchParams()
      if (filters?.status) params.append('status', filters.status)
      if (filters?.role) params.append('role', filters.role)
      if (filters?.task_type) params.append('task_type', filters.task_type)
      if (filters?.limit !== undefined) params.append('limit', filters.limit.toString())
      const res = await fetch(`${API_URL}/api/company/tasks?${params.toString()}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch tasks')
      return res.json()
    },
    staleTime: 5000,
  })
}

export function useAgentTask(taskId: string) {
  return useQuery({
    queryKey: companyKeys.task(taskId),
    queryFn: async (): Promise<AgentTask> => {
      const res = await fetch(`${API_URL}/api/company/tasks/${taskId}`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch task')
      return res.json()
    },
    enabled: !!taskId,
    staleTime: 5000,
  })
}

export function useCreateAgentTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: AgentTaskCreate): Promise<AgentTask> => {
      const res = await fetch(`${API_URL}/api/company/tasks`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('Failed to create task')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: companyKeys.tasks() })
      qc.invalidateQueries({ queryKey: companyKeys.stats() })
    },
  })
}

export function useExecuteAgentTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (taskId: string): Promise<AgentTask> => {
      const res = await fetch(`${API_URL}/api/company/tasks/${taskId}/execute`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error('Failed to execute task')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: companyKeys.tasks() })
      qc.invalidateQueries({ queryKey: companyKeys.stats() })
    },
  })
}

export function useCeoPlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: { description: string }): Promise<AgentTask[]> => {
      const res = await fetch(`${API_URL}/api/company/plan`, {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error('Failed to create plan')
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: companyKeys.tasks() })
      qc.invalidateQueries({ queryKey: companyKeys.stats() })
    },
  })
}

export function useAiCompanyStats() {
  return useQuery({
    queryKey: companyKeys.stats(),
    queryFn: async (): Promise<AiCompanyStats> => {
      const res = await fetch(`${API_URL}/api/company/stats`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Failed to fetch stats')
      return res.json()
    },
    staleTime: 10000,
  })
}
