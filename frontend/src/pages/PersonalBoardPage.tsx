import { useMemo, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, Sparkles, ExternalLink, Trash2, RefreshCw, Search } from 'lucide-react'

import {
  usePersonalWorkItems,
  usePersonalTopics,
  useCreatePersonalWorkItem,
  useUpdatePersonalWorkItem,
  useDeletePersonalWorkItem,
  useReopenPersonalWorkItem,
  useCompletePersonalWorkItem,
  usePersonalSeedVAStatus,
  useSeedVAClaim,
  usePersonalTaskEvents,
} from '@/hooks/usePersonalWorkItemsApi'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TaskNotesPanel } from '@/components/TaskNotesPanel'
import type { Task, TaskPriority, TaskStatus } from '@/types'

const ALL_TOPICS = '__all__'
const VA_TOPIC = 'VA Disability'

const COLUMNS: Array<{ status: TaskStatus; label: string; tone: string }> = [
  { status: 'backlog', label: 'Backlog', tone: 'border-gray-700 bg-gray-900/40' },
  { status: 'todo', label: 'To Do', tone: 'border-blue-800 bg-blue-950/30' },
  { status: 'in_progress', label: 'In Progress', tone: 'border-amber-800 bg-amber-950/30' },
  { status: 'blocked', label: 'Blocked', tone: 'border-rose-800 bg-rose-950/30' },
  { status: 'done', label: 'Done', tone: 'border-emerald-800 bg-emerald-950/30' },
]

const PRIORITY_TONE: Record<TaskPriority, string> = {
  critical: 'bg-rose-500/20 text-rose-300 border-rose-700',
  high: 'bg-amber-500/20 text-amber-300 border-amber-700',
  medium: 'bg-blue-500/20 text-blue-300 border-blue-700',
  low: 'bg-gray-500/20 text-gray-300 border-gray-700',
}

function phaseTag(task: Task): string | null {
  const tag = (task.tags || []).find((t) => t.startsWith('phase:'))
  if (!tag) return null
  return tag.replace('phase:', '').replace('d', ' days').replace('reference', 'reference')
}

