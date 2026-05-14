import { useEffect, useRef, useState } from 'react'
import { Camera, CameraOff, Loader2, Pause, Play, Scan } from 'lucide-react'
import { useCameraStatus } from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

interface Props {
  height?: number
  compact?: boolean
}

/**
 * Live Reachy camera viewer.
 *
 * Embeds `/api/reachy/camera/mjpeg` in an <img> so the browser pipelines
 * each JPEG frame as it arrives. Polls `/api/reachy/camera/status` every
 * 2s for fps/backend/error surfacing, and exposes a freeze (drop the
 * <img>) + snapshot-to-vision action.
 */
export function ReachyCameraViewer({ height = 360, compact = false }: Props) {
  const [frozen, setFrozen] = useState(false)
  const [cacheKey, setCacheKey] = useState(() => Date.now())
  const [imgError, setImgError] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [lastAnalysis, setLastAnalysis] = useState<string | null>(null)
  const status = useCameraStatus(frozen ? 10_000 : 2_000)
  const { toast } = useToast()
  const imgRef = useRef<HTMLImageElement | null>(null)

  // Reset the error banner when status flips back to active.
  useEffect(() => {
    if (status.data?.active) setImgError(null)
  }, [status.data?.active])

  const src = frozen ? '' : `/api/reachy/camera/mjpeg?t=${cacheKey}`

  const restart = () => {
    setFrozen(false)
    setCacheKey(Date.now())
    setImgError(null)
  }

  const snapshot = async () => {
    setAnalyzing(true)
    setLastAnalysis(null)
    try {
      // Full VLM scene analysis: caption + actionable tag + face/hand
      // detections in one call. Runs against the active SightProvider,
      // so the same button works whether the frame is from Reachy's
      // camera or the Meta glasses bridge.
      const resp = await fetch(`/api/reachy/vision/scene?provider_id=reachy`, {
        method: 'POST',
      })
      if (!resp.ok) {
        // Try the meta_rayban provider as a fallback when Reachy's camera
        // is held by the daemon.
        const fallback = await fetch(`/api/reachy/vision/scene?provider_id=meta_rayban`, {
          method: 'POST',
        })
        if (!fallback.ok) throw new Error(`scene failed: ${resp.status}`)
        const data = await fallback.json()
        surfaceScene(data)
        return
      }
      const data = await resp.json()
      surfaceScene(data)
    } catch (e) {
      toast({
        title: 'Snapshot failed',
        description: String(e),
        variant: 'destructive',
      })
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
    toast({
      title: `Scene (${data.provider ?? '?'} via ${data.model ?? '?'})`,
      description: summary,
    })
  }

  const fps = status.data?.fps ?? 0
  const active = status.data?.active ?? false
  const hasError = imgError || status.data?.last_error || status.data?.reason

  return (
    <div className="glass-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide flex items-center gap-2">
          <Camera className="w-4 h-4" /> Zero sees
        </h2>
        <div className="flex items-center gap-2 text-[11px] text-gray-500">
          {active ? (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block animate-pulse" />
              {fps.toFixed(1)} fps · {status.data?.width}×{status.data?.height}
            </span>
          ) : (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-600 inline-block" />
              offline
            </span>
          )}
          <span className="text-gray-600">· {status.data?.backend ?? '—'}</span>
        </div>
      </div>

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
            <Loader2 className="w-4 h-4 animate-spin" /> Waiting for host_agent camera…
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
            <button
              onClick={restart}
              className="glass-card-hover px-3 py-1 flex items-center gap-1"
            >
              <Play className="w-3 h-3" /> Resume
            </button>
          ) : (
            <button
              onClick={() => setFrozen(true)}
              className="glass-card-hover px-3 py-1 flex items-center gap-1"
            >
              <Pause className="w-3 h-3" /> Freeze
            </button>
          )}
          <button
            onClick={snapshot}
            disabled={analyzing || !active}
            className="glass-card-hover px-3 py-1 flex items-center gap-1 disabled:opacity-40"
          >
            {analyzing ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Scan className="w-3 h-3" />
            )}
            Snapshot & analyze
          </button>
          {lastAnalysis && <span className="text-gray-400">· {lastAnalysis}</span>}
        </div>
      )}
    </div>
  )
}
