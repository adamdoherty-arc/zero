import { useState } from 'react'
import {
  Cpu,
  Loader2,
  Check,
  Pencil,
  X,
  DollarSign,
  Activity,
  Zap,
  ArrowRight,
} from 'lucide-react'
import {
  useLlmConfig,
  useSetDefaultModel,
  useSetTaskModel,
  useLlmProviders,
  useLlmUsageToday,
  useLlmAvailableModels,
} from '@/hooks/useLlmApi'
import type { ModelAssignment } from '@/types'

const TASK_LABELS: Record<string, string> = {
  coding: 'Code Generation',
  analysis: 'Signal Analysis',
  research: 'Research & Scoring',
  chat: 'Chat / Conversation',
  classification: 'Email Classification',
  workflow: 'Workflow Steps',
  planning: 'Planning & Scheduling',
  summarization: 'Summarization',
}

const PROVIDER_COLORS: Record<string, string> = {
  ollama: 'text-blue-400',
  gemini: 'text-emerald-400',
  openrouter: 'text-purple-400',
  huggingface: 'text-yellow-400',
  kimi: 'text-orange-400',
}

function getProviderFromModel(model: string): string {
  if (model.includes('/')) return model.split('/')[0]
  return 'ollama'
}

function getModelName(model: string): string {
  if (model.includes('/')) return model.split('/').slice(1).join('/')
  return model
}

function ProviderBadge({ model }: { model: string }) {
  const provider = getProviderFromModel(model)
  const colorClass = PROVIDER_COLORS[provider] || 'text-gray-400'
  return (
    <span className={`text-[10px] font-semibold uppercase ${colorClass} bg-gray-800 px-1.5 py-0.5 rounded`}>
      {provider}
    </span>
  )
}

