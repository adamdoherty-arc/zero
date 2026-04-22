import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Gamepad2, Keyboard, Camera, RotateCcw, Square, Disc3, Play, Trash2, CircleDot, Eye, Radio, Hand, Volume2, Mic, Zap, BellRing } from 'lucide-react'
import {
  useMoveHead,
  useSetAntennas,
  useStopMove,
  useWakeUp,
  useGoToSleep,
  useReachyStatus,
  useCameraStream,
  useReachyState,
  useRecordStatus,
  useStartRecording,
  useStopRecording,
  useUserMoves,
  usePlayUserMove,
  useDeleteUserMove,
  useVisionBackends,
  useRadioStatus,
  useStartRadio,
  useStopRadio,
  useVolume,
  useSetVolume,
  useTestSound,
  useMotorStatus,
  useSetMotorMode,
  useWakeWordStatus,
  type VisionDetection,
} from '@/hooks/useReachyApi'
import { getAuthHeaders } from '@/lib/auth'
import { useToast } from '@/hooks/use-toast'

/**
 * Minimal teleop console. Keyboard: arrows = pitch/yaw, a/d = roll, q/e = antenna
 * spread. Sliders expose the same axes for touch. Uses the existing REST
 * endpoints (POST /reachy/move, /reachy/antennas, /reachy/look).
 */
