import { useEffect, useRef, useState } from 'react'
import { Camera, X, Loader2 } from 'lucide-react'

/**
 * Feature-69 — webcam face capture for the Identities page.
 *
 * Opens a getUserMedia preview, grabs a 720p frame on click, converts
 * to a JPEG Blob that the consumer wraps as a File and feeds into the
 * existing /api/faceprints/enroll endpoint.
 *
 * No new backend surface required — Feature-52 already ships the
 * multipart enroll route. This is purely a friction-removal UI.
 */

interface Props {
  onCapture: (file: File) => Promise<void> | void
  onCancel?: () => void
  disabled?: boolean
}

export function WebcamFaceCapture({ onCapture, onCancel, disabled }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState(false)
  const [capturing, setCapturing] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => {})
        }
        setActive(true)
      } catch (e) {
        setError(
          e instanceof Error
            ? `${e.name}: ${e.message}`
            : 'Webcam unavailable. Check browser permissions.',
        )
      }
    }
    start()
    return () => {
      cancelled = true
      const stream = streamRef.current
      streamRef.current = null
      if (stream) stream.getTracks().forEach((t) => t.stop())
      setActive(false)
    }
  }, [])

  async function snapshot() {
    if (!videoRef.current || capturing || disabled) return
    setCapturing(true)
    try {
      const video = videoRef.current
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth || 1280
      canvas.height = video.videoHeight || 720
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('Canvas 2D context unavailable')
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.92),
      )
      if (!blob) throw new Error('Snapshot encoding failed')
      const file = new File([blob], `webcam-${Date.now()}.jpg`, { type: 'image/jpeg' })
      await onCapture(file)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Capture failed')
    } finally {
      setCapturing(false)
    }
  }

  return (
    <div className="relative bg-gray-950 rounded border border-gray-700 overflow-hidden">
      {error ? (
        <div className="aspect-video flex items-center justify-center p-4 text-sm text-amber-300 text-center">
          {error}
        </div>
      ) : (
        <video
          ref={videoRef}
          className="w-full aspect-video object-cover bg-black"
          playsInline
          muted
          autoPlay
        />
      )}
      <div className="absolute inset-x-0 bottom-0 p-2 flex items-center justify-between gap-2 bg-gradient-to-t from-black/80 to-transparent">
        <span className="text-[11px] text-gray-400">
          {active ? 'Look into the camera • clear front-facing frame' : ''}
        </span>
        <div className="flex gap-2">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={capturing}
              className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 flex items-center gap-1 disabled:opacity-50"
            >
              <X className="w-3 h-3" /> Cancel
            </button>
          )}
          <button
            type="button"
            onClick={snapshot}
            disabled={capturing || !active || disabled}
            className="text-xs px-3 py-1 rounded bg-emerald-500 hover:bg-emerald-600 text-white flex items-center gap-1 disabled:opacity-50"
          >
            {capturing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Camera className="w-3 h-3" />}
            {capturing ? 'Enrolling…' : 'Capture & enroll'}
          </button>
        </div>
      </div>
    </div>
  )
}
