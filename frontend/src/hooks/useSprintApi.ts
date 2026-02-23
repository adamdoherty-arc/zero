import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type {
  Sprint, SprintBoard,
  Task, TaskCreate, TaskUpdate, TaskMove,
  OrchestratorStatus, EnhancementSignal, EnhancementStats,
  Project, ProjectCreate, ProjectUpdate, ProjectScanResult, ProjectContext, ProjectStatus,
  GitHubConnectRequest, GitHubStatus, GitHubSyncResult,
  Note, NoteCreate, NoteUpdate, NoteType,
  UserProfile, UserProfileUpdate, UserFact, UserContact,
  RecallResult, KnowledgeStats, KnowledgeCategory,
  TranscriptionResult, TranscriptionJob, TranscriptionStatus,
  WhisperModel, WhisperModelInfo, TranscribeToNoteResult,
  Email, EmailSummary, EmailLabel, EmailDigest, EmailSyncStatus,
  EmailCategory, EmailStatusType, EmailToTaskRequest,
  CalendarEvent, EventSummary, CalendarInfo, EventCreate, EventUpdate,
  CalendarSyncStatus, TodaySchedule, TaskToEventRequest,
  Reminder, ReminderCreate, ReminderUpdate, ReminderStatus,
  DailyBriefing, Notification, NotificationChannel, AssistantStatus, ReminderStats,
  ResearchRule, ResearchRuleStats,
} from '../types'

import { getAuthHeaders } from '@/lib/auth'

const API_BASE = '/api'

// Query key factory for cache management
export const sprintKeys = {
  all: ['sprints'] as const,
  lists: () => [...sprintKeys.all, 'list'] as const,
  list: (filters?: { project_id?: number; status?: string }) => [...sprintKeys.lists(), filters] as const,
  current: () => [...sprintKeys.all, 'current'] as const,
  detail: (id: string) => [...sprintKeys.all, 'detail', id] as const,
  board: (id: string) => [...sprintKeys.all, 'board', id] as const,
}

export const taskKeys = {
  all: ['tasks'] as const,
  lists: () => [...taskKeys.all, 'list'] as const,
  list: (filters?: { sprint_id?: string }) => [...taskKeys.lists(), filters] as const,
  backlog: () => [...taskKeys.all, 'backlog'] as const,
  detail: (id: string) => [...taskKeys.all, 'detail', id] as const,
}

export const orchestratorKeys = {
  status: ['orchestrator', 'status'] as const,
}

export const enhancementKeys = {
  signals: (filters?: object) => ['enhancements', 'signals', filters] as const,
  stats: ['enhancements', 'stats'] as const,
}

export const projectKeys = {
  all: ['projects'] as const,
  lists: () => [...projectKeys.all, 'list'] as const,
  list: (filters?: { status?: ProjectStatus }) => [...projectKeys.lists(), filters] as const,
  detail: (id: string) => [...projectKeys.all, 'detail', id] as const,
  context: (id: string) => [...projectKeys.all, 'context', id] as const,
  tasks: (id: string) => [...projectKeys.all, 'tasks', id] as const,
  githubStatus: (id: string) => [...projectKeys.all, 'github', id] as const,
}

// Fetch helper
async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// Sprint hooks
export function useSprints(filters?: { project_id?: number; status?: string }) {
  return useQuery({
    queryKey: sprintKeys.list(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.project_id) params.set('project_id', String(filters.project_id))
      if (filters?.status) params.set('status', filters.status)
      const queryStr = params.toString()
      return fetchApi<Sprint[]>(`/sprints${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useCurrentSprint() {
  return useQuery({
    queryKey: sprintKeys.current(),
    queryFn: () => fetchApi<Sprint | null>('/sprints/current'),
  })
}

export function useSprint(id: string) {
  return useQuery({
    queryKey: sprintKeys.detail(id),
    queryFn: () => fetchApi<Sprint>(`/sprints/${id}`),
    enabled: !!id,
  })
}

export function useSprintBoard(id: string) {
  return useQuery({
    queryKey: sprintKeys.board(id),
    queryFn: () => fetchApi<SprintBoard>(`/sprints/${id}/board`),
    enabled: !!id,
    refetchInterval: 30000, // Refresh board every 30s
  })
}

// Task hooks
export function useTasks(sprintId?: string) {
  return useQuery({
    queryKey: taskKeys.list({ sprint_id: sprintId }),
    queryFn: () => {
      const params = sprintId ? `?sprint_id=${sprintId}` : ''
      return fetchApi<Task[]>(`/tasks${params}`)
    },
  })
}

export function useBacklog() {
  return useQuery({
    queryKey: taskKeys.backlog(),
    queryFn: () => fetchApi<Task[]>('/tasks/backlog'),
  })
}

export function useTask(id: string) {
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: () => fetchApi<Task>(`/tasks/${id}`),
    enabled: !!id,
  })
}

export function useCreateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskCreate) =>
      fetchApi<Task>('/tasks', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      if (task.sprint_id) {
        queryClient.invalidateQueries({ queryKey: sprintKeys.board(task.sprint_id) })
      }
    },
  })
}

export function useUpdateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: TaskUpdate }) =>
      fetchApi<Task>(`/tasks/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(task.id) })
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() })
      if (task.sprint_id) {
        queryClient.invalidateQueries({ queryKey: sprintKeys.board(task.sprint_id) })
      }
    },
  })
}

