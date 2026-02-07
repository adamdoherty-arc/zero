// Sprint types
export type SprintStatus = 'planning' | 'active' | 'paused' | 'completed' | 'cancelled'

export interface Sprint {
  id: string
  number: number
  name: string
  description?: string
  status: SprintStatus
  start_date?: string
  end_date?: string
  duration_days: number
  goals: string[]
  total_points: number
  completed_points: number
  created_at: string
  updated_at?: string
}

export interface SprintCreate {
  name: string
  description?: string
  duration_days?: number
  goals?: string[]
}

export interface SprintUpdate {
  name?: string
  description?: string
  status?: SprintStatus
  goals?: string[]
  end_date?: string
}

// Task types
export type TaskStatus = 'backlog' | 'todo' | 'in_progress' | 'review' | 'testing' | 'done' | 'blocked'
export type TaskCategory = 'bug' | 'feature' | 'enhancement' | 'chore' | 'documentation'
export type TaskPriority = 'critical' | 'high' | 'medium' | 'low'
export type TaskSource = 'MANUAL' | 'QA_DETECTED' | 'ERROR_LOG' | 'ENHANCEMENT_ENGINE' | 'USER_REPORTED' | 'TODO_SCAN'

export interface Task {
  id: string
  sprint_id?: string
  project_id?: string
  title: string
  description?: string
  status: TaskStatus
  category: TaskCategory
  priority: TaskPriority
  points?: number
  source: TaskSource
  source_reference?: string
  blocked_reason?: string
  started_at?: string
  completed_at?: string
  created_at: string
  updated_at?: string
}

export interface TaskCreate {
  title: string
  description?: string
  sprint_id?: string
  project_id?: string
  category?: TaskCategory
  priority?: TaskPriority
  points?: number
  source?: TaskSource
  source_reference?: string
}

export interface TaskUpdate {
  title?: string
  description?: string
  sprint_id?: string
  project_id?: string
  status?: TaskStatus
  category?: TaskCategory
  priority?: TaskPriority
  points?: number
  blocked_reason?: string
}

export interface TaskMove {
  status: TaskStatus
  reason?: string
}

// Board types
export interface BoardColumn {
  [status: string]: Task[]
}

export interface BoardStats {
  total_tasks: number
  total_points: number
  completed_points: number
  by_status: { [status: string]: number }
}

export interface SprintBoard {
  sprint: Sprint
  columns: BoardColumn
  stats: BoardStats
}

// Enhancement types
export interface EnhancementSignal {
  id: string
  type: string
  source_file?: string
  line_number?: number
  message: string
  severity: string
  detected_at: string
  status: string
}

export interface EnhancementStats {
  total_signals: number
  pending: number
  converted_to_tasks: number
  dismissed: number
  by_type: { [type: string]: number }
  by_severity: { [severity: string]: number }
}

// Orchestrator types
export interface OrchestratorStatus {
  status: string
  started_at?: string
  current_task?: string
  completed_tasks: number
  errors: number
  uptime_seconds?: number
}

// Project types
export type ProjectType = 'local' | 'git' | 'github' | 'gitlab'
export type ProjectStatus = 'active' | 'archived' | 'scanning'

export interface ProjectScanConfig {
  enabled: boolean
  scan_todos: boolean
  scan_errors: boolean
  scan_tests: boolean
  exclude_patterns: string[]
  include_extensions: string[]
  max_file_size_kb: number
}

export interface ProjectScanResult {
  scanned_at: string
  files_scanned: number
  signals_found: number
  errors: string[]
  summary: { [key: string]: number }
}

export interface Project {
  id: string
  name: string
  description?: string
  path: string
  project_type: ProjectType
  status: ProjectStatus
  scan_config: ProjectScanConfig
  tags: string[]
  last_scan?: ProjectScanResult
  task_count: number
  open_signals: number
  git_remote?: string
  git_branch?: string
  last_commit_hash?: string
  last_commit_message?: string
  // GitHub Integration
  github_repo_url?: string
  github_owner?: string
  github_repo?: string
  github_default_branch?: string
  github_sync_enabled: boolean
  github_last_sync?: string
  github_sync_issues: boolean
  github_sync_prs: boolean
  github_open_issues: number
  github_open_prs: number
  github_stars: number
  github_forks: number
  created_at: string
  updated_at?: string
}

