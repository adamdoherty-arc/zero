import { Users } from 'lucide-react'
import { ComingSoon } from '@/components/placeholders/ComingSoon'

export function CrmPage() {
  return (
    <ComingSoon
      title="CRM"
      description="Contacts, companies, deals pipeline, and relationship management."
      icon={<Users className="w-16 h-16 text-cyan-400" />}
    />
  )
}
