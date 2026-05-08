import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { useToast } from '@/hooks/use-toast'

const API_BASE = '/api'

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders(), ...init?.headers },
    ...init,
  })
  if (!resp.ok) throw new Error(`${resp.status}`)
  return resp.json()
}

/**
 * Global "Zero eyes off" kill switch — top-nav button. One tap:
 *   - every SightProvider stops returning frames
 *   - every push buffer rejects ingest
 *   - in-memory ring buffers are purged
 *
 * Non-negotiable: has to exist before you wear wearable-cam hardware
 * around other people (per the plan's privacy risk note).
 */
export function EyesOffButton() {
  const status = useQuery<{ eyes_off: boolean }>({
    queryKey: ['sight', 'eyes-off'],
    queryFn: () => fetchJson('/sight/eyes-off'),
    refetchInterval: 10_000,
  })
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const toggle = useMutation({
    mutationFn: (next: boolean) =>
      fetchJson<{ eyes_off: boolean; purged_frames: number }>('/sight/eyes-off', {
        method: 'POST',
        body: JSON.stringify({ eyes_off: next }),
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['sight'] })
      toast({
        title: data.eyes_off ? 'Zero eyes off' : 'Zero eyes on',
        description: data.eyes_off
          ? `No frames streaming. Purged ${data.purged_frames} buffered frame(s).`
          : 'All sight providers re-enabled.',
      })
    },
    onError: (e) =>
      toast({ title: 'Eyes-off toggle failed', description: String(e), variant: 'destructive' }),
  })

  const eyesOff = status.data?.eyes_off ?? false
  const busy = toggle.isPending || status.isLoading

  return (
    <button
      onClick={() => toggle.mutate(!eyesOff)}
      disabled={busy}
      title={eyesOff ? 'Zero can not see anything right now (click to re-enable)' : 'Click to turn off all sight providers'}
      className={
        'flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md border transition-colors ' +
        (eyesOff
          ? 'bg-red-500/10 text-red-300 border-red-500/40 hover:bg-red-500/20'
          : 'bg-emerald-500/5 text-emerald-300/80 border-emerald-500/20 hover:bg-emerald-500/10')
      }
    >
      {busy ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
      ) : eyesOff ? (
        <EyeOff className="w-3.5 h-3.5" />
      ) : (
        <Eye className="w-3.5 h-3.5" />
      )}
      <span className="hidden sm:inline">{eyesOff ? 'Eyes off' : 'Eyes on'}</span>
    </button>
  )
}