function TaskRow({
  taskType,
  assignment,
  allModels,
  onSave,
  saving,
}: {
  taskType: string
  assignment: ModelAssignment
  allModels: string[]
  onSave: (taskType: string, model: string, fallbacks: string[]) => void
  saving: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [selectedModel, setSelectedModel] = useState(assignment.model)

  const handleSave = () => {
    onSave(taskType, selectedModel, assignment.fallbacks || [])
    setEditing(false)
  }

  return (
    <tr className="border-b border-border/50">
      <td className="py-2.5 pr-4">
        <span className="text-sm font-medium text-foreground">
          {TASK_LABELS[taskType] || taskType}
        </span>
        <span className="text-xs text-muted-foreground ml-2">({taskType})</span>
      </td>
      <td className="py-2.5 pr-4">
        {editing ? (
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="bg-gray-800 text-sm text-foreground border border-border rounded px-2 py-1 w-full"
          >
            {allModels.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : (
          <div className="flex items-center gap-2">
            <ProviderBadge model={assignment.model} />
            <span className="text-sm text-muted-foreground font-mono">
              {getModelName(assignment.model)}
            </span>
          </div>
        )}
      </td>
      <td className="py-2.5 pr-4">
        {assignment.fallbacks && assignment.fallbacks.length > 0 ? (
          <div className="flex items-center gap-1 flex-wrap">
            {assignment.fallbacks.map((fb, i) => (
              <span key={i} className="flex items-center gap-1">
                {i > 0 && <ArrowRight className="w-2.5 h-2.5 text-gray-600" />}
                <span className="text-[10px] font-mono text-gray-500 bg-gray-800/50 px-1 py-0.5 rounded">
                  {getProviderFromModel(fb)}/{getModelName(fb).slice(0, 15)}
                </span>
              </span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-gray-600">—</span>
        )}
      </td>
      <td className="py-2.5 pr-4 text-xs text-muted-foreground">
        {assignment.temperature !== null ? `t=${assignment.temperature}` : '-'}
      </td>
      <td className="py-2.5">
        {editing ? (
          <div className="flex gap-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-green-400 hover:text-green-300 p-1"
              title="Save"
            >
              <Check className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => {
                setEditing(false)
                setSelectedModel(assignment.model)
              }}
              className="text-muted-foreground hover:text-foreground p-1"
              title="Cancel"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setEditing(true)}
            className="text-muted-foreground hover:text-foreground p-1"
            title="Edit model"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        )}
      </td>
    </tr>
  )
}

export function LlmTab() {
  const { data: config, isLoading } = useLlmConfig()
  const { data: providersData } = useLlmProviders()
  const { data: usageData } = useLlmUsageToday()
  const { data: modelsData } = useLlmAvailableModels()
  const setDefault = useSetDefaultModel()
  const setTask = useSetTaskModel()
  const [editingDefault, setEditingDefault] = useState(false)
  const [newDefault, setNewDefault] = useState('')

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading LLM configuration...
      </div>
    )
  }

  if (!config) {
    return (
      <div className="text-sm text-muted-foreground">
        Could not reach LLM router endpoint.
      </div>
    )
  }

  // Build flat list of all models for selectors
  const allModels: string[] = []
  if (modelsData?.models_by_provider) {
    for (const [provider, models] of Object.entries(modelsData.models_by_provider)) {
      for (const m of models) {
        allModels.push(provider === 'ollama' ? m : `${provider}/${m}`)
      }
    }
  }
  if (allModels.length === 0) allModels.push(config.default_model)

  const providers = providersData?.providers || []

  const handleSetDefault = () => {
    setDefault.mutate(
      { model: newDefault, update_all_tasks: false },
      { onSuccess: () => setEditingDefault(false) },
    )
  }

  const handleSetAllToDefault = () => {
    setDefault.mutate(
      { model: config.default_model, update_all_tasks: true },
    )
  }

  const handleSaveTask = (taskType: string, model: string, fallbacks: string[]) => {
    setTask.mutate({ task_type: taskType, model, fallbacks })
  }

  const budgetPercent = config.daily_budget_usd > 0
    ? ((config.current_spend_usd / config.daily_budget_usd) * 100)
    : 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Cpu className="w-5 h-5 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium text-foreground">
            Multi-Provider LLM Router
          </p>
          <p className="text-xs text-muted-foreground">
            Routes tasks across Ollama, Gemini, OpenRouter, HuggingFace &amp; Kimi with fallback chains
          </p>
        </div>
      </div>

      {/* Provider Health + Cost Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Provider Status */}
        <div className="glass-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="w-4 h-4 text-muted-foreground" />
            <h3 className="text-sm font-medium text-foreground">Provider Status</h3>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {providers.map((p) => (
              <div key={p.name} className="flex items-center gap-2 py-1.5 px-2 rounded bg-gray-800/50">
                <div
                  className={`w-2 h-2 rounded-full ${
                    !p.configured
                      ? 'bg-gray-600'
                      : p.healthy
                        ? 'bg-green-500'
                        : 'bg-red-500'
                  }`}
                />
                <span className={`text-sm font-medium ${PROVIDER_COLORS[p.name] || 'text-gray-400'}`}>
                  {p.name}
                </span>
                <span className="text-[10px] text-gray-500 ml-auto">
                  {!p.configured ? 'no key' : p.healthy ? 'online' : 'down'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Cost Dashboard */}
        <div className="glass-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <DollarSign className="w-4 h-4 text-muted-foreground" />
            <h3 className="text-sm font-medium text-foreground">Today's Usage</h3>
          </div>
          {usageData ? (
            <div className="space-y-3">
              <div className="flex items-baseline gap-3">
                <span className="text-2xl font-bold text-foreground">
                  ${usageData.total_cost_usd.toFixed(4)}
                </span>
                <span className="text-xs text-muted-foreground">
                  / ${usageData.daily_budget_usd.toFixed(2)} budget
                </span>
              </div>
              {/* Budget bar */}
              <div className="w-full bg-gray-800 rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    budgetPercent > 80 ? 'bg-red-500' : budgetPercent > 50 ? 'bg-yellow-500' : 'bg-emerald-500'
                  }`}
                  style={{ width: `${Math.min(budgetPercent, 100)}%` }}
                />
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-lg font-semibold text-foreground">{usageData.total_calls}</p>
                  <p className="text-[10px] text-muted-foreground">calls</p>
                </div>
                <div>
                  <p className="text-lg font-semibold text-foreground">
                    {((usageData.prompt_tokens + usageData.completion_tokens) / 1000).toFixed(1)}k
                  </p>
                  <p className="text-[10px] text-muted-foreground">tokens</p>
                </div>
                <div>
                  <p className="text-lg font-semibold text-foreground">
                    {usageData.avg_latency_ms.toFixed(0)}ms
                  </p>
                  <p className="text-[10px] text-muted-foreground">avg latency</p>
                </div>
              </div>
              {/* Per-provider breakdown */}
              {usageData.by_provider.length > 0 && (
                <div className="border-t border-border/50 pt-2 space-y-1">
                  {usageData.by_provider.map((bp) => (
                    <div key={bp.provider} className="flex items-center justify-between text-xs">
                      <span className={`font-medium ${PROVIDER_COLORS[bp.provider] || 'text-gray-400'}`}>
                        {bp.provider}
                      </span>
                      <span className="text-muted-foreground">
                        {bp.calls} calls · ${bp.cost_usd.toFixed(4)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Loading usage data...</p>
          )}
        </div>
      </div>

      {/* Default Model */}
      <div className="glass-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">Default Model</h3>
        <div className="flex items-center gap-3">
          {editingDefault ? (
            <>
              <select
                value={newDefault}
                onChange={(e) => setNewDefault(e.target.value)}
                className="bg-gray-800 text-sm text-foreground border border-border rounded px-3 py-1.5 flex-1"
              >
                {allModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <button
                onClick={handleSetDefault}
                disabled={setDefault.isPending}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded disabled:opacity-50"
              >
                {setDefault.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  'Save'
                )}
              </button>
              <button
                onClick={() => setEditingDefault(false)}
                className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <ProviderBadge model={config.default_model} />
              <span className="text-sm font-mono text-indigo-400">
                {getModelName(config.default_model)}
              </span>
              <button
                onClick={() => {
                  setNewDefault(config.default_model)
                  setEditingDefault(true)
                }}
                className="text-muted-foreground hover:text-foreground p-1"
                title="Change default model"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
        <div className="mt-3">
          <button
            onClick={handleSetAllToDefault}
            disabled={setDefault.isPending}
            className="text-xs text-muted-foreground hover:text-foreground underline"
          >
            Set all tasks to use default model
          </button>
        </div>
      </div>

      {/* Task Assignments */}
      <div className="glass-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="w-4 h-4 text-muted-foreground" />
          <h3 className="text-sm font-medium text-foreground">
            Task Routing ({Object.keys(config.task_assignments).length} tasks)
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-2 pr-4">Task</th>
                <th className="py-2 pr-4">Primary Model</th>
                <th className="py-2 pr-4">Fallback Chain</th>
                <th className="py-2 pr-4">Temp</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.task_assignments).map(([taskType, assignment]) => (
                <TaskRow
                  key={taskType}
                  taskType={taskType}
                  assignment={assignment}
                  allModels={allModels}
                  onSave={handleSaveTask}
                  saving={setTask.isPending}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
