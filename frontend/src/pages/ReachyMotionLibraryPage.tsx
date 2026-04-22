import { useMemo, useRef, useState } from 'react'
import { Bot, Music, Sparkles, Play, Square, MoonStar, Sun, Search, UserRound, Mic, MicOff, Timer, Coffee, CalendarClock, BarChart3, RotateCcw } from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import {
  useMotionLibrary,
  usePersonas,
  usePlayMotion,
  useReachyStatus,
  useSelectPersona,
  useStopMove,
  useWakeUp,
  useGoToSleep,
  usePomodoroState,
  useStartPomodoro,
  useStopPomodoro,
  useMeetingState,
  useStartMeetingMode,
  useStopMeetingMode,
  useContextHint,
  usePersonaStats,
  useResetPersonaStats,
  type MotionClip,
  type MotionKind,
} from '@/hooks/useReachyApi'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { useToast } from '@/hooks/use-toast'

function ConnectionBadge() {
  const { data } = useReachyStatus()
  const connected = data?.connected
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${
        connected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
      }`}
      title={data?.base_url}
    >
      {connected ? 'Reachy connected' : 'Reachy offline'}
    </span>
  )
}

function PushToTalk() {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [lastResult, setLastResult] = useState<{ said: string; heard: string } | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const { toast } = useToast()

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mime = MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : MediaRecorder.isTypeSupported('audio/ogg')
          ? 'audio/ogg'
          : ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        if (blob.size < 400) {
          toast({ title: 'Too short', description: 'Press and hold to speak.', variant: 'destructive' })
          return
        }
        setBusy(true)
        try {
          const form = new FormData()
          form.append('audio', blob, 'ptt.webm')
          const response = await fetch('/api/reachy/voice', {
            method: 'POST',
            headers: { ...getAuthHeaders() },
            body: form,
          })
          const payload = await response.json()
          if (!response.ok) throw new Error(payload?.detail ?? `${response.status}`)
          const heard = payload.transcription?.text ?? ''
          const said = payload.llm_response ?? ''
          setLastResult({ heard, said })
          // Play back the TTS reply if present
          if (payload.audio_response_b64) {
            const audioBytes = Uint8Array.from(atob(payload.audio_response_b64), (c) => c.charCodeAt(0))
            const url = URL.createObjectURL(new Blob([audioBytes], { type: 'audio/wav' }))
            new Audio(url).play().catch(() => undefined)
          }
        } catch (e) {
          toast({ title: 'Voice failed', description: String(e), variant: 'destructive' })
        } finally {
          setBusy(false)
        }
      }
      recorder.start()
      mediaRecorderRef.current = recorder
      setRecording(true)
    } catch (e) {
      toast({ title: 'Mic access denied', description: String(e), variant: 'destructive' })
    }
  }

  const stop = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    setRecording(false)
  }

  return (
    <div className="glass-card p-3 mb-4">
      <div className="flex items-center gap-3">
        <button
          onMouseDown={start}
          onMouseUp={stop}
          onMouseLeave={() => recording && stop()}
          onTouchStart={(e) => { e.preventDefault(); start() }}
          onTouchEnd={(e) => { e.preventDefault(); stop() }}
          disabled={busy}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg font-semibold select-none ${
            recording ? 'bg-red-500/30 text-red-200 ring-2 ring-red-500' :
            busy ? 'bg-gray-700 text-gray-400' :
            'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'
          }`}
        >
          {recording ? <MicOff className="w-5 h-5 animate-pulse" /> : <Mic className="w-5 h-5" />}
          {busy ? 'Thinking…' : recording ? 'Listening — release to send' : 'Hold to talk to Reachy'}
        </button>
        <div className="flex-1 min-w-0 text-xs">
          {lastResult?.heard && (
            <div className="text-gray-400 truncate"><span className="text-gray-500">you: </span>{lastResult.heard}</div>
          )}
          {lastResult?.said && (
            <div className="text-white truncate"><span className="text-gray-500">reachy: </span>{lastResult.said}</div>
          )}
        </div>
      </div>
    </div>
  )
}

function PersonaPicker() {
  const { data } = usePersonas()
  const select = useSelectPersona()
  const { toast } = useToast()

  if (!data) return null
  const active = data.personas.find((p) => p.id === data.active_id)

  const onChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value
    try {
      await select.mutateAsync(id)
      const p = data.personas.find((x) => x.id === id)
      toast({ title: `Persona: ${p?.name ?? id}`, description: p?.tagline })
    } catch (err) {
      toast({ title: 'Failed to switch persona', description: String(err), variant: 'destructive' })
    }
  }

  return (
    <div className="glass-card p-3 flex items-center gap-3 mb-4">
      <div className="p-2 rounded-lg bg-fuchsia-500/10">
        <UserRound className="w-5 h-5 text-fuchsia-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-gray-400 mb-0.5">Active persona</div>
        <select
          value={data.active_id}
          onChange={onChange}
          disabled={select.isPending}
          className="w-full bg-gray-800/70 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-fuchsia-500"
        >
          {data.personas.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {active && <p className="text-xs text-gray-500 mt-1 italic">{active.tagline}</p>}
      </div>
    </div>
  )
}