export function useMoveTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, move }: { id: string; move: TaskMove }) =>
      fetchApi<Task>(`/tasks/${id}/move`, {
        method: 'POST',
        body: JSON.stringify(move),
      }),
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      if (task.sprint_id) {
        queryClient.invalidateQueries({ queryKey: sprintKeys.board(task.sprint_id) })
        queryClient.invalidateQueries({ queryKey: sprintKeys.detail(task.sprint_id) })
      }
    },
  })
}

export function useDeleteTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<void>(`/tasks/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({ queryKey: sprintKeys.all })
    },
  })
}

// Orchestrator hooks
export function useOrchestratorStatus() {
  return useQuery({
    queryKey: orchestratorKeys.status,
    queryFn: () => fetchApi<OrchestratorStatus>('/orchestrator/status'),
    refetchInterval: 5000, // Refresh status every 5s
  })
}

export function useStartOrchestrator() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<{ status: string }>('/orchestrator/start', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orchestratorKeys.status })
    },
  })
}

export function useStopOrchestrator() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<{ status: string }>('/orchestrator/stop', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orchestratorKeys.status })
    },
  })
}

// Enhancement hooks
export function useEnhancementSignals(status?: string) {
  return useQuery({
    queryKey: enhancementKeys.signals({ status }),
    queryFn: () => {
      const params = status ? `?status=${status}` : ''
      return fetchApi<EnhancementSignal[]>(`/enhancements/signals${params}`)
    },
  })
}

export function useEnhancementStats() {
  return useQuery({
    queryKey: enhancementKeys.stats,
    queryFn: () => fetchApi<EnhancementStats>('/enhancements/stats'),
  })
}

export function useTriggerEnhancementScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<{ status: string }>('/enhancements/scan', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: enhancementKeys.signals() })
      queryClient.invalidateQueries({ queryKey: enhancementKeys.stats })
    },
  })
}

// Project hooks
export function useProjects(status?: ProjectStatus) {
  return useQuery({
    queryKey: projectKeys.list({ status }),
    queryFn: () => {
      const params = status ? `?status=${status}` : ''
      return fetchApi<Project[]>(`/projects${params}`)
    },
  })
}

export function useProject(id: string) {
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: () => fetchApi<Project>(`/projects/${id}`),
    enabled: !!id,
  })
}

export function useProjectContext(id: string) {
  return useQuery({
    queryKey: projectKeys.context(id),
    queryFn: () => fetchApi<ProjectContext>(`/projects/${id}/context`),
    enabled: !!id,
  })
}

export function useProjectTasks(id: string) {
  return useQuery({
    queryKey: projectKeys.tasks(id),
    queryFn: () => fetchApi<Task[]>(`/projects/${id}/tasks`),
    enabled: !!id,
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectCreate) =>
      fetchApi<Project>('/projects', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.all })
    },
  })
}

export function useUpdateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ProjectUpdate }) =>
      fetchApi<Project>(`/projects/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(project.id) })
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<void>(`/projects/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.all })
    },
  })
}

export function useScanProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<ProjectScanResult>(`/projects/${id}/scan`, { method: 'POST' }),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useAnalyzeProjectPath() {
  return useMutation({
    mutationFn: (path: string) =>
      fetchApi<{
        name: string
        description: string
        project_type: string
        tech_stack: string[]
        tags: string[]
        github_url?: string
      }>('/projects/analyze', {
        method: 'POST',
        body: JSON.stringify({ path }),
      }),
  })
}

// ============================================================================
// GitHub Integration Hooks
// ============================================================================

export function useGitHubStatus(projectId: string) {
  return useQuery({
    queryKey: projectKeys.githubStatus(projectId),
    queryFn: () => fetchApi<GitHubStatus>(`/projects/${projectId}/github/status`),
    enabled: !!projectId,
  })
}

export function useGitHubConnect() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, data }: { projectId: string; data: GitHubConnectRequest }) =>
      fetchApi<{ status: string; github_owner: string; github_repo: string }>(`/projects/${projectId}/github/connect`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.githubStatus(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useGitHubSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) =>
      fetchApi<GitHubSyncResult>(`/projects/${projectId}/github/sync`, { method: 'POST' }),
    onSuccess: (_, projectId) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.githubStatus(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useGitHubDisconnect() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) =>
      fetchApi<{ status: string }>(`/projects/${projectId}/github/disconnect`, { method: 'POST' }),
    onSuccess: (_, projectId) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.githubStatus(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useGitHubSyncToTasks() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, sprintId }: { projectId: string; sprintId?: string }) => {
      const params = sprintId ? `?sprint_id=${sprintId}` : ''
      return fetchApi<{ tasks_created: number }>(`/projects/${projectId}/github/sync-to-tasks${params}`, {
        method: 'POST',
      })
    },
    onSuccess: (_, { projectId }) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: projectKeys.tasks(projectId) })
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({ queryKey: sprintKeys.all })
    },
  })
}

// ============================================================================
// Knowledge / Second Brain Hooks
// ============================================================================

export const knowledgeKeys = {
  all: ['knowledge'] as const,
  notes: () => [...knowledgeKeys.all, 'notes'] as const,
  notesList: (filters?: { type?: NoteType; tags?: string; search?: string; category_id?: string }) =>
    [...knowledgeKeys.notes(), 'list', filters] as const,
  noteDetail: (id: string) => [...knowledgeKeys.notes(), 'detail', id] as const,
  user: () => [...knowledgeKeys.all, 'user'] as const,
  stats: () => [...knowledgeKeys.all, 'stats'] as const,
  recall: (context: string) => [...knowledgeKeys.all, 'recall', context] as const,
  categories: () => [...knowledgeKeys.all, 'categories'] as const,
}

export function useKnowledgeCategories() {
  return useQuery({
    queryKey: knowledgeKeys.categories(),
    queryFn: () => fetchApi<KnowledgeCategory[]>('/knowledge/categories?tree=true'),
  })
}

export function useNotes(filters?: { type?: NoteType; tags?: string; search?: string; category_id?: string; limit?: number }) {
  return useQuery({
    queryKey: knowledgeKeys.notesList(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.type) params.set('type', filters.type)
      if (filters?.tags) params.set('tags', filters.tags)
      if (filters?.search) params.set('search', filters.search)
      if (filters?.category_id) params.set('category_id', filters.category_id)
      if (filters?.limit) params.set('limit', String(filters.limit))
      const queryStr = params.toString()
      return fetchApi<Note[]>(`/knowledge/notes${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useNote(id: string) {
  return useQuery({
    queryKey: knowledgeKeys.noteDetail(id),
    queryFn: () => fetchApi<Note>(`/knowledge/notes/${id}`),
    enabled: !!id,
  })
}

export function useCreateNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: NoteCreate) =>
      fetchApi<Note>('/knowledge/notes', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.notes() })
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.stats() })
    },
  })
}

