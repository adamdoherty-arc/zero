import { useParams, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import {
  ArrowLeft, Search, Loader2, ChevronLeft, ChevronRight,
  Sparkles, Zap, Star, Film, BookOpen, Users, Swords,
  AlertTriangle, Clock, CheckCircle,
  Plus, RefreshCw, Eye, ThumbsUp, Image as ImageIcon,
} from 'lucide-react'
import {
  useCharacter,
  useCharacterImages,
  useCharacterCarousels,
  useResearchCharacter,
  useGenerateCarousel,
  useSourceImages,
  useAiReviewCarousel,
  useApproveCarousel,
  type CharacterImage as CharacterImageType,
  type CharacterCarousel,
  type CharacterFact,
  type ContentAngle,
} from '@/hooks/useCharacterContentApi'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'

const UNIVERSE_COLORS: Record<string, string> = {
  marvel: 'bg-red-500/20 text-red-400',
  dc: 'bg-blue-500/20 text-blue-400',
  star_wars: 'bg-yellow-500/20 text-yellow-400',
  lotr: 'bg-green-500/20 text-green-400',
  harry_potter: 'bg-purple-500/20 text-purple-400',
  anime: 'bg-pink-500/20 text-pink-400',
  tv: 'bg-orange-500/20 text-orange-400',
  film: 'bg-cyan-500/20 text-cyan-400',
  gaming: 'bg-emerald-500/20 text-emerald-400',
  other: 'bg-gray-500/20 text-gray-400',
}

const RESEARCH_STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-500/20 text-gray-400',
  researching: 'bg-yellow-500/20 text-yellow-400',
  completed: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
}

const CATEGORY_COLORS: Record<string, string> = {
  origin: 'bg-blue-500/20 text-blue-400',
  powers: 'bg-purple-500/20 text-purple-400',
  relationships: 'bg-pink-500/20 text-pink-400',
  hidden_details: 'bg-amber-500/20 text-amber-400',
  fan_theories: 'bg-cyan-500/20 text-cyan-400',
  behind_scenes: 'bg-green-500/20 text-green-400',
  character_evolution: 'bg-indigo-500/20 text-indigo-400',
  dark_facts: 'bg-red-500/20 text-red-400',
}

const CAROUSEL_STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-500/20 text-gray-400',
  ai_reviewed: 'bg-yellow-500/20 text-yellow-400',
  pending_review: 'bg-orange-500/20 text-orange-400',
  approved: 'bg-green-500/20 text-green-400',
  rejected: 'bg-red-500/20 text-red-400',
  published: 'bg-blue-500/20 text-blue-400',
}

