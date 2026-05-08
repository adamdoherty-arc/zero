import { useState } from 'react'
import { Search, Film, Tv, Plus, Check, X, Star } from 'lucide-react'
import { useTMDBSearch, useCreateMediaTitle } from '@/hooks/useMediaContentApi'
import type { TMDBSearchResult } from '@/hooks/useMediaContentApi'

interface TMDBSearchModalProps {
  isOpen: boolean
  onClose: () => void
}

export function TMDBSearchModal({ isOpen, onClose }: TMDBSearchModalProps) {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | undefined>()

  const { data: results, isLoading } = useTMDBSearch(query, typeFilter)
  const createTitle = useCreateMediaTitle()

  const handleImport = async (result: TMDBSearchResult) => {
    try {
      await createTitle.mutateAsync({
        title: result.title,
        media_type: result.media_type as 'tv_show' | 'movie',
        year: result.year ?? undefined,
        synopsis: result.overview ?? undefined,
        tmdb_id: result.tmdb_id,
      })
    } catch {
      // Error handled by React Query
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-gray-800 border border-gray-700 rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">Search TMDB</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-700 text-gray-400">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search input */}
        <div className="p-4 space-y-3 border-b border-gray-700">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for TV shows or movies..."
              className="w-full pl-10 pr-4 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-indigo-500"
              autoFocus
            />
          </div>

          {/* Type filter */}
          <div className="flex gap-2">
            <button
              onClick={() => setTypeFilter(undefined)}
              className={`px-3 py-1 text-xs rounded-full transition-colors ${!typeFilter ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
            >
              All
            </button>
            <button
              onClick={() => setTypeFilter('tv_show')}
              className={`px-3 py-1 text-xs rounded-full flex items-center gap-1 transition-colors ${typeFilter === 'tv_show' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
            >
              <Tv className="w-3 h-3" /> TV Shows
            </button>
            <button
              onClick={() => setTypeFilter('movie')}
              className={`px-3 py-1 text-xs rounded-full flex items-center gap-1 transition-colors ${typeFilter === 'movie' ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
            >
              <Film className="w-3 h-3" /> Movies
            </button>
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {isLoading && query.length >= 2 && (
            <div className="text-center text-gray-400 py-8">Searching TMDB...</div>
          )}

          {!isLoading && query.length < 2 && (
            <div className="text-center text-gray-500 py-8">Type at least 2 characters to search</div>
          )}

          {results?.map((result) => (
            <div
              key={`${result.tmdb_id}-${result.media_type}`}
              className="flex items-center gap-3 p-3 rounded-lg bg-gray-900 border border-gray-700 hover:border-gray-600 transition-colors"
            >
              {/* Poster */}
              <div className="w-12 h-16 rounded bg-gray-700 flex-shrink-0 overflow-hidden">
                {result.poster_url ? (
                  <img src={result.poster_url} alt={result.title} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    {result.media_type === 'tv_show' ? <Tv className="w-5 h-5 text-gray-500" /> : <Film className="w-5 h-5 text-gray-500" />}
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-white truncate">{result.title}</h3>
                  {result.year && <span className="text-xs text-gray-400 flex-shrink-0">{result.year}</span>}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    {result.media_type === 'tv_show' ? <Tv className="w-3 h-3" /> : <Film className="w-3 h-3" />}
                    {result.media_type === 'tv_show' ? 'TV Show' : 'Movie'}
                  </span>
                  {result.vote_average != null && result.vote_average > 0 && (
                    <span className="text-xs text-yellow-400 flex items-center gap-0.5">
                      <Star className="w-3 h-3" /> {result.vote_average.toFixed(1)}
                    </span>
                  )}
                </div>
                {result.overview && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-1">{result.overview}</p>
                )}
              </div>

              {/* Import button */}
              <div className="flex-shrink-0">
                {result.already_imported ? (
                  <span className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded bg-green-900/50 text-green-400">
                    <Check className="w-3 h-3" /> Imported
                  </span>
                ) : (
                  <button
                    onClick={() => handleImport(result)}
                    disabled={createTitle.isPending}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50 transition-colors"
                  >
                    <Plus className="w-3 h-3" /> Import
                  </button>
                )}
              </div>
            </div>
          ))}

          {!isLoading && query.length >= 2 && results?.length === 0 && (
            <div className="text-center text-gray-500 py-8">No results found</div>
          )}
        </div>
      </div>
    </div>
  )
}
