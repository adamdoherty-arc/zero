import {
  useEcosystemStatus,
  useEcosystemAlerts,
  useEcosystemTimeline,
  useEcosystemSuggestions,
  useTriggerEcosystemSync,
} from '@/hooks/useSprintApi'
import { ProjectCard } from '@/components/ecosystem/ProjectCard'
import { AlertsPanel } from '@/components/ecosystem/AlertsPanel'
import { SprintTimeline } from '@/components/ecosystem/SprintTimeline'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { OrchestrationPanel } from '@/components/ecosystem/OrchestrationPanel'
import { OrchestrationLog } from '@/components/ecosystem/OrchestrationLog'
import {
  Globe,
  RefreshCw,
  Activity,
  Layers,
  AlertTriangle,
  Heart,
  Lightbulb,
} from 'lucide-react'

function StatCard({
  label,
  value,
  icon: Icon,
  color = 'text-foreground',
}: {
  label: string
  value: number | string
  icon: React.ElementType
  color?: string
}) {
  return (
    <div className="glass-card p-4 flex items-center gap-3">
      <Icon className={`w-5 h-5 ${color}`} />
      <div>
        <div className="text-xl font-bold text-foreground">{value}</div>
        <div className="text-[11px] text-muted-foreground">{label}</div>
      </div>
    </div>
  )
}

export function EcosystemPage() {
  const { data: status, isLoading } = useEcosystemStatus()
  const { data: alertsData } = useEcosystemAlerts()
  const { data: timelineData } = useEcosystemTimeline()
  const { data: suggestionsData } = useEcosystemSuggestions()
  const triggerSync = useTriggerEcosystemSync()

  const alerts = alertsData?.alerts ?? []
  const timeline = timelineData?.sprints ?? []
  const suggestions = suggestionsData?.suggestions ?? []

  const handleSync = (full: boolean) => {
    triggerSync.mutate(full)
  }

  if (isLoading) {
    return (
      <div className="page-content">
        <div className="flex items-center gap-3 mb-8">
          <Globe className="w-8 h-8 text-primary" />
          <h1 className="page-title">Ecosystem</h1>
        </div>
        <LoadingSkeleton variant="page" message="Loading ecosystem data..." />
      </div>
    )
  }

  const noData = !status?.projects?.length

  return (
    <div className="page-content">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Globe className="w-8 h-8 text-primary" />
          <div>
            <h1 className="page-title">Ecosystem</h1>
            {status?.last_full_sync && (
              <p className="text-xs text-muted-foreground">
                Last sync: {new Date(status.last_full_sync).toLocaleString()}
              </p>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => handleSync(false)}
            disabled={triggerSync.isPending}
            className="btn-secondary text-xs flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${triggerSync.isPending ? 'animate-spin' : ''}`} />
            Quick Sync
          </button>
          <button
            onClick={() => handleSync(true)}
            disabled={triggerSync.isPending}
            className="btn-primary text-xs flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${triggerSync.isPending ? 'animate-spin' : ''}`} />
            Full Sync
          </button>
        </div>
      </div>

      {noData ? (
        <div className="glass-card p-12 text-center">
          <Globe className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-lg font-semibold text-foreground mb-2">No Ecosystem Data</h2>
          <p className="text-sm text-muted-foreground mb-4">
            Click "Full Sync" to pull project data from Legion.
          </p>
        </div>
      ) : (
        <>
          {/* Stats Row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <StatCard
              label="Active Projects"
              value={status?.total_projects ?? 0}
              icon={Layers}
              color="text-blue-400"
            />
            <StatCard
              label="Active Sprints"
              value={status?.total_active_sprints ?? 0}
              icon={Activity}
              color="text-green-400"
            />
            <StatCard
              label="Overall Health"
              value={Math.round(status?.overall_health ?? 0)}
              icon={Heart}
              color={
                (status?.overall_health ?? 0) >= 80
                  ? 'text-green-400'
                  : (status?.overall_health ?? 0) >= 50
                    ? 'text-yellow-400'
                    : 'text-red-400'
              }
            />
            <StatCard
              label="Blocked Tasks"
              value={status?.total_blocked_tasks ?? 0}
              icon={AlertTriangle}
              color={
                (status?.total_blocked_tasks ?? 0) > 0 ? 'text-red-400' : 'text-muted-foreground'
              }
            />
          </div>

          {/* Alerts */}
          <AlertsPanel alerts={alerts} />

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className="glass-card p-5 mb-6">
              <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-yellow-400" />
                Suggestions
              </h2>
              <ul className="space-y-1.5">
                {suggestions.map((s, i) => (
                  <li key={i} className="text-xs text-foreground/80 flex items-start gap-2">
                    <span className="text-muted-foreground">-</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Autopilot */}
          <OrchestrationPanel />
          <OrchestrationLog />

          {/* Project Cards */}
          <h2 className="text-sm font-semibold text-foreground mb-3">Projects</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            {status?.projects?.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>

          {/* Sprint Timeline */}
          <SprintTimeline sprints={timeline} />
        </>
      )}
    </div>
  )
}