export interface ProjectCreate {
  name: string
  description?: string
  path: string
  project_type?: ProjectType
  scan_config?: Partial<ProjectScanConfig>
  tags?: string[]
  github_repo_url?: string
  github_sync_enabled?: boolean
}

export interface ProjectUpdate {
  name?: string
  description?: string
  path?: string
  status?: ProjectStatus
  scan_config?: Partial<ProjectScanConfig>
  tags?: string[]
  github_repo_url?: string
  github_sync_enabled?: boolean
  github_sync_issues?: boolean
  github_sync_prs?: boolean
}

// GitHub Integration types
export interface GitHubConnectRequest {
  github_url: string
  sync_issues: boolean
  sync_prs: boolean
  auto_sync: boolean
}

export interface GitHubStatus {
  connected: boolean
  project_id: string
  github_url?: string
  github_owner?: string
  github_repo?: string
  default_branch?: string
  sync_enabled?: boolean
  sync_issues?: boolean
  sync_prs?: boolean
  last_sync?: string
  stats?: {
    open_issues: number
    open_prs: number
    stars: number
    forks: number
  }
}

export interface GitHubIssue {
  number: number
  title: string
  body?: string
  state: string
  labels: string[]
  assignees: string[]
  created_at: string
  updated_at: string
  html_url: string
  user: string
}

export interface GitHubPullRequest {
  number: number
  title: string
  body?: string
  state: string
  draft: boolean
  head_branch: string
  base_branch: string
  created_at: string
  updated_at: string
  html_url: string
  user: string
  labels: string[]
}

export interface GitHubSyncResult {
  status: string
  project_id: string
  synced_at: string
  issues_count: number
  prs_count: number
  issues: GitHubIssue[]
  prs: GitHubPullRequest[]
  errors: string[]
}

// ============================================================================
// Knowledge / Second Brain Types
// ============================================================================

export type NoteType = 'note' | 'idea' | 'fact' | 'preference' | 'memory' | 'bookmark' | 'snippet'
export type NoteSource = 'manual' | 'whatsapp' | 'discord' | 'slack' | 'audio' | 'email' | 'web_clip' | 'task' | 'github'

export interface Note {
  id: string
  type: NoteType
  title?: string
  content: string
  source: NoteSource
  source_reference?: string
  tags: string[]
  project_id?: string
  task_id?: string
  embedding?: number[]
  created_at: string
  updated_at?: string
}

export interface NoteCreate {
  type?: NoteType
  title?: string
  content: string
  source?: NoteSource
  source_reference?: string
  tags?: string[]
  project_id?: string
  task_id?: string
}

export interface NoteUpdate {
  type?: NoteType
  title?: string
  content?: string
  tags?: string[]
  project_id?: string
  task_id?: string
}

export interface UserFact {
  id: string
  fact: string
  category: string
  confidence: number
  source: string
  learned_at: string
}

export interface UserContact {
  name: string
  relation?: string
  email?: string
  phone?: string
  notes?: string
}

export interface UserProfile {
  name: string
  timezone: string
  facts: UserFact[]
  preferences: Record<string, unknown>
  communication_style?: string
  work_hours?: { start: string; end: string }
  interests: string[]
  skills: string[]
  contacts: UserContact[]
  goals: string[]
  updated_at?: string
}

export interface UserProfileUpdate {
  name?: string
  timezone?: string
  communication_style?: string
  work_hours?: { start: string; end: string }
  interests?: string[]
  skills?: string[]
  goals?: string[]
}

export interface RecallRequest {
  context: string
  limit?: number
  include_notes?: boolean
  include_facts?: boolean
  include_tasks?: boolean
}

