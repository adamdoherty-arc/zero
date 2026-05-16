import { CompanionConsole } from '@/components/reachy/CompanionConsole'
import { InteractiveModeHero } from '@/components/reachy/ReachyManagementPanels'

/**
 * AssistantHero — the merged "robot assistant console" + "robot assistant"
 * surface that lives at the top-left of /zero.
 *
 * The two underlying components were already wired to the same realtime
 * voice session (`useSharedRealtimeVoice`), they just rendered as two
 * separate cards. This wrapper groups them in one visual frame so the
 * user sees one cockpit instead of two stacked panels — and adds a tiny
 * intro line that explains the order ("start a session, then steer it
 * with modes + skills below").
 *
 * No internal logic is duplicated. Both inner components keep their own
 * hooks, mutations, and styling; this file is purely composition.
 */
export function AssistantHero() {
  return (
    <div className="space-y-4 min-w-0">
      {/* Primary action — start/stop session, transcript, duration. */}
      <InteractiveModeHero />

      {/* Steering — modes, skills, body/health diagnostics. */}
      <CompanionConsole />
    </div>
  )
}
