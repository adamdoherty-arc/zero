import { useState } from 'react'
import {
  Monitor,
  Loader2,
  RefreshCw,
  Upload,
  Trash2,
  CheckCircle,
  AlertTriangle,
} from 'lucide-react'
import {
  useGpuStatus,
  useAvailableModels,
  useLoadModel,
  useUnloadModel,
  useForceGpuRefresh,
} from '@/hooks/useGpuApi'
import type { LoadedModel, OllamaModelInfo } from '@/types'

function formatMB(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

function VramBar({
  total,
  used,
  models,
}: {
  total: number
  used: number
  models: LoadedModel[]
}) {
  const usedPercent = Math.min((used / total) * 100, 100)
  const freePercent = 100 - usedPercent

  const colors = [
    'bg-indigo-500',
    'bg-purple-500',
    'bg-cyan-500',
    'bg-amber-500',
    'bg-emerald-500',
  ]

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{formatMB(used)} used</span>
        <span>{formatMB(total - used)} free</span>
        <span>{formatMB(total)} total</span>
      </div>
      <div className="h-6 bg-gray-800 rounded-lg overflow-hidden flex">
        {models.map((m, i) => {
          const pct = (m.size_vram_mb / total) * 100
          if (pct < 0.5) return null
          return (
            <div
              key={m.name}
              className={`${colors[i % colors.length]} relative group`}
              style={{ width: `${pct}%` }}
              title={`${m.name}: ${formatMB(m.size_vram_mb)} (${m.vram_percent}%)`}
            >
              {pct > 8 && (
                <span className="absolute inset-0 flex items-center justify-center text-[10px] text-white font-medium truncate px-1">
                  {m.name.split(':')[0]}
                </span>
              )}
            </div>
          )
        })}
        {freePercent > 1 && (
          <div
            className="bg-gray-700"
            style={{ width: `${freePercent}%` }}
          />
        )}
      </div>
    </div>
  )
}

