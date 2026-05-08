import { useCallback, useEffect, useRef, useState } from 'react'
import { Radio, AlertCircle, Check, Loader2 } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import { useProviderStatus, type ProviderStatus } from '@/hooks/useProviderStatus'

/**
 * Clickable badge that shows the active LLM provider + health dot, and opens
 * a switcher popover listing every classic + realtime backend with status
 * colors. Addresses the "I have no idea what LLM is being used" pain.
 *
 * - Green dot: provider probed OK within the last 15s cache window.
 * - Amber dot: probe took longer than 800 ms (reachable but slow).
 * - Red dot: probe failed or timed out.
 * - Grey dot: provider status not yet known (first render before first poll).
 *
 * Classic providers are swapped via POST /api/reachy-intent/providers.
 * Realtime (OpenAI Realtime / Gemini Live) is swapped via
 * PUT /api/reachy/realtime/config with {backend} — cheap, persists.
 */

interface RealtimeCfg {
  backend: 'openai' | 'gemini'
  preferred_backend: 'openai' | 'gemini' | null
  realtime_available: boolean
  has_openai_key: boolean
  has_gemini_key: boolean
  model: string
  voice: string
}

interface Props {
  /** Whether Interactive Mode (realtime) is currently the active voice path. */
  realtimeActive?: boolean
  /** Called when the user picks a realtime backend and the session is live — the parent
   *  can restart the session cleanly. If omitted, a page-reload toast is shown. */
  onRealtimeSwitch?: (backend: 'openai' | 'gemini') => void
}

const REALTIME_LABELS: Record<string, { label: string; model: string }> = {
  openai: { label: 'OpenAI Realtime', model: 'gpt-realtime' },
  gemini: { label: 'Gemini Live', model: 'gemini-3.1-flash-live-preview' },
}

function statusColorClass(p: ProviderStatus | null): string {
  if (!p) return 'bg-zinc-500'
  if (!p.ok) return 'bg-red-500'
  if ((p.latency_ms ?? 0) > 800) return 'bg-amber-400'
  return 'bg-emerald-500'
}

function statusLabel(p: ProviderStatus | null): string {
  if (!p) return 'unknown'
  if (!p.ok) return `down${p.error ? ` · ${p.error}` : ''}`
  return p.latency_ms != null ? `${p.latency_ms} ms` : 'ok'
}