export function PersonalBoardPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const topicParam = searchParams.get('topic')
  const currentTopic = topicParam || ALL_TOPICS

  const [search, setSearch] = useState('')
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [creating, setCreating] = useState(false)

  const filters = useMemo(() => {
    const f: { topic?: string; search?: string } = {}
    if (currentTopic !== ALL_TOPICS) f.topic = currentTopic
    if (search.trim()) f.search = search.trim()
    return f
  }, [currentTopic, search])

  const { data: tasks = [], isLoading } = usePersonalWorkItems(filters)
  const { data: topics = [] } = usePersonalTopics()
  const { data: vaSeedStatus } = usePersonalSeedVAStatus()
  const seedVA = useSeedVAClaim()

  const setTopic = (t: string) => {
    const next = new URLSearchParams(searchParams)
    if (t === ALL_TOPICS) next.delete('topic')
    else next.set('topic', t)
    setSearchParams(next, { replace: true })
  }

  const columns = useMemo(() => {
    const grouped: Record<TaskStatus, Task[]> = {
      backlog: [], todo: [], on_hold: [], in_progress: [], review: [], testing: [], done: [], blocked: [], archived: [],
    }
    for (const t of tasks) (grouped[t.status] || (grouped[t.status] = [])).push(t)
    return grouped
  }, [tasks])

  const showVAEmptyState =
    currentTopic === VA_TOPIC && tasks.length === 0 && !isLoading && vaSeedStatus && !vaSeedStatus.has_va_tasks
  const showGlobalEmptyState =
    currentTopic === ALL_TOPICS && tasks.length === 0 && !isLoading && vaSeedStatus && !vaSeedStatus.has_va_tasks

  // Auto-redirect to VA topic right after seeding so the user lands on the new board.
  useEffect(() => {
    if (seedVA.isSuccess && seedVA.data && seedVA.data.created > 0) {
      setTopic(VA_TOPIC)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedVA.isSuccess])

  return (
    <div className="page-content space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-gray-500">Topic</span>
          <Select value={currentTopic} onValueChange={setTopic}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="All topics" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_TOPICS}>All topics</SelectItem>
              {topics.map((t) => (
                <SelectItem key={t.topic} value={t.topic}>
                  {t.topic} <span className="text-gray-500 ml-1">({t.open}/{t.total})</span>
                </SelectItem>
              ))}
              {!topics.find((t) => t.topic === VA_TOPIC) && (
                <SelectItem value={VA_TOPIC}>{VA_TOPIC} (not seeded)</SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-md">
          <Search className="w-4 h-4 text-gray-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search titles + descriptions..."
            className="bg-gray-900 border border-gray-800 rounded px-3 py-1.5 text-sm w-full focus:outline-none focus:border-indigo-600"
          />
        </div>

        <button
          onClick={() => setCreating(true)}
          className="ml-auto inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium"
        >
          <Plus className="w-4 h-4" />
          New Task
        </button>

        {vaSeedStatus && !vaSeedStatus.has_va_tasks && (
          <button
            onClick={() => seedVA.mutate()}
            disabled={seedVA.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium"
          >
            <Sparkles className="w-4 h-4" />
            {seedVA.isPending ? 'Seeding VA playbook...' : 'Seed VA Disability Playbook'}
          </button>
        )}
      </div>

      {currentTopic !== ALL_TOPICS && (
        <div className="text-sm text-gray-400 flex items-center gap-3">
          <span>
            Showing <span className="text-white font-medium">{currentTopic}</span> only.{' '}
            <button onClick={() => setTopic(ALL_TOPICS)} className="text-indigo-400 hover:underline">
              Show all topics
            </button>
          </span>
          {isLoading && <span className="text-gray-500 italic">loading…</span>}
        </div>
      )}

      {currentTopic === ALL_TOPICS && isLoading && (
        <div className="text-sm text-gray-500 italic">loading personal board…</div>
      )}

      {/* Empty states */}
      {(showVAEmptyState || showGlobalEmptyState) && (
        <div className="glass-card p-8 text-center">
          <Sparkles className="w-10 h-10 mx-auto text-indigo-400 mb-3" />
          <h2 className="text-xl font-semibold mb-2">Set up the VA Disability Claim Playbook</h2>
          <p className="text-gray-400 max-w-2xl mx-auto mb-6">
            Seeds ~22 tasks broken into phases (7 days / 30 days / 60 days / 90 days / reference). Includes three "living narrative"
            tasks for GERD, Anxiety, and Tinnitus that you refine over time — every edit creates an audit-trail event.
          </p>
          <button
            onClick={() => seedVA.mutate()}
            disabled={seedVA.isPending}
            className="px-6 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium"
          >
            {seedVA.isPending ? 'Seeding...' : 'Seed VA Disability Playbook'}
          </button>
        </div>
      )}

      {/* Topic-specific empty hint (when seed has already run but this topic has zero items) */}
      {!showVAEmptyState && !showGlobalEmptyState && !isLoading && tasks.length === 0 && currentTopic !== ALL_TOPICS && (
        <div className="glass-card p-6 text-center text-sm text-gray-400">
          No tasks yet under <span className="text-white font-medium">{currentTopic}</span>. Click{' '}
          <span className="text-indigo-400">+ New Task</span> to add one, or{' '}
          <button onClick={() => setTopic(ALL_TOPICS)} className="text-indigo-400 hover:underline">
            switch back to all topics
          </button>
          .
        </div>
      )}

      {/* Kanban */}
      {!showVAEmptyState && !showGlobalEmptyState && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
          {COLUMNS.map((col) => {
            const items = columns[col.status] || []
            return (
              <div key={col.status} className={`rounded-lg border ${col.tone} p-3 min-h-[200px]`}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold text-sm text-gray-200">{col.label}</h3>
                  <span className="text-xs text-gray-500">{items.length}</span>
                </div>
                <div className="space-y-2">
                  {items.map((task) => (
                    <TaskCard key={task.id} task={task} onClick={() => setSelectedTask(task)} />
                  ))}
                  {items.length === 0 && (
                    <div className="text-xs text-gray-600 italic">empty</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <TaskDetailDialog
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
      />
      {creating && (
        <NewTaskDialog
          defaultTopic={currentTopic === ALL_TOPICS ? 'General' : currentTopic}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  )
}

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const phase = phaseTag(task)
  const isNarrative = (task.tags || []).includes('narrative')
  const isPinned = (task.tags || []).includes('pinned')
  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-md border border-gray-800 bg-gray-950/60 hover:border-indigo-600 hover:bg-gray-900 p-3 transition-colors"
    >
      <div className="flex items-start gap-2 mb-2">
        <div className="flex-1">
          <div className="text-sm font-medium leading-snug">{task.title}</div>
        </div>
        {isPinned && <span className="text-xs">📌</span>}
      </div>
      <div className="flex flex-wrap gap-1.5 items-center text-[10px]">
        <span className={`px-1.5 py-0.5 rounded border ${PRIORITY_TONE[task.priority] ?? PRIORITY_TONE.medium}`}>
          {task.priority}
        </span>
        {phase && <span className="px-1.5 py-0.5 rounded border border-gray-700 text-gray-400">{phase}</span>}
        {isNarrative && <span className="px-1.5 py-0.5 rounded border border-purple-700 text-purple-300">narrative</span>}
        {task.domain && <span className="text-gray-500">{task.domain}</span>}
      </div>
    </button>
  )
}

function TaskDetailDialog({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const update = useUpdatePersonalWorkItem()
  const remove = useDeletePersonalWorkItem()
  const reopen = useReopenPersonalWorkItem()
  const complete = useCompletePersonalWorkItem()
  const { data: events = [] } = usePersonalTaskEvents(task?.id)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<TaskStatus>('backlog')
  const [priority, setPriority] = useState<TaskPriority>('medium')

  useEffect(() => {
    if (task) {
      setTitle(task.title)
      setDescription(task.description || '')
      setStatus(task.status)
      setPriority(task.priority)
    }
  }, [task])

  if (!task) return null

  const dirty =
    title !== task.title ||
    description !== (task.description || '') ||
    status !== task.status ||
    priority !== task.priority

  const save = () => {
    update.mutate({
      id: task.id,
      data: { title, description, status, priority },
    })
  }

  const onDelete = () => {
    if (confirm(`Delete "${task.title}"? This is irreversible.`)) {
      remove.mutate(task.id)
      onClose()
    }
  }

  const links = (task.links || []) as Array<{ label?: string; url?: string }>
  const isNarrative = (task.tags || []).includes('narrative')

  return (
    <Dialog open={!!task} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="bg-transparent border-none w-full text-lg font-semibold focus:outline-none focus:ring-0"
            />
          </DialogTitle>
          <DialogDescription className="sr-only">
            Edit a personal task. Changes to the description are tracked in the audit trail below.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex gap-2 flex-wrap">
            <Select value={status} onValueChange={(v) => setStatus(v as TaskStatus)}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                {COLUMNS.map((c) => (
                  <SelectItem key={c.status} value={c.status}>{c.label}</SelectItem>
                ))}
                <SelectItem value="archived">Archived</SelectItem>
              </SelectContent>
            </Select>
            <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
              <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="critical">Critical</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="low">Low</SelectItem>
              </SelectContent>
            </Select>
            {(task.tags || []).map((t) => (
              <span key={t} className="px-2 py-1 text-[10px] uppercase tracking-wider rounded border border-gray-700 text-gray-400">
                {t}
              </span>
            ))}
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider text-gray-500 mb-1 block">
              {isNarrative ? 'Living narrative — edits are timestamped in the audit trail below' : 'Description'}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={isNarrative ? 22 : 12}
              className="w-full bg-gray-950 border border-gray-800 rounded p-3 text-sm font-mono leading-relaxed whitespace-pre-wrap focus:outline-none focus:border-indigo-600"
            />
          </div>

          {links.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">Links</div>
              <div className="space-y-1">
                {links.map((l, i) =>
                  l?.url ? (
                    <a
                      key={i}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      {l.label || l.url}
                    </a>
                  ) : null,
                )}
              </div>
            </div>
          )}

          <TaskNotesPanel taskId={task.id} scope="personal" />

          <div>
            {(() => {
              const auditOnly = events.filter((e) => e.event_type !== 'note')
              return (
                <>
                  <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">
                    Activity ({auditOnly.length})
                  </div>
                  <div className="space-y-1 max-h-40 overflow-y-auto text-xs text-gray-400">
                    {auditOnly.slice(0, 20).map((e) => (
                      <div key={e.id} className="flex gap-2">
                        <span className="text-gray-600 whitespace-nowrap">
                          {new Date(e.created_at).toLocaleString()}
                        </span>
                        <span className="text-gray-500">{e.event_type}</span>
                        <span>{e.summary || ''}</span>
                      </div>
                    ))}
                    {auditOnly.length === 0 && <div className="italic text-gray-600">no activity yet</div>}
                  </div>
                </>
              )
            })()}
          </div>

          <div className="flex items-center gap-2 pt-2 border-t border-gray-800">
            <button
              onClick={save}
              disabled={!dirty || update.isPending}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm font-medium"
            >
              {update.isPending ? 'Saving...' : dirty ? 'Save changes' : 'No changes'}
            </button>
            {task.status !== 'done' ? (
              <button
                onClick={async () => {
                  // Don't drop unsaved description/title edits when marking done.
                  if (dirty) {
                    await update.mutateAsync({ id: task.id, data: { title, description, status, priority } })
                  }
                  complete.mutate({ id: task.id })
                }}
                disabled={complete.isPending || update.isPending}
                className="px-4 py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm"
                title={dirty ? 'Saves your edits, then marks done' : 'Marks done'}
              >
                {update.isPending ? 'Saving…' : complete.isPending ? 'Completing…' : 'Mark Done'}
              </button>
            ) : (
              <button
                onClick={() => reopen.mutate(task.id)}
                disabled={reopen.isPending}
                className="px-4 py-2 rounded-lg bg-amber-700 hover:bg-amber-600 text-white text-sm inline-flex items-center gap-1.5"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Reopen
              </button>
            )}
            <button
              onClick={onDelete}
              className="ml-auto px-3 py-2 rounded-lg border border-rose-900 text-rose-400 hover:bg-rose-950 text-sm inline-flex items-center gap-1.5"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function NewTaskDialog({ defaultTopic, onClose }: { defaultTopic: string; onClose: () => void }) {
  const create = useCreatePersonalWorkItem()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [topic, setTopic] = useState(defaultTopic)
  const [priority, setPriority] = useState<TaskPriority>('medium')

  const submit = () => {
    if (!title.trim()) return
    create.mutate(
      {
        title: title.trim(),
        description: description.trim() || undefined,
        domain: topic.trim() || 'General',
        priority,
        category: 'chore',
        source: 'MANUAL',
      },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New personal task</DialogTitle>
          <DialogDescription className="sr-only">
            Create a new task on the personal board. Pick a topic to keep related work grouped.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-xs uppercase tracking-wider text-gray-500 mb-1 block">Topic (groups the task)</label>
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g., VA Disability, Health, Finance"
              className="w-full bg-gray-950 border border-gray-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-600"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wider text-gray-500 mb-1 block">Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              className="w-full bg-gray-950 border border-gray-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-600"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wider text-gray-500 mb-1 block">Priority</label>
            <Select value={priority} onValueChange={(v) => setPriority(v as TaskPriority)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="critical">Critical</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="low">Low</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-wider text-gray-500 mb-1 block">Description (optional)</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="w-full bg-gray-950 border border-gray-800 rounded p-2 text-sm focus:outline-none focus:border-indigo-600"
            />
          </div>
          <div className="flex gap-2 pt-2">
            <button
              onClick={submit}
              disabled={!title.trim() || create.isPending}
              className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-800 text-white text-sm font-medium"
            >
              {create.isPending ? 'Creating...' : 'Create'}
            </button>
            <button onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-900 text-sm">
              Cancel
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
