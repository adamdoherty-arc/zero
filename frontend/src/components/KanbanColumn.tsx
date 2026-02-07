import { useDroppable } from '@dnd-kit/core'
import type { ReactNode } from 'react'

interface KanbanColumnProps {
  id: string
  title: string
  count: number
  colorClass: string
  children: ReactNode
}

export function KanbanColumn({ id, title, count, colorClass, children }: KanbanColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id })

  return (
    <div
      ref={setNodeRef}
      className={`
        kanban-column min-w-[280px] w-[280px] flex-shrink-0
        border-t-2 ${colorClass}
        ${isOver ? 'bg-primary/10' : ''}
        transition-colors
      `}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium text-gray-300">{title}</h3>
        <span className="badge badge-neutral">
          {count}
        </span>
      </div>

      <div className="space-y-2 min-h-[400px]">
        {children}
      </div>
    </div>
  )
}