export function useUpdateNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: NoteUpdate }) =>
      fetchApi<Note>(`/knowledge/notes/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (note) => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.noteDetail(note.id) })
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.notes() })
    },
  })
}

export function useDeleteNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<void>(`/knowledge/notes/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.notes() })
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.stats() })
    },
  })
}

export function useUserProfile() {
  return useQuery({
    queryKey: knowledgeKeys.user(),
    queryFn: () => fetchApi<UserProfile>('/knowledge/user'),
  })
}

export function useUpdateUserProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: UserProfileUpdate) =>
      fetchApi<UserProfile>('/knowledge/user', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.user() })
    },
  })
}

export function useLearnFact() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ fact, category, source }: { fact: string; category?: string; source?: string }) => {
      const params = new URLSearchParams()
      params.set('fact', fact)
      if (category) params.set('category', category)
      if (source) params.set('source', source)
      return fetchApi<UserFact>(`/knowledge/user/facts?${params.toString()}`, {
        method: 'POST',
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.user() })
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.stats() })
    },
  })
}

export function useAddContact() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (contact: UserContact) =>
      fetchApi<UserProfile>('/knowledge/user/contacts', {
        method: 'POST',
        body: JSON.stringify(contact),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.user() })
    },
  })
}

export function useKnowledgeStats() {
  return useQuery({
    queryKey: knowledgeKeys.stats(),
    queryFn: () => fetchApi<KnowledgeStats>('/knowledge/stats'),
  })
}

export function useRecall(context: string, options?: {
  limit?: number
  include_notes?: boolean
  include_facts?: boolean
  include_tasks?: boolean
}) {
  return useQuery({
    queryKey: knowledgeKeys.recall(context),
    queryFn: () => {
      const params = new URLSearchParams()
      if (options?.limit) params.set('limit', String(options.limit))
      if (options?.include_notes !== undefined) params.set('include_notes', String(options.include_notes))
      if (options?.include_facts !== undefined) params.set('include_facts', String(options.include_facts))
      if (options?.include_tasks !== undefined) params.set('include_tasks', String(options.include_tasks))
      const queryStr = params.toString()
      return fetchApi<RecallResult>(`/knowledge/recall/${encodeURIComponent(context)}${queryStr ? `?${queryStr}` : ''}`)
    },
    enabled: !!context && context.length > 2,
  })
}

// ============================================================================
// Audio Transcription Hooks
// ============================================================================

export const audioKeys = {
  all: ['audio'] as const,
  models: () => [...audioKeys.all, 'models'] as const,
  formats: () => [...audioKeys.all, 'formats'] as const,
  jobs: () => [...audioKeys.all, 'jobs'] as const,
  jobsList: (status?: TranscriptionStatus) => [...audioKeys.jobs(), 'list', status] as const,
  jobDetail: (id: string) => [...audioKeys.all, 'job', id] as const,
}

export function useWhisperModels() {
  return useQuery({
    queryKey: audioKeys.models(),
    queryFn: () => fetchApi<{ models: WhisperModelInfo[]; default: string }>('/audio/models'),
    staleTime: 1000 * 60 * 60, // Cache for 1 hour
  })
}

export function useAudioFormats() {
  return useQuery({
    queryKey: audioKeys.formats(),
    queryFn: () => fetchApi<{ formats: string[]; description: string }>('/audio/formats'),
    staleTime: 1000 * 60 * 60, // Cache for 1 hour
  })
}

