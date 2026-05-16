import { AlertTriangle, RefreshCw } from 'lucide-react'
import { useProviderStatus } from '@/hooks/useProviderStatus'

/**
 * LlmProviderBanner — surfaces "LLM provider is down" on the /zero cockpit.
 *
 * The realtime config can say `realtime_available: true` while the active
 * provider is actually returning 500s through Bifrost (we shipped this
 * exact regression on 2026-05-15 because the Hyper-V firewall blocked
 * Docker -> Bifrost without us noticing). This banner reads the same
 * /api/reachy-intent/providers/status endpoint that the TopBar's
 * LLMStatusBadge already polls; when the active provider is `ok: false`
 * AND no fallback is `ok: true`, we render an amber strip so the user
 * sees the failure before clicking "Start session" and waiting on a
 * connect that will never complete.
 */
export function LlmProviderBanner() {
  // Poll at the slow (60s) cadence — TopBar's badge already drives the
  // faster cadence when the user is interacting.
  const { data, error, refetch, loading } = useProviderStatus({ active: false })

  if (error || !data) return null
  const providers = data.providers ?? []
  if (providers.length === 0) return null

  const activeId = data.active_id
  const activeProvider = providers.find((p) => p.id === activeId) ?? providers[0]
  const anyOk = providers.some((p) => p.ok)

  // Don't shout if the active provider is healthy.
  if (activeProvider?.ok) return null

  // If at least one fallback is reachable, render a milder note. Otherwise
  // red-flag the cockpit — the user is about to click a button that won't
  // work.
  const allDown = !anyOk
  const tone = allDown
    ? 'border-red-500/40 bg-red-500/10 text-red-100'
    : 'border-amber-500/40 bg-amber-500/10 text-amber-100'
  const iconTone = allDown ? 'text-red-400' : 'text-amber-400'
  const headline = allDown
    ? 'No LLM provider is reachable'
    : `Active provider "${activeProvider?.label ?? activeId}" is unreachable`
  const detail =
    activeProvider?.error ??
    (allDown
      ? 'Every Bifrost / Local probe failed. Check shared-bifrost + llama-cpp-chat containers, and the Hyper-V firewall rules (run host_agent\\unblock-hyperv-firewall.ps1 as admin).'
      : 'A fallback provider is reachable; the cockpit will keep working but conversations will route through the fallback until the active provider recovers.')

  return (
    <div role="alert" className={`mb-4 rounded-lg border px-4 py-3 ${tone}`}>
      <div className="flex items-start gap-3">
        <AlertTriangle className={`mt-0.5 h-5 w-5 shrink-0 ${iconTone}`} />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{headline}</div>
          <p className="mt-1 text-sm opacity-90 break-words">{detail}</p>
          <p className="mt-1 text-xs opacity-60">
            Probed providers:{' '}
            {providers
              .map((p) => `${p.label}: ${p.ok ? 'ok' : 'down'}`)
              .join(' · ')}
          </p>
        </div>
        <button
          onClick={() => void refetch()}
          disabled={loading}
          className="shrink-0 inline-flex items-center gap-1.5 rounded border border-current/40 bg-black/30 px-2.5 py-1 text-xs font-medium hover:bg-black/50 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Re-probe
        </button>
      </div>
    </div>
  )
}
