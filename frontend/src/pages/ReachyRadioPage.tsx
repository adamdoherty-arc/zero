import { useRef, useState } from 'react'
import { Radio, Play, Square, Music } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { useToast } from '@/hooks/use-toast'

const API = '/api/reachy'

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: { ...getAuthHeaders() } })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json', ...getAuthHeaders() } : getAuthHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

interface RadioStatus {
  running: boolean
  bpm?: number
  beats_per_dance?: number
  dances?: string[]
  started_at?: string
}

interface BpmAnalysis {
  available: boolean
  bpm?: number
  confidence?: number
  duration_seconds?: number
}

export function ReachyRadioPage() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const status = useQuery<RadioStatus>({
    queryKey: ['reachy', 'radio', 'status'],
    queryFn: () => apiGet<RadioStatus>('/radio/status'),
    refetchInterval: 5000,
  })

  const [bpm, setBpm] = useState(110)
  const [beats, setBeats] = useState(8)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [analysis, setAnalysis] = useState<BpmAnalysis | null>(null)

  const startRadio = useMutation({
    mutationFn: () => apiPost('/radio/start', { bpm, beats_per_dance: beats }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['reachy', 'radio', 'status'] })
      toast({ title: 'Radio started', description: `${bpm} BPM, ${beats} beats/dance` })
    },
    onError: (e) =>
      toast({ title: 'Radio start failed', description: String(e), variant: 'destructive' }),
  })

  const stopRadio = useMutation({
    mutationFn: () => apiPost('/radio/stop'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['reachy', 'radio', 'status'] })
      toast({ title: 'Radio stopped' })
    },
  })

  const analyze = async (file: File) => {
    const form = new FormData()
    form.append('audio', file, file.name)
    const res = await fetch(`${API}/radio/analyze`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: form,
    })
    if (!res.ok) {
      toast({
        title: 'BPM analyze failed',
        description: `${res.status} ${await res.text()}`,
        variant: 'destructive',
      })
      return
    }
    const data: BpmAnalysis = await res.json()
    setAnalysis(data)
    if (data.bpm) {
      setBpm(Math.round(data.bpm))
      toast({ title: `BPM detected: ${Math.round(data.bpm)}`, description: `Confidence ${data.confidence?.toFixed?.(2) ?? '-'}` })
    }
  }

  const running = status.data?.running ?? false

  return (
    <div className="p-4 md:p-6 space-y-6">
      <header className="flex items-center gap-2">
        <Radio className="w-5 h-5 text-indigo-400" />
        <h1 className="text-xl font-semibold text-gray-100">Zero Radio</h1>
        <span
          className={`text-[10px] px-2 py-0.5 rounded-full ${
            running ? 'bg-emerald-500/20 text-emerald-400' : 'bg-gray-700 text-gray-400'
          }`}
        >
          {running ? 'Running' : 'Idle'}
        </span>
      </header>

      <section className="glass-card p-4 max-w-lg">
        <h2 className="text-sm font-semibold text-gray-100 mb-3 flex items-center gap-2">
          <Music className="w-4 h-4" /> Dance loop
        </h2>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1 text-xs text-gray-400">
            BPM
            <input
              type="number"
              min={40}
              max={200}
              value={bpm}
              onChange={(e) => setBpm(Number(e.target.value) || 0)}
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-gray-400">
            Beats per dance
            <input
              type="number"
              min={2}
              max={32}
              value={beats}
              onChange={(e) => setBeats(Number(e.target.value) || 0)}
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-100"
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => startRadio.mutate()}
            disabled={running || startRadio.isPending}
            className="flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-50 text-sm"
          >
            <Play className="w-4 h-4" /> Start
          </button>
          <button
            onClick={() => stopRadio.mutate()}
            disabled={!running || stopRadio.isPending}
            className="flex items-center gap-1 px-3 py-1.5 rounded bg-red-500/20 text-red-300 hover:bg-red-500/30 disabled:opacity-50 text-sm"
          >
            <Square className="w-4 h-4" /> Stop
          </button>
        </div>
        {status.data?.dances && status.data.dances.length > 0 && (
          <div className="mt-3 text-xs text-gray-400">
            Cycling: {status.data.dances.join(', ')}
          </div>
        )}
      </section>

      <section className="glass-card p-4 max-w-lg">
        <h2 className="text-sm font-semibold text-gray-100 mb-2">Detect BPM from audio</h2>
        <p className="text-xs text-gray-400 mb-3">
          Upload a clip (MP3/WAV) to auto-detect tempo via librosa. The detected BPM fills in the
          field above.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="audio/*"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void analyze(f)
          }}
          className="block w-full text-xs text-gray-300"
        />
        {analysis && (
          <div className="mt-2 text-xs text-gray-300 font-mono">
            {analysis.available
              ? `bpm: ${analysis.bpm?.toFixed?.(1)} · conf: ${analysis.confidence?.toFixed?.(2)} · ${analysis.duration_seconds?.toFixed?.(1)}s`
              : 'Analysis unavailable.'}
          </div>
        )}
      </section>
    </div>
  )
}
