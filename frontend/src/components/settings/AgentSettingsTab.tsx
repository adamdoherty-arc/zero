import { useState, useEffect } from 'react'
import { Cpu, Save } from 'lucide-react'
import { useAgentSettings, useUpdateAgentSettings, usePauseAgent, useResumeAgent, useAgentStatus } from '@/hooks/useAgentApi'

export function AgentSettingsTab() {
  const { data: settings, isLoading } = useAgentSettings()
  const { data: status } = useAgentStatus()
  const updateSettings = useUpdateAgentSettings()
  const pauseAgent = usePauseAgent()
  const resumeAgent = useResumeAgent()

  const [maxFiles, setMaxFiles] = useState(10)
  const [maxLines, setMaxLines] = useState(200)
  const [protectedPaths, setProtectedPaths] = useState('')

  useEffect(() => {
    if (settings) {
      setMaxFiles(settings.max_files_per_task ?? 10)
      setMaxLines(settings.max_lines_per_file ?? 200)
      setProtectedPaths((settings.protected_paths ?? []).join('\n'))
    }
  }, [settings])

  const handleSave = () => {
    updateSettings.mutate({
      max_files_per_task: maxFiles,
      max_lines_per_file: maxLines,
      protected_paths: protectedPaths.split('\n').map((p) => p.trim()).filter(Boolean),
    })
  }

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">Loading settings...</div>
  }

  return (
    <div className="space-y-6">
      {/* Worker status */}
      <div className="glass-card p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Cpu className="w-5 h-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">Task Worker</p>
              <p className="text-xs text-muted-foreground">
                {status?.paused ? 'Paused — not picking up new tasks' : 'Active — checking queue every 2 minutes'}
              </p>
            </div>
          </div>
          {status?.paused ? (
            <button onClick={() => resumeAgent.mutate()} className="btn-primary text-sm px-4 py-1.5">
              Resume
            </button>
          ) : (
            <button onClick={() => pauseAgent.mutate()} className="text-sm px-4 py-1.5 rounded-md border border-border text-yellow-400 hover:bg-accent/30">
              Pause
            </button>
          )}
        </div>
      </div>

      {/* Limits */}
      <div className="glass-card p-5 space-y-4">
        <h3 className="text-sm font-semibold text-foreground">Execution Limits</h3>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Max files per task</label>
            <input
              type="number"
              min={1}
              max={50}
              value={maxFiles}
              onChange={(e) => setMaxFiles(Number(e.target.value))}
              className="w-full px-3 py-2 bg-background/50 border border-border rounded-md text-sm text-foreground"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Max lines per file</label>
            <input
              type="number"
              min={10}
              max={1000}
              value={maxLines}
              onChange={(e) => setMaxLines(Number(e.target.value))}
              className="w-full px-3 py-2 bg-background/50 border border-border rounded-md text-sm text-foreground"
            />
          </div>
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1">Protected paths (one per line)</label>
          <textarea
            value={protectedPaths}
            onChange={(e) => setProtectedPaths(e.target.value)}
            rows={4}
            className="w-full px-3 py-2 bg-background/50 border border-border rounded-md text-sm text-foreground font-mono resize-none"
          />
        </div>

        <button
          onClick={handleSave}
          disabled={updateSettings.isPending}
          className="btn-primary text-sm px-4 py-1.5 flex items-center gap-2"
        >
          <Save className="w-4 h-4" />
          {updateSettings.isPending ? 'Saving...' : 'Save Settings'}
        </button>

        {updateSettings.isSuccess && (
          <p className="text-xs text-green-400">Settings saved.</p>
        )}
        {updateSettings.isError && (
          <p className="text-xs text-red-400">Failed: {updateSettings.error?.message}</p>
        )}
      </div>
    </div>
  )
}