export function ReachyTeleopPage() {
  const status = useReachyStatus()
  const stream = useCameraStream()
  const moveHead = useMoveHead()
  const setAntennas = useSetAntennas()
  const stop = useStopMove()
  const wake = useWakeUp()
  const sleep = useGoToSleep()
  const { toast } = useToast()

  const [pitch, setPitch] = useState(0)
  const [yaw, setYaw] = useState(0)
  const [roll, setRoll] = useState(0)
  const [antennaSpread, setAntennaSpread] = useState(0)
  const [duration, setDuration] = useState(0.6)

  const sendHead = useCallback(
    (p: number, y: number, r: number) => {
      moveHead.mutate({ pitch: p, yaw: y, roll: r, duration })
    },
    [moveHead, duration],
  )

  const sendAntennas = useCallback(
    (spread: number) => {
      setAntennas.mutate({
        left_angle: -spread,
        right_angle: spread,
        duration,
      })
    },
    [setAntennas, duration],
  )

  const reset = useCallback(() => {
    setPitch(0)
    setYaw(0)
    setRoll(0)
    setAntennaSpread(0)
    sendHead(0, 0, 0)
    sendAntennas(0)
  }, [sendHead, sendAntennas])

  // Keyboard teleop
  useEffect(() => {
    const STEP_HEAD = 10 // degrees per key press
    const STEP_ANT = 10
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return
      let handled = true
      let p = pitch
      let y = yaw
      let r = roll
      let a = antennaSpread
      if (e.key === 'ArrowUp') p = Math.min(30, p + STEP_HEAD)
      else if (e.key === 'ArrowDown') p = Math.max(-30, p - STEP_HEAD)
      else if (e.key === 'ArrowLeft') y = Math.max(-45, y - STEP_HEAD)
      else if (e.key === 'ArrowRight') y = Math.min(45, y + STEP_HEAD)
      else if (e.key === 'a' || e.key === 'A') r = Math.max(-25, r - STEP_HEAD)
      else if (e.key === 'd' || e.key === 'D') r = Math.min(25, r + STEP_HEAD)
      else if (e.key === 'q' || e.key === 'Q') a = Math.max(-60, a - STEP_ANT)
      else if (e.key === 'e' || e.key === 'E') a = Math.min(60, a + STEP_ANT)
      else if (e.key === ' ') reset()
      else handled = false
      if (handled) {
        e.preventDefault()
        setPitch(p); setYaw(y); setRoll(r); setAntennaSpread(a)
        sendHead(p, y, r)
        if (a !== antennaSpread) sendAntennas(a)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pitch, yaw, roll, antennaSpread, sendHead, sendAntennas, reset])

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-emerald-500/10">
          <Gamepad2 className="w-6 h-6 text-emerald-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Reachy Teleop</h1>
          <p className="text-sm text-gray-400">
            {status.data?.connected ? 'Connected' : 'Offline'} · keyboard or sliders
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => wake.mutate()} className="glass-card-hover px-3 py-1.5 text-sm">Wake</button>
          <button onClick={() => sleep.mutate()} className="glass-card-hover px-3 py-1.5 text-sm">Sleep</button>
          <button onClick={reset} className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1">
            <RotateCcw className="w-4 h-4" /> Reset
          </button>
          <button onClick={() => stop.mutate()} className="glass-card-hover px-3 py-1.5 text-sm text-red-400 flex items-center gap-1">
            <Square className="w-4 h-4" /> Stop
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div className="glass-card p-4">
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
              <Keyboard className="w-4 h-4" /> Keyboard
            </h2>
            <div className="text-xs text-gray-400 space-y-1">
              <div>Arrow keys — head pitch / yaw</div>
              <div>A / D — head roll</div>
              <div>Q / E — antenna spread</div>
              <div>Space — reset all axes to center</div>
            </div>
          </div>

          <SliderRow label="Pitch" value={pitch} min={-30} max={30} onChange={(v) => { setPitch(v); sendHead(v, yaw, roll) }} unit="°" />
          <SliderRow label="Yaw"   value={yaw}   min={-45} max={45} onChange={(v) => { setYaw(v); sendHead(pitch, v, roll) }} unit="°" />
          <SliderRow label="Roll"  value={roll}  min={-25} max={25} onChange={(v) => { setRoll(v); sendHead(pitch, yaw, v) }} unit="°" />
          <SliderRow label="Antenna Spread" value={antennaSpread} min={-60} max={60} onChange={(v) => { setAntennaSpread(v); sendAntennas(v) }} unit="°" />
          <SliderRow label="Duration" value={duration} min={0.1} max={2.0} step={0.1} onChange={setDuration} unit="s" />

          <button
            onClick={() => {
              const res = moveHead.mutateAsync({ pitch, yaw, roll, duration })
              res.then(() => toast({ title: 'Moved', description: `pitch=${pitch}° yaw=${yaw}° roll=${roll}°` }))
                 .catch((e) => toast({ title: 'Move failed', description: String(e), variant: 'destructive' }))
            }}
            className="w-full glass-card-hover py-2 text-sm font-semibold"
          >
            Send
          </button>
        </div>

        <div className="space-y-4">
          <PuppetView />
          <DiagnosticsPanel />
          <RadioPanel />
          <VisionPanel />
          <MoveRecorderPanel />
          <div className="glass-card p-4">
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
              <Camera className="w-4 h-4" /> Camera feed
            </h2>
            {stream.data?.url ? (
              <div className="text-xs text-gray-400">
                <p>Daemon serves WebRTC on:</p>
                <a href={stream.data.url} target="_blank" rel="noreferrer" className="text-indigo-400 break-all">
                  {stream.data.url}
                </a>
              </div>
            ) : (
              <div className="text-sm text-gray-500">Camera URL unavailable.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function MoveRecorderPanel() {
  const status = useRecordStatus(500)
  const moves = useUserMoves()
  const start = useStartRecording()
  const stop = useStopRecording()
  const play = usePlayUserMove()
  const del = useDeleteUserMove()
  const { toast } = useToast()

  const [library, setLibrary] = useState('user')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const recording = status.data?.recording ?? false

  const handleStart = async () => {
    if (!name.trim()) {
      toast({ title: 'Name required', variant: 'destructive' })
      return
    }
    try {
      const res = await start.mutateAsync({ library, name, description })
      toast({ title: `Recording "${name}"`, description: 'Move Reachy by hand. Torque is released.' })
      return res
    } catch (e) {
      toast({ title: 'Start failed', description: String(e), variant: 'destructive' })
    }
  }

  const handleStop = async () => {
    try {
      const res = await stop.mutateAsync()
      toast({ title: `Saved ${(res as { duration_s?: number })?.duration_s?.toFixed?.(1) ?? '?'}s`, description: `${(res as { frames?: number })?.frames ?? 0} frames` })
      setName('')
      setDescription('')
    } catch (e) {
      toast({ title: 'Stop failed', description: String(e), variant: 'destructive' })
    }
  }

  return (
    <div className="glass-card p-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Disc3 className={`w-4 h-4 ${recording ? 'text-red-400 animate-pulse' : ''}`} />
        Move Recorder
      </h2>

      {!recording ? (
        <div className="space-y-2">
          <input
            type="text"
            placeholder="Move name (e.g. hello_wave)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full text-sm bg-gray-800/70 border border-gray-700 rounded px-2 py-1"
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full text-sm bg-gray-800/70 border border-gray-700 rounded px-2 py-1"
          />
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="library"
              value={library}
              onChange={(e) => setLibrary(e.target.value)}
              className="flex-1 text-sm bg-gray-800/70 border border-gray-700 rounded px-2 py-1"
            />
            <button
              onClick={handleStart}
              disabled={start.isPending}
              className="px-3 py-1.5 text-sm font-semibold bg-red-500/20 text-red-300 hover:bg-red-500/30 rounded flex items-center gap-1"
            >
              <CircleDot className="w-4 h-4" /> Record
            </button>
          </div>
          <p className="text-[10px] text-gray-500">
            Torque releases on start. Move the head by hand. Stop to save.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-sm text-red-400">
            Recording "{status.data?.name}" — {status.data?.frame_count ?? 0} frames · {status.data?.elapsed_s?.toFixed?.(1) ?? '?'}s
          </div>
          <button
            onClick={handleStop}
            disabled={stop.isPending}
            className="w-full px-3 py-1.5 text-sm font-semibold bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 rounded"
          >
            Stop & Save
          </button>
        </div>
      )}

      {moves.data?.moves && moves.data.moves.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-700/50">
          <p className="text-xs text-gray-400 mb-2">Saved ({moves.data.moves.length})</p>
          <div className="space-y-1 max-h-40 overflow-auto">
            {moves.data.moves.map((m) => (
              <div key={`${m.library}/${m.name}`} className="flex items-center gap-2 text-xs bg-gray-800/30 rounded px-2 py-1">
                <span className="flex-1 min-w-0 truncate">
                  <span className="text-white font-mono">{m.library}/{m.name}</span>
                  <span className="text-gray-500"> · {m.duration_s.toFixed(1)}s · {m.frame_count}f</span>
                </span>
                <button
                  onClick={() => play.mutate({ library: m.library, name: m.name })}
                  className="text-indigo-400 hover:text-indigo-300"
                  title="Play"
                >
                  <Play className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => del.mutate({ library: m.library, name: m.name })}
                  className="text-red-400 hover:text-red-300"
                  title="Delete"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function PuppetView() {
  const { data } = useReachyState(300)
  // Pseudo-3D puppet using CSS perspective transforms — real head geometry
  // without pulling three.js into the bundle. Refreshes at ~3 Hz.
  const pose = data?.head_pose
  const ant = data?.antenna_positions ?? [0, 0]
  const pitchDeg = pose ? (pose.pitch * 180) / Math.PI : 0
  const yawDeg = pose ? (pose.yaw * 180) / Math.PI : 0
  const rollDeg = pose ? (pose.roll * 180) / Math.PI : 0
  const leftAnt = (ant[0] * 180) / Math.PI
  const rightAnt = (ant[1] * 180) / Math.PI
  const bodyYawDeg = data?.body_yaw ? (data.body_yaw * 180) / Math.PI : 0
  const doaDeg = data?.doa?.speech_detected && data.doa.angle !== undefined
    ? (data.doa.angle * 180) / Math.PI
    : null

  return (
    <div className="glass-card p-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Bot className="w-4 h-4" /> Live Puppet
      </h2>
      <div className="relative flex items-center justify-center py-4" style={{ perspective: '600px' }}>
        {/* DoA ring behind the puppet */}
        <svg viewBox="-110 -110 220 220" width="240" height="240" className="absolute inset-0 m-auto text-gray-600">
          <circle cx="0" cy="0" r="100" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="2 4" />
          {doaDeg !== null && (
            <g>
              <line
                x1="0" y1="0"
                x2={100 * Math.cos((doaDeg * Math.PI) / 180)}
                y2={100 * Math.sin((doaDeg * Math.PI) / 180)}
                stroke="#f59e0b" strokeWidth="2"
              />
              <circle
                cx={100 * Math.cos((doaDeg * Math.PI) / 180)}
                cy={100 * Math.sin((doaDeg * Math.PI) / 180)}
                r="4" fill="#f59e0b"
              />
            </g>
          )}
        </svg>

        {/* Body base with independent yaw rotation */}
        <div
          className="relative"
          style={{
            transform: `rotateY(${bodyYawDeg}deg)`,
            transformStyle: 'preserve-3d',
            transition: 'transform 0.1s linear',
          }}
        >
          {/* Head with full 3D rotation (yaw + pitch + roll) */}
          <div
            className="relative"
            style={{
              transform: `rotateY(${yawDeg}deg) rotateX(${-pitchDeg}deg) rotateZ(${rollDeg}deg)`,
              transformStyle: 'preserve-3d',
              transition: 'transform 0.12s ease-out',
            }}
          >
            {/* Head front face */}
            <div
              className="w-32 h-32 rounded-full bg-gradient-to-br from-indigo-500/30 to-indigo-700/40 border-2 border-indigo-400 flex items-center justify-center relative shadow-2xl shadow-indigo-500/30"
              style={{
                boxShadow:
                  'inset -8px -8px 20px rgba(0,0,0,0.3), inset 8px 8px 20px rgba(255,255,255,0.05)',
              }}
            >
              {/* Eyes */}
              <div className="absolute top-10 left-5 w-4 h-4 rounded-full bg-indigo-200 shadow-inner" />
              <div className="absolute top-10 right-5 w-4 h-4 rounded-full bg-indigo-200 shadow-inner" />
              {/* Mouth */}
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-8 h-3 border-b-2 border-indigo-200 rounded-b-full" />
            </div>

            {/* Antennas — each with its own local rotation */}
            <div
              className="absolute -top-8 left-4 w-1 h-10 bg-indigo-300 rounded-full origin-bottom"
              style={{
                transform: `rotate(${leftAnt}deg)`,
                transformOrigin: 'bottom center',
                transition: 'transform 0.12s ease-out',
              }}
            >
              <div className="absolute -top-1 -left-1 w-3 h-3 rounded-full bg-indigo-300 shadow-md shadow-indigo-500/50" />
            </div>
            <div
              className="absolute -top-8 right-4 w-1 h-10 bg-indigo-300 rounded-full origin-bottom"
              style={{
                transform: `rotate(${-rightAnt}deg)`,
                transformOrigin: 'bottom center',
                transition: 'transform 0.12s ease-out',
              }}
            >
              <div className="absolute -top-1 -left-1 w-3 h-3 rounded-full bg-indigo-300 shadow-md shadow-indigo-500/50" />
            </div>
          </div>

          {/* Body/neck cylinder */}
          <div className="w-20 h-12 mx-auto -mt-4 bg-gray-700/70 rounded-b-2xl border-x border-b border-gray-600" />
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center text-xs text-gray-400 mt-2">
        <div><div className="text-white font-mono">{pitchDeg.toFixed(0)}°</div>pitch</div>
        <div><div className="text-white font-mono">{yawDeg.toFixed(0)}°</div>yaw</div>
        <div><div className="text-white font-mono">{rollDeg.toFixed(0)}°</div>roll</div>
        <div><div className="text-white font-mono">{bodyYawDeg.toFixed(0)}°</div>body</div>
      </div>
      {doaDeg !== null && (
        <p className="text-xs text-amber-400 text-center mt-2">Speech at {doaDeg.toFixed(0)}°</p>
      )}
    </div>
  )
}

function SliderRow(props: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  unit: string
  onChange: (v: number) => void
}) {
  const { label, value, min, max, step = 1, unit, onChange } = props
  return (
    <div className="glass-card p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-400">{label}</span>
        <span className="text-xs font-mono text-white">{value.toFixed(step < 1 ? 2 : 0)}{unit}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-emerald-500"
      />
    </div>
  )
}

function RadioPanel() {
  const status = useRadioStatus()
  const startRadio = useStartRadio()
  const stopRadio = useStopRadio()
  const { toast } = useToast()
  const [bpm, setBpm] = useState(114)
  const [beats, setBeats] = useState(8)
  const [analyzing, setAnalyzing] = useState(false)

  const active = status.data?.active ?? false

  const handleStart = async () => {
    try {
      await startRadio.mutateAsync({ bpm, beats_per_dance: beats })
      toast({ title: `Radio mode started @ ${bpm} BPM` })
    } catch (e) {
      toast({ title: 'Start failed', description: String(e), variant: 'destructive' })
    }
  }

  const handleFileAnalyze = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setAnalyzing(true)
    try {
      const form = new FormData()
      form.append('audio', file)
      const res = await fetch('/api/reachy/radio/analyze', {
        method: 'POST',
        headers: { ...getAuthHeaders() },
        body: form,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail ?? `${res.status}`)
      if (data.bpm) {
        setBpm(Math.round(data.bpm))
        toast({ title: `Detected ${Math.round(data.bpm)} BPM`, description: `${data.beat_count} beats in ${data.duration_s.toFixed(1)}s` })
      } else {
        toast({ title: 'No BPM detected', description: data.error ?? '', variant: 'destructive' })
      }
    } catch (err) {
      toast({ title: 'Analyze failed', description: String(err), variant: 'destructive' })
    } finally {
      setAnalyzing(false)
      e.target.value = ''
    }
  }

  return (
    <div className="glass-card p-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Radio className={`w-4 h-4 ${active ? 'text-fuchsia-400 animate-pulse' : ''}`} /> Radio Mode
      </h2>
      <div className="flex gap-2 mb-2">
        <div className="flex-1">
          <label className="text-xs text-gray-400">BPM</label>
          <input
            type="number"
            min={40} max={200}
            value={bpm}
            onChange={(e) => setBpm(Math.max(40, Math.min(200, Number(e.target.value) || 0)))}
            disabled={active}
            className="w-full text-sm bg-gray-800/70 border border-gray-700 rounded px-2 py-1"
          />
        </div>
        <div className="flex-1">
          <label className="text-xs text-gray-400">Beats / dance</label>
          <input
            type="number"
            min={2} max={32}
            value={beats}
            onChange={(e) => setBeats(Math.max(2, Math.min(32, Number(e.target.value) || 0)))}
            disabled={active}
            className="w-full text-sm bg-gray-800/70 border border-gray-700 rounded px-2 py-1"
          />
        </div>
      </div>
      <label className={`block mb-2 text-xs text-center py-1.5 border border-dashed border-gray-600 rounded cursor-pointer hover:border-indigo-500 ${analyzing ? 'opacity-50' : ''}`}>
        {analyzing ? 'Analyzing…' : 'Upload a song to auto-detect BPM'}
        <input type="file" accept="audio/*" className="hidden" onChange={handleFileAnalyze} disabled={analyzing} />
      </label>
      {!active ? (
        <button onClick={handleStart} disabled={startRadio.isPending} className="w-full px-3 py-1.5 text-sm font-semibold bg-fuchsia-500/20 text-fuchsia-300 hover:bg-fuchsia-500/30 rounded">
          Start dancing
        </button>
      ) : (
        <div className="space-y-1">
          <div className="text-xs text-fuchsia-400">
            Dancing @ {status.data?.bpm} BPM · {status.data?.dances_played} dances played
          </div>
          {status.data?.current_dance && (
            <div className="text-xs text-gray-400">Now: {status.data.current_dance}</div>
          )}
          <button onClick={() => stopRadio.mutate()} className="w-full px-3 py-1.5 text-sm font-semibold bg-gray-700 hover:bg-gray-600 rounded">Stop</button>
        </div>
      )}
    </div>
  )
}

function VisionPanel() {
  const backends = useVisionBackends()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [active, setActive] = useState(false)
  const [kind, setKind] = useState<'face' | 'hands'>('face')
  const [lastResult, setLastResult] = useState<{ detections: VisionDetection[]; backend?: string } | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const { toast } = useToast()

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } })
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      streamRef.current = stream
      setActive(true)
    } catch (e) {
      toast({ title: 'Camera denied', description: String(e), variant: 'destructive' })
    }
  }

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setActive(false)
  }

  const detect = async () => {
    if (!videoRef.current || !canvasRef.current) return
    const v = videoRef.current
    const c = canvasRef.current
    const w = v.videoWidth
    const h = v.videoHeight
    if (w === 0) return
    c.width = w
    c.height = h
    const ctx = c.getContext('2d')
    if (!ctx) return
    ctx.drawImage(v, 0, 0, w, h)
    const blob: Blob | null = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.85))
    if (!blob) return

    const form = new FormData()
    form.append('image', blob, 'frame.jpg')
    try {
      const res = await fetch(`/api/reachy/vision/detect?kind=${kind}`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
        body: form,
      })
      const data = await res.json()
      if (res.ok) {
        setLastResult({ detections: data.detections || [], backend: data.backend })
      } else {
        toast({ title: 'Detect failed', description: data?.detail?.reason ?? `${res.status}`, variant: 'destructive' })
      }
    } catch (e) {
      toast({ title: 'Detect failed', description: String(e), variant: 'destructive' })
    }
  }

  useEffect(() => {
    return () => stop()

  }, [])

  const canHand = backends.data?.hands?.available
  const canFace = backends.data?.face?.available

  return (
    <div className="glass-card p-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Eye className="w-4 h-4" /> Vision detect
      </h2>
      <div className="flex items-center gap-2 mb-2 text-xs">
        <button
          onClick={() => setKind('face')}
          className={`px-2 py-1 rounded ${kind === 'face' ? 'bg-indigo-500/30 text-white' : 'bg-gray-800 text-gray-400'}`}
          disabled={!canFace}
        >
          Face {canFace ? '' : '(unavailable)'}
        </button>
        <button
          onClick={() => setKind('hands')}
          className={`px-2 py-1 rounded flex items-center gap-1 ${kind === 'hands' ? 'bg-indigo-500/30 text-white' : 'bg-gray-800 text-gray-400'}`}
          disabled={!canHand}
        >
          <Hand className="w-3 h-3" /> Hands {canHand ? '' : '(unavailable)'}
        </button>
      </div>
      <div className="relative bg-black/60 rounded overflow-hidden aspect-video mb-2">
        <video ref={videoRef} muted playsInline className="w-full h-full object-cover" />
        <canvas ref={canvasRef} className="hidden" />
        {lastResult && videoRef.current && (
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 1 1" preserveAspectRatio="none">
            {lastResult.detections.map((d, i) => (
              <rect
                key={i}
                x={d.x - d.width / 2}
                y={d.y - d.height / 2}
                width={d.width}
                height={d.height}
                fill="none" stroke="#4ade80" strokeWidth="0.005"
              />
            ))}
          </svg>
        )}
      </div>
      <div className="flex gap-2">
        {!active ? (
          <button onClick={start} className="flex-1 px-3 py-1.5 text-sm bg-emerald-500/20 text-emerald-300 rounded">Start camera</button>
        ) : (
          <>
            <button onClick={detect} className="flex-1 px-3 py-1.5 text-sm bg-indigo-500/20 text-indigo-300 rounded">Detect</button>
            <button onClick={stop} className="px-3 py-1.5 text-sm bg-gray-700 rounded">Stop</button>
          </>
        )}
      </div>
      {lastResult && (
        <p className="text-xs text-gray-400 mt-2">
          {lastResult.detections.length} {kind}(s) detected via {lastResult.backend}
        </p>
      )}
    </div>
  )
}

