import { Link } from 'react-router-dom'
import { ArrowLeft, Bot } from 'lucide-react'
import { CompanionConsole } from '@/components/reachy/CompanionConsole'
import { DaemonPanel } from '@/components/reachy/DaemonPanel'
import { HostAgentOfflineBanner } from '@/components/reachy/HostAgentOfflineBanner'
import { InteractiveModeHero } from '@/components/reachy/ReachyManagementPanels'
import { StreamingHealthCard } from '@/components/reachy/StreamingHealthCard'

/**
 * Legacy /zero view — kept as a one-week escape hatch after the
 * 2026-05-15 cockpit merge. Renders the original three stacked
 * components (CompanionConsole, InteractiveModeHero, DaemonPanel)
 * separately, exactly as they were before the merged AssistantHero.
 *
 * Removed in a follow-up once we're confident nothing was lost in
 * the merge.
 */
export function ReachyLegacyConsolePage() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <HostAgentOfflineBanner />

      <div className="flex items-center justify-between gap-4 mb-5 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-500/10">
            <Bot className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Zero Assistant Console (legacy)</h1>
            <p className="text-sm text-gray-400">
              Pre-cockpit view. Use the{' '}
              <Link to="/zero" className="text-indigo-400 hover:underline inline-flex items-center gap-1">
                new cockpit <ArrowLeft className="w-3 h-3 rotate-180" />
              </Link>{' '}
              if you don't have a specific reason to be here.
            </p>
          </div>
        </div>
      </div>

      <CompanionConsole />

      <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-2 mt-1">
        Live Conversation
      </div>
      <InteractiveModeHero />

      <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-2 mt-4">
        Daemon
      </div>
      <DaemonPanel />

      <StreamingHealthCard />
    </div>
  )
}
