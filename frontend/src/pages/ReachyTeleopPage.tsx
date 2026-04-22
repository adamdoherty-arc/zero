import { useCallback, useEffect, useState } from 'react'
import { Bot, Gamepad2, Keyboard, Camera, RotateCcw, Square } from 'lucide-react'
import {
  useMoveHead,
  useSetAntennas,
  useStopMove,
  useWakeUp,
  useGoToSleep,
  useReachyStatus,
  useCameraStream,
  useReachyState,
} from '@/hooks/useReachyApi'
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

function PuppetView() {
  const { data } = useReachyState(500)
  // SVG puppet: a head silhouette that rotates with the live pose. Cheap,
  // zero deps, and refreshes at 2 Hz so callers don't hammer the daemon.
  const pose = data?.head_pose
  const ant = data?.antenna_positions ?? [0, 0]
  const pitchDeg = pose ? (pose.pitch * 180) / Math.PI : 0
  const yawDeg = pose ? (pose.yaw * 180) / Math.PI : 0
  const rollDeg = pose ? (pose.roll * 180) / Math.PI : 0
  const leftAnt = (ant[0] * 180) / Math.PI
  const rightAnt = (ant[1] * 180) / Math.PI
  const doaDeg = data?.doa?.speech_detected && data.doa.angle !== undefined
    ? (data.doa.angle * 180) / Math.PI
    : null

  return (
    <div className="glass-card p-4">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
        <Bot className="w-4 h-4" /> Live Puppet
      </h2>
      <div className="flex items-center justify-center py-2">
        <svg viewBox="-110 -110 220 220" width="220" height="220" className="text-indigo-400">
          {/* DoA ring */}
          <circle cx="0" cy="0" r="100" fill="none" stroke="#333" strokeWidth="1" strokeDasharray="2 4" />
          {doaDeg !== null && (
            <line
              x1="0" y1="0"
              x2={100 * Math.cos((doaDeg * Math.PI) / 180)}
              y2={100 * Math.sin((doaDeg * Math.PI) / 180)}
              stroke="#f59e0b" strokeWidth="2"
            />
          )}
          {/* head: rotates yaw around Z, roll in-plane; pitch shown as vertical shift */}
          <g transform={`translate(0 ${pitchDeg * 0.8}) rotate(${rollDeg})`}>
            {/* antennas */}
            <line
              x1={-40} y1={-80}
              x2={-40 - 30 * Math.sin((leftAnt * Math.PI) / 180)}
              y2={-80 - 30 * Math.cos((leftAnt * Math.PI) / 180)}
              stroke="currentColor" strokeWidth="3" strokeLinecap="round"
            />
            <line
              x1={40} y1={-80}
              x2={40 + 30 * Math.sin((rightAnt * Math.PI) / 180)}
              y2={-80 - 30 * Math.cos((rightAnt * Math.PI) / 180)}
              stroke="currentColor" strokeWidth="3" strokeLinecap="round"
            />
            {/* head circle */}
            <circle cx="0" cy="0" r="70" fill="rgba(99, 102, 241, 0.12)" stroke="currentColor" strokeWidth="2" />
            {/* eyes shifted by yaw to simulate 3D gaze */}
            <circle cx={-20 + yawDeg * 0.35} cy="-10" r="8" fill="currentColor" />
            <circle cx={20 + yawDeg * 0.35} cy="-10" r="8" fill="currentColor" />
            {/* mouth */}
            <path d="M -20 25 Q 0 40 20 25" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </g>
        </svg>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-xs text-gray-400">
        <div><div className="text-white font-mono">{pitchDeg.toFixed(0)}°</div>pitch</div>
        <div><div className="text-white font-mono">{yawDeg.toFixed(0)}°</div>yaw</div>
        <div><div className="text-white font-mono">{rollDeg.toFixed(0)}°</div>roll</div>
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
