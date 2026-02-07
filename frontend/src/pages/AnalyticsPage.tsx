import { BarChart3 } from 'lucide-react'
import { ComingSoon } from '@/components/placeholders/ComingSoon'

export function AnalyticsPage() {
  return (
    <ComingSoon
      title="Analytics"
      description="Sprint velocity, task trends, email volume, project health, and activity feed."
      icon={<BarChart3 className="w-16 h-16 text-indigo-400" />}
    />
  )
}