export interface RecallResult {
  notes: Note[]
  facts: UserFact[]
  related_tasks: Array<{ id: string; title: string; status: string }>
  summary?: string
}

export interface KnowledgeStats {
  total_notes: number
  by_type: Record<string, number>
  by_source: Record<string, number>
  total_tags: number
  top_tags: string[]
  total_facts: number
  total_contacts: number
  total_skills: number
  total_interests: number
}

export interface ProjectContext {
  project: {
    id: string
    name: string
    path: string
    type: string
  }
  claude_md?: string
  readme?: string
  structure: string[]
  git?: {
    remote?: string
    branch?: string
    commit_hash?: string
    commit_message?: string
  }
}

// ============================================================================
// Audio Transcription Types
// ============================================================================

export type TranscriptionStatus = 'pending' | 'processing' | 'completed' | 'failed'
export type WhisperModel = 'tiny' | 'base' | 'small' | 'medium' | 'large'

export interface TranscriptionSegment {
  start: number
  end: number
  text: string
  confidence?: number
}

export interface TranscriptionResult {
  text: string
  language?: string
  duration_seconds?: number
  segments: TranscriptionSegment[]
  model_used: string
  processing_time_seconds?: number
}

export interface TranscriptionJob {
  id: string
  status: TranscriptionStatus
  audio_file: string
  audio_format?: string
  file_size_bytes?: number
  result?: TranscriptionResult
  error?: string
  created_at: string
  completed_at?: string
}

export interface WhisperModelInfo {
  id: WhisperModel
  name: string
  description: string
  size_mb: number
}

export interface TranscribeToNoteResult {
  transcription: TranscriptionResult
  note: Note
}

// ============================================================================
// Email Types
// ============================================================================

export type EmailCategory = 'urgent' | 'important' | 'normal' | 'low_priority' | 'spam' | 'newsletter'
export type EmailStatusType = 'unread' | 'read' | 'archived' | 'deleted'

export interface EmailAddress {
  email: string
  name?: string
}

export interface EmailAttachment {
  filename: string
  mime_type: string
  size_bytes: number
  attachment_id?: string
}

export interface Email {
  id: string
  thread_id: string
  subject: string
  snippet: string
  body_text?: string
  body_html?: string
  from_address: EmailAddress
  to_addresses: EmailAddress[]
  cc_addresses: EmailAddress[]
  bcc_addresses: EmailAddress[]
  labels: string[]
  attachments: EmailAttachment[]
  category: EmailCategory
  status: EmailStatusType
  is_starred: boolean
  is_important: boolean
  received_at: string
  internal_date: number
  synced_at: string
}

export interface EmailSummary {
  id: string
  thread_id: string
  subject: string
  snippet: string
  from_address: EmailAddress
  category: EmailCategory
  status: EmailStatusType
  is_starred: boolean
  is_important: boolean
  has_attachments: boolean
  received_at: string
}

export interface EmailLabel {
  id: string
  name: string
  type: string
  message_count: number
  unread_count: number
}

export interface EmailSyncStatus {
  connected: boolean
  email_address?: string
  last_sync?: string
  total_messages: number
  unread_count: number
  sync_errors: string[]
}

export interface EmailDigest {
  date: string
  total_emails: number
  unread_emails: number
  by_category: Record<string, number>
  urgent_emails: EmailSummary[]
  important_emails: EmailSummary[]
  highlights: string[]
}

export interface EmailToTaskRequest {
  email_id: string
  sprint_id?: string
  project_id?: string
  priority?: string
  category?: string
}

// ============================================================================
// Calendar Types
// ============================================================================

export type EventStatus = 'confirmed' | 'tentative' | 'cancelled'
export type EventVisibility = 'default' | 'public' | 'private'
export type EventResponseStatus = 'needsAction' | 'declined' | 'tentative' | 'accepted'

export interface EventDateTime {
  date_time?: string
  date?: string
  timezone?: string
}

