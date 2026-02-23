import { useState } from 'react'
import { Send } from 'lucide-react'
import { useSubmitTask } from '@/hooks/useAgentApi'

export function TaskSubmitForm() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState('medium')
  const [expanded, setExpanded] = useState(false)
  const submitTask = useSubmitTask()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !description.trim()) return

    submitTask.mutate(
      { title: title.trim(), description: description.trim(), priority },
      {
        onSuccess: () => {
          setTitle('')
          setDescription('')
          setPriority('medium')
          setExpanded(false)
        },
      }
    )
  }

  return (
    <div className="glass-card p-5">
      <form onSubmit={handleSubmit}>
        <div className="flex items-center gap-3 mb-3">
          <Send className="w-5 h-5 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">Give Zero a Task</h3>
        </div>

        <input
          type="text"
          placeholder="What should Zero work on?"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value)
            if (!expanded && e.target.value.length > 0) setExpanded(true)
          }}
          className="w-full px-3 py-2 bg-background/50 border border-border rounded-md text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />

        {expanded && (
          <div className="mt-3 space-y-3">
            <textarea
              placeholder="Describe in detail what needs to be done..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 bg-background/50 border border-border rounded-md text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-none"
            />

            <div className="flex items-center justify-between">
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="px-3 py-1.5 bg-background/50 border border-border rounded-md text-sm text-foreground"
              >
                <option value="low">Low Priority</option>
                <option value="medium">Medium Priority</option>
                <option value="high">High Priority</option>
                <option value="critical">Critical</option>
              </select>

              <button
                type="submit"
                disabled={!title.trim() || !description.trim() || submitTask.isPending}
                className="btn-primary text-sm px-4 py-1.5 disabled:opacity-50"
              >
                {submitTask.isPending ? 'Submitting...' : 'Submit to Zero'}
              </button>
            </div>

            {submitTask.isError && (
              <p className="text-xs text-red-400">
                Failed: {submitTask.error?.message}
              </p>
            )}
            {submitTask.isSuccess && (
              <p className="text-xs text-green-400">
                Task submitted successfully
              </p>
            )}
          </div>
        )}
      </form>
    </div>
  )
}