export function useTranscriptionJobs(status?: TranscriptionStatus) {
  return useQuery({
    queryKey: audioKeys.jobsList(status),
    queryFn: () => {
      const params = status ? `?status=${status}` : ''
      return fetchApi<TranscriptionJob[]>(`/audio/jobs${params}`)
    },
  })
}

export function useTranscriptionJob(id: string) {
  return useQuery({
    queryKey: audioKeys.jobDetail(id),
    queryFn: () => fetchApi<TranscriptionJob>(`/audio/jobs/${id}`),
    enabled: !!id,
  })
}

export function useTranscribeAudio() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      file,
      model = 'base',
      language,
    }: {
      file: File
      model?: WhisperModel
      language?: string
    }) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('model', model)
      if (language) formData.append('language', language)

      const response = await fetch(`${API_BASE}/audio/transcribe`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(error.detail || `HTTP ${response.status}`)
      }

      return response.json() as Promise<TranscriptionResult>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: audioKeys.jobs() })
    },
  })
}

export function useTranscribeToNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      file,
      model = 'base',
      language,
      title,
      tags,
      projectId,
      taskId,
    }: {
      file: File
      model?: WhisperModel
      language?: string
      title?: string
      tags?: string[]
      projectId?: string
      taskId?: string
    }) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('model', model)
      if (language) formData.append('language', language)
      if (title) formData.append('title', title)
      if (tags?.length) formData.append('tags', tags.join(','))
      if (projectId) formData.append('project_id', projectId)
      if (taskId) formData.append('task_id', taskId)

      const response = await fetch(`${API_BASE}/audio/transcribe-to-note`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(error.detail || `HTTP ${response.status}`)
      }

      return response.json() as Promise<TranscribeToNoteResult>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: audioKeys.jobs() })
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.notes() })
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.stats() })
    },
  })
}

// ============================================================================
// Email Hooks
// ============================================================================

export const emailKeys = {
  all: ['email'] as const,
  status: () => [...emailKeys.all, 'status'] as const,
  messages: () => [...emailKeys.all, 'messages'] as const,
  messagesList: (filters?: { category?: EmailCategory; status?: EmailStatusType }) =>
    [...emailKeys.messages(), 'list', filters] as const,
  messageDetail: (id: string) => [...emailKeys.messages(), 'detail', id] as const,
  labels: () => [...emailKeys.all, 'labels'] as const,
  digest: () => [...emailKeys.all, 'digest'] as const,
}

export function useEmailStatus() {
  return useQuery({
    queryKey: emailKeys.status(),
    queryFn: () => fetchApi<EmailSyncStatus>('/email/status'),
  })
}