function DiagnosticsPanel() {
  const speakerVol = useVolume('speaker')
  const micVol = useVolume('mic')
  const setSpeakerVol = useSetVolume('speaker')
  const setMicVol = useSetVolume('mic')
  const testSound = useTestSound()
  const motors = useMotorStatus()
  const setMotorMode = useSetMotorMode()
  const wakeWord = useWakeWordStatus()
  const { toast } = useToast()

  const speakerVal = speakerVol.data?.volume ?? 0
  const micVal = micVol.data?.volume ?? 0
  const motorMode = (motors.data as Record<string, unknown>)?.motor_control_mode ?? (motors.data as Record<string, unknown>)?.mode ?? 'unknown'
  const wwAvail = wakeWord.data?.available ?? false

  return (
    <div className="glass-card p-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Zap className="w-4 h-4" /> Diagnostics
      </h2>

      {/* Speaker volume */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400 flex items-center gap-1"><Volume2 className="w-3 h-3" /> Speaker</span>
          <span className="text-xs font-mono text-white">{speakerVal}%</span>
        </div>
        <input type="range" min={0} max={100} value={speakerVal}
          onChange={(e) => setSpeakerVol.mutate(Number(e.target.value))}
          className="w-full accent-indigo-500" />
      </div>

      {/* Mic volume */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400 flex items-center gap-1"><Mic className="w-3 h-3" /> Microphone</span>
          <span className="text-xs font-mono text-white">{micVal}%</span>
        </div>
        <input type="range" min={0} max={100} value={micVal}
          onChange={(e) => setMicVol.mutate(Number(e.target.value))}
          className="w-full accent-indigo-500" />
      </div>

      <button
        onClick={() => {
          testSound.mutate(undefined, {
            onSuccess: () => toast({ title: 'Test chime played' }),
            onError: (e) => toast({ title: 'Test sound failed', description: String(e), variant: 'destructive' }),
          })
        }}
        className="w-full mb-3 px-2 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 rounded flex items-center justify-center gap-1"
      >
        <BellRing className="w-3 h-3" /> Play test chime
      </button>

      {/* Motor mode */}
      <div className="mb-3">
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">Motor torque</div>
        <div className="flex gap-1">
          {(['enabled', 'compliant', 'disabled'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setMotorMode.mutate(mode)}
              className={`flex-1 px-2 py-1 text-xs rounded ${
                motorMode === mode
                  ? 'bg-indigo-500/30 text-white ring-1 ring-indigo-400'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-gray-500 mt-1">
          "compliant" = user-movable, "enabled" = stiff, "disabled" = limp.
        </p>
      </div>

      {/* Wake word */}
      <div className="flex items-center justify-between text-xs pt-2 border-t border-gray-700/50">
        <span className="text-gray-400">Wake-word</span>
        <span className={wwAvail ? 'text-emerald-400' : 'text-gray-500'}>
          {wwAvail ? `${wakeWord.data?.model} ready` : 'not installed'}
        </span>
      </div>
    </div>
  )
}
