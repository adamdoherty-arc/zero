import { useCurrentSprint, useDailyBriefing } from '@/hooks/useSprintApi'
import { useHealthReady, useSchedulerStatus } from '@/hooks/useSystemApi'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { Zap, ListTodo, Mail, Calendar, Brain, HeartPulse } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AgentStatusCard } from '@/components/agent/AgentStatusCard'
import { TaskSubmitForm } from '@/components/agent/TaskSubmitForm'
import { TaskHistory } from '@/components/agent/TaskHistory'

function SystemStatusCard() {
  const { data: health } = useHealthReady()
  const { data: scheduler } = useSchedulerStatus()

  const checks = health?.checks ?? {}
  const totalChecks = Object.keys(checks).length
  const okChecks = Object.values(checks).filter((s) => s === 'ok').length
  const allGreen = totalChecks > 0 && okChecks === totalChecks

  return (
    <Link to="/system-health" className="glass-card-hover p-4 flex items-center gap-4">
      <div className={`p-2 rounded-lg ${allGreen ? 'bg-green-500/10' : 'bg-yellow-500/10'}`}>
        <HeartPulse className={`w-6 h-6 ${allGreen ? 'text-green-400' : 'text-yellow-400'}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">System Health</span>
          <span className={`text-xs px-1.5 py-0.5 rounded-full ${allGreen ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
            {okChecks}/{totalChecks} OK
          </span>
        </div>
        <p className="text-xs text-gray-400 mt-0.5">
          {scheduler?.job_count ?? 0} jobs {scheduler?.running ? 'running' : 'stopped'}
        </p>
      </div>
    </Link>
  )
}

export function DashboardPage() {
  const { data: currentSprint } = useCurrentSprint()
  const { data: briefing, isLoading: isLoadingBriefing } = useDailyBriefing()

  const quickLinks = [
    { label: 'Sprint Board', href: '/board', icon: ListTodo, color: 'text-blue-400' },
    { label: 'Email', href: '/email', icon: Mail, color: 'text-green-400' },
    { label: 'Calendar', href: '/calendar', icon: Calendar, color: 'text-purple-400' },
    { label: 'Knowledge', href: '/knowledge', icon: Brain, color: 'text-amber-400' },
  ]

  return (
    <div className="page-content">
      <div className="flex items-center gap-3 mb-8">
        <Zap className="w-8 h-8 text-primary" />
        <h1 className="page-title">Welcome to Zero</h1>
      </div>

      {/* Agent Controls — front and center */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <AgentStatusCard />
        <TaskSubmitForm />
      </div>

      {/* System Status */}
      <div className="mb-8">
        <SystemStatusCard />
      </div>

      {/* Daily Briefing Card */}
      <div className="glass-card p-6 mb-8 border-l-4 border-l-primary/50">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <span>Daily Briefing</span>
          {briefing?.date && <span className="text-xs font-normal text-muted-foreground ml-auto">{briefing.date}</span>}
        </h2>

        {isLoadingBriefing ? (
          <LoadingSkeleton variant="cards" count={4} />
        ) : briefing ? (
          <div className="space-y-4">
            <p className="text-lg font-medium text-accent">{briefing.greeting}</p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {briefing.sections.map((section, idx) => (
                <div key={idx} className="bg-white/5 rounded-lg p-4">
                  <h3 className="font-semibold mb-2 flex items-center gap-2">
                    <span>{section.icon}</span>
                    {section.title}
                  </h3>
                  <ul className="space-y-1">
                    {section.items.map((item, i) => (
                      <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                        <span className="mt-1.5 w-1 h-1 rounded-full bg-white/20 shrink-0" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            {briefing.suggestions.length > 0 && (
              <div className="mt-4 pt-4 border-t border-white/10">
                <div className="flex items-center gap-2 text-warning mb-2">
                  <Zap className="w-4 h-4" />
                  <span className="font-semibold text-sm">Suggestions</span>
                </div>
                <ul className="list-disc list-inside text-sm text-muted-foreground">
                  {briefing.suggestions.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="text-muted-foreground">
            No briefing generated yet for today.
          </div>
        )}
      </div>

      {currentSprint && (
        <div className="glass-card p-6 mb-8">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-foreground">{currentSprint.name}</h2>
              <p className="text-sm text-muted-foreground mt-1">
                {currentSprint.goals?.length ? currentSprint.goals[0] : 'No sprint goal set'}
              </p>
            </div>
            <Link to="/board" className="btn-primary">
              Open Board
            </Link>
          </div>
          {currentSprint.total_points > 0 && (
            <div className="mt-4">
              <div className="flex justify-between text-sm text-muted-foreground mb-1">
                <span>Progress</span>
                <span>{currentSprint.completed_points}/{currentSprint.total_points} pts</span>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{ width: `${(currentSprint.completed_points / currentSprint.total_points) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Recent Agent Activity */}
      <div className="mb-8">
        <TaskHistory />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {quickLinks.map((link) => (
          <Link
            key={link.href}
            to={link.href}
            className="glass-card-hover p-6 flex flex-col items-center gap-3 text-center"
          >
            <link.icon className={`w-8 h-8 ${link.color}`} />
            <span className="text-sm font-medium text-foreground">{link.label}</span>
          </Link>
        ))}
      </div>
    </div>
  )
}
