import { Settings } from 'lucide-react'
import { ComingSoon } from '@/components/placeholders/ComingSoon'

export function SettingsPage() {
  return (
    <ComingSoon
      title="Settings"
      description="Service health, circuit breakers, scheduler, backups, and integrations."
      icon={<Settings className="w-16 h-16 text-gray-400" />}
    />
  )
}
