import { useEffect, useRef, useState } from 'react'
import { Camera, CameraOff, ChevronDown, Loader2, Pause, Play, Scan, Settings } from 'lucide-react'
import {
  useCameraDevices,
  useCameraStatus,
  useSightProviders,
  useSwitchCamera,
} from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

interface Props {
  height?: number
  compact?: boolean
}

/**
 * Live Reachy camera viewer.
 *
 * Primary source: Reachy robot body camera (host_agent MJPEG stream).
 * Secondary source: Phone camera (companion PWA at /m/camera pushes frames
 * to the backend PhoneCameraProvider).
 *
 * Device picker: enumerates Windows DirectShow devices and lets the user
 * switch the active index — needed when a phone or other USB camera shifts
 * the Reachy camera off index 0.
 */
export function ReachyCameraViewer({ height = 360, compact = false }: Props) {
  const [frozen, setFrozen] = useState(false)
  const [cacheKey, setCacheKey] = useState(() => Date.now())
  const [imgError, setImgError] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [lastAnalysis, setLastAnalysis] = useState<string | null>(null)
  const [showDevicePicker, setShowDevicePicker] = useState(false)
  const status = useCameraStatus(frozen ? 10_000 : 2_000)
  const { data: devices } = useCameraDevices()
  const { data: sight } = useSightProviders()
  const switchCamera = useSwitchCamera()
  const { toast } = useToast()
  const imgRef = useRef<HTMLImageElement | null>(null)

  const activeProvider = sight?.active ?? 'reachy'
  const isPhoneActive = activeProvider === 'phone_camera'

  // When camera reports active but the img has a load error (MJPEG stream
  // dropped after a container restart), auto-reconnect by bumping cacheKey.
  useEffect(() => {
    if (status.data?.active && imgError) {
      const t = setTimeout(() => {
        setCacheKey(Date.now())
        setImgError(null)
      }, 1500)
      return () => clearTimeout(t)
    }
    if (status.data?.active) setImgError(null)
  }, [status.data?.active, imgError])

  // Show device picker automatically when camera is persistently offline.
  // Debounced: only opens after 8s of sustained offline to avoid false triggers
  // during page load or container restart (camera warmup takes 2-4s).
  useEffect(() => {
    if (!frozen && status.data && !status.data.active && !isPhoneActive) {
      const t = setTimeout(() => setShowDevicePicker(true), 8000)
      return () => clearTimeout(t)
    }
  }, [status.data?.active, frozen, isPhoneActive])

  const src = frozen || isPhoneActive
    ? (isPhoneActive ? `/api/sight/phone_camera/mjpeg?t=${cacheKey}` : '')
    : `/api/reachy/camera/mjpeg?t=${cacheKey}`

  const restart = () => {
    setFrozen(false)
    setCacheKey(Date.now())
    setImgError(null)
  }

  const handleSelectDevice = async (index: number) => {
    setShowDevicePicker(false)
    try {
      await switchCamera.mutateAsync(index)
      restart()
      toast({ title: 'Camera switched', description: `Now using device ${index}` })
    } catch {
      toast({ title: 'Switch failed', variant: 'destructive' })
    }
  }

  const snapshot = async () => {
    setAnalyzing(true)
    setLastAnalysis(null)
    try {
      const provId = isPhoneActive ? 'phone_camera' : 'reachy'
      const resp = await fetch(`/api/reachy/vision/scene?provider_id=${provId}`, { method: 'POST' })
      if (!resp.ok) {
        const fallback = await fetch(`/api/reachy/vision/scene?provider_id=meta_rayban`, { method: 'POST' })
        if (!fallback.ok) throw new Error(`scene failed: ${resp.status}`)
        surfaceScene(await fallback.json())
        return
      }
      surfaceScene(await resp.json())
    } catch (e) {
      toast({ title: 'Snapshot failed', description: String(e), variant: 'destructive' })
    } finally {
      setAnalyzing(false)
    }
  }

  const surfaceScene = (data: {
    caption?: string
    actionable?: string | null
    answer?: string | null
    provider?: string
    model?: string
    detections?: unknown[]
  }) => {
    const parts: string[] = []
    if (data.caption) parts.push(data.caption)
    if (data.actionable) parts.push(`→ ${data.actionable}`)
    const faces = data.detections?.length ?? 0
    if (faces) parts.push(`Detections: ${faces}`)
    const summary = parts.join(' · ') || 'No caption returned'
    setLastAnalysis(summary)
    toast({ title: `Scene (${data.provider ?? '?'} via ${data.model ?? '?'})`, description: summary })
  }

  const fps = status.data?.fps ?? 0
  const active = isPhoneActive
    ? (sight?.providers.find(p => p.provider === 'phone_camera')?.active ?? false)
    : (status.data?.active ?? false)
  const hasError = imgError || (!isPhoneActive && (status.data?.last_error || status.data?.reason))

  return (
    <div className="glass-card p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide flex items-center gap-2">
          <Camera className="w-4 h-4" /> Zero sees
        </h2>
        <div className="flex items-center gap-2">
          {/* Provider: Reachy robot camera only. Phone provider hidden — causes OS connection prompts. */}

          {/* Status pill */}
          <div className="text-[11px] text-gray-500 flex items-center gap-1">
            {active ? (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block animate-pulse" />
                {!isPhoneActive && `${fps.toFixed(1)} fps · ${status.data?.width}×${status.data?.height}`}
              </>
            ) : (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-gray-600 inline-block" />
                offline
              </>
            )}
            {!isPhoneActive && (
              <span className="text-gray-600">· {status.data?.backend ?? '—'}</span>
            )}
          </div>

          {/* Device picker toggle (robot mode only) */}
          {!isPhoneActive && (
            <button
              onClick={() => setShowDevicePicker(v => !v)}
              className="glass-card-hover px-1.5 py-0.5 flex items-center gap-1 text-[11px] text-gray-400"
              title="Select camera device"
            >
              <Settings className="w-3 h-3" />
              <ChevronDown className={`w-3 h-3 transition-transform ${showDevicePicker ? 'rotate-180' : ''}`} />
            </button>
          )}
        </div>
      </div>

      {/* Device picker dropdown */}
      {showDevicePicker && !isPhoneActive && (
        <div className="mb-3 border border-gray-700 rounded bg-gray-900 divide-y divide-gray-800 text-xs">
          {!devices ? (
            <div className="px-3 py-2 text-gray-500 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> Loading devices…
            </div>
          ) : devices.length === 0 ? (
            <div className="px-3 py-2 text-gray-500">No camera devices found</div>
          ) : (
            devices.map(dev => (
              <button
                key={dev.index}
                onClick={() => handleSelectDevice(dev.index)}
                disabled={!dev.available || switchCamera.isPending}
                className={`w-full text-left px-3 py-2 flex items-center justify-between hover:bg-gray-800 disabled:opacity-40 transition-colors ${
                  dev.index === (status.data?.device_index ?? -1) ? 'bg-gray-800' : ''
                }`}
              >
                <span className="flex items-center gap-2">
                  {dev.is_reachy && (
                    <span className="text-indigo-400 font-medium">★</span>
                  )}
                  <span className={dev.is_reachy ? 'text-white' : 'text-gray-300'}>
                    [{dev.index}] {dev.name}
                  </span>
                  {dev.is_reachy && (
                    <span className="text-indigo-400 text-[10px]">(robot)</span>
                  )}
                </span>
                <span className="text-gray-500">
                  {dev.available ? `${dev.width}×${dev.height}` : 'unavailable'}
                </span>
              </button>
            ))
          )}
        </div>
      )}


      {/* Video frame */}
      <div
        className="relative bg-black rounded overflow-hidden flex items-center justify-center"
        style={{ height }}
      >
        {frozen ? (
          <div className="text-xs text-gray-500 flex items-center gap-2">
            <Pause className="w-4 h-4" /> Paused
          </div>
        ) : src ? (
          <img
            ref={imgRef}
            src={src}
            alt="Zero live camera"
            className="max-h-full max-w-full object-contain"
            onError={() => setImgError('stream unavailable')}
          />
        ) : null}

        {!frozen && !active && !imgError && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-xs text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            {isPhoneActive ? 'Waiting for phone frames…' : 'Waiting for host_agent camera…'}
          </div>
        )}

        {hasError && (
          <div className="absolute top-2 left-2 right-2 text-[11px] text-red-300 bg-red-900/60 rounded px-2 py-1 flex items-center gap-1">
            <CameraOff className="w-3 h-3" />
            <span className="truncate">{hasError}</span>
          </div>
        )}
      </div>

      {!compact && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {frozen ? (
            <button onClick={restart} className="glass-card-hover px-3 py-1 flex items-center gap-1">
              <Play className="w-3 h-3" /> Resume
            </button>
          ) : (
            <button onClick={() => setFrozen(true)} className="glass-card-hover px-3 py-1 flex items-center gap-1">
              <Pause className="w-3 h-3" /> Freeze
            </button>
          )}
          <button
            onClick={snapshot}
            disabled={analyzing || !active}
            className="glass-card-hover px-3 py-1 flex items-center gap-1 disabled:opacity-40"
          >
            {analyzing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Scan className="w-3 h-3" />}
            Snapshot & analyze
          </button>
          {lastAnalysis && <span className="text-gray-400">· {lastAnalysis}</span>}
        </div>
      )}
    </div>
  )
}