export function useEmails(filters?: { category?: EmailCategory; status?: EmailStatusType; limit?: number; offset?: number }) {
  return useQuery({
    queryKey: emailKeys.messagesList(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.category) params.set('category', filters.category)
      if (filters?.status) params.set('status', filters.status)
      if (filters?.limit) params.set('limit', String(filters.limit))
      if (filters?.offset) params.set('offset', String(filters.offset))
      const queryStr = params.toString()
      return fetchApi<EmailSummary[]>(`/email/messages${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useEmail(id: string) {
  return useQuery({
    queryKey: emailKeys.messageDetail(id),
    queryFn: () => fetchApi<Email>(`/email/messages/${id}`),
    enabled: !!id,
  })
}

export function useEmailLabels() {
  return useQuery({
    queryKey: emailKeys.labels(),
    queryFn: () => fetchApi<EmailLabel[]>('/email/labels'),
  })
}

export function useEmailDigest() {
  return useQuery({
    queryKey: emailKeys.digest(),
    queryFn: () => fetchApi<EmailDigest>('/email/digest'),
  })
}

export function useSyncEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (options?: { max_results?: number; days_back?: number }) => {
      const params = new URLSearchParams()
      if (options?.max_results) params.set('max_results', String(options.max_results))
      if (options?.days_back) params.set('days_back', String(options.days_back))
      const queryStr = params.toString()
      return fetchApi<{ status: string; synced_at: string; total_messages: number; unread_count: number }>(
        `/email/sync${queryStr ? `?${queryStr}` : ''}`,
        { method: 'POST' }
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: emailKeys.all })
    },
  })
}

export function useMarkEmailRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (emailId: string) =>
      fetchApi<{ status: string }>(`/email/messages/${emailId}/read`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: emailKeys.messages() })
      queryClient.invalidateQueries({ queryKey: emailKeys.status() })
    },
  })
}

export function useArchiveEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (emailId: string) =>
      fetchApi<{ status: string }>(`/email/messages/${emailId}/archive`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: emailKeys.messages() })
      queryClient.invalidateQueries({ queryKey: emailKeys.status() })
    },
  })
}

export function useStarEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ emailId, starred }: { emailId: string; starred: boolean }) =>
      fetchApi<{ status: string; starred: boolean }>(
        `/email/messages/${emailId}/star?starred=${starred}`,
        { method: 'POST' }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: emailKeys.messages() })
    },
  })
}

export function useEmailToTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: EmailToTaskRequest) =>
      fetchApi<{ status: string; task_id: string; task_title: string }>(
        `/email/messages/${data.email_id}/to-task`,
        {
          method: 'POST',
          body: JSON.stringify(data),
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all })
      queryClient.invalidateQueries({ queryKey: sprintKeys.all })
    },
  })
}

export function useGetEmailAuthUrl() {
  return useMutation({
    mutationFn: (redirectUri?: string) => {
      const params = redirectUri ? `?redirect_uri=${encodeURIComponent(redirectUri)}` : ''
      return fetchApi<{ auth_url: string; state: string }>(`/email/auth/url${params}`)
    },
  })
}

export function useDisconnectEmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<{ status: string }>('/email/disconnect', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: emailKeys.all })
    },
  })
}

// ============================================================================
// Calendar Hooks
// ============================================================================

export const calendarKeys = {
  all: ['calendar'] as const,
  status: () => [...calendarKeys.all, 'status'] as const,
  calendars: () => [...calendarKeys.all, 'calendars'] as const,
  events: () => [...calendarKeys.all, 'events'] as const,
  eventsList: (filters?: { start_date?: string; end_date?: string }) =>
    [...calendarKeys.events(), 'list', filters] as const,
  eventDetail: (id: string) => [...calendarKeys.events(), 'detail', id] as const,
  today: () => [...calendarKeys.all, 'today'] as const,
}

export function useCalendarStatus() {
  return useQuery({
    queryKey: calendarKeys.status(),
    queryFn: () => fetchApi<CalendarSyncStatus>('/calendar/status'),
  })
}

export function useCalendars() {
  return useQuery({
    queryKey: calendarKeys.calendars(),
    queryFn: () => fetchApi<CalendarInfo[]>('/calendar/calendars'),
  })
}

export function useCalendarEvents(filters?: { start_date?: string; end_date?: string; limit?: number }) {
  return useQuery({
    queryKey: calendarKeys.eventsList(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.start_date) params.set('start_date', filters.start_date)
      if (filters?.end_date) params.set('end_date', filters.end_date)
      if (filters?.limit) params.set('limit', String(filters.limit))
      const queryStr = params.toString()
      return fetchApi<EventSummary[]>(`/calendar/events${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useCalendarEvent(id: string) {
  return useQuery({
    queryKey: calendarKeys.eventDetail(id),
    queryFn: () => fetchApi<CalendarEvent>(`/calendar/events/${id}`),
    enabled: !!id,
  })
}

export function useTodaySchedule() {
  return useQuery({
    queryKey: calendarKeys.today(),
    queryFn: () => fetchApi<TodaySchedule>('/calendar/today'),
  })
}

export function useSyncCalendar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (daysAhead?: number) => {
      const params = daysAhead ? `?days_ahead=${daysAhead}` : ''
      return fetchApi<{ status: string; synced_at: string; events_count: number }>(
        `/calendar/sync${params}`,
        { method: 'POST' }
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

export function useCreateCalendarEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: EventCreate) =>
      fetchApi<CalendarEvent>('/calendar/events', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.events() })
      queryClient.invalidateQueries({ queryKey: calendarKeys.today() })
    },
  })
}

export function useUpdateCalendarEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: EventUpdate }) =>
      fetchApi<CalendarEvent>(`/calendar/events/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.eventDetail(id) })
      queryClient.invalidateQueries({ queryKey: calendarKeys.events() })
      queryClient.invalidateQueries({ queryKey: calendarKeys.today() })
    },
  })
}

export function useDeleteCalendarEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<{ status: string }>(`/calendar/events/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.events() })
      queryClient.invalidateQueries({ queryKey: calendarKeys.today() })
    },
  })
}

export function useTaskToCalendarEvent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: TaskToEventRequest) =>
      fetchApi<CalendarEvent>('/calendar/events/from-task', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.events() })
      queryClient.invalidateQueries({ queryKey: calendarKeys.today() })
    },
  })
}

export function useGetCalendarAuthUrl() {
  return useMutation({
    mutationFn: (redirectUri?: string) => {
      const params = redirectUri ? `?redirect_uri=${encodeURIComponent(redirectUri)}` : ''
      return fetchApi<{ auth_url: string; state: string }>(`/calendar/auth/url${params}`)
    },
  })
}

export function useDisconnectCalendar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<{ status: string }>('/calendar/disconnect', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}

// ============================================================================
// Assistant Hooks
// ============================================================================

export const assistantKeys = {
  all: ['assistant'] as const,
  status: () => [...assistantKeys.all, 'status'] as const,
  briefing: () => [...assistantKeys.all, 'briefing'] as const,
  reminders: () => [...assistantKeys.all, 'reminders'] as const,
  remindersList: (status?: ReminderStatus) => [...assistantKeys.reminders(), 'list', status] as const,
  reminderDetail: (id: string) => [...assistantKeys.reminders(), 'detail', id] as const,
  remindersUpcoming: (hours: number) => [...assistantKeys.reminders(), 'upcoming', hours] as const,
  reminderStats: () => [...assistantKeys.reminders(), 'stats'] as const,
  notifications: () => [...assistantKeys.all, 'notifications'] as const,
  notificationsList: (filters?: { unread_only?: boolean; channel?: NotificationChannel }) =>
    [...assistantKeys.notifications(), 'list', filters] as const,
  notificationCount: () => [...assistantKeys.notifications(), 'count'] as const,
}

export function useAssistantStatus() {
  return useQuery({
    queryKey: assistantKeys.status(),
    queryFn: () => fetchApi<AssistantStatus>('/assistant/status'),
  })
}

