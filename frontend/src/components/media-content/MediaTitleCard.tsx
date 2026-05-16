import { Film, Tv, Search, Sparkles, Image, ChevronRight } from 'lucide-react'
import type { MediaTitle } from '@/hooks/useMediaContentApi'
import { CONTENT_PRODUCTION_PAUSED_TOOLTIP } from '@/hooks/useContentControlApi'

interface MediaTitleCardProps {
  title: MediaTitle
  onResearch?: (id: string) => void
  onGenerate?: (id: string) => void
  onClick?: (id: string) => void
  isResearching?: boolean
  isGenerating?: boolean
  productionPaused?: boolean
}

export function MediaTitleCard({
  title,
  onResearch,
  onGenerate,
  onClick,
  isResearching,
  isGenerating,
  productionPaused = false,
}: MediaTitleCardProps) {
  const isTV = title.media_type === 'tv_show'
  const TypeIcon = isTV ? Tv : Film

  const statusColors: Record<string, string> = {
    pending: 'bg-gray-700 text-gray-300',
    researching: 'bg-blue-900 text-blue-300',
    completed: 'bg-green-900 text-green-300',
    failed: 'bg-red-900 text-red-300',
  }

  return (
    <div
      className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden hover:border-gray-600 transition-colors cursor-pointer group"
      onClick={() => onClick?.(title.id)}
    >
      {/* Poster / Backdrop */}
      <div className="relative h-36 bg-gray-900 overflow-hidden">
        {title.poster_url ? (
          <img
            src={title.poster_url}
            alt={title.title}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <TypeIcon className="w-12 h-12 text-gray-600" />
          </div>
        )}
        {/* Type badge */}
        <span className="absolute top-2 left-2 px-2 py-0.5 rounded text-xs font-medium bg-black/60 text-white flex items-center gap-1">
          <TypeIcon className="w-3 h-3" />
          {isTV ? 'TV Show' : 'Movie'}
        </span>
        {/* Year badge */}
        {title.year && (
          <span className="absolute top-2 right-2 px-2 py-0.5 rounded text-xs font-medium bg-black/60 text-white">
            {title.year}{title.end_year && title.end_year !== title.year ? `\u2013${title.end_year}` : ''}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="p-3 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold text-white text-sm line-clamp-1">{title.title}</h3>
          <ChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0 mt-0.5" />
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-2 text-xs text-gray-400 flex-wrap">
          {title.genre?.slice(0, 2).map((g) => (
            <span key={g} className="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">{g}</span>
          ))}
          {isTV && title.season_count && (
            <span>{title.season_count} seasons</span>
          )}
          {!isTV && title.runtime_minutes && (
            <span>{title.runtime_minutes} min</span>
          )}
        </div>

        {/* Research status */}
        <div className="flex items-center justify-between">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColors[title.research_status] || statusColors.pending}`}>
            {title.research_status}
          </span>
          <div className="flex items-center gap-1 text-xs text-gray-400">
            <Image className="w-3 h-3" />
            <span>{title.carousels_created}</span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
          {title.research_status !== 'completed' && (
            <button
              onClick={() => onResearch?.(title.id)}
              disabled={isResearching || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Research media title'}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 transition-colors"
            >
              <Search className="w-3 h-3" />
              {isResearching ? 'Researching...' : 'Research'}
            </button>
          )}
          {title.research_status === 'completed' && (
            <button
              onClick={() => onGenerate?.(title.id)}
              disabled={isGenerating || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Generate media carousel'}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium rounded bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50 transition-colors"
            >
              <Sparkles className="w-3 h-3" />
              {isGenerating ? 'Generating...' : 'Generate'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
