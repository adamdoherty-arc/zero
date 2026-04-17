import { useState, useCallback } from 'react'
import { Workflow, Plus, Play, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useVisualWorkflows, useCreateWorkflow,
  useDeleteWorkflow, useExecuteWorkflow,
  useNodeTypes,
} from '@/hooks/useVisualWorkflowApi'

const statusColors: Record<string, string> = {
  draft: 'bg-gray-600 text-gray-200',
  active: 'bg-green-600 text-green-100',
  archived: 'bg-yellow-600 text-yellow-100',
  running: 'bg-blue-600 text-blue-100',
  completed: 'bg-green-600 text-green-100',
  failed: 'bg-red-600 text-red-100',
}

const nodeTypeColors: Record<string, string> = {
  llm_call: 'border-purple-500 bg-purple-500/10',
  api_request: 'border-blue-500 bg-blue-500/10',
  conditional: 'border-yellow-500 bg-yellow-500/10',
  human_approval: 'border-red-500 bg-red-500/10',
  data_transform: 'border-green-500 bg-green-500/10',
  timer: 'border-gray-500 bg-gray-500/10',
  route: 'border-pink-500 bg-pink-500/10',
}

interface WorkflowNode {
  id: string
  type: string
  data: Record<string, unknown>
  position?: { x: number; y: number }
}

export function VisualWorkflowPage() {
  const { data: rawWorkflows, isLoading } = useVisualWorkflows()
  const workflows = (Array.isArray(rawWorkflows) ? rawWorkflows : []) as Record<string, unknown>[]
  const { data: rawNodeTypes } = useNodeTypes()
  const nodeTypes = (Array.isArray(rawNodeTypes) ? rawNodeTypes : []) as Record<string, unknown>[]
  const createMutation = useCreateWorkflow()
  const deleteMutation = useDeleteWorkflow()
  const executeMutation = useExecuteWorkflow()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')

  const handleCreate = useCallback(() => {
    if (!newName.trim()) return
    createMutation.mutate({ name: newName, nodes: [], edges: [] }, {
      onSuccess: () => { setNewName(''); setShowCreate(false) },
    })
  }, [newName, createMutation])

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-48" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-end">
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm"
        >
          <Plus className="w-4 h-4" /> New Workflow
        </button>
      </div>

      {/* Create Dialog */}
      {showCreate && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-sm text-gray-400 mb-1 block">Workflow Name</label>
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="My workflow..."
              className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm"
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
            />
          </div>
          <button onClick={handleCreate} className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded text-sm">Create</button>
          <button onClick={() => setShowCreate(false)} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded text-sm">Cancel</button>
        </div>
      )}

      {/* Node Types Palette */}
      <div className="flex gap-2 flex-wrap">
        {nodeTypes.map((nt: Record<string, unknown>) => (
          <div
            key={nt.type as string}
            className={`px-3 py-1.5 rounded-lg border text-xs font-medium ${nodeTypeColors[nt.type as string] || 'border-gray-600'}`}
          >
            {nt.label as string}
          </div>
        ))}
      </div>

      {/* Workflow Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {workflows.map((wf: Record<string, unknown>) => (
          <div
            key={wf.id as string}
            className={`bg-gray-800 border rounded-lg p-4 cursor-pointer transition-colors hover:border-indigo-500 ${
              selectedId === wf.id ? 'border-indigo-500' : 'border-gray-700'
            }`}
            onClick={() => setSelectedId(selectedId === wf.id ? null : wf.id as string)}
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-medium text-white truncate">{wf.name as string}</h3>
              <Badge className={`text-xs ${statusColors[wf.status as string] || 'bg-gray-600'}`}>
                {wf.status as string}
              </Badge>
            </div>
            {wf.description != null && (
              <p className="text-sm text-gray-400 mb-3 line-clamp-2">{String(wf.description)}</p>
            )}
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span>{((wf.nodes as unknown[]) || []).length} nodes</span>
              <span>{((wf.edges as unknown[]) || []).length} edges</span>
              <span>v{wf.version as number}</span>
            </div>

            {/* Node Preview */}
            {((wf.nodes as WorkflowNode[]) || []).length > 0 && (
              <div className="flex gap-1 mt-3 flex-wrap">
                {((wf.nodes as WorkflowNode[]) || []).slice(0, 6).map((node, i) => (
                  <div
                    key={i}
                    className={`w-6 h-6 rounded border flex items-center justify-center text-[10px] ${
                      nodeTypeColors[node.type] || 'border-gray-600'
                    }`}
                    title={node.type}
                  >
                    {node.type.charAt(0).toUpperCase()}
                  </div>
                ))}
              </div>
            )}

            {/* Actions */}
            {selectedId === wf.id && (
              <div className="flex gap-2 mt-4 pt-3 border-t border-gray-700">
                <button
                  onClick={e => { e.stopPropagation(); executeMutation.mutate(wf.id as string) }}
                  className="flex items-center gap-1 px-3 py-1.5 bg-green-600/20 text-green-400 rounded text-xs hover:bg-green-600/30"
                  disabled={wf.status !== 'active'}
                >
                  <Play className="w-3 h-3" /> Run
                </button>
                <button
                  onClick={e => { e.stopPropagation(); deleteMutation.mutate(wf.id as string) }}
                  className="flex items-center gap-1 px-3 py-1.5 bg-red-600/20 text-red-400 rounded text-xs hover:bg-red-600/30"
                >
                  <Trash2 className="w-3 h-3" /> Delete
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {workflows.length === 0 && (
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-12 text-center">
          <Workflow className="w-12 h-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400">No workflows yet. Create one to get started.</p>
        </div>
      )}
    </div>
  )
}