function ClipCard({ clip, onPlay, busy }: { clip: MotionClip; onPlay: () => void; busy: boolean }) {
  return (
    <button
      onClick={onPlay}
      disabled={busy}
      className="glass-card-hover p-3 text-left flex flex-col gap-1 disabled:opacity-50"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-sm text-white truncate" title={clip.name}>
          {clip.name}
        </span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full ${
            clip.kind === 'emotion'
              ? 'bg-indigo-500/20 text-indigo-300'
              : 'bg-fuchsia-500/20 text-fuchsia-300'
          }`}
        >
          {clip.kind}
        </span>
      </div>
      <p className="text-xs text-gray-400 line-clamp-2">{clip.description}</p>
      {clip.aliases.length > 0 && (
        <p className="text-[10px] text-gray-500 truncate">
          aliases: {clip.aliases.join(', ')}
        </p>
      )}
    </button>
  )
}

export function ReachyMotionLibraryPage() {
  const [kindFilter, setKindFilter] = useState<MotionKind | 'all'>('all')
  const [q, setQ] = useState('')
  const effectiveKind = kindFilter === 'all' ? undefined : kindFilter
  const { data, isLoading } = useMotionLibrary(effectiveKind)
  const play = usePlayMotion()
  const stop = useStopMove()
  const wakeUp = useWakeUp()
  const sleep = useGoToSleep()
  const { toast } = useToast()

  const filteredByCategory = useMemo(() => {
    if (!data) return {}
    const needle = q.trim().toLowerCase()
    const out: Record<string, MotionClip[]> = {}
    for (const [cat, clips] of Object.entries(data.by_category)) {
      const picks = needle
        ? clips.filter(
            (c) =>
              c.name.toLowerCase().includes(needle) ||
              c.description.toLowerCase().includes(needle) ||
              c.aliases.some((a) => a.toLowerCase().includes(needle)),
          )
        : clips
      if (picks.length) out[cat] = picks
    }
    return out
  }, [data, q])

  const handlePlay = async (clip: MotionClip) => {
    try {
      const result = await play.mutateAsync({ name: clip.name, kind: clip.kind })
      if ((result as { error?: string })?.error) {
        toast({
          title: `Failed to play ${clip.name}`,
          description: (result as { error?: string }).error,
          variant: 'destructive',
        })
      } else {
        toast({ title: `Playing ${clip.name}`, description: clip.description })
      }
    } catch (e) {
      toast({
        title: `Failed to play ${clip.name}`,
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-500/10">
            <Bot className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Reachy Motion Library</h1>
            <p className="text-sm text-gray-400">
              {data ? `${data.emotions} emotions · ${data.dances} dances` : 'Loading catalog…'}
            </p>
          </div>
          <ConnectionBadge />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => wakeUp.mutate()}
            className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
          >
            <Sun className="w-4 h-4" /> Wake
          </button>
          <button
            onClick={() => sleep.mutate()}
            className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
          >
            <MoonStar className="w-4 h-4" /> Sleep
          </button>
          <button
            onClick={() => stop.mutate()}
            className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 text-red-400"
          >
            <Square className="w-4 h-4" /> Stop
          </button>
        </div>
      </div>

      <PushToTalk />
      <PersonaPicker />
      <ModesPanel />
      <PersonaStatsPanel />

      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <div className="flex items-center gap-1 bg-gray-800/50 rounded-lg p-1">
          {(['all', 'emotion', 'dance'] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className={`px-3 py-1 text-sm rounded flex items-center gap-1.5 ${
                kindFilter === k ? 'bg-indigo-500/30 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {k === 'emotion' && <Sparkles className="w-3.5 h-3.5" />}
              {k === 'dance' && <Music className="w-3.5 h-3.5" />}
              {k === 'all' && <Play className="w-3.5 h-3.5" />}
              <span className="capitalize">{k}</span>
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search clips, descriptions, or aliases…"
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded-lg focus:outline-none focus:border-indigo-500"
          />
        </div>
      </div>

      {isLoading && <LoadingSkeleton />}

      {data && (
        <div className="space-y-6">
          {Object.entries(filteredByCategory)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([category, clips]) => (
              <section key={category}>
                <h2 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wide">
                  {category}{' '}
                  <span className="text-gray-500 font-normal">({clips.length})</span>
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                  {clips.map((clip) => (
                    <ClipCard
                      key={`${clip.kind}-${clip.name}`}
                      clip={clip}
                      onPlay={() => handlePlay(clip)}
                      busy={play.isPending}
                    />
                  ))}
                </div>
              </section>
            ))}
          {Object.keys(filteredByCategory).length === 0 && (
            <p className="text-center text-gray-500 py-12">No clips match {JSON.stringify(q)}.</p>
          )}
        </div>
      )}
    </div>
  )
}

