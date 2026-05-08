import { useState } from 'react'
import { Send, Loader2, CheckCircle, Sparkles } from 'lucide-react'
import {
  useSubmitContentRequest,
  type ContentRequestResult,
} from '@/hooks/useCharacterContentApi'

interface ContentRequestBarProps {
  placeholder?: string
  context?: 'characters' | 'movies' | 'tv_shows'
}

export function ContentRequestBar({
  placeholder = 'Type what you want queued... (e.g., "Doctor Doom, Dune characters, Street Fighter movie")',
  context,
}: ContentRequestBarProps) {
  const [text, setText] = useState('')
  const [lastResult, setLastResult] = useState<ContentRequestResult | null>(null)
  const submitMutation = useSubmitContentRequest()

  const handleSubmit = () => {
    if (!text.trim() || submitMutation.isPending) return

    let enrichedText = text
    if (context === 'movies') {
      enrichedText = `Focus on movies: ${text}`
    } else if (context === 'tv_shows') {
      enrichedText = `Focus on TV shows: ${text}`
    }

    submitMutation.mutate(
      { text: enrichedText, auto_research: true },
      {
        onSuccess: (result) => {
          setLastResult(result)
          setText('')
          setTimeout(() => setLastResult(null), 8000)
        },
      }
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const totalCreated =
    (lastResult?.characters_created.length ?? 0) +
    (lastResult?.movies_created.length ?? 0) +
    (lastResult?.tv_shows_created.length ?? 0)

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-indigo-400" />
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={submitMutation.isPending}
            className="w-full pl-10 pr-4 py-2.5 bg-gray-800/80 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 disabled:opacity-50 transition-all"
            aria-label="Content request input"
          />
        </div>
        <button
          onClick={handleSubmit}
          disabled={!text.trim() || submitMutation.isPending}
          className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg text-sm font-medium flex items-center gap-2 transition-colors whitespace-nowrap"
          aria-label="Submit content request"
        >
          {submitMutation.isPending ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Queuing...
            </>
          ) : (
            <>
              <Send className="w-4 h-4" />
              Queue
            </>
          )}
        </button>
      </div>

      {/* Result toast */}
      {lastResult && (
        <div className="flex items-center gap-2 px-3 py-2 bg-emerald-900/30 border border-emerald-700/50 rounded-lg text-sm animate-in fade-in slide-in-from-top-1">
          <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
          <span className="text-emerald-300">
            {totalCreated > 0 && (
              <span>
                Created {lastResult.characters_created.length > 0 && `${lastResult.characters_created.length} characters`}
                {lastResult.characters_created.length > 0 && lastResult.movies_created.length > 0 && ', '}
                {lastResult.movies_created.length > 0 && `${lastResult.movies_created.length} movies`}
                {(lastResult.characters_created.length > 0 || lastResult.movies_created.length > 0) && lastResult.tv_shows_created.length > 0 && ', '}
                {lastResult.tv_shows_created.length > 0 && `${lastResult.tv_shows_created.length} TV shows`}
                .{' '}
              </span>
            )}
            {lastResult.already_existed.length > 0 && (
              <span className="text-gray-400">
                Already had: {lastResult.already_existed.join(', ')}.{' '}
              </span>
            )}
            {lastResult.research_queued > 0 && (
              <span>Researching {lastResult.research_queued} characters in background.</span>
            )}
          </span>
        </div>
      )}

      {/* Error */}
      {submitMutation.isError && (
        <div className="flex items-center gap-2 px-3 py-2 bg-red-900/30 border border-red-700/50 rounded-lg text-sm text-red-300">
          Failed to process request: {submitMutation.error?.message}
        </div>
      )}
    </div>
  )
}
