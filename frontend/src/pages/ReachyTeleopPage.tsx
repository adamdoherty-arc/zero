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

        <div className="glass-card p-4 flex flex-col">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3 flex items-center gap-2">
            <Camera className="w-4 h-4" /> Camera
          </h2>
          {stream.data?.url ? (
            <div className="flex-1 min-h-[300px] flex items-center justify-center text-sm text-gray-400 border border-dashed border-gray-700 rounded-lg p-6 text-center">
              <div>
                <Bot className="w-12 h-12 mx-auto mb-2 text-gray-600" />
                <p>Feed available at</p>
                <a href={stream.data.url} target="_blank" rel="noreferrer" className="text-indigo-400 break-all">
                  {stream.data.url}
                </a>
                <p className="text-xs text-gray-500 mt-3">
                  The Reachy daemon serves WebRTC on :8443. Embed a viewer here when the frontend grows a
                  WebRTC client.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
              Camera URL unavailable.
            </div>
          )}
        </div>
      </div>
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
