import { useEffect, useState } from 'react'
import { Loader2, Mic, Trash2, Star, CheckCircle2 } from 'lucide-react'
import {
  useDeleteVoiceprint,
  useEnrollVoiceprint,
  useVoiceprints,
  type Voiceprint,
} from '@/hooks/useMeetings'
import { useToast } from '@/hooks/use-toast'

const ENROLL_DURATION = 30

export function VoiceEnrollmentPanel() {
  const { toast } = useToast()
  const voiceprints = useVoiceprints()
  const enroll = useEnrollVoiceprint()
  const remove = useDeleteVoiceprint()
  const [displayName, setDisplayName] = useState('Me')
  const [countdown, setCountdown] = useState(0)

  useEffect(() => {
    if (countdown <= 0) return
    const t = window.setTimeout(() => setCountdown((c) => c - 1), 1000)
    return () => window.clearTimeout(t)
  }, [countdown])

  async function handleEnroll() {
    if (!displayName.trim()) {
      toast({ title: 'Display name required', variant: 'destructive' })
      return
    }
    setCountdown(ENROLL_DURATION)
    try {
      await enroll.mutateAsync({
        display_name: displayName.trim(),
        duration_seconds: ENROLL_DURATION,
        is_primary: true,
      })
      toast({ title: 'Voiceprint enrolled', description: displayName.trim() })
    } catch (e) {
      toast({
        title: 'Enrollment failed',
        description: String(e),
        variant: 'destructive',
      })
    } finally {
      setCountdown(0)
    }
  }

  async function handleDelete(vp: Voiceprint) {
    if (!confirm(`Delete voiceprint for "${vp.display_name}"?`)) return
    try {
      await remove.mutateAsync(vp.id)
      toast({ title: 'Voiceprint deleted' })
    } catch (e) {
      toast({ title: 'Delete failed', description: String(e), variant: 'destructive' })
    }
  }

  const list = voiceprints.data ?? []
  const isRecording = enroll.isPending && countdown > 0
  const primary = list.find((v) => v.is_primary)

  return (
    <div className="space-y-3">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="block text-[10px] uppercase tracking-wide text-gray-500 mb-1">
            Display name
          </label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Me"
            disabled={isRecording}
            className="w-full bg-gray-900/60 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 disabled:opacity-50 focus:outline-none focus:border-emerald-500/50"
          />
        </div>
        <button
          onClick={handleEnroll}
          disabled={isRecording || !displayName.trim()}
          className="px-3 py-2 text-sm font-semibold rounded bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50 flex items-center gap-2 whitespace-nowrap"
        >
          {isRecording ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Recording {countdown}s…
            </>
          ) : (
            <>
              <Mic className="w-4 h-4" />
              Enroll yourself ({ENROLL_DURATION}s)
            </>
          )}
        </button>
      </div>

      {isRecording && (
        <div className="text-xs text-emerald-300">
          Speak naturally for the full {ENROLL_DURATION} seconds. The Reachy mic is listening.
        </div>
      )}

      {primary && !isRecording && (
        <div className="text-xs text-gray-400 flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          Primary voice: <span className="text-gray-200">{primary.display_name}</span>
        </div>
      )}

      {voiceprints.isLoading && (
        <div className="text-xs text-gray-500">
          <Loader2 className="w-3 h-3 inline animate-spin mr-1" /> Loading voiceprints…
        </div>
      )}

      {!voiceprints.isLoading && list.length === 0 && (
        <div className="text-xs text-gray-500">
          No voiceprints yet. Enroll yourself to get auto-labeled in future meetings.
        </div>
      )}

      {list.length > 0 && (
        <div className="space-y-1">
          {list.map((vp) => (
            <div
              key={vp.id}
              className="flex items-center gap-2 px-3 py-2 rounded bg-gray-900/40 border border-gray-700/40"
            >
              {vp.is_primary && <Star className="w-3 h-3 text-emerald-400" />}
              <span className="text-sm text-gray-100 flex-1 truncate">
                {vp.display_name}
              </span>
              <span className="text-[10px] text-gray-500">
                {vp.samples_seconds.toFixed(0)}s sample
              </span>
              <button
                onClick={() => handleDelete(vp)}
                disabled={remove.isPending}
                className="p-1 rounded text-gray-400 hover:text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                title="Delete voiceprint"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
