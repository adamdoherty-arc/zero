import { useState } from 'react'
import { Settings, Cpu, Clock, Activity, Monitor, Route } from 'lucide-react'
import { AgentSettingsTab } from '@/components/settings/AgentSettingsTab'
import { SchedulerTab } from '@/components/settings/SchedulerTab'
import { HealthTab } from '@/components/settings/HealthTab'
import { GpuTab } from '@/components/settings/GpuTab'
import { LlmTab } from '@/components/settings/LlmTab'

const tabs = [
  { id: 'agent', label: 'Agent', icon: Cpu },
  { id: 'llm', label: 'LLM Router', icon: Route },
  { id: 'gpu', label: 'GPU / Ollama', icon: Monitor },
  { id: 'scheduler', label: 'Scheduler', icon: Clock },
  { id: 'health', label: 'Health', icon: Activity },
] as const

type TabId = (typeof tabs)[number]['id']

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('agent')

  return (
    <div className="page-content">
      <div className="flex items-center gap-3 mb-8">
        <Settings className="w-8 h-8 text-primary" />
        <h1 className="page-title">Settings</h1>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 border-b border-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'agent' && <AgentSettingsTab />}
      {activeTab === 'llm' && <LlmTab />}
      {activeTab === 'gpu' && <GpuTab />}
      {activeTab === 'scheduler' && <SchedulerTab />}
      {activeTab === 'health' && <HealthTab />}
    </div>
  )
}