function LoadedModelsTable({
  models,
  onUnload,
  unloading,
}: {
  models: LoadedModel[]
  onUnload: (name: string) => void
  unloading: boolean
}) {
  if (models.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No models currently loaded in VRAM.</p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted-foreground">
            <th className="py-2 pr-4">Model</th>
            <th className="py-2 pr-4">VRAM</th>
            <th className="py-2 pr-4">%</th>
            <th className="py-2 pr-4">Context</th>
            <th className="py-2 pr-4">Expires</th>
            <th className="py-2" />
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.name} className="border-b border-border/50">
              <td className="py-2 pr-4 font-medium text-foreground">{m.name}</td>
              <td className="py-2 pr-4 text-muted-foreground">
                {formatMB(m.size_vram_mb)}
              </td>
              <td className="py-2 pr-4 text-muted-foreground">
                {m.vram_percent.toFixed(1)}%
              </td>
              <td className="py-2 pr-4 text-muted-foreground">
                {m.context_length ? m.context_length.toLocaleString() : '-'}
              </td>
              <td className="py-2 pr-4 text-muted-foreground text-xs">
                {m.expires_at
                  ? new Date(m.expires_at).toLocaleTimeString()
                  : '-'}
              </td>
              <td className="py-2">
                <button
                  onClick={() => onUnload(m.name)}
                  disabled={unloading}
                  className="text-red-400 hover:text-red-300 disabled:opacity-50 p-1"
                  title="Unload from VRAM"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AvailableModelsList({
  models,
  loadedNames,
  onLoad,
  loading,
}: {
  models: OllamaModelInfo[]
  loadedNames: Set<string>
  onLoad: (name: string) => void
  loading: boolean
}) {
  if (models.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No models found in Ollama.</p>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {models.map((m) => {
        const isLoaded = loadedNames.has(m.name)
        return (
          <div
            key={m.name}
            className="glass-card p-3 flex items-center justify-between"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground truncate">
                {m.name}
              </p>
              <p className="text-xs text-muted-foreground">
                {m.size_gb} GB
                {m.parameter_size && ` | ${m.parameter_size}`}
                {m.family && ` | ${m.family}`}
              </p>
            </div>
            {isLoaded ? (
              <span className="text-xs text-green-400 flex items-center gap-1 shrink-0">
                <CheckCircle className="w-3 h-3" /> Loaded
              </span>
            ) : (
              <button
                onClick={() => onLoad(m.name)}
                disabled={loading}
                className="text-indigo-400 hover:text-indigo-300 disabled:opacity-50 p-1 shrink-0"
                title="Load into VRAM"
              >
                <Upload className="w-4 h-4" />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function GpuTab() {
  const { data: status, isLoading } = useGpuStatus()
  const { data: availableData } = useAvailableModels()
  const loadModel = useLoadModel()
  const unloadModel = useUnloadModel()
  const forceRefresh = useForceGpuRefresh()
  const [loadingModel, setLoadingModel] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading GPU status...
      </div>
    )
  }

  if (!status) {
    return (
      <div className="text-sm text-muted-foreground">
        Could not reach GPU management endpoint.
      </div>
    )
  }

  const loadedNames = new Set(status.loaded_models.map((m) => m.name))
  const availableModels = availableData?.models ?? status.available_models

  const handleLoad = async (model: string) => {
    setLoadingModel(model)
    try {
      await loadModel.mutateAsync({ model, force: false })
    } catch {
      // Error handled by React Query
    } finally {
      setLoadingModel(null)
    }
  }

  const handleUnload = async (model: string) => {
    try {
      await unloadModel.mutateAsync({ model })
    } catch {
      // Error handled by React Query
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Monitor className="w-5 h-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium text-foreground">
              GPU / Ollama Resource Manager
            </p>
            <p className="text-xs text-muted-foreground">
              {status.gpu.name} | Ollama:{' '}
              {status.ollama_healthy ? (
                <span className="text-green-400">Connected</span>
              ) : (
                <span className="text-red-400">Disconnected</span>
              )}
              {status.last_refresh && (
                <> | Updated {new Date(status.last_refresh).toLocaleTimeString()}</>
              )}
            </p>
          </div>
        </div>
        <button
          onClick={() => forceRefresh.mutate()}
          disabled={forceRefresh.isPending}
          className="text-muted-foreground hover:text-foreground p-1.5 rounded"
          title="Force refresh"
        >
          <RefreshCw
            className={`w-4 h-4 ${forceRefresh.isPending ? 'animate-spin' : ''}`}
          />
        </button>
      </div>

      {/* VRAM Bar */}
      <div className="glass-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">VRAM Usage</h3>
        <VramBar
          total={status.gpu.total_vram_mb}
          used={status.gpu.used_vram_mb}
          models={status.loaded_models}
        />
      </div>

      {/* Loaded Models */}
      <div className="glass-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">
          Loaded Models ({status.loaded_models.length})
        </h3>
        <LoadedModelsTable
          models={status.loaded_models}
          onUnload={handleUnload}
          unloading={unloadModel.isPending}
        />
      </div>

      {/* Available Models */}
      <div className="glass-card p-4">
        <h3 className="text-sm font-medium text-foreground mb-3">
          Available Models ({availableModels.length})
        </h3>
        {loadingModel && (
          <div className="flex items-center gap-2 text-sm text-indigo-400 mb-3">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Loading {loadingModel}... This may take a minute.
          </div>
        )}
        <AvailableModelsList
          models={availableModels}
          loadedNames={loadedNames}
          onLoad={handleLoad}
          loading={loadModel.isPending}
        />
      </div>

      {/* Project Usage */}
      {status.project_usage.length > 0 && (
        <div className="glass-card p-4">
          <h3 className="text-sm font-medium text-foreground mb-3">
            Project Usage
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-2 pr-4">Project</th>
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4">Requests</th>
                  <th className="py-2">Last Used</th>
                </tr>
              </thead>
              <tbody>
                {status.project_usage.map((u) => (
                  <tr
                    key={`${u.project}:${u.model}`}
                    className="border-b border-border/50"
                  >
                    <td className="py-2 pr-4 font-medium text-foreground capitalize">
                      {u.project}
                    </td>
                    <td className="py-2 pr-4 text-muted-foreground">{u.model}</td>
                    <td className="py-2 pr-4 text-muted-foreground">
                      {u.request_count}
                    </td>
                    <td className="py-2 text-muted-foreground text-xs">
                      {new Date(u.last_used_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Warnings */}
      {!status.ollama_healthy && (
        <div className="flex items-center gap-2 text-sm text-amber-400">
          <AlertTriangle className="w-4 h-4" />
          Ollama is not reachable at {status.ollama_url}
        </div>
      )}
    </div>
  )
}
