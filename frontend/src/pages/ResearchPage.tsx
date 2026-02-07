import { Search } from 'lucide-react'
import { ComingSoon } from '@/components/placeholders/ComingSoon'

export function ResearchPage() {
  return (
    <ComingSoon
      title="Research Agent"
      description="Automated research cycles, findings, topic tracking, and self-improvement."
      icon={<Search className="w-16 h-16 text-teal-400" />}
    />
  )
}
