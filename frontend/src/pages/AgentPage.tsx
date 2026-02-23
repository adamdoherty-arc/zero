import { Cpu } from 'lucide-react'
import { AgentStatusCard } from '@/components/agent/AgentStatusCard'
import { EngineStatusCard } from '@/components/agent/EngineStatusCard'
import { TaskSubmitForm } from '@/components/agent/TaskSubmitForm'
import { ActivityFeed } from '@/components/agent/ActivityFeed'
import { TaskHistory } from '@/components/agent/TaskHistory'

export function AgentPage() {
  return (
    <div className="page-content">
      <div className="flex items-center gap-3 mb-8">
        <Cpu className="w-8 h-8 text-primary" />
        <h1 className="page-title">Agent Tasks</h1>
      </div>

      {/* Top row: Agent Status | Engine Status | Submit Form */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <AgentStatusCard />
        <EngineStatusCard />
        <TaskSubmitForm />
      </div>

      {/* Activity Feed */}
      <div className="mb-8">
        <ActivityFeed />
      </div>

      {/* Task History */}
      <TaskHistory />
    </div>
  )
}