export function useDailyBriefing(refresh?: boolean) {
  return useQuery({
    queryKey: assistantKeys.briefing(),
    queryFn: () => fetchApi<DailyBriefing>(`/assistant/briefing${refresh ? '?refresh=true' : ''}`),
  })
}

export function useRefreshBriefing() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<DailyBriefing>('/assistant/briefing?refresh=true'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.briefing() })
    },
  })
}

// Reminder hooks
export function useReminders(status?: ReminderStatus) {
  return useQuery({
    queryKey: assistantKeys.remindersList(status),
    queryFn: () => {
      const params = status ? `?status=${status}` : ''
      return fetchApi<Reminder[]>(`/assistant/reminders${params}`)
    },
  })
}

export function useUpcomingReminders(hours: number = 24) {
  return useQuery({
    queryKey: assistantKeys.remindersUpcoming(hours),
    queryFn: () => fetchApi<Reminder[]>(`/assistant/reminders/upcoming?hours=${hours}`),
  })
}

export function useReminder(id: string) {
  return useQuery({
    queryKey: assistantKeys.reminderDetail(id),
    queryFn: () => fetchApi<Reminder>(`/assistant/reminders/${id}`),
    enabled: !!id,
  })
}

export function useReminderStats() {
  return useQuery({
    queryKey: assistantKeys.reminderStats(),
    queryFn: () => fetchApi<ReminderStats>('/assistant/reminders/stats'),
  })
}

export function useCreateReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ReminderCreate) =>
      fetchApi<Reminder>('/assistant/reminders', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminders() })
      queryClient.invalidateQueries({ queryKey: assistantKeys.status() })
    },
  })
}

export function useUpdateReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: ReminderUpdate }) =>
      fetchApi<Reminder>(`/assistant/reminders/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminderDetail(id) })
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminders() })
    },
  })
}

export function useDeleteReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<{ status: string }>(`/assistant/reminders/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminders() })
      queryClient.invalidateQueries({ queryKey: assistantKeys.status() })
    },
  })
}

export function useSnoozeReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, minutes }: { id: string; minutes?: number }) =>
      fetchApi<Reminder>(`/assistant/reminders/${id}/snooze${minutes ? `?minutes=${minutes}` : ''}`, {
        method: 'POST',
      }),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminderDetail(id) })
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminders() })
    },
  })
}

export function useDismissReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<Reminder>(`/assistant/reminders/${id}/dismiss`, { method: 'POST' }),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminderDetail(id) })
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminders() })
    },
  })
}

export function useCompleteReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<Reminder>(`/assistant/reminders/${id}/complete`, { method: 'POST' }),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminderDetail(id) })
      queryClient.invalidateQueries({ queryKey: assistantKeys.reminders() })
      queryClient.invalidateQueries({ queryKey: assistantKeys.status() })
    },
  })
}

// Notification hooks
export function useNotifications(filters?: { unread_only?: boolean; channel?: NotificationChannel; limit?: number }) {
  return useQuery({
    queryKey: assistantKeys.notificationsList(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.unread_only) params.set('unread_only', 'true')
      if (filters?.channel) params.set('channel', filters.channel)
      if (filters?.limit) params.set('limit', String(filters.limit))
      const queryStr = params.toString()
      return fetchApi<Notification[]>(`/assistant/notifications${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useNotificationCount() {
  return useQuery({
    queryKey: assistantKeys.notificationCount(),
    queryFn: () => fetchApi<{ unread_count: number }>('/assistant/notifications/count'),
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<Notification>(`/assistant/notifications/${id}/read`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.notifications() })
    },
  })
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ status: string; marked_count: number }>('/assistant/notifications/read-all', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.notifications() })
    },
  })
}

export function useDeleteNotification() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<{ status: string }>(`/assistant/notifications/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.notifications() })
    },
  })
}

export function useClearNotifications() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<{ status: string; deleted_count: number }>('/assistant/notifications', {
        method: 'DELETE',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: assistantKeys.notifications() })
    },
  })
}

// ============================================
// Ecosystem (S70)
// ============================================

export interface EcosystemProject {
  id: number
  name: string
  status: string
  tech_stack: Record<string, unknown>
  current_sprint: {
    id: number
    name: string
    status: string
    total_tasks: number
    completed_tasks: number
  } | null
  task_summary: {
    total: number
    completed: number
    in_progress: number
    blocked: number
  }
  health_score: number
  completion_rate: number
  blocked_ratio: number
}

export interface EcosystemStatus {
  projects: EcosystemProject[]
  total_projects: number
  total_active_sprints: number
  total_blocked_tasks: number
  overall_health: number
  alert_count: number
  last_quick_sync: string | null
  last_full_sync: string | null
  hint?: string
}

export interface EcosystemAlert {
  id: string
  type: string
  severity: 'critical' | 'warning' | 'info'
  project: string
  sprint_id?: number
  sprint_name?: string
  message: string
  error?: string
  generated_at?: string
}

export interface EcosystemTimeline {
  id: number
  project_id: number
  project_name: string
  name: string
  status: string
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  planned_start?: string
  planned_end?: string
  progress: number
}

