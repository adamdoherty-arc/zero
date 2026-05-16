import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { StickyNote, Send, X } from 'lucide-react'

import { getAuthHeaders } from '@/lib/auth'
import { useCompanyTaskEvents } from '@/hooks/useCompanyWorkItemsApi'
import { usePersonalTaskEvents, personalWorkItemKeys } from '@/hooks/usePersonalWorkItemsApi'
import { companyWorkItemKeys } from '@/hooks/useCompanyWorkItemsApi'

export type TaskNotesScope = 'personal' | 'company'

interface NoteEvent {
  id: string
  task_id: string
  event_type: string
  actor: string
  summary?: string
  created_at: string
}

interface TaskNotesPanelProps {
  taskId: string
  scope: TaskNotesScope
  // Optional actor override — personal defaults to 'self', company to 'dashboard'
  actor?: string
}

function endpoint(scope: TaskNotesScope, taskId: string) {
  const prefix = scope === 'personal' ? '/api/personal/work-items' : '/api/company/work-items'
  return `${prefix}/${taskId}/notes`
}

/**
 * Shared notes composer + history. Notes are persisted as
 * `company_task_events` rows with event_type='note' — they show up in the
 * underlying audit log too, but this panel filters to that one type so it
 * reads like a chat thread of human-authored notes.
 */
export function TaskNotesPanel({ taskId, scope, actor }: TaskNotesPanelProps) {
  const qc = useQueryClient()
  const personalEvents = usePersonalTaskEvents(scope === 'personal' ? taskId : undefined)
  const companyEvents = useCompanyTaskEvents(scope === 'company' ? taskId : undefined)
  const events = (scope === 'personal' ? personalEvents.data : companyEvents.data) ?? []

  const notes = useMemo(
    () => events.filter((e: NoteEvent) => e.event_type === 'note').slice(0, 200),
    [events],
  )

  const [draft, setDraft] = useState('')
  const defaultActor = actor ?? (scope === 'personal' ? 'self' : 'dashboard')

  const addNote = useMutation({
    mutationFn: (note: string) =>
      fetch(endpoint(scope, taskId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ actor: defaultActor, note }),
      }).then(async (r) => {
        if (!r.ok) {
          const detail = await r.json().catch(() => ({ detail: r.statusText }))
          throw new Error(String(detail.detail || r.statusText))
        }
        return r.json()
      }),
    onSuccess: () => {
      setDraft('')
      const keys =
        scope === 'personal'
          ? personalWorkItemKeys.events(taskId)
          : companyWorkItemKeys.events(taskId)
      qc.invalidateQueries({ queryKey: keys })
    },
  })

  const submit = () => {
    const text = draft.trim()
    if (!text) return
    addNote.mutate(text)
  }

  const deleteNote = useMutation({
    mutationFn: (eventId: string) =>
      fetch(`${endpoint(scope, taskId)}/${eventId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      }).then(async (r) => {
        if (!r.ok) {
          const detail = await r.json().catch(() => ({ detail: r.statusText }))
          throw new Error(String(detail.detail || r.statusText))
        }
        return r.json()
      }),
    onSuccess: () => {
      const keys =
        scope === 'personal'
          ? personalWorkItemKeys.events(taskId)
          : companyWorkItemKeys.events(taskId)
      qc.invalidateQueries({ queryKey: keys })
    },
  })

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-gray-500">
        <StickyNote className="w-3.5 h-3.5" />
        <span>Notes ({notes.length})</span>
        <span className="text-gray-600 normal-case tracking-normal text-[10px]">
          — captured before completion; preserved in audit trail
        </span>
      </div>

      <div className="space-y-1.5 max-h-60 overflow-y-auto pr-1">
        {notes.map((n: NoteEvent) => (
          <div
            key={n.id}
            className="group rounded-md border border-amber-900/40 bg-amber-950/20 p-2 text-sm text-gray-200"
          >
            <div className="flex items-center justify-between gap-2 mb-1 text-[11px] text-gray-500">
              <span>{n.actor}</span>
              <div className="flex items-center gap-2">
                <span>{new Date(n.created_at).toLocaleString()}</span>
                <button
                  onClick={() => {
                    if (confirm('Delete this note? Audit-trail events remain untouched.')) {
                      deleteNote.mutate(n.id)
                    }
                  }}
                  className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-rose-400 transition-opacity"
                  title="Delete note"
                  aria-label="Delete note"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            </div>
            <div className="whitespace-pre-wrap break-words">{n.summary}</div>
          </div>
        ))}
        {notes.length === 0 && (
          <div className="text-xs italic text-gray-600">No notes yet. Add one before completing the task.</div>
        )}
      </div>

      <div className="flex items-start gap-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          placeholder="Jot a note (e.g., spoke with Duval CVSO at 904-255-5550, appt 2026-05-20…)"
          className="flex-1 bg-gray-950 border border-gray-800 rounded p-2 text-sm focus:outline-none focus:border-amber-600"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit()
          }}
        />
        <button
          onClick={submit}
          disabled={!draft.trim() || addNote.isPending}
          className="px-3 py-2 rounded-lg bg-amber-700 hover:bg-amber-600 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm inline-flex items-center gap-1.5 self-stretch"
          title="Add note (⌘/Ctrl+Enter)"
        >
          <Send className="w-3.5 h-3.5" />
          {addNote.isPending ? 'Adding…' : 'Add note'}
        </button>
      </div>

      {addNote.isError && (
        <div className="text-xs text-rose-400">Failed to add note: {(addNote.error as Error).message}</div>
      )}
    </section>
  )
}