function ScoreBar({ value, maxWidth = 100 }: { value: number; maxWidth?: number }) {
  const color = value >= 7 ? 'bg-green-500' : value >= 4 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full`} style={{ width: `${Math.min(value * 10, maxWidth)}%` }} />
    </div>
  )
}

function ImageGallery({ images, characterName, onSourceMore, isSourcing }: {
  images: CharacterImageType[]
  characterName: string
  onSourceMore: () => void
  isSourcing: boolean
}) {
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [errors, setErrors] = useState<Set<number>>(new Set())

  const validImages = images.filter((_, i) => !errors.has(i))

  if (validImages.length === 0) {
    return (
      <div className="bg-white/5 rounded-xl p-8 text-center">
        <ImageIcon className="w-12 h-12 text-white/20 mx-auto mb-3" />
        <p className="text-sm text-gray-400 mb-4">No images sourced yet</p>
        <button
          onClick={onSourceMore}
          disabled={isSourcing}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-sm rounded-lg disabled:opacity-50"
          aria-label="Source images for this character"
        >
          {isSourcing ? <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> : <Search className="w-4 h-4 inline mr-2" />}
          Source Images
        </button>
      </div>
    )
  }

  const currentIdx = Math.min(selectedIdx, validImages.length - 1)

  return (
    <div className="space-y-3">
      <div className="relative group">
        <img
          src={validImages[currentIdx].url}
          alt={`${characterName} image ${currentIdx + 1} of ${validImages.length}`}
          className="w-full h-80 object-contain rounded-xl bg-gray-900"
          onError={() => {
            const originalIdx = images.indexOf(validImages[currentIdx])
            setErrors(prev => new Set([...prev, originalIdx]))
          }}
        />
        {validImages.length > 1 && (
          <>
            <button
              aria-label="Previous image"
              onClick={() => setSelectedIdx(prev => (prev - 1 + validImages.length) % validImages.length)}
              className="absolute left-2 top-1/2 -translate-y-1/2 p-1.5 bg-black/60 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <button
              aria-label="Next image"
              onClick={() => setSelectedIdx(prev => (prev + 1) % validImages.length)}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-black/60 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </>
        )}
        <div className="absolute bottom-2 right-2 px-2 py-1 bg-black/60 rounded text-xs text-gray-300">
          {currentIdx + 1} / {validImages.length}
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-2">
        {validImages.map((img, i) => (
          <button
            key={img.id}
            onClick={() => setSelectedIdx(i)}
            className={`flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden border-2 transition-all ${i === currentIdx ? 'border-indigo-500' : 'border-transparent hover:border-white/20'}`}
          >
            <img
              src={img.url}
              alt={`${characterName} ${i + 1}`}
              className="w-full h-full object-cover"
              onError={() => {
                const originalIdx = images.indexOf(img)
                setErrors(prev => new Set([...prev, originalIdx]))
              }}
            />
          </button>
        ))}
        <button
          onClick={onSourceMore}
          disabled={isSourcing}
          className="flex-shrink-0 w-16 h-16 rounded-lg border-2 border-dashed border-white/20 flex items-center justify-center hover:border-indigo-500 transition-colors disabled:opacity-50"
          aria-label="Source more images"
        >
          {isSourcing ? <Loader2 className="w-5 h-5 animate-spin text-gray-400" /> : <Plus className="w-5 h-5 text-gray-400" />}
        </button>
      </div>
    </div>
  )
}

function FactBankSection({ facts, categoryFilter, onCategoryChange }: {
  facts: CharacterFact[]
  categoryFilter: string
  onCategoryChange: (cat: string) => void
}) {
  const categories = [...new Set(facts.map(f => f.category))]
  const filtered = categoryFilter ? facts.filter(f => f.category === categoryFilter) : facts

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Star className="w-5 h-5 text-yellow-400" />
          Fact Bank ({facts.length} facts)
        </h3>
      </div>

      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => onCategoryChange('')}
          className={`px-3 py-1 rounded-full text-xs transition-colors ${!categoryFilter ? 'bg-indigo-600 text-white' : 'bg-white/5 text-gray-400 hover:bg-white/10'}`}
          aria-label="Show all fact categories"
          aria-pressed={!categoryFilter}
        >
          All
        </button>
        {categories.map(cat => (
          <button
            key={cat}
            onClick={() => onCategoryChange(cat)}
            className={`px-3 py-1 rounded-full text-xs transition-colors ${categoryFilter === cat ? 'bg-indigo-600 text-white' : (CATEGORY_COLORS[cat] || 'bg-white/5 text-gray-400') + ' hover:opacity-80'}`}
            aria-label={`Filter by ${cat.replace('_', ' ')} category`}
            aria-pressed={categoryFilter === cat}
          >
            {cat.replace('_', ' ')}
          </button>
        ))}
      </div>

      <div className="space-y-2 max-h-[500px] overflow-y-auto">
        {filtered.map((fact, i) => (
          <div key={i} className="bg-white/5 rounded-lg p-3 hover:bg-white/8 transition-colors">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <p className="text-sm text-gray-200">{fact.text}</p>
                <div className="flex items-center gap-2 mt-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${CATEGORY_COLORS[fact.category] || 'bg-white/10 text-gray-400'}`}>
                    {fact.category.replace('_', ' ')}
                  </span>
                  {fact.source && <span className="text-xs text-gray-500">{fact.source}</span>}
                  {fact.verified && <CheckCircle className="w-3 h-3 text-green-400" />}
                </div>
              </div>
              <div className="flex flex-col items-center">
                <span className={`text-lg font-bold ${fact.surprise_score >= 8 ? 'text-green-400' : fact.surprise_score >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {fact.surprise_score}
                </span>
                <span className="text-[10px] text-gray-500">surprise</span>
              </div>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-sm text-gray-500 text-center py-4">No facts found{categoryFilter ? ` for "${categoryFilter}"` : ''}</p>
        )}
      </div>
    </div>
  )
}

function CarouselsSection({ carousels, onGenerateCarousel, isGenerating, onReview, onApprove }: {
  carousels: CharacterCarousel[]
  onGenerateCarousel: (angle: ContentAngle) => void
  isGenerating: boolean
  onReview: (id: string) => void
  onApprove: (id: string) => void
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-purple-400" />
          Carousels ({carousels.length})
        </h3>
        <button
          onClick={() => onGenerateCarousel('hidden_truths' as ContentAngle)}
          disabled={isGenerating}
          className="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-sm rounded-lg disabled:opacity-50 flex items-center gap-2"
          aria-label="Generate new carousel"
        >
          {isGenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          Generate
        </button>
      </div>

      {carousels.length === 0 ? (
        <p className="text-sm text-gray-500 text-center py-8">No carousels generated yet. Click Generate to create one.</p>
      ) : (
        <div className="space-y-3">
          {carousels.map(carousel => (
            <div key={carousel.id} className="bg-white/5 rounded-lg p-4 hover:bg-white/8 transition-colors space-y-3">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${CAROUSEL_STATUS_COLORS[carousel.status] || 'bg-gray-500/20 text-gray-400'}`}>
                    {carousel.status.replace('_', ' ')}
                  </span>
                  <span className="text-xs text-gray-500">{carousel.angle.replace('_', ' ')}</span>
                </div>
                <div className="flex items-center gap-2">
                  {carousel.ai_review && (
                    <span className={`text-sm font-bold ${(carousel.ai_review.overall_score as number) >= 7 ? 'text-green-400' : 'text-yellow-400'}`}>
                      {carousel.ai_review.overall_score}/10
                    </span>
                  )}
                  {carousel.status === 'draft' && (
                    <button
                      onClick={() => onReview(carousel.id)}
                      className="px-2 py-1 bg-yellow-600/20 text-yellow-400 text-xs rounded hover:bg-yellow-600/30"
                      aria-label="Request AI review for this carousel"
                    >
                      AI Review
                    </button>
                  )}
                  {(carousel.status === 'pending_review' || carousel.status === 'ai_reviewed') && (
                    <button
                      onClick={() => onApprove(carousel.id)}
                      className="px-2 py-1 bg-green-600/20 text-green-400 text-xs rounded hover:bg-green-600/30"
                      aria-label="Approve this carousel for publishing"
                    >
                      Approve
                    </button>
                  )}
                </div>
              </div>

              {carousel.hook_text && (
                <div className="bg-indigo-950/30 border border-indigo-500/20 rounded-lg px-3 py-2">
                  <p className="text-sm font-bold text-white">{carousel.hook_text}</p>
                </div>
              )}

              {carousel.slides?.length > 0 && (
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {carousel.slides.map((slide, i) => (
                    <div key={i} className="relative flex-shrink-0 w-24 h-32 rounded-lg overflow-hidden bg-gray-800 border border-gray-700">
                      {slide.image_url ? (
                        <img src={slide.image_url} alt={`Slide ${slide.slide_num || i + 1} image`} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <span className="text-2xl font-bold text-gray-600">{slide.slide_num || i + 1}</span>
                        </div>
                      )}
                      <div className="absolute top-1 left-1 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded">
                        {slide.slide_num || i + 1}
                      </div>
                      {slide.text && (
                        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-1.5 pt-4">
                          <p className="text-[10px] text-white leading-tight line-clamp-2">{slide.text}</p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {carousel.caption && (
                <p className="text-xs text-gray-400 italic">"{carousel.caption}"</p>
              )}

              {carousel.hashtags?.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {carousel.hashtags.map((tag) => (
                    <span key={tag} className="text-[10px] text-indigo-400">#{tag}</span>
                  ))}
                </div>
              )}

              {carousel.ai_review && (
                <div className="grid grid-cols-4 gap-3">
                  {(['hook_strength', 'fact_quality', 'engagement_potential', 'caption_quality'] as const).map(key => (
                    <div key={key} className="space-y-1">
                      <div className="flex justify-between">
                        <span className="text-[10px] text-gray-500">{key.replace('_', ' ')}</span>
                        <span className="text-[10px] text-gray-400">{carousel.ai_review?.[key]}</span>
                      </div>
                      <ScoreBar value={carousel.ai_review?.[key] as number || 0} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function CharacterDetailPage() {
  const { characterId } = useParams<{ characterId: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<'overview' | 'facts' | 'carousels' | 'media'>('overview')
  const [categoryFilter, setCategoryFilter] = useState('')

  const { data: character, isLoading, error } = useCharacter(characterId || '')
  const { data: images = [] } = useCharacterImages(characterId || '')
  const { data: carousels = [] } = useCharacterCarousels(characterId || '')

  const researchMut = useResearchCharacter()
  const generateMut = useGenerateCarousel()
  const sourceImagesMut = useSourceImages()
  const reviewMut = useAiReviewCarousel()
  const approveMut = useApproveCarousel()

  if (isLoading) {
    return <LoadingSkeleton variant="page" message="Loading character..." />
  }

  if (error || !character) {
    return (
      <div className="p-8 text-center">
        <AlertTriangle className="w-12 h-12 text-red-400 mx-auto mb-4" />
        <p className="text-gray-400">Character not found</p>
        <button onClick={() => navigate('/characters')} className="mt-4 text-indigo-400 hover:text-indigo-300" aria-label="Back to characters list">
          Back to Characters
        </button>
      </div>
    )
  }

  const rd = character.research_data as Record<string, unknown>
  const bio = (rd.bio as string) || character.description || 'No biography available. Run research to generate.'
  const powers = (rd.powers as string[]) || []
  const relationships = (rd.key_relationships as { name: string; relation: string; details?: string }[]) || []
  const filmography = (rd.filmography as { title: string; year: number; role: string; type: string }[]) || []
  const notableArcs = (rd.notable_arcs as ({ name: string; description: string; year?: string } | string)[]) || []
  const quotes = (rd.quotes as { text: string; source: string }[]) || []
  const aliases = (rd.aliases as string[]) || []
  const firstAppearance = (rd.first_appearance as string) || ''
  const createdBy = (rd.created_by as string) || ''
  const alternateVersions = (rd.alternate_versions as string[]) || []

  const tabs = [
    { key: 'overview' as const, label: 'Overview', icon: BookOpen },
    { key: 'facts' as const, label: `Facts (${character.fact_bank.length})`, icon: Star },
    { key: 'carousels' as const, label: `Carousels (${carousels.length})`, icon: Sparkles },
    { key: 'media' as const, label: `Media (${images.length})`, icon: ImageIcon },
  ]

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Back button */}
      <button
        onClick={() => navigate('/characters')}
        className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors"
        aria-label="Back to characters list"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Characters
      </button>

      {/* Hero Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <ImageGallery
            images={images}
            characterName={character.name}
            onSourceMore={() => sourceImagesMut.mutate(character.id)}
            isSourcing={sourceImagesMut.isPending}
          />
        </div>

        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <h1 className="text-3xl font-bold">{character.name}</h1>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${UNIVERSE_COLORS[character.universe] || UNIVERSE_COLORS.other}`}>
                  {character.universe.replace('_', ' ')}
                </span>
              </div>
              {character.real_name && (
                <p className="text-lg text-gray-400">{character.real_name}</p>
              )}
              {character.franchise && (
                <p className="text-sm text-gray-500">{character.franchise}</p>
              )}
              {aliases.length > 0 && (
                <p className="text-xs text-gray-500 mt-1">Also known as: {aliases.join(', ')}</p>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span className={`px-2 py-1 rounded text-xs ${RESEARCH_STATUS_COLORS[character.research_status] || ''}`}>
                {character.research_status}
              </span>
            </div>
          </div>

          {/* Quick stats */}
          <div className="grid grid-cols-4 gap-3">
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-indigo-400">{character.fact_bank.length}</p>
              <p className="text-xs text-gray-500">Facts</p>
            </div>
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-purple-400">{carousels.length}</p>
              <p className="text-xs text-gray-500">Carousels</p>
            </div>
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-green-400">{images.length}</p>
              <p className="text-xs text-gray-500">Images</p>
            </div>
            <div className="bg-white/5 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-yellow-400">{character.posts_created}</p>
              <p className="text-xs text-gray-500">Published</p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => researchMut.mutate(character.id)}
              disabled={researchMut.isPending || character.research_status === 'researching'}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-sm rounded-lg disabled:opacity-50 flex items-center gap-2"
              aria-label={character.research_status === 'completed' ? `Re-research ${character.name}` : `Research ${character.name}`}
            >
              {researchMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              {character.research_status === 'completed' ? 'Re-Research' : 'Research'}
            </button>
            <button
              onClick={() => generateMut.mutate({ character_id: character.id })}
              disabled={generateMut.isPending || character.research_status !== 'completed'}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-sm rounded-lg disabled:opacity-50 flex items-center gap-2"
              aria-label={`Generate carousel for ${character.name}`}
            >
              {generateMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              Generate Carousel
            </button>
            <button
              onClick={() => sourceImagesMut.mutate(character.id)}
              disabled={sourceImagesMut.isPending}
              className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-sm rounded-lg disabled:opacity-50 flex items-center gap-2"
              aria-label={`Source images for ${character.name}`}
            >
              {sourceImagesMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ImageIcon className="w-4 h-4" />}
              Source Images
            </button>
          </div>

          {/* Meta info */}
          <div className="flex gap-4 text-xs text-gray-500 flex-wrap">
            {firstAppearance && <span>First: {firstAppearance}</span>}
            {createdBy && <span>Created by: {createdBy}</span>}
            {character.last_researched && (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                Researched: {new Date(character.last_researched).toLocaleDateString()}
              </span>
            )}
            {character.tags.length > 0 && (
              <span>Tags: {character.tags.join(', ')}</span>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-white/10" role="tablist" aria-label="Character detail sections">
        <div className="flex gap-1">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              role="tab"
              aria-selected={activeTab === tab.key}
              aria-label={`${tab.label} tab`}
              className={`px-4 py-2.5 text-sm font-medium flex items-center gap-2 border-b-2 transition-colors ${activeTab === tab.key ? 'border-indigo-500 text-white' : 'border-transparent text-gray-400 hover:text-gray-200'}`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Biography */}
          <div className="bg-white/5 rounded-xl p-6 space-y-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-indigo-400" /> Biography
            </h3>
            <div className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">
              {bio}
            </div>
          </div>

          {/* Powers & Abilities */}
          <div className="space-y-6">
            {powers.length > 0 && (
              <div className="bg-white/5 rounded-xl p-6">
                <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
                  <Zap className="w-5 h-5 text-yellow-400" /> Powers & Abilities
                </h3>
                <div className="flex flex-wrap gap-2">
                  {powers.map((p, i) => (
                    <span key={i} className="px-3 py-1.5 bg-yellow-500/10 text-yellow-400 rounded-lg text-sm">
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Relationships */}
            {relationships.length > 0 && (
              <div className="bg-white/5 rounded-xl p-6">
                <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
                  <Users className="w-5 h-5 text-pink-400" /> Key Relationships
                </h3>
                <div className="space-y-2">
                  {relationships.map((rel, i) => (
                    <div key={i} className="flex items-center gap-3 py-2 border-b border-white/5 last:border-0">
                      <span className="text-sm font-medium text-gray-200 w-32">{rel.name}</span>
                      <span className="px-2 py-0.5 bg-white/10 rounded text-xs text-gray-400">{rel.relation}</span>
                      {rel.details && <span className="text-xs text-gray-500 flex-1">{rel.details}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Filmography */}
          {filmography.length > 0 && (
            <div className="bg-white/5 rounded-xl p-6 lg:col-span-2">
              <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
                <Film className="w-5 h-5 text-cyan-400" /> Filmography & Appearances
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filmography.sort((a, b) => (b.year || 0) - (a.year || 0)).map((f, i) => (
                  <div key={i} className="bg-white/5 rounded-lg p-3 flex items-center gap-3">
                    <div className="text-2xl font-bold text-gray-600 w-14 text-center">{f.year}</div>
                    <div>
                      <p className="text-sm font-medium text-gray-200">{f.title}</p>
                      <div className="flex gap-2 mt-1">
                        <span className="text-xs text-gray-500">{f.role}</span>
                        <span className={`text-xs px-1.5 rounded ${f.type === 'movie' ? 'bg-cyan-500/20 text-cyan-400' : f.type === 'tv_series' ? 'bg-orange-500/20 text-orange-400' : 'bg-gray-500/20 text-gray-400'}`}>
                          {f.type?.replace('_', ' ')}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Notable Arcs */}
          {notableArcs.length > 0 && (
            <div className="bg-white/5 rounded-xl p-6">
              <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
                <Swords className="w-5 h-5 text-red-400" /> Notable Arcs
              </h3>
              <div className="space-y-3">
                {notableArcs.map((arc, i) => (
                  <div key={i} className="border-l-2 border-indigo-500/50 pl-4 py-1">
                    {typeof arc === 'string' ? (
                      <p className="text-sm text-gray-300">{arc}</p>
                    ) : (
                      <>
                        <p className="text-sm font-medium text-gray-200">{arc.name}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{arc.description}</p>
                        {arc.year && <p className="text-xs text-gray-500 mt-0.5">{arc.year}</p>}
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Quotes */}
          {quotes.length > 0 && (
            <div className="bg-white/5 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-3">Memorable Quotes</h3>
              <div className="space-y-3">
                {quotes.map((q, i) => (
                  <blockquote key={i} className="border-l-2 border-purple-500/50 pl-4 py-1">
                    <p className="text-sm text-gray-300 italic">"{q.text}"</p>
                    <p className="text-xs text-gray-500 mt-1">- {q.source}</p>
                  </blockquote>
                ))}
              </div>
            </div>
          )}

          {/* Alternate Versions */}
          {alternateVersions.length > 0 && (
            <div className="bg-white/5 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-3">Alternate Versions</h3>
              <div className="space-y-2">
                {alternateVersions.map((v, i) => (
                  <p key={i} className="text-sm text-gray-300 flex items-start gap-2">
                    <RefreshCw className="w-3 h-3 mt-1 text-gray-500 flex-shrink-0" />
                    {v}
                  </p>
                ))}
              </div>
            </div>
          )}

          {/* Performance */}
          {(character.total_views > 0 || character.total_likes > 0) && (
            <div className="bg-white/5 rounded-xl p-6">
              <h3 className="text-lg font-semibold mb-3">Performance</h3>
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center">
                  <Eye className="w-5 h-5 text-blue-400 mx-auto mb-1" />
                  <p className="text-lg font-bold">{character.total_views.toLocaleString()}</p>
                  <p className="text-xs text-gray-500">Views</p>
                </div>
                <div className="text-center">
                  <ThumbsUp className="w-5 h-5 text-green-400 mx-auto mb-1" />
                  <p className="text-lg font-bold">{character.total_likes.toLocaleString()}</p>
                  <p className="text-xs text-gray-500">Likes</p>
                </div>
                <div className="text-center">
                  <Zap className="w-5 h-5 text-yellow-400 mx-auto mb-1" />
                  <p className="text-lg font-bold">{character.avg_engagement.toFixed(1)}%</p>
                  <p className="text-xs text-gray-500">Engagement</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'facts' && (
        <FactBankSection
          facts={character.fact_bank}
          categoryFilter={categoryFilter}
          onCategoryChange={setCategoryFilter}
        />
      )}

      {activeTab === 'carousels' && (
        <CarouselsSection
          carousels={carousels}
          onGenerateCarousel={(angle) => generateMut.mutate({ character_id: character.id, angle })}
          isGenerating={generateMut.isPending}
          onReview={(id) => reviewMut.mutate(id)}
          onApprove={(id) => approveMut.mutate({ id })}
        />
      )}

      {activeTab === 'media' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <ImageIcon className="w-5 h-5 text-cyan-400" />
              Image Library ({images.length})
            </h3>
            <button
              onClick={() => sourceImagesMut.mutate(character.id)}
              disabled={sourceImagesMut.isPending}
              className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-sm rounded-lg disabled:opacity-50 flex items-center gap-2"
              aria-label="Source more images for this character"
            >
              {sourceImagesMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              Source More
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {images.map(img => (
              <div key={img.id} className="group relative">
                <img
                  src={img.url}
                  alt={`${character.name} image from ${img.source}`}
                  className="w-full h-40 object-cover rounded-lg bg-gray-900"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                />
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2 rounded-b-lg opacity-0 group-hover:opacity-100 transition-opacity">
                  <span className="text-xs text-gray-300">{img.source}</span>
                  {img.is_primary && <span className="text-xs text-yellow-400 ml-2">Primary</span>}
                </div>
              </div>
            ))}
          </div>

          {images.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              <ImageIcon className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>No images yet. Click "Source More" to search for character images.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