export interface EventAttendee {
  email: string
  display_name?: string
  response_status: EventResponseStatus
  is_organizer: boolean
  is_self: boolean
}

export interface EventReminder {
  method: string
  minutes: number
}

export interface CalendarEvent {
  id: string
  calendar_id: string
  summary: string
  description?: string
  location?: string
  start: EventDateTime
  end: EventDateTime
  status: EventStatus
  visibility: EventVisibility
  html_link?: string
  hangout_link?: string
  attendees: EventAttendee[]
  reminders: EventReminder[]
  recurrence?: string[]
  recurring_event_id?: string
  is_all_day: boolean
  created_at?: string
  updated_at?: string
}

export interface EventSummary {
  id: string
  summary: string
  start: EventDateTime
  end: EventDateTime
  location?: string
  is_all_day: boolean
  status: EventStatus
  has_attendees: boolean
  html_link?: string
}

export interface EventCreate {
  summary: string
  description?: string
  location?: string
  start: EventDateTime
  end: EventDateTime
  attendees?: string[]
  reminders?: EventReminder[]
  visibility?: EventVisibility
  recurrence?: string[]
}

export interface EventUpdate {
  summary?: string
  description?: string
  location?: string
  start?: EventDateTime
  end?: EventDateTime
  status?: EventStatus
}

export interface CalendarInfo {
  id: string
  summary: string
  description?: string
  timezone: string
  is_primary: boolean
  background_color?: string
  foreground_color?: string
}

export interface CalendarSyncStatus {
  connected: boolean
  email_address?: string
  last_sync?: string
  calendars_count: number
  upcoming_events_count: number
  sync_errors: string[]
}

export interface TodaySchedule {
  date: string
  events: EventSummary[]
  total_events: number
  has_conflicts: boolean
  free_slots: { start: string; end: string }[]
}

export interface TaskToEventRequest {
  task_id: string
  start: EventDateTime
  end?: EventDateTime
  duration_minutes?: number
  add_reminders?: boolean
}

// ============================================================================
// Assistant Types
// ============================================================================

export type ReminderStatus = 'active' | 'triggered' | 'snoozed' | 'dismissed' | 'completed'
export type ReminderRecurrence = 'once' | 'daily' | 'weekly' | 'monthly' | 'custom'
export type NotificationChannel = 'ui' | 'discord' | 'whatsapp' | 'email'

export interface Reminder {
  id: string
  title: string
  description?: string
  trigger_at: string
  recurrence: ReminderRecurrence
  cron_expression?: string
  channels: NotificationChannel[]
  status: ReminderStatus
  snooze_until?: string
  task_id?: string
  project_id?: string
  tags: string[]
  created_at: string
  updated_at?: string
  last_triggered_at?: string
}

export interface ReminderCreate {
  title: string
  description?: string
  trigger_at: string
  recurrence?: ReminderRecurrence
  cron_expression?: string
  channels?: NotificationChannel[]
  task_id?: string
  project_id?: string
  tags?: string[]
}

export interface ReminderUpdate {
  title?: string
  description?: string
  trigger_at?: string
  recurrence?: ReminderRecurrence
  cron_expression?: string
  channels?: NotificationChannel[]
  status?: ReminderStatus
}

export interface BriefingSection {
  title: string
  icon: string
  items: string[]
  priority: number
}

export interface DailyBriefing {
  date: string
  greeting: string
  weather?: string
  sections: BriefingSection[]
  calendar_summary?: string
  task_summary?: string
  email_summary?: string
  reminders_due: Reminder[]
  suggestions: string[]
  generated_at: string
}

export interface Notification {
  id: string
  title: string
  message: string
  channel: NotificationChannel
  read: boolean
  action_url?: string
  source?: string
  source_id?: string
  created_at: string
}

export interface AssistantStatus {
  scheduler_running: boolean
  last_briefing_at?: string
  pending_reminders: number
  unread_notifications: number
  active_jobs: string[]
}

export interface ReminderStats {
  total: number
  by_status: Record<string, number>
  upcoming_24h: number
  active: number
}
