import { Brain } from 'lucide-react'
import { ComingSoon } from '@/components/placeholders/ComingSoon'

export function KnowledgePage() {
  return (
    <ComingSoon
      title="Knowledge Base"
      description="Notes, ideas, bookmarks, snippets — your second brain with semantic search."
      icon={<Brain className="w-16 h-16 text-amber-400" />}
    />
  )
}
