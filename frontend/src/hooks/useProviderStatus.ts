import { useCallback, useEffect, useRef, useState } from 'react'
import { getAuthHeaders } from '@/lib/auth'

/**
 * React hook that polls /api/reachy-intent/providers/status so the UI can
 * paint red/green dots next to each classic LLM provider. The backend caches
 * probes for 15 s, so polling faster than that is a no-op.
 *
 * Poll cadence adapts to interactivity: 20 s when the caller sets
 * ``active=true`` (user has the badge popover open or Interactive Mode is
 * running), 60 s otherwise. Pass ``active=false`` or unmount the caller to
 * stop polling.
 */

export interface ProviderStatus {
  id: string
  label: string
  provider: string
  model: string
  ok: boolean
  latency_ms: number | null
  error: string | null
  checked_at: number
}

export interface ProvidersStatusResponse {
  active_id: string
  checked_at: number
  providers: ProviderStatus[]
}

interface Opts {
  active?: boolean
}

export function useProviderStatus({ active = false }: Opts = {}) {
  const [data, setData] = useState<ProvidersStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const fetchOnce = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    try {
      const res = await fetch('/api/reachy-intent/providers/status', {
        headers: getAuthHeaders(),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = (await res.json()) as ProvidersStatusResponse
      setData(body)
      setError(null)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchOnce()
    const intervalMs = active ? 20_000 : 60_000
    const id = window.setInterval(() => {
      void fetchOnce()
    }, intervalMs)
    return () => {
      window.clearInterval(id)
      abortRef.current?.abort()
    }
  }, [active, fetchOnce])

  return { data, error, loading, refetch: fetchOnce }
}