function ModesPanel() {
  const pomo = usePomodoroState()
  const startPomo = useStartPomodoro()
  const stopPomo = useStopPomodoro()
  const meeting = useMeetingState()
  const startMeeting = useStartMeetingMode()
  const stopMeeting = useStopMeetingMode()
  const context = useContextHint()
  const { toast } = useToast()

  const pomoActive = pomo.data?.active ?? false
  const meetingActive = meeting.data?.active ?? false
  const [focusMin, setFocusMin] = useState(25)
  const [breakMin, setBreakMin] = useState(5)

  const formatElapsed = (s: number | null | undefined) => {
    if (!s) return '0s'
    if (s < 60) return `${s.toFixed(0)}s`
    return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`
  }

  return (
    <div className="glass-card p-4 mb-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Timer className="w-4 h-4" /> Modes &amp; Context
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Pomodoro */}
        <div className="bg-gray-800/40 rounded p-3">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
            <Coffee className="w-3 h-3" /> Pomodoro
          </div>
          {pomoActive ? (
            <div className="space-y-2">
              <div className="text-sm">
                <span className={`font-semibold ${pomo.data?.phase === 'focus' ? 'text-red-300' : 'text-emerald-300'}`}>
                  {pomo.data?.phase}
                </span>
                <span className="text-gray-400 ml-2">· cycle {pomo.data?.cycle_index}</span>
              </div>
              <div className="text-xs text-gray-400 font-mono">{formatElapsed(pomo.data?.elapsed_s)} elapsed</div>
              <button
                onClick={async () => {
                  try { await stopPomo.mutateAsync(); toast({ title: 'Pomodoro stopped' }) }
                  catch (e) { toast({ title: 'Stop failed', description: String(e), variant: 'destructive' }) }
                }}
                className="w-full px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
              >
                Stop
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-[10px] text-gray-500">Focus</label>
                  <input type="number" min={5} max={90} value={focusMin} onChange={(e) => setFocusMin(Number(e.target.value))}
                    className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-1 py-0.5" />
                </div>
                <div className="flex-1">
                  <label className="text-[10px] text-gray-500">Break</label>
                  <input type="number" min={1} max={30} value={breakMin} onChange={(e) => setBreakMin(Number(e.target.value))}
                    className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-1 py-0.5" />
                </div>
              </div>
              <button
                onClick={() => startPomo.mutate({ focus_minutes: focusMin, break_minutes: breakMin })}
                disabled={startPomo.isPending}
                className="w-full px-2 py-1 text-xs font-semibold bg-red-500/20 text-red-300 hover:bg-red-500/30 rounded"
              >
                Start {focusMin}/{breakMin}
              </button>
            </div>
          )}
        </div>

        {/* Meeting mode */}
        <div className="bg-gray-800/40 rounded p-3">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
            <Mic className="w-3 h-3" /> Meeting mode
          </div>
          {meetingActive ? (
            <div className="space-y-2">
              <div className="text-sm text-amber-300 font-semibold">Looking at speaker</div>
              <div className="text-xs text-gray-400 font-mono">{formatElapsed(meeting.data?.elapsed_s)}</div>
              <button
                onClick={() => stopMeeting.mutate()}
                className="w-full px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
              >
                Exit meeting
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-gray-500">Tracks DoA and plays attentive gestures.</p>
              <button
                onClick={() => startMeeting.mutate(undefined)}
                className="w-full px-2 py-1 text-xs font-semibold bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 rounded"
              >
                Start meeting mode
              </button>
            </div>
          )}
        </div>

        {/* Context hint */}
        <div className="bg-gray-800/40 rounded p-3">
          <div className="text-xs text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
            <CalendarClock className="w-3 h-3" /> Context hint
          </div>
          <p className="text-[10px] text-gray-500 mb-1">Injected into every LLM turn.</p>
          <pre className="text-[11px] text-gray-300 whitespace-pre-wrap break-words max-h-24 overflow-y-auto bg-gray-900/50 p-1 rounded">
            {context.data?.hint?.replace(/^\s*###\s*CURRENT CONTEXT\s*/, '').trim() || '(empty)'}
          </pre>
        </div>
      </div>
    </div>
  )
}

function PersonaStatsPanel() {
  const stats = usePersonaStats()
  const reset = useResetPersonaStats()
  const { toast } = useToast()

  const personas = stats.data?.personas ?? {}
  const entries = Object.entries(personas).sort(([, a], [, b]) => (b.interactions - a.interactions))

  if (entries.length === 0) return null

  return (
    <div className="glass-card p-4 mb-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide flex items-center gap-2">
          <BarChart3 className="w-4 h-4" /> Persona usage
        </h2>
        <button
          onClick={async () => {
            try { await reset.mutateAsync(undefined); toast({ title: 'Stats reset' }) }
            catch (e) { toast({ title: 'Reset failed', description: String(e), variant: 'destructive' }) }
          }}
          className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1"
        >
          <RotateCcw className="w-3 h-3" /> Reset
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {entries.slice(0, 8).map(([id, s]) => (
          <div key={id} className="bg-gray-800/40 rounded px-2 py-1.5">
            <div className="text-xs text-white truncate" title={id}>{id}</div>
            <div className="text-[10px] text-gray-400">
              {s.interactions} turns · {s.emotions_fired}😀 · {s.dances_fired}💃
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
