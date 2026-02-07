import { useState, useMemo } from 'react'
import { useSprints } from '@/hooks/useSprintApi'
import { SprintList } from '@/components/SprintList'

const STATUS_TABS: { label: string; value: string | undefined }[] = [
  { label: 'All', value: undefined },
  { label: 'Active', value: 'active' },
  { label: 'Planning', value: 'planning' },
  { label: 'Completed', value: 'completed' },
  { label: 'Paused', value: 'paused' },
]

export function SprintsPage() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [projectFilter, setProjectFilter] = useState<number | undefined>()

  const { data: sprints, isLoading, error } = useSprints({
    project_id: projectFilter,
    status: statusFilter,
  })

  // Extract unique project names from sprint data for the project filter dropdown
  const projects = useMemo(() => {
    if (!sprints) return []
    const seen = new Map<number, string>()
    for (const s of sprints) {
      if (s.project_id && s.project_name && !seen.has(s.project_id)) {
        seen.set(s.project_id, s.project_name)
      }
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }))
  }, [sprints])

  return (
    <div className="page-content">
      <h1 className="page-title mb-6">Sprints</h1>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 mb-6">
        {/* Status tabs */}
        <div className="flex gap-1 bg-gray-800/50 rounded-lg p-1">
          {STATUS_TABS.map(tab => (
            <button
              key={tab.label}
              onClick={() => setStatusFilter(tab.value)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                statusFilter === tab.value
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700/50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Project filter */}
        {projects.length > 1 && (
          <select
            value={projectFilter ?? ''}
            onChange={e => setProjectFilter(e.target.value ? Number(e.target.value) : undefined)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">All Projects</option>
            {projects.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
      </div>

      {/* Content */}
      {error && (
        <div className="text-center py-8 text-red-400">
          Failed to load sprints: {(error as Error).message}
        </div>
      )}

      {isLoading && (
        <div className="text-center py-8 text-gray-400">Loading sprints...</div>
      )}

      {!isLoading && !error && (
        <SprintList sprints={sprints || []} />
      )}
    </div>
  )
}