export function LLMStatusBadge({ realtimeActive = false, onRealtimeSwitch }: Props) {
  const [open, setOpen] = useState(false)
  const [realtimeCfg, setRealtimeCfg] = useState<RealtimeCfg | null>(null)
  const [classicActiveId, setClassicActiveId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  const { data: status, refetch } = useProviderStatus({ active: open || realtimeActive })

  const loadRealtimeCfg = useCallback(async () => {
    try {
      const res = await fetch('/api/reachy/realtime/config', { headers: getAuthHeaders() })
      if (!res.ok) return
      setRealtimeCfg((await res.json()) as RealtimeCfg)
    } catch {
      /* optional */
    }
  }, [])

  const loadClassic = useCallback(async () => {
    try {
      const res = await fetch('/api/reachy-intent/providers', { headers: getAuthHeaders() })
      if (!res.ok) return
      const body = (await res.json()) as { active_id?: string }
      setClassicActiveId(body.active_id ?? null)
    } catch {
      /* optional */
    }
  }, [])

  useEffect(() => {
    void loadRealtimeCfg()
    void loadClassic()
  }, [loadRealtimeCfg, loadClassic])

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', onDocClick)
    return () => window.removeEventListener('mousedown', onDocClick)
  }, [open])

  const setClassic = useCallback(
    async (providerId: string) => {
      setBusy(true)
      try {
        const res = await fetch('/api/reachy-intent/providers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ provider_id: providerId }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const body = (await res.json()) as { active_id: string; label?: string }
        setClassicActiveId(body.active_id)
        toast({
          title: 'Voice brain switched',
          description: `Classic voice now uses ${body.label ?? body.active_id}`,
        })
        await refetch()
      } catch (e) {
        toast({
          variant: 'destructive',
          title: 'Could not switch provider',
          description: e instanceof Error ? e.message : String(e),
        })
      } finally {
        setBusy(false)
      }
    },
    [refetch],
  )

  const setRealtimeBackend = useCallback(
    async (backend: 'openai' | 'gemini') => {
      if (!realtimeCfg) return
      const hasKey = backend === 'openai' ? realtimeCfg.has_openai_key : realtimeCfg.has_gemini_key
      if (!hasKey) {
        toast({
          variant: 'destructive',
          title: 'API key missing',
          description: `Add a ${backend === 'openai' ? 'OpenAI' : 'Gemini'} key in realtime settings.`,
        })
        return
      }
      setBusy(true)
      try {
        const res = await fetch('/api/reachy/realtime/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ backend }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const updated = (await res.json()) as RealtimeCfg
        setRealtimeCfg(updated)
        toast({
          title: 'Interactive Mode backend switched',
          description: `${REALTIME_LABELS[backend].label} — ${REALTIME_LABELS[backend].model}`,
        })
        if (onRealtimeSwitch) onRealtimeSwitch(backend)
      } catch (e) {
        toast({
          variant: 'destructive',
          title: 'Could not switch realtime backend',
          description: e instanceof Error ? e.message : String(e),
        })
      } finally {
        setBusy(false)
      }
    },
    [realtimeCfg, onRealtimeSwitch],
  )

  // Determine which provider the badge is currently representing. Realtime
  // mode trumps classic — when the user is in Interactive Mode, show which
  // realtime backend; otherwise show classic.
  const classicStatuses: Record<string, ProviderStatus> = {}
  status?.providers?.forEach((p) => {
    classicStatuses[p.id] = p
  })
  const activeClassicStatus = classicActiveId ? classicStatuses[classicActiveId] : null

  const showRealtime = realtimeActive && realtimeCfg?.realtime_available
  const activeLabel = showRealtime
    ? `Interactive · ${REALTIME_LABELS[realtimeCfg!.backend].label}`
    : activeClassicStatus
      ? activeClassicStatus.label
      : classicActiveId ?? 'Loading…'
  const activeDotClass = showRealtime
    ? 'bg-emerald-500 animate-pulse'
    : statusColorClass(activeClassicStatus)

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={
          showRealtime
            ? `Live through ${REALTIME_LABELS[realtimeCfg!.backend].label}. Click to switch.`
            : activeClassicStatus
              ? `Classic voice via ${activeClassicStatus.label} (${statusLabel(activeClassicStatus)})`
              : 'Click to pick a voice brain'
        }
        className={[
          'flex items-center gap-2 rounded-full border px-3 py-1 text-xs',
          'bg-zinc-900 hover:bg-zinc-800 border-zinc-700 text-zinc-100',
          'transition-colors',
        ].join(' ')}
      >
        <span className={`w-2 h-2 rounded-full ${activeDotClass}`} aria-hidden />
        <span className="font-medium">{activeLabel}</span>
        {showRealtime && <Radio className="w-3 h-3 text-indigo-400" />}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 w-80 z-50 bg-zinc-950 border border-zinc-700 rounded-lg shadow-xl overflow-hidden"
          role="dialog"
          aria-label="Voice brain picker"
        >
          {/* Realtime section */}
          <div className="px-3 pt-3 pb-1 text-[10px] uppercase tracking-wide text-zinc-500">
            Interactive Mode (live conversation)
          </div>
          {(['openai', 'gemini'] as const).map((backend) => {
            const meta = REALTIME_LABELS[backend]
            const hasKey =
              backend === 'openai' ? realtimeCfg?.has_openai_key : realtimeCfg?.has_gemini_key
            const isActive = showRealtime && realtimeCfg?.backend === backend
            return (
              <button
                key={backend}
                type="button"
                disabled={busy || !hasKey}
                onClick={() => void setRealtimeBackend(backend)}
                className={[
                  'w-full flex items-center gap-2 px-3 py-2 text-xs text-left',
                  isActive
                    ? 'bg-indigo-900/40 text-indigo-100'
                    : 'hover:bg-zinc-800 text-zinc-200',
                  !hasKey && 'opacity-40 cursor-not-allowed',
                ].join(' ')}
              >
                <span
                  className={`w-2 h-2 rounded-full ${hasKey ? 'bg-emerald-500' : 'bg-zinc-600'}`}
                  aria-hidden
                />
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{meta.label}</div>
                  <div className="text-[10px] text-zinc-500 truncate">{meta.model}</div>
                </div>
                {!hasKey && <span className="text-[10px] text-amber-400">key needed</span>}
                {isActive && <Check className="w-3 h-3 text-indigo-400" />}
              </button>
            )
          })}

          {/* Classic section */}
          <div className="px-3 pt-3 pb-1 mt-1 text-[10px] uppercase tracking-wide text-zinc-500 border-t border-zinc-800">
            Classic (push-to-talk)
          </div>
          {status?.providers?.map((p) => {
            const isActive = classicActiveId === p.id
            return (
              <button
                key={p.id}
                type="button"
                disabled={busy}
                onClick={() => void setClassic(p.id)}
                className={[
                  'w-full flex items-center gap-2 px-3 py-2 text-xs text-left',
                  isActive
                    ? 'bg-indigo-900/40 text-indigo-100'
                    : 'hover:bg-zinc-800 text-zinc-200',
                ].join(' ')}
              >
                <span className={`w-2 h-2 rounded-full ${statusColorClass(p)}`} aria-hidden />
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{p.label}</div>
                  <div className="text-[10px] text-zinc-500 truncate">
                    {p.model} · {statusLabel(p)}
                  </div>
                </div>
                {isActive && <Check className="w-3 h-3 text-indigo-400" />}
                {busy && isActive && <Loader2 className="w-3 h-3 animate-spin" />}
              </button>
            )
          })}
          {!status && (
            <div className="px-3 py-3 text-xs text-zinc-500 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> Probing providers…
            </div>
          )}

          {/* Failure hint */}
          {status && status.providers.every((p) => !p.ok) && (
            <div className="px-3 py-2 text-[11px] text-red-300 bg-red-900/40 border-t border-red-800 flex items-start gap-1.5">
              <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" />
              All classic providers are down. Interactive Mode (realtime) still
              works if you have an OpenAI or Gemini key.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
