import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Film, Tv, Search, Sparkles, Users, Image,
  ChevronDown, ChevronUp, Link2, Unlink,
} from 'lucide-react'
import {
  useMediaTitle, useLinkedCharacters, useMediaCarousels,
  useMediaImages, useResearchMediaTitle, useGenerateMediaCarousel,
  useMediaAngles, useMediaTemplates,
  useLinkCharacter, useUnlinkCharacter,
} from '@/hooks/useMediaContentApi'
import { useCharacters } from '@/hooks/useCharacterContentApi'
import type { MediaContentAngle } from '@/hooks/useMediaContentApi'

export function MediaDetailPage() {
  const { mediaId } = useParams<{ mediaId: string }>()
  const navigate = useNavigate()

  const { data: title, isLoading } = useMediaTitle(mediaId || '')
  const { data: characters } = useLinkedCharacters(mediaId || '')
  const { data: carousels } = useMediaCarousels({ media_title_id: mediaId })
  const { data: images } = useMediaImages(mediaId || '')
  const { data: angles } = useMediaAngles()
  const { data: templates } = useMediaTemplates()
  const { data: allCharacters } = useCharacters()

  const researchMutation = useResearchMediaTitle()
  const generateMutation = useGenerateMediaCarousel()
  const linkMutation = useLinkCharacter()
  const unlinkMutation = useUnlinkCharacter()

  const [activeTab, setActiveTab] = useState<'overview' | 'facts' | 'carousels' | 'characters' | 'images'>('overview')
  const [selectedAngle, setSelectedAngle] = useState<string>('hidden_details')
  const [selectedTemplate, setSelectedTemplate] = useState<string>('')
  const [showLinkModal, setShowLinkModal] = useState(false)
  const [expandedFact, setExpandedFact] = useState<number | null>(null)

  if (isLoading || !title) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-800 rounded w-48" />
        <div className="h-48 bg-gray-800 rounded" />
      </div>
    )
  }

  const isTV = title.media_type === 'tv_show'
  const TypeIcon = isTV ? Tv : Film
  const tabs = ['overview', 'facts', 'carousels', 'characters', 'images'] as const

  const handleGenerate = async () => {
    await generateMutation.mutateAsync({
      media_title_id: title.id,
      angle: selectedAngle as MediaContentAngle,
      story_template: selectedTemplate || undefined,
    })
  }

  const handleLinkCharacter = async (characterId: string) => {
    await linkMutation.mutateAsync({
      media_title_id: title.id,
      character_id: characterId,
    })
    setShowLinkModal(false)
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={() => navigate(`/characters?tab=${title.media_type === 'tv_show' ? 'tv-shows' : 'movies'}`)}
        className="flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to {title.media_type === 'tv_show' ? 'TV Shows' : 'Movies'}
      </button>

      {/* Hero section */}
      <div className="flex gap-6">
        {/* Poster */}
        <div className="w-48 h-72 rounded-lg bg-gray-800 border border-gray-700 flex-shrink-0 overflow-hidden">
          {title.poster_url ? (
            <img src={title.poster_url} alt={title.title} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <TypeIcon className="w-16 h-16 text-gray-600" />
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 space-y-3">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white">{title.title}</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-900/50 text-indigo-300 flex items-center gap-1">
              <TypeIcon className="w-3 h-3" />
              {isTV ? 'TV Show' : 'Movie'}
            </span>
          </div>

          {/* Meta */}
          <div className="flex items-center gap-4 text-sm text-gray-400 flex-wrap">
            {title.year && <span>{title.year}{title.end_year && title.end_year !== title.year ? `-${title.end_year}` : ''}</span>}
            {title.genre?.length > 0 && <span>{title.genre.join(', ')}</span>}
            {isTV && title.network && <span>{title.network}</span>}
            {isTV && title.season_count && <span>{title.season_count} seasons</span>}
            {!isTV && title.runtime_minutes && <span>{title.runtime_minutes} min</span>}
            {title.mpaa_rating && <span>{title.mpaa_rating}</span>}
          </div>

          {title.tagline && <p className="text-gray-400 italic text-sm">"{title.tagline}"</p>}
          {title.synopsis && <p className="text-gray-300 text-sm line-clamp-3">{title.synopsis}</p>}

          {/* Research status + actions */}
          <div className="flex items-center gap-3 pt-2">
            <span className={`px-3 py-1 rounded text-xs font-medium ${
              title.research_status === 'completed' ? 'bg-green-900/50 text-green-300' :
              title.research_status === 'researching' ? 'bg-blue-900/50 text-blue-300' :
              'bg-gray-700 text-gray-300'
            }`}>
              Research: {title.research_status}
            </span>
            {title.research_depth_score > 0 && (
              <span className="text-xs text-gray-400">Depth: {title.research_depth_score.toFixed(0)}%</span>
            )}
            <button
              onClick={() => researchMutation.mutateAsync(title.id)}
              disabled={researchMutation.isPending}
              className="px-3 py-1 text-xs rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 flex items-center gap-1 transition-colors"
            >
              <Search className="w-3 h-3" />
              {researchMutation.isPending ? 'Researching...' : title.research_status === 'completed' ? 'Re-research' : 'Research'}
            </button>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-4 text-xs text-gray-400">
            <span>{title.carousels_created} carousels</span>
            <span>{title.character_count} characters</span>
            {title.fact_bank?.length > 0 && <span>{title.fact_bank.length} facts</span>}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-700 pb-0">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              activeTab === tab
                ? 'bg-gray-800 text-white border-b-2 border-indigo-500'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Generate carousel */}
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-indigo-400" /> Generate Carousel
            </h3>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Content Angle</label>
              <select
                value={selectedAngle}
                onChange={(e) => setSelectedAngle(e.target.value)}
                className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-1.5 text-sm text-white"
              >
                {angles?.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Story Template (optional)</label>
              <select
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                className="w-full bg-gray-900 border border-gray-600 rounded-lg px-3 py-1.5 text-sm text-white"
              >
                <option value="">Auto-select</option>
                {templates?.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={handleGenerate}
              disabled={generateMutation.isPending || title.research_status !== 'completed'}
              className="w-full py-2 text-sm font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50 flex items-center justify-center gap-2 transition-colors"
            >
              <Sparkles className="w-4 h-4" />
              {generateMutation.isPending ? 'Generating...' : 'Generate Carousel'}
            </button>
            {title.research_status !== 'completed' && (
              <p className="text-xs text-yellow-500">Research must be completed before generating</p>
            )}
          </div>

          {/* Box office / financials for movies */}
          {!isTV && (title.budget_usd || title.box_office_usd) && (
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-2">
              <h3 className="text-sm font-semibold text-white">Box Office</h3>
              {title.budget_usd != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Budget</span>
                  <span className="text-white">${(title.budget_usd / 1_000_000).toFixed(0)}M</span>
                </div>
              )}
              {title.box_office_usd != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Box Office</span>
                  <span className="text-white">${(title.box_office_usd / 1_000_000).toFixed(0)}M</span>
                </div>
              )}
            </div>
          )}

          {/* TV show info */}
          {isTV && (
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-2">
              <h3 className="text-sm font-semibold text-white">Show Info</h3>
              {title.network && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Network</span>
                  <span className="text-white">{title.network}</span>
                </div>
              )}
              {title.show_status && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Status</span>
                  <span className="text-white capitalize">{title.show_status}</span>
                </div>
              )}
              {title.season_count != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Seasons</span>
                  <span className="text-white">{title.season_count}</span>
                </div>
              )}
              {title.episode_count != null && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Episodes</span>
                  <span className="text-white">{title.episode_count}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeTab === 'facts' && (
        <div className="space-y-2">
          {title.fact_bank?.length > 0 ? (
            title.fact_bank.map((fact, i) => (
              <div
                key={i}
                className="bg-gray-800 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-gray-600 transition-colors"
                onClick={() => setExpandedFact(expandedFact === i ? null : i)}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-gray-200">{fact.fact}</p>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-300">{fact.category}</span>
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      fact.surprise_score >= 0.8 ? 'bg-green-900 text-green-300' :
                      fact.surprise_score >= 0.5 ? 'bg-yellow-900 text-yellow-300' :
                      'bg-gray-700 text-gray-400'
                    }`}>
                      {(fact.surprise_score * 10).toFixed(0)}/10
                    </span>
                    {expandedFact === i ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
                  </div>
                </div>
                {expandedFact === i && fact.source && (
                  <p className="text-xs text-gray-500 mt-2">Source: {fact.source}</p>
                )}
              </div>
            ))
          ) : (
            <div className="text-center py-12 text-gray-400">
              <Search className="w-8 h-8 mx-auto mb-2 text-gray-600" />
              <p>No facts yet. Research this title first.</p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'carousels' && (
        <div className="space-y-3">
          {(carousels as Array<Record<string, unknown>>)?.length > 0 ? (
            (carousels as Array<Record<string, unknown>>).map((carousel) => (
              <div
                key={carousel.id as string}
                className="bg-gray-800 border border-gray-700 rounded-lg p-4 hover:border-gray-600 cursor-pointer transition-colors"
                onClick={() => navigate(`/characters/media/${mediaId}/carousels/${carousel.id}/edit`)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <h4 className="text-sm font-medium text-white">{carousel.title as string || 'Untitled'}</h4>
                    <p className="text-xs text-gray-400 mt-1 line-clamp-1">{carousel.hook_text as string}</p>
                    <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                      <span className="px-2 py-0.5 rounded bg-gray-700 text-gray-300">{(carousel.angle as string || '').replace(/_/g, ' ')}</span>
                      <span className={`px-2 py-0.5 rounded ${
                        carousel.status === 'approved' ? 'bg-green-900 text-green-300' :
                        carousel.status === 'pending_review' ? 'bg-yellow-900 text-yellow-300' :
                        'bg-gray-700 text-gray-300'
                      }`}>{carousel.status as string}</span>
                    </div>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-12 text-gray-400">
              <Sparkles className="w-8 h-8 mx-auto mb-2 text-gray-600" />
              <p>No carousels yet. Generate one from the Overview tab.</p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'characters' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <button
              onClick={() => setShowLinkModal(true)}
              className="px-3 py-1.5 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white flex items-center gap-1.5 transition-colors"
            >
              <Link2 className="w-4 h-4" /> Link Character
            </button>
          </div>

          {characters?.length ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {characters.map((link) => (
                <div
                  key={link.id}
                  className="bg-gray-800 border border-gray-700 rounded-lg p-3 flex items-center gap-3 hover:border-indigo-500/60 transition-colors group"
                >
                  <button
                    onClick={() => navigate(`/characters/${link.character_id}`)}
                    className="flex items-center gap-3 flex-1 min-w-0 text-left"
                    title={`View ${link.character_name}`}
                  >
                    {link.character_image_url ? (
                      <img
                        src={link.character_image_url}
                        alt={link.character_name || ''}
                        className="w-12 h-12 rounded-lg object-cover flex-shrink-0 bg-gray-900"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded-lg bg-gray-900 flex items-center justify-center flex-shrink-0">
                        <Users className="w-5 h-5 text-gray-500" />
                      </div>
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-white truncate group-hover:text-indigo-300">
                        {link.character_name}
                        {link.character_status === 'pending' && (
                          <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 align-middle">
                            auto
                          </span>
                        )}
                      </p>
                      <div className="flex items-center gap-1.5 text-xs text-gray-400 flex-wrap">
                        {link.role_name && <span className="truncate">as {link.role_name}</span>}
                        <span className="px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 capitalize">{link.role_type}</span>
                        {link.actor_name && <span className="text-gray-500 truncate">({link.actor_name})</span>}
                      </div>
                    </div>
                  </button>
                  <button
                    onClick={() => unlinkMutation.mutate({ mediaId: title.id, characterId: link.character_id })}
                    className="p-1.5 rounded hover:bg-gray-700 text-gray-500 hover:text-red-400 transition-colors flex-shrink-0"
                    title="Unlink character"
                  >
                    <Unlink className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 text-gray-400">
              <Users className="w-8 h-8 mx-auto mb-2 text-gray-600" />
              <p>No characters linked yet.</p>
              <p className="text-xs text-gray-500 mt-1">
                Run TMDB cast sync from the admin panel, or link manually.
              </p>
            </div>
          )}

          {/* Link character modal */}
          {showLinkModal && (
            <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowLinkModal(false)}>
              <div
                className="bg-gray-800 border border-gray-700 rounded-xl w-full max-w-lg max-h-[60vh] overflow-y-auto p-4"
                onClick={(e) => e.stopPropagation()}
              >
                <h3 className="text-lg font-semibold text-white mb-3">Link Character</h3>
                <div className="space-y-2">
                  {allCharacters?.filter(c =>
                    !characters?.some(link => link.character_id === c.id)
                  ).map((char) => (
                    <button
                      key={char.id}
                      onClick={() => handleLinkCharacter(char.id)}
                      className="w-full flex items-center gap-3 p-3 rounded-lg bg-gray-900 border border-gray-700 hover:border-indigo-500 text-left transition-colors"
                    >
                      <Users className="w-5 h-5 text-gray-400" />
                      <div>
                        <p className="text-sm font-medium text-white">{char.name}</p>
                        <p className="text-xs text-gray-400">{char.universe}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'images' && (
        <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          {images?.map((img) => (
            <div
              key={img.id}
              className="aspect-video rounded-lg bg-gray-800 border border-gray-700 overflow-hidden"
            >
              <img src={img.url} alt="" className="w-full h-full object-cover" />
            </div>
          ))}
          {(!images || images.length === 0) && (
            <div className="col-span-full text-center py-12 text-gray-400">
              <Image className="w-8 h-8 mx-auto mb-2 text-gray-600" />
              <p>No images yet. Research to pull from TMDB.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
