import { useState } from 'react'
import { useEcosystemStatus, useTriggerEcosystemSync } from '@/hooks/useSprintApi'
import { LegionProjectCard } from './LegionProjectCard'
import { LegionProjectDetail } from './LegionProjectDetail'
import { RefreshCw, CloudOff } from 'lucide-react'

export function LegionProjectList() {
  const [selectedId, setSelectedId] = useState<number>(0)
  const { data: status, isLoading, error } = useEcosystemStatus()
  const syncMutation = useTriggerEcosystemSync()

  const projects = status?.projects ?? []

  const handleSelect = (id: number) => {
    setSelectedId((prev) => (prev === id ? 0 : id))
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="glass-card p-5 animate-pulse">
            <div className="h-5 bg-muted rounded w-2/3 mb-3" />
            <div className="h-3 bg-muted rounded w-full mb-2" />
            <div className="h-3 bg-muted rounded w-1/2" />
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="glass-card p-8 text-center">
        <CloudOff className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
        <p className="text-sm text-muted-foreground mb-3">Failed to load projects from ecosystem cache.</p>
        <button
          type="button"
          onClick={() => syncMutation.mutate(true)}
          disabled={syncMutation.isPending}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-md disabled:opacity-50"
        >
          {syncMutation.isPending ? 'Syncing...' : 'Sync Now'}
        </button>
      </div>
    )
  }

  if (projects.length === 0) {
    return (
      <div className="glass-card p-8 text-center">
        <CloudOff className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
        <p className="text-sm text-foreground mb-1">No projects cached yet</p>
        <p className="text-xs text-muted-foreground mb-4">
          Trigger a full ecosystem sync to pull projects from Legion.
        </p>
        <button
          type="button"
          onClick={() => syncMutation.mutate(true)}
          disabled={syncMutation.isPending}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-md disabled:opacity-50"
        >
          {syncMutation.isPending ? 'Syncing...' : 'Full Sync'}
        </button>
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-muted-foreground">
          {projects.length} project{projects.length !== 1 ? 's' : ''} from Legion
          {status?.last_full_sync && (
            <span className="ml-2">
              &middot; Last sync: {new Date(status.last_full_sync).toLocaleTimeString()}
            </span>
          )}
        </p>
        <button
          type="button"
          onClick={() => syncMutation.mutate(true)}
          disabled={syncMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted rounded-md transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
          {syncMutation.isPending ? 'Syncing...' : 'Sync'}
        </button>
      </div>

      {/* Project Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mb-4">
        {projects.map((project) => (
          <LegionProjectCard
            key={project.id}
            project={project}
            isSelected={selectedId === project.id}
            onSelect={handleSelect}
          />
        ))}
      </div>

      {/* Detail Panel */}
      {selectedId > 0 && (
        <LegionProjectDetail
          projectId={selectedId}
          onClose={() => setSelectedId(0)}
        />
      )}
    </div>
  )
}