export interface EcosystemProjectTask {
  id: number
  sprint_id: number
  title: string
  status: string
  priority: number
  description?: string
  story_points?: number
  blocked_reason?: string
  project_id: number
  project_name: string
  sprint_name: string
}

export interface EcosystemProjectDetail {
  project: EcosystemProject
  sprints: EcosystemTimeline[]
  tasks: EcosystemProjectTask[]
}

export const ecosystemKeys = {
  all: ['ecosystem'] as const,
  status: () => [...ecosystemKeys.all, 'status'] as const,
  alerts: () => [...ecosystemKeys.all, 'alerts'] as const,
  timeline: () => [...ecosystemKeys.all, 'timeline'] as const,
  suggestions: () => [...ecosystemKeys.all, 'suggestions'] as const,
  syncStatus: () => [...ecosystemKeys.all, 'sync-status'] as const,
  projectDetail: (id: number) => [...ecosystemKeys.all, 'project', id] as const,
  projectSprints: (id: number) => [...ecosystemKeys.all, 'project', id, 'sprints'] as const,
}

export function useEcosystemStatus() {
  return useQuery({
    queryKey: ecosystemKeys.status(),
    queryFn: () => fetchApi<EcosystemStatus>('/ecosystem/status'),
    refetchInterval: 30000,
  })
}

export function useEcosystemAlerts() {
  return useQuery({
    queryKey: ecosystemKeys.alerts(),
    queryFn: () => fetchApi<{ alerts: EcosystemAlert[]; count: number; critical: number; warning: number }>('/ecosystem/alerts'),
    refetchInterval: 30000,
  })
}

export function useEcosystemTimeline() {
  return useQuery({
    queryKey: ecosystemKeys.timeline(),
    queryFn: () => fetchApi<{ sprints: EcosystemTimeline[]; count: number }>('/ecosystem/timeline'),
    refetchInterval: 60000,
  })
}

export function useEcosystemSuggestions() {
  return useQuery({
    queryKey: ecosystemKeys.suggestions(),
    queryFn: () => fetchApi<{ suggestions: string[]; count: number }>('/ecosystem/suggestions'),
    refetchInterval: 60000,
  })
}

export function useTriggerEcosystemSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (full: boolean = false) =>
      fetchApi<Record<string, unknown>>(`/ecosystem/sync/trigger?full=${full}`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ecosystemKeys.all })
    },
  })
}

export function useEcosystemProjectDetail(projectId: number) {
  return useQuery({
    queryKey: ecosystemKeys.projectDetail(projectId),
    queryFn: () => fetchApi<EcosystemProjectDetail>(`/ecosystem/projects/${projectId}/detail`),
    enabled: projectId > 0,
  })
}

export function useEcosystemProjectSprints(projectId: number) {
  return useQuery({
    queryKey: ecosystemKeys.projectSprints(projectId),
    queryFn: () => fetchApi<{ sprints: EcosystemTimeline[]; count: number }>(`/ecosystem/projects/${projectId}/sprints`),
    enabled: projectId > 0,
  })
}

// ============================================
// Orchestration / Autopilot (S70 Phase 2)
// ============================================

export interface OrchestrationLogEntry {
  action: string
  result: string
  details: Record<string, unknown>
  timestamp: string
}

export interface OrchestrationAction {
  action: string
  project?: string
  project_id?: number
  sprint_id?: number
  pending_tasks?: number
  error?: string
  [key: string]: unknown
}

export interface OrchestrationStatusResponse {
  last_daily_orchestration: OrchestrationLogEntry | null
  last_continuous_monitor: OrchestrationLogEntry | null
  last_enhancement_cycle: OrchestrationLogEntry | null
  total_actions: number
  recent_actions: OrchestrationLogEntry[]
}

export interface OrchestrationTriggerResult {
  status: string
  actions: OrchestrationAction[]
  errors: { step: string; error: string }[]
  actions_taken: number
  errors_count?: number
  projects_processed: number
}

export const orchestrationKeys = {
  all: ['orchestration'] as const,
  status: () => [...orchestrationKeys.all, 'status'] as const,
  log: (limit?: number) => [...orchestrationKeys.all, 'log', limit] as const,
}

export function useOrchestrationStatus() {
  return useQuery({
    queryKey: orchestrationKeys.status(),
    queryFn: () => fetchApi<OrchestrationStatusResponse>('/ecosystem/orchestration/status'),
    refetchInterval: 30000,
  })
}

export function useOrchestrationLog(limit: number = 50) {
  return useQuery({
    queryKey: orchestrationKeys.log(limit),
    queryFn: () => fetchApi<{ entries: OrchestrationLogEntry[]; count: number }>(
      `/ecosystem/orchestration/log?limit=${limit}`
    ),
    refetchInterval: 30000,
  })
}

export function useTriggerOrchestration() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchApi<OrchestrationTriggerResult>('/ecosystem/orchestration/trigger', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orchestrationKeys.all })
      queryClient.invalidateQueries({ queryKey: ecosystemKeys.all })
    },
  })
}

// ============================================================================
// Research Hooks
// ============================================================================

