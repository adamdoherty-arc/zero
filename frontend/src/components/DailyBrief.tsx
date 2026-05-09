import { useState } from 'react'
import {
  useDailyBriefToday,
  useRegenerateBrief,
  useSendBriefNow,
  useSpeakBrief,
} from '@/hooks/useDailyBriefApi'

/**
 * Daily-brief dashboard tile.
 *
 * Renders today's composed brief (sections + bullets), a "speak it" button
 * that streams Reachy/Piper TTS to the browser, "send by email", and a
 * manual "regenerate" trigger. Used on the main dashboard plus the
 * exec-dashboard page.
 */
export function DailyBrief() {
  const { data, isLoading, error, refetch } = useDailyBriefToday()
  const regen = useRegenerateBrief()
  const sendNow = useSendBriefNow()
  const speak = useSpeakBrief()
  const [status, setStatus] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 text-gray-400">
        Composing today's brief…
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-950/50 p-4 text-red-300">
        Failed to load daily brief.
      </div>
    )
  }
  if (!data) {
    return null
  }

  const onSpeak = async () => {
    setStatus('Speaking…')
    try {
      await speak.mutateAsync(data.spoken_summary || data.markdown.slice(0, 2000))
      setStatus(null)
    } catch (e) {
      setStatus('Speak failed')
    }
  }

  const onSend = async () => {
    setStatus('Sending…')
    try {
      const res = await sendNow.mutateAsync({})
      setStatus(res.sent ? 'Sent' : `Skipped: ${res.error || 'no recipient'}`)
    } catch (e) {
      setStatus('Send failed')
    }
  }

  const onRegenerate = async () => {
    setStatus('Regenerating…')
    try {
      await regen.mutateAsync()
      setStatus('Updated')
      refetch()
    } catch (e) {
      setStatus('Regenerate failed')
    }
  }

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Daily brief</h2>
          <p className="text-xs text-gray-500">
            {data.date} — composed{' '}
            {new Date((data.generated_at || 0) * 1000).toLocaleTimeString()}
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <button
            onClick={onSpeak}
            className="rounded bg-indigo-600 px-3 py-1 text-white hover:bg-indigo-500"
          >
            Speak it
          </button>
          <button
            onClick={onSend}
            className="rounded bg-gray-800 px-3 py-1 text-gray-200 hover:bg-gray-700"
          >
            Email me
          </button>
          <button
            onClick={onRegenerate}
            className="rounded bg-gray-800 px-3 py-1 text-gray-200 hover:bg-gray-700"
          >
            Regenerate
          </button>
        </div>
      </div>
      {status && <div className="text-xs text-gray-400">{status}</div>}
      <div className="space-y-3">
        {data.sections.map((s) => (
          <section key={s.title}>
            <h3 className="text-sm font-medium text-indigo-300">{s.title}</h3>
            {s.error ? (
              <p className="text-xs text-amber-400">unavailable: {s.error}</p>
            ) : (
              <>
                {s.body && (
                  <p className="text-sm text-gray-300 whitespace-pre-wrap">{s.body}</p>
                )}
                {s.bullets.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-sm text-gray-300">
                    {s.bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
