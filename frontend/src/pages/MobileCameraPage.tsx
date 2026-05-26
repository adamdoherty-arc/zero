import { useEffect, useRef, useState } from 'react'
import { Camera, CameraOff, Loader2, Video, VideoOff } from 'lucide-react'

/**
 * Phone camera companion page (/m/camera).
 *
 * Captures frames via getUserMedia and POSTs them to
 * /api/sight/phone_camera/ingest at ~1 fps.  Zero's backend buffers the
 * last 30 frames so the desktop ZERO SEES panel and VLM analysis always
 * have a recent frame regardless of network jitter.
 *
 * Switch the active sight provider to "phone_camera" from the ZERO SEES
 * panel (Robot | Phone toggle) on the desktop to see this feed there.
 */
export default function MobileCameraPage() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [state, setState] = useState<'idle' | 'starting' | 'streaming' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [frameCount, setFrameCount] = useState(0)
  const [lastStatus, setLastStatus] = useState<string | null>(null)

  const startCamera = async () => {
    setState('starting')
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setState('streaming')

      // Capture and POST frames at 1 fps
      intervalRef.current = setInterval(async () => {
        if (!videoRef.current || !canvasRef.current) return
        const video = videoRef.current
        const canvas = canvasRef.current
        canvas.width = video.videoWidth || 1280
        canvas.height = video.videoHeight || 720
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        const blob = await new Promise<Blob | null>(res => canvas.toBlob(res, 'image/jpeg', 0.8))
        if (!blob) return
        try {
          const resp = await fetch('/api/sight/phone_camera/ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'image/jpeg' },
            body: blob,
          })
          setLastStatus(resp.ok ? 'ok' : `${resp.status}`)
          if (resp.ok) setFrameCount(n => n + 1)
        } catch {
          setLastStatus('network error')
        }
      }, 1000)
    } catch (e) {
      setError(String(e))
      setState('error')
    }
  }

  const stopCamera = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setState('idle')
    setFrameCount(0)
    setLastStatus(null)
  }

  // Auto-stop on unmount
  useEffect(() => () => stopCamera(), [])

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      {/* Header */}
      <div className="px-4 pt-safe-top pt-4 pb-3 flex items-center gap-3 border-b border-gray-800">
        <Camera className="w-5 h-5 text-indigo-400" />
        <div>
          <h1 className="font-semibold text-sm">Phone Camera</h1>
          <p className="text-[11px] text-gray-500">Streams to Zero's ZERO SEES panel</p>
        </div>
      </div>

      {/* Video preview */}
      <div className="flex-1 bg-black relative">
        <video
          ref={videoRef}
          className="w-full h-full object-cover"
          playsInline
          muted
          autoPlay={false}
        />
        <canvas ref={canvasRef} className="hidden" />

        {state === 'idle' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 text-gray-500">
            <VideoOff className="w-10 h-10" />
            <p className="text-sm">Camera is off</p>
          </div>
        )}
        {state === 'starting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-gray-400">
            <Loader2 className="w-8 h-8 animate-spin" />
            <p className="text-sm">Starting camera…</p>
          </div>
        )}
        {state === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-red-400 px-6 text-center">
            <CameraOff className="w-8 h-8" />
            <p className="text-sm">{error || 'Camera access denied'}</p>
            <p className="text-xs text-gray-500">Allow camera in browser settings, then try again.</p>
          </div>
        )}

        {/* Live status overlay */}
        {state === 'streaming' && (
          <div className="absolute top-3 left-3 flex items-center gap-2 bg-black/60 rounded-full px-3 py-1 text-xs">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            LIVE · {frameCount} frames sent
            {lastStatus && lastStatus !== 'ok' && (
              <span className="text-red-300 ml-1">({lastStatus})</span>
            )}
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="px-4 pb-safe-bottom pb-6 pt-4 border-t border-gray-800 space-y-3">
        {state !== 'streaming' ? (
          <button
            onClick={startCamera}
            disabled={state === 'starting'}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium py-3 rounded-xl flex items-center justify-center gap-2 transition-colors"
          >
            {state === 'starting' ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Starting…</>
            ) : (
              <><Video className="w-4 h-4" /> Start streaming</>
            )}
          </button>
        ) : (
          <button
            onClick={stopCamera}
            className="w-full bg-red-700 hover:bg-red-800 text-white font-medium py-3 rounded-xl flex items-center justify-center gap-2 transition-colors"
          >
            <VideoOff className="w-4 h-4" /> Stop streaming
          </button>
        )}

        <p className="text-[11px] text-gray-600 text-center">
          Switch to "Phone" in the ZERO SEES panel on the desktop to view this feed.
          Frames are buffered in Zero — keep this tab open to stay live.
        </p>
      </div>
    </div>
  )
}
