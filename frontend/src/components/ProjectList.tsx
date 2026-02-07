import { useState } from 'react'
import { FolderGit2, Scan, Trash2, AlertCircle, CheckCircle, Clock, Plus } from 'lucide-react'
import { useProjects, useDeleteProject, useScanProject } from '../hooks/useSprintApi'
import type { ProjectStatus } from '../types'
import { RegisterProjectModal } from './RegisterProjectModal'

const STATUS_COLORS: Record<ProjectStatus, string> = {
  active: 'badge-success',
  archived: 'badge-neutral',
  scanning: 'badge-info',
}

const STATUS_ICONS: Record<ProjectStatus, React.ComponentType<{ className?: string }>> = {
  active: CheckCircle,
  archived: Clock,
  scanning: Scan,
}

export function ProjectList() {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const { data: projects, isLoading, error } = useProjects()
  const deleteProject = useDeleteProject()
  const scanProject = useScanProject()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12 text-red-400">
        <AlertCircle className="w-5 h-5 mr-2" />
        Failed to load projects
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">Projects</h2>
        <button
          onClick={() => setIsModalOpen(true)}
          className="btn-primary gap-2"
        >
          <Plus className="w-4 h-4" />
          Register Project
        </button>
      </div>

      {/* Project grid */}
      {!projects || projects.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <FolderGit2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p>No projects registered yet.</p>
          <p className="text-sm mt-1">Register your first project to track tasks and scan for improvements.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map(project => {
            const StatusIcon = STATUS_ICONS[project.status]

            return (
              <div
                key={project.id}
                className="glass-card-hover p-4"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <FolderGit2 className="w-5 h-5 text-primary" />
                    <h3 className="font-semibold">{project.name}</h3>
                  </div>
                  <span className={`badge flex items-center gap-1 ${STATUS_COLORS[project.status]}`}>
                    <StatusIcon className="w-3 h-3" />
                    {project.status}
                  </span>
                </div>

                {project.description && (
                  <p className="text-gray-400 text-sm mb-3">{project.description}</p>
                )}

                <div className="text-xs text-gray-500 mb-3 font-mono truncate" title={project.path}>
                  {project.path}
                </div>

                {/* Git info */}
                {project.git_branch && (
                  <div className="text-xs text-gray-400 mb-3">
                    <span className="text-secondary">{project.git_branch}</span>
                    {project.last_commit_hash && (
                      <span className="ml-2 text-gray-500">
                        {project.last_commit_hash}
                      </span>
                    )}
                  </div>
                )}

                {/* Stats */}
                <div className="flex items-center gap-4 text-sm mb-4">
                  <div className="flex items-center gap-1 text-gray-400">
                    <span className="font-semibold text-white">{project.task_count}</span> tasks
                  </div>
                  {project.open_signals > 0 && (
                    <div className="flex items-center gap-1 text-warning">
                      <AlertCircle className="w-4 h-4" />
                      <span>{project.open_signals} signals</span>
                    </div>
                  )}
                </div>

                {/* Last scan */}
                {project.last_scan && (
                  <div className="text-xs text-gray-500 mb-3">
                    Last scan: {new Date(project.last_scan.scanned_at).toLocaleString()}
                    <span className="ml-2">({project.last_scan.files_scanned} files)</span>
                  </div>
                )}

                {/* Tags */}
                {project.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-4">
                    {project.tags.map(tag => (
                      <span key={tag} className="badge badge-neutral">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 pt-3 border-t border-gray-700/50">
                  <button
                    onClick={() => scanProject.mutate(project.id)}
                    disabled={scanProject.isPending || project.status === 'scanning'}
                    className="flex-1 btn-ghost text-primary hover:bg-primary/10 text-sm gap-1 disabled:opacity-50"
                  >
                    <Scan className={`w-4 h-4 ${project.status === 'scanning' ? 'animate-spin' : ''}`} />
                    {project.status === 'scanning' ? 'Scanning...' : 'Scan'}
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`Delete project "${project.name}"?`)) {
                        deleteProject.mutate(project.id)
                      }
                    }}
                    disabled={deleteProject.isPending}
                    className="p-1.5 text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                    title="Delete project"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Register modal */}
      <RegisterProjectModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />
    </div>
  )
}
