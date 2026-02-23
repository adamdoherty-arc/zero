import { useState } from 'react'
import { X, FolderOpen, Github, Sparkles, Loader2 } from 'lucide-react'
import { useCreateProject, useAnalyzeProjectPath } from '../hooks/useSprintApi'
import type { ProjectType } from '../types'

interface RegisterProjectModalProps {
  isOpen: boolean
  onClose: () => void
}

export function RegisterProjectModal({ isOpen, onClose }: RegisterProjectModalProps) {
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [description, setDescription] = useState('')
  const [projectType, setProjectType] = useState<ProjectType>('local')
  const [tags, setTags] = useState('')
  const [githubUrl, setGithubUrl] = useState('')
  const [githubSyncEnabled, setGithubSyncEnabled] = useState(false)

  const createProject = useCreateProject()
  const analyzeProject = useAnalyzeProjectPath()
  const [analyzeError, setAnalyzeError] = useState('')

  if (!isOpen) return null

  const handleAnalyze = () => {
    if (!path.trim()) return
    setAnalyzeError('')
    analyzeProject.mutate(path.trim(), {
      onSuccess: (data) => {
        if (data.name) setName(data.name)
        if (data.description) setDescription(data.description)
        if (data.project_type) {
          const validTypes = ['local', 'git', 'github', 'gitlab']
          if (validTypes.includes(data.project_type)) {
            setProjectType(data.project_type as ProjectType)
          }
        }
        if (data.tags?.length) setTags(data.tags.join(', '))
        if (data.github_url) setGithubUrl(data.github_url)
      },
      onError: (err) => {
        setAnalyzeError(err instanceof Error ? err.message : 'Analysis failed')
      },
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !path.trim()) return

    createProject.mutate(
      {
        name: name.trim(),
        path: path.trim(),
        description: description.trim() || undefined,
        project_type: projectType,
        tags: tags.trim() ? tags.split(',').map(t => t.trim()).filter(Boolean) : [],
        github_repo_url: githubUrl.trim() || undefined,
        github_sync_enabled: githubSyncEnabled,
      },
      {
        onSuccess: () => {
          setName('')
          setPath('')
          setDescription('')
          setProjectType('local')
          setTags('')
          setGithubUrl('')
          setGithubSyncEnabled(false)
          onClose()
        },
      }
    )
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-50">
      <div className="modal-content w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700/50">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold">Register Project</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-700 rounded transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Project Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="My Project"
              className="input-field"
              autoFocus
              required
            />
          </div>

          {/* Path + AI Analyze */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Path *
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={path}
                onChange={e => setPath(e.target.value)}
                placeholder="C:\code\my-project or /home/user/projects/my-project"
                className="input-field font-mono text-sm flex-1"
                required
              />
              <button
                type="button"
                onClick={handleAnalyze}
                disabled={!path.trim() || analyzeProject.isPending}
                className="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 whitespace-nowrap"
                title="AI Analyze — auto-fill fields from project directory"
              >
                {analyzeProject.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {analyzeProject.isPending ? 'Analyzing...' : 'AI Analyze'}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Full path to the project folder — click AI Analyze to auto-fill fields
            </p>
            {analyzeError && (
              <p className="text-xs text-red-400 mt-1">{analyzeError}</p>
            )}
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Description
            </label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Brief description of the project..."
              rows={2}
              className="input-field resize-none"
            />
          </div>

          {/* Project Type */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Project Type
            </label>
            <select
              value={projectType}
              onChange={e => setProjectType(e.target.value as ProjectType)}
              className="input-field"
            >
              <option value="local">Local Folder</option>
              <option value="git">Git Repository</option>
              <option value="github">GitHub</option>
              <option value="gitlab">GitLab</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              Git info will be auto-detected if the folder contains a .git directory
            </p>
          </div>

          {/* GitHub URL */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              <Github className="w-4 h-4 inline mr-1" />
              GitHub Repository URL
            </label>
            <input
              type="url"
              value={githubUrl}
              onChange={e => setGithubUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="input-field"
            />
            <p className="text-xs text-gray-500 mt-1">
              Optional: Link to GitHub for issue sync and PR tracking
            </p>
          </div>

          {/* GitHub Sync Toggle */}
          {githubUrl && (
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="github-sync"
                checked={githubSyncEnabled}
                onChange={e => setGithubSyncEnabled(e.target.checked)}
                className="rounded border-gray-600 bg-gray-700 text-indigo-500 focus:ring-indigo-500"
              />
              <label htmlFor="github-sync" className="text-sm text-gray-400">
                Enable automatic GitHub sync (issues & PRs)
              </label>
            </div>
          )}

          {/* Tags */}
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1">
              Tags
            </label>
            <input
              type="text"
              value={tags}
              onChange={e => setTags(e.target.value)}
              placeholder="frontend, react, typescript"
              className="input-field"
            />
            <p className="text-xs text-gray-500 mt-1">
              Comma-separated tags for organizing projects
            </p>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || !path.trim() || createProject.isPending}
              className="btn-primary"
            >
              {createProject.isPending ? 'Registering...' : 'Register Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
