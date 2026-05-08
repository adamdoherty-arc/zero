import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Film, Tv, Plus, Sparkles, Download,
} from 'lucide-react'
import {
  useMediaTitles, useMediaStats, useResearchMediaTitle,
  useGenerateMediaCarousel, useSeedMediaTitles,
} from '@/hooks/useMediaContentApi'
import { MediaTitleCard } from '@/components/media-content/MediaTitleCard'
import { TMDBSearchModal } from '@/components/media-content/TMDBSearchModal'
import { ContentRequestBar } from '@/components/character-content/ContentRequestBar'
import { AlphabetFilter, bucketOf, sortByName } from '@/components/character-content/AlphabetFilter'

interface MediaContentTabProps {
  mediaTypeFilter?: 'tv_show' | 'movie'
}

export function MediaContentTab({ mediaTypeFilter }: MediaContentTabProps) {
  const navigate = useNavigate()
  const [showTMDBSearch, setShowTMDBSearch] = useState(false)
  const [researchingId, setResearchingId] = useState<string | null>(null)
  const [generatingId, setGeneratingId] = useState<string | null>(null)
  const [letterFilter, setLetterFilter] = useState<string | null>(null)

  const { data: titles, isLoading } = useMediaTitles({ media_type: mediaTypeFilter, limit: 100 })
  const sortedTitles = titles ? sortByName(titles, (t) => t.title) : []
  const visibleTitles = letterFilter
    ? sortedTitles.filter((t) => bucketOf(t.title) === letterFilter)
    : sortedTitles
  const { data: stats } = useMediaStats()
  const researchMutation = useResearchMediaTitle()
  const generateMutation = useGenerateMediaCarousel()
  const seedMutation = useSeedMediaTitles()

  const handleResearch = async (id: string) => {
    setResearchingId(id)
    try {
      await researchMutation.mutateAsync(id)
    } finally {
      setResearchingId(null)
    }
  }

  const handleGenerate = async (id: string) => {
    setGeneratingId(id)
    try {
      await generateMutation.mutateAsync({ media_title_id: id })
    } finally {
      setGeneratingId(null)
    }
  }

  const handleSeed = async (mediaType: string) => {
    await seedMutation.mutateAsync({ count: 10, media_type: mediaType })
  }

  return (
    <div className="space-y-6">
      {/* Content request bar */}
      <ContentRequestBar
        placeholder={mediaTypeFilter === 'tv_show'
          ? "Queue TV shows... (e.g., 'Daredevil Born Again, Ironheart, Agatha All Along')"
          : "Queue movies... (e.g., 'Avengers Doomsday, Dune Messiah, Street Fighter movie')"
        }
        context={mediaTypeFilter === 'tv_show' ? 'tv_shows' : 'movies'}
      />

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-1 flex items-center gap-1">
              {mediaTypeFilter === 'tv_show' ? <Tv className="w-3 h-3" /> : <Film className="w-3 h-3" />}
              {mediaTypeFilter === 'tv_show' ? 'TV Shows' : 'Movies'}
            </div>
            <div className="text-xl font-bold text-white">{mediaTypeFilter === 'tv_show' ? stats.tv_shows : stats.movies}</div>
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-1">Researched</div>
            <div className="text-xl font-bold text-white">{stats.titles_researched}</div>
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-1 flex items-center gap-1"><Sparkles className="w-3 h-3" /> Carousels</div>
            <div className="text-xl font-bold text-white">{stats.total_carousels}</div>
          </div>
        </div>
      )}

      {/* Actions bar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm text-gray-400">
          {visibleTitles.length}
          {letterFilter ? ` of ${sortedTitles.length}` : ''} {mediaTypeFilter === 'tv_show' ? 'TV shows' : 'movies'}
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => handleSeed(mediaTypeFilter || 'movie')}
            disabled={seedMutation.isPending}
            className="px-3 py-1.5 text-sm rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 border border-gray-700 flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <Download className="w-4 h-4" />
            {seedMutation.isPending ? 'Seeding...' : `Seed Popular`}
          </button>
          <button
            onClick={() => setShowTMDBSearch(true)}
            className="px-3 py-1.5 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white flex items-center gap-1.5 transition-colors"
          >
            <Plus className="w-4 h-4" /> Add from TMDB
          </button>
        </div>
      </div>

      {/* Title grid */}
      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="bg-gray-800 border border-gray-700 rounded-lg h-64 animate-pulse" />
          ))}
        </div>
      ) : sortedTitles.length > 0 ? (
        <>
          <AlphabetFilter
            items={sortedTitles}
            getName={(t) => t.title}
            selected={letterFilter}
            onSelect={setLetterFilter}
          />
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {visibleTitles.map((title) => (
              <MediaTitleCard
                key={title.id}
                title={title}
                onResearch={handleResearch}
                onGenerate={handleGenerate}
                onClick={(id) => navigate(`/characters/media/${id}`)}
                isResearching={researchingId === title.id}
                isGenerating={generatingId === title.id}
              />
            ))}
          </div>
        </>
      ) : (
        <div className="text-center py-16 text-gray-400">
          {mediaTypeFilter === 'tv_show'
            ? <Tv className="w-12 h-12 mx-auto mb-3 text-gray-600" />
            : <Film className="w-12 h-12 mx-auto mb-3 text-gray-600" />
          }
          <p className="text-lg font-medium text-gray-300">
            No {mediaTypeFilter === 'tv_show' ? 'TV shows' : 'movies'} yet
          </p>
          <p className="text-sm mt-1">Add from TMDB or seed popular {mediaTypeFilter === 'tv_show' ? 'TV shows' : 'movies'}</p>
          <button
            onClick={() => setShowTMDBSearch(true)}
            className="mt-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm transition-colors"
          >
            <Plus className="w-4 h-4 inline mr-1" /> Search TMDB
          </button>
        </div>
      )}

      {/* TMDB Search Modal */}
      <TMDBSearchModal isOpen={showTMDBSearch} onClose={() => setShowTMDBSearch(false)} />
    </div>
  )
}