export const researchKeys = {
  all: ['research'] as const,
  topics: () => [...researchKeys.all, 'topics'] as const,
  topicsList: (status?: string) => [...researchKeys.topics(), 'list', status] as const,
  topicDetail: (id: string) => [...researchKeys.topics(), 'detail', id] as const,
  findings: () => [...researchKeys.all, 'findings'] as const,
  findingsList: (filters?: Record<string, unknown>) => [...researchKeys.findings(), 'list', filters] as const,
  findingsTop: (limit?: number) => [...researchKeys.findings(), 'top', limit] as const,
  cycles: () => [...researchKeys.all, 'cycles'] as const,
  stats: () => [...researchKeys.all, 'stats'] as const,
}

export function useResearchTopics(status?: string) {
  return useQuery({
    queryKey: researchKeys.topicsList(status),
    queryFn: () => {
      const params = status ? `?status=${status}` : ''
      return fetchApi<import('@/types').ResearchTopic[]>(`/research/topics${params}`)
    },
  })
}

export function useResearchTopic(id: string) {
  return useQuery({
    queryKey: researchKeys.topicDetail(id),
    queryFn: () => fetchApi<import('@/types').ResearchTopic>(`/research/topics/${id}`),
    enabled: !!id,
  })
}

export function useCreateResearchTopic() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: import('@/types').ResearchTopicCreate) =>
      fetchApi<import('@/types').ResearchTopic>('/research/topics', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.topics() })
      queryClient.invalidateQueries({ queryKey: researchKeys.stats() })
    },
  })
}

export function useDeleteResearchTopic() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<{ status: string }>(`/research/topics/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.topics() })
      queryClient.invalidateQueries({ queryKey: researchKeys.stats() })
    },
  })
}

export function useResearchFindings(filters?: { topic_id?: string; status?: string; min_score?: number; limit?: number }) {
  return useQuery({
    queryKey: researchKeys.findingsList(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.topic_id) params.set('topic_id', filters.topic_id)
      if (filters?.status) params.set('status', filters.status)
      if (filters?.min_score) params.set('min_score', String(filters.min_score))
      if (filters?.limit) params.set('limit', String(filters.limit))
      const queryStr = params.toString()
      return fetchApi<import('@/types').ResearchFinding[]>(`/research/findings${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useTopFindings(limit: number = 10) {
  return useQuery({
    queryKey: researchKeys.findingsTop(limit),
    queryFn: () => fetchApi<import('@/types').ResearchFinding[]>(`/research/findings/top?limit=${limit}`),
  })
}

export function useReviewFinding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<import('@/types').ResearchFinding>(`/research/findings/${id}/review`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.findings() })
    },
  })
}

export function useDismissFinding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<import('@/types').ResearchFinding>(`/research/findings/${id}/dismiss`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.findings() })
    },
  })
}

export function useCreateTaskFromFinding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      fetchApi<{ status: string }>(`/research/findings/${id}/create-task`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.findings() })
      queryClient.invalidateQueries({ queryKey: researchKeys.stats() })
    },
  })
}

export function useResearchCycles(limit: number = 10) {
  return useQuery({
    queryKey: researchKeys.cycles(),
    queryFn: () => fetchApi<import('@/types').ResearchCycleResult[]>(`/research/cycles?limit=${limit}`),
  })
}

export function useResearchStats() {
  return useQuery({
    queryKey: researchKeys.stats(),
    queryFn: () => fetchApi<import('@/types').ResearchStats>('/research/stats'),
  })
}

export function useRunResearchCycle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<import('@/types').ResearchCycleResult>('/research/cycle/run', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.all })
    },
  })
}

export function useSeedResearchTopics() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<{ status: string; created: number }>('/research/topics/seed', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.topics() })
      queryClient.invalidateQueries({ queryKey: researchKeys.stats() })
    },
  })
}

// --- Research Rules ---

export const researchRulesKeys = {
  all: ['research-rules'] as const,
  list: (filters?: Record<string, unknown>) => [...researchRulesKeys.all, 'list', filters] as const,
  detail: (id: string) => [...researchRulesKeys.all, 'detail', id] as const,
  stats: () => [...researchRulesKeys.all, 'stats'] as const,
}

export function useResearchRules(filters?: { rule_type?: string; enabled?: boolean }) {
  return useQuery({
    queryKey: researchRulesKeys.list(filters),
    queryFn: () => {
      const params = new URLSearchParams()
      if (filters?.rule_type) params.set('rule_type', filters.rule_type)
      if (filters?.enabled !== undefined) params.set('enabled', String(filters.enabled))
      const queryStr = params.toString()
      return fetchApi<ResearchRule[]>(`/research/rules${queryStr ? `?${queryStr}` : ''}`)
    },
  })
}

export function useResearchRuleStats() {
  return useQuery({
    queryKey: researchRulesKeys.stats(),
    queryFn: () => fetchApi<ResearchRuleStats>('/research/rules/stats'),
  })
}

export function useCreateResearchRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      fetchApi<ResearchRule>('/research/rules', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchRulesKeys.all })
    },
  })
}

export function useToggleResearchRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) =>
      fetchApi<ResearchRule>(`/research/rules/${ruleId}/toggle`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchRulesKeys.all })
    },
  })
}

export function useDeleteResearchRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) =>
      fetchApi<{ status: string }>(`/research/rules/${ruleId}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchRulesKeys.all })
    },
  })
}

export function useRecalibrateRules() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fetchApi<Record<string, unknown>>('/research/rules/recalibrate', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchRulesKeys.all })
    },
  })
}
