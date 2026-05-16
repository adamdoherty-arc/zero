import { useState, useEffect, Component, type ErrorInfo, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  useCharacters,
  useCharacterStats,
  useCarousels,
  useReviewQueue,
  useSmartReviewQueue,
  useCreateCharacter,
  useResearchCharacter,
  useSeedCharacters,
  useGenerateCarousel,
  useAiReviewCarousel,
  useApproveCarousel,
  useRejectCarousel,
  useUpdateCarousel,
  useReimageSlide,
  useBatchResearch,
  useDeleteCharacter,
  useInspirations,
  useInspirationPatterns,
  useDiscoverInspirations,
  useAnalyzeInspiration,
  useTemplates,
  useSeedTemplates,
  useSeedMusic,
  useSmartBatchGenerate,
  useGenerateSeries,
  useSourceAnalytics,
  useTemplateAnalytics,
  useResearchQueue,
  useStartResearchQueue,
  useCancelResearchQueue,
  useRetryResearch,
  useCarouselEmployeeReport,
  type Character,
  type CharacterCarousel,
  type ContentAngle,
  type CharacterUniverse,
  type AIReview,
  type ResearchJob,
  type ResearchJobStep,
} from '@/hooks/useCharacterContentApi'
import { CarouselCard } from '@/components/character-content/CarouselCard'
import {
  Users, Search, Sparkles, Eye, Heart,
  CheckCircle, XCircle, RefreshCw, Plus, Loader2,
  Zap, Brain, Music, Lightbulb,
  TrendingUp, Award, Layers, Clock, AlertTriangle,
  Play, Square, ImageIcon, BookOpen,
  ChevronDown, ChevronUp, RotateCcw, Timer, X,
  Link, ExternalLink,
  Pencil, Save, Music2, Trash2, Film,
} from 'lucide-react'
import { ReferenceVideosTab } from '@/components/character-content/ReferenceVideosTab'
import { ContentRequestBar } from '@/components/character-content/ContentRequestBar'
import { AlphabetFilter, bucketOf, sortByName } from '@/components/character-content/AlphabetFilter'
import TikTokPhonePreview from '@/components/character-content/TikTokPhonePreview'
import MusicPickerModal from '@/components/character-content/MusicPickerModal'
import { ContentProductionPausedBanner } from '@/components/content-control/ContentProductionPausedBanner'
import {
  CONTENT_PRODUCTION_PAUSED_TOOLTIP,
  useContentProductionStatus,
} from '@/hooks/useContentControlApi'

class CharacterContentErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('CharacterContent error:', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 text-center">
          <AlertTriangle className="w-12 h-12 mx-auto mb-4 text-red-400" />
          <h2 className="text-lg font-semibold text-white mb-2">Something went wrong</h2>
          <p className="text-gray-400 mb-4">{this.state.error?.message}</p>
          <Button onClick={() => this.setState({ hasError: false, error: null })}>
            Try Again
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}

function InlineError({ error, onRetry, label }: { error: Error | null; onRetry: () => void; label: string }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center py-12 text-center">
      <AlertTriangle className="w-8 h-8 text-red-400 mb-3" />
      <p className="text-gray-300 mb-2">Failed to load {label}</p>
      <p className="text-gray-500 text-sm mb-4">{error?.message || 'Unknown error'}</p>
      <button
        onClick={onRetry}
        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-white text-sm"
        aria-label={`Retry loading ${label}`}
      >
        Try Again
      </button>
    </div>
  )
}

const UNIVERSE_LABELS: Record<string, string> = {
  marvel: 'Marvel', dc: 'DC', star_wars: 'Star Wars', lotr: 'LOTR',
  harry_potter: 'Harry Potter', anime: 'Anime', tv: 'TV', film: 'Film',
  gaming: 'Gaming', other: 'Other',
}

const ANGLE_LABELS: Record<string, string> = {
  hidden_truths: 'Hidden Truths', power_secrets: 'Power Secrets',
  underrated_moments: 'Underrated Moments', origin_story: 'Origin Story',
  character_evolution: 'Character Evolution', controversial_takes: 'Controversial Takes',
  vs_comparison: 'VS Comparison', behind_scenes: 'Behind the Scenes',
  fan_theories: 'Fan Theories', dark_facts: 'Dark Facts',
  actor_secrets: 'Actor Secrets', easter_eggs: 'Easter Eggs',
  crossover_connections: 'Crossover Connections', what_if: 'What If',
  timeline_deep_dive: 'Timeline Deep Dive',
  storyline_recap: 'Storyline Recap', power_ranking: 'Power Ranking',
}

const TEMPLATE_LABELS: Record<string, string> = {
  secrets_revealed: 'Secrets Revealed',
  hidden_connection: 'Hidden Connection',
  dark_origin: 'Dark Origin',
  fan_theory_deep_dive: 'Fan Theory Deep Dive',
  actor_behind_role: 'Actor Behind Role',
  versus_breakdown: 'Versus Breakdown',
  timeline_tragedy: 'Timeline Tragedy',
  what_they_changed: 'What They Changed',
  real_life_inspiration: 'Real Life Inspiration',
  deleted_scenes: 'Deleted Scenes',
  storyline_recap: 'Storyline Recap',
  power_ranking: 'Power Ranking',
  versus_battle: 'Versus Battle',
  timeline_story: 'Timeline Story',
  hot_take: 'Hot Take',
}

const HOOK_STYLE_LABELS: Record<string, string> = {
  numbered_list: 'Numbered List ("5 Things...")',
  story_opener: 'Story Opener ("When X did...")',
  hot_take: 'Hot Take (Bold claim)',
  question: 'Question ("Do you know...?")',
  comparison: 'Comparison ("A vs B")',
  reveal: 'Reveal ("X\'s secret...")',
  superlative: 'Superlative ("The most...")',
}

const MOOD_LABELS: Record<string, string> = {
  epic: 'Epic', dark: 'Dark', emotional: 'Emotional',
  mysterious: 'Mysterious', dramatic: 'Dramatic', hype: 'Hype', chill: 'Chill',
}

import { MediaContentTab } from '@/pages/MediaContentPage'

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-600', ai_reviewed: 'bg-blue-600', pending_review: 'bg-yellow-600',
  approved: 'bg-green-600', rejected: 'bg-red-600', published: 'bg-purple-600',
  pending: 'bg-gray-500', researching: 'bg-blue-500', completed: 'bg-green-500',
  failed: 'bg-red-500', active: 'bg-green-500',
}

export function CharacterContentPage() {
  const [searchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'characters'

  return (
    <CharacterContentErrorBoundary>
      <div className="space-y-4">
        <ContentProductionPausedBanner />
        {tab === 'characters' && <CharactersTab />}
        {tab === 'tv-shows' && <MediaContentTab mediaTypeFilter="tv_show" />}
        {tab === 'movies' && <MediaContentTab mediaTypeFilter="movie" />}
        {tab === 'reference-videos' && <ReferenceVideosTab />}
        {tab === 'research' && <ResearchQueueTab />}
        {tab === 'studio' && <ContentStudioTab />}
        {tab === 'review' && <ReviewQueueTab />}
        {tab === 'inspiration' && <InspirationTab />}
        {tab === 'analytics' && <AnalyticsTab />}
        {tab === 'employee-report' && <EmployeeReportTab />}
      </div>
    </CharacterContentErrorBoundary>
  )
}

function EmployeeReportTab() {
  const [windowHours, setWindowHours] = useState(12)
  const { data, isLoading, error, refetch } = useCarouselEmployeeReport(windowHours)

  if (isLoading) {
    return <div className="flex items-center justify-center py-16 text-gray-400"><Loader2 className="w-6 h-6 animate-spin mr-2" />Loading report...</div>
  }
  if (error) {
    return <InlineError error={error as Error} onRetry={() => refetch()} label="employee report" />
  }
  if (!data) return null

  const c = data.carousels || {}
  const l = data.learning || {}
  const q = data.queue || {}
  const avg = c.stage2_avg_score
  const gradeColor = avg == null ? 'text-gray-400' : avg >= 85 ? 'text-green-400' : avg >= 70 ? 'text-yellow-400' : 'text-red-400'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Zero Carousel Employee</h2>
          <p className="text-sm text-gray-400">What Zero did in the last {data.window_hours}h. Same report delivered to Discord at 8am + 8pm.</p>
        </div>
        <div className="flex items-center gap-2">
          {[6, 12, 24, 72].map(h => (
            <button
              key={h}
              onClick={() => setWindowHours(h)}
              className={`px-3 py-1 text-sm rounded-md ${windowHours === h ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
            >{h}h</button>
          ))}
          <Button variant="ghost" size="sm" onClick={() => refetch()} aria-label="Refresh report">
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-400 uppercase">Generated</p>
            <p className="text-2xl font-semibold text-white">{c.generated ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-400 uppercase">Approved</p>
            <p className="text-2xl font-semibold text-green-400">{c.approved ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-400 uppercase">Needs Work</p>
            <p className="text-2xl font-semibold text-yellow-400">{c.rejected ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-gray-400 uppercase">Stage 2 Avg</p>
            <p className={`text-2xl font-semibold ${gradeColor}`}>{avg == null ? '—' : avg.toFixed(1)}</p>
            <p className="text-xs text-gray-500 mt-1">n={c.reviewed ?? 0}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2"><TrendingUp className="w-4 h-4 text-indigo-400" />Top Variants (30d)</CardTitle>
            <CardDescription>Hook style + story template pairs ranked by Stage 2 score</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(l.top_variants || []).length === 0 && (
              <p className="text-sm text-gray-500">No Stage 2 data yet — Thompson Sampler is cold-starting via rotation.</p>
            )}
            {(l.top_variants || []).map((v, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-gray-800 rounded">
                <div>
                  <p className="text-sm text-white">{v.hook_style} + {v.story_template}</p>
                  <p className="text-xs text-gray-500">n={v.uses}</p>
                </div>
                <Badge className="bg-indigo-600">{v.avg_score.toFixed(1)}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2"><Layers className="w-4 h-4 text-blue-400" />Research Queue</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex justify-between text-sm"><span className="text-gray-400">Pending</span><span className="text-white">{q.pending ?? 0}</span></div>
            <div className="flex justify-between text-sm"><span className="text-gray-400">In progress</span><span className="text-white">{q.in_progress ?? 0}</span></div>
            <div className="flex justify-between text-sm"><span className="text-gray-400">Completed</span><span className="text-white">{q.completed ?? 0}</span></div>
            {q.error && <p className="text-xs text-red-400">{q.error}</p>}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-red-400" />Issues</CardTitle>
          </CardHeader>
          <CardContent>
            {data.issues.length === 0 ? (
              <p className="text-sm text-gray-500">No issues detected.</p>
            ) : (
              <ul className="space-y-1 text-sm text-gray-200">
                {data.issues.map((i, idx) => (<li key={idx}>• {i}</li>))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2"><Award className="w-4 h-4 text-green-400" />Wins</CardTitle>
          </CardHeader>
          <CardContent>
            {data.wins.length === 0 ? (
              <p className="text-sm text-gray-500">No standout wins yet — check back after more Stage 2 reviews complete.</p>
            ) : (
              <ul className="space-y-1 text-sm text-gray-200">
                {data.wins.map((w, idx) => (<li key={idx}>• {w}</li>))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ============================================
// CHARACTERS TAB
// ============================================

function CharactersTab() {
  const navigate = useNavigate()
  const [universeFilter, setUniverseFilter] = useState<string>('')
  const [letterFilter, setLetterFilter] = useState<string | null>(null)
  const { data: characters, isLoading, isError, error, refetch } = useCharacters(
    universeFilter && universeFilter !== 'all' ? { universe: universeFilter } : undefined
  )
  const seedMutation = useSeedCharacters()
  const researchMutation = useResearchCharacter()
  const batchResearchMutation = useBatchResearch()
  const deleteCharacterMutation = useDeleteCharacter()
  const { data: contentControl } = useContentProductionStatus()
  const productionPaused = contentControl?.paused ?? true

  const sortedCharacters = characters ? sortByName(characters, (c) => c.name) : []
  const visibleCharacters = letterFilter
    ? sortedCharacters.filter((c) => bucketOf(c.name) === letterFilter)
    : sortedCharacters

  return (
    <div className="space-y-4">
      <ContentRequestBar
        placeholder="Queue characters... (e.g., 'Doctor Doom, Avengers Doomsday cast, Dune characters')"
        context="characters"
      />
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Select value={universeFilter} onValueChange={setUniverseFilter}>
            <SelectTrigger className="w-[180px] bg-gray-800 border-gray-700" aria-label="Select universe filter">
              <SelectValue placeholder="All Universes" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Universes</SelectItem>
              {Object.entries(UNIVERSE_LABELS).map(([val, label]) => (
                <SelectItem key={val} value={val}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-sm text-gray-400" aria-live="polite">
            {visibleCharacters.length}
            {letterFilter ? ` of ${sortedCharacters.length}` : ''} characters
          </span>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => batchResearchMutation.mutate({})}
            disabled={batchResearchMutation.isPending || productionPaused}
            title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Research all characters'}
            aria-label="Research all characters"
          >
            {batchResearchMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}
            Research All
          </Button>
          <AddCharacterDialog productionPaused={productionPaused} />
          <Button
            variant="outline"
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending || productionPaused}
            title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Seed character library'}
            aria-label="Seed character library"
          >
            {seedMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
            Seed Characters
          </Button>
        </div>
      </div>

      {isError ? (
        <InlineError error={error} onRetry={() => refetch()} label="characters" />
      ) : isLoading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-8 h-8 animate-spin text-gray-400" /></div>
      ) : characters?.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Users className="w-12 h-12 text-gray-600 mb-4" />
          <p className="text-gray-300 text-lg mb-2">No characters yet</p>
          <p className="text-gray-500 text-sm">Create your first character or seed the library to get started.</p>
        </div>
      ) : (
        <>
          <AlphabetFilter
            items={sortedCharacters}
            getName={(c) => c.name}
            selected={letterFilter}
            onSelect={setLetterFilter}
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
            {visibleCharacters.map((char) => (
              <CharacterCard
                key={char.id}
                character={char}
                onResearch={(e) => { e.stopPropagation(); researchMutation.mutate(char.id) }}
                isResearching={researchMutation.isPending}
                onClick={() => navigate(`/characters/${char.id}`)}
                onDelete={(e) => {
                  e.stopPropagation()
                  if (window.confirm(`Delete "${char.name}" and all associated content? This cannot be undone.`)) {
                    deleteCharacterMutation.mutate(char.id)
                  }
                }}
                isDeleting={deleteCharacterMutation.isPending && deleteCharacterMutation.variables === char.id}
                productionPaused={productionPaused}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function CharacterCard({ character, onResearch, isResearching, onClick, onDelete, isDeleting, productionPaused }: {
  character: Character
  onResearch: (e: React.MouseEvent) => void
  isResearching: boolean
  onClick: () => void
  onDelete: (e: React.MouseEvent) => void
  isDeleting: boolean
  productionPaused: boolean
}) {
  const factCount = character.fact_bank?.length || 0

  return (
    <Card className="bg-gray-800/50 border-gray-700 hover:border-indigo-500/50 transition-colors cursor-pointer" onClick={onClick} aria-label={`View ${character.name} details`}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base text-white leading-tight line-clamp-2 break-words" title={character.name}>
              {character.name}
            </CardTitle>
            <CardDescription className="text-gray-400 text-xs truncate mt-1" title={character.franchise || UNIVERSE_LABELS[character.universe] || character.universe}>
              {character.real_name && `${character.real_name} · `}
              {character.franchise || UNIVERSE_LABELS[character.universe] || character.universe}
            </CardDescription>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <Badge className={`${STATUS_COLORS[character.universe] || 'bg-gray-600'} text-white text-[10px] whitespace-nowrap`} aria-label={`Universe: ${UNIVERSE_LABELS[character.universe] || character.universe}`}>
              {UNIVERSE_LABELS[character.universe] || character.universe}
            </Badge>
            <Button
              size="icon"
              variant="ghost"
              onClick={onDelete}
              disabled={isDeleting}
              aria-label={`Delete ${character.name}`}
              title="Delete character"
              className="h-7 w-7 text-red-400 hover:bg-red-500/10 hover:text-red-300"
            >
              {isDeleting
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <Trash2 className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>
        <div className="flex items-center gap-1.5 mt-2 flex-wrap">
          {(!character.image_urls || character.image_urls.length === 0) && (
            <Badge className="bg-rose-600/80 text-white text-[10px]" aria-label="No images sourced">
              no images
            </Badge>
          )}
          {character.status === 'pending' && (
            <Badge className="bg-amber-500/80 text-white text-[10px]" title="Auto-imported from TMDB cast — review needed">
              auto-imported
            </Badge>
          )}
          {(() => {
            const first = character.appears_in?.[0] as { _count?: number } | undefined
            const count = first?._count ?? character.appears_in?.length ?? 0
            return count > 0 ? (
              <Badge className="bg-cyan-600/80 text-white text-[10px] flex items-center gap-1" title="Cast linkage from TMDB">
                <Film className="w-2.5 h-2.5" />appears in {count}
              </Badge>
            ) : null
          })()}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {character.image_url && (
          <div className="w-full h-32 rounded-md overflow-hidden bg-gray-900">
            <img src={character.image_url} alt={`${character.name} character image`} className="w-full h-full object-cover" />
          </div>
        )}

        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="flex flex-col items-center gap-0.5 rounded-md bg-gray-900/60 py-2">
            <Brain className="w-4 h-4 text-indigo-400" />
            <span className="text-white font-semibold">{factCount}</span>
            <span className="text-gray-500">facts</span>
          </div>
          <div className="flex flex-col items-center gap-0.5 rounded-md bg-gray-900/60 py-2">
            <Sparkles className="w-4 h-4 text-amber-400" />
            <span className="text-white font-semibold">{character.posts_created ?? 0}</span>
            <span className="text-gray-500">posts</span>
          </div>
          <div className="flex flex-col items-center gap-0.5 rounded-md bg-gray-900/60 py-2">
            <Layers className="w-4 h-4 text-emerald-400" />
            <span className="text-white font-semibold">{character.carousels_created ?? 0}</span>
            <span className="text-gray-500">carousels</span>
          </div>
        </div>

        {character.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {character.tags.slice(0, 4).map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs border-gray-600 text-gray-400">
                #{tag}
              </Badge>
            ))}
          </div>
        )}

        <Button
          size="sm"
          className="w-full"
          variant={character.research_status === 'completed' ? 'outline' : 'default'}
          onClick={onResearch}
          disabled={isResearching || character.research_status === 'researching' || productionPaused}
          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : undefined}
          aria-label={character.research_status === 'researching' ? `Researching ${character.name}` : character.research_status === 'completed' ? `Re-research ${character.name}` : `Research ${character.name}`}
        >
          {character.research_status === 'researching' ? (
            <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Researching...</>
          ) : character.research_status === 'completed' ? (
            <><RefreshCw className="w-4 h-4 mr-2" />Re-Research</>
          ) : (
            <><Search className="w-4 h-4 mr-2" />Research Character</>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

function AddCharacterDialog({ productionPaused = false }: { productionPaused?: boolean }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [universe, setUniverse] = useState<CharacterUniverse>('marvel')
  const [franchise, setFranchise] = useState('')
  const [realName, setRealName] = useState('')
  const createMutation = useCreateCharacter()

  const handleSubmit = () => {
    createMutation.mutate(
      { name, universe, franchise: franchise || undefined, real_name: realName || undefined },
      { onSuccess: () => { setOpen(false); setName(''); setFranchise(''); setRealName('') } }
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          aria-label="Add new character"
          disabled={productionPaused}
          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Add new character'}
        >
          <Plus className="w-4 h-4 mr-2" />Add Character
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-gray-800 border-gray-700" aria-label="Add character dialog">
        <DialogHeader>
          <DialogTitle className="text-white">Add Character</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <Input placeholder="Character name" value={name} onChange={(e) => setName(e.target.value)} className="bg-gray-900 border-gray-700" aria-label="Character name" />
          <Select value={universe} onValueChange={(v) => setUniverse(v as CharacterUniverse)}>
            <SelectTrigger className="bg-gray-900 border-gray-700" aria-label="Select universe"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(UNIVERSE_LABELS).map(([val, label]) => (
                <SelectItem key={val} value={val}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input placeholder="Franchise (e.g., Avengers)" value={franchise} onChange={(e) => setFranchise(e.target.value)} className="bg-gray-900 border-gray-700" aria-label="Franchise name" />
          <Input placeholder="Real name (e.g., Tony Stark)" value={realName} onChange={(e) => setRealName(e.target.value)} className="bg-gray-900 border-gray-700" aria-label="Real name" />
          <Button
            onClick={handleSubmit}
            disabled={!name || createMutation.isPending || productionPaused}
            className="w-full"
            aria-label="Create character"
          >
            {createMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
            Create Character
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// ============================================
// RESEARCH QUEUE TAB
// ============================================

const STEP_LABELS: Record<string, string> = {
  searxng_search: 'Web Search',
  wiki_scrape: 'Wikipedia',
  deep_research: 'Deep Sources',
  synthesis: 'AI Synthesis',
  fact_extraction: 'Fact Mining',
  image_sourcing: 'Image Search',
  save_results: 'Saving',
}

const STEP_ORDER = ['searxng_search', 'wiki_scrape', 'deep_research', 'synthesis', 'fact_extraction', 'image_sourcing', 'save_results']

function ResearchQueueTab() {
  const [pollingEnabled, setPollingEnabled] = useState(true)
  const { data: queue, isLoading, isError, error, refetch } = useResearchQueue(pollingEnabled)
  const startMutation = useStartResearchQueue()
  const cancelMutation = useCancelResearchQueue()
  const [filterUniverse, setFilterUniverse] = useState<string>('')
  const [limit, setLimit] = useState<number>(0)
  const navigate = useNavigate()
  const { data: contentControl } = useContentProductionStatus()
  const productionPaused = contentControl?.paused ?? true

  const isRunning = (queue?.queued ?? 0) > 0 || (queue?.researching ?? 0) > 0

  // Keep polling active when queue is running
  useEffect(() => {
    if (isRunning && !pollingEnabled) {
      setPollingEnabled(true)
    }
  }, [isRunning, pollingEnabled])

  const handleStart = () => {
    const params: { universe?: string; limit?: number } = {}
    if (productionPaused) return
    if (filterUniverse && filterUniverse !== 'all') params.universe = filterUniverse
    if (limit > 0) params.limit = limit
    startMutation.mutate(params)
    setPollingEnabled(true)
  }

  const completedCount = queue?.completed ?? 0
  const totalCount = queue?.total_jobs ?? 0
  const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

  const queuedJobs = (queue?.jobs ?? []).filter(j => j.status === 'queued')
  const inProgressJobs = (queue?.jobs ?? []).filter(j => j.status === 'researching')
  const completedJobs = (queue?.jobs ?? []).filter(j => j.status === 'completed')
  const failedJobs = (queue?.jobs ?? []).filter(j => j.status === 'failed')

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Research Queue</h2>
        <div className="flex items-center gap-2">
          <Select value={filterUniverse} onValueChange={setFilterUniverse}>
            <SelectTrigger className="w-[150px] bg-gray-800 border-gray-700 h-9 text-sm" aria-label="Filter research by universe">
              <SelectValue placeholder="All Universes" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Universes</SelectItem>
              {Object.entries(UNIVERSE_LABELS).map(([val, label]) => (
                <SelectItem key={val} value={val}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={String(limit)} onValueChange={(v) => setLimit(Number(v))}>
            <SelectTrigger className="w-[100px] bg-gray-800 border-gray-700 h-9 text-sm" aria-label="Limit number of research jobs">
              <SelectValue placeholder="All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">All</SelectItem>
              <SelectItem value="5">5</SelectItem>
              <SelectItem value="10">10</SelectItem>
              <SelectItem value="24">24</SelectItem>
            </SelectContent>
          </Select>
          <Button
            className="bg-green-600 hover:bg-green-700 h-9"
            onClick={handleStart}
            disabled={startMutation.isPending || isRunning || productionPaused}
            title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Start research queue'}
            aria-label="Start research queue"
          >
            {startMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Play className="w-4 h-4 mr-2" />
            )}
            Start Research
          </Button>
          {isRunning && (
            <Button
              variant="destructive"
              className="h-9"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              aria-label="Cancel research queue"
            >
              {cancelMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Square className="w-4 h-4 mr-2" />
              )}
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* Progress Overview (when running) */}
      {queue && totalCount > 0 && isRunning && (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardContent className="pt-4 pb-4" aria-live="polite">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">
                  Overall Progress: {completedCount} / {totalCount} characters
                </span>
                <span className="text-white font-medium">{progressPct}%</span>
              </div>
              <div className="w-full h-3 bg-gray-700 rounded-full overflow-hidden" role="progressbar" aria-valuenow={progressPct} aria-valuemin={0} aria-valuemax={100} aria-label="Research queue progress">
                <div
                  className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-xs text-gray-500">
                {(queue.researching ?? 0) > 0 && (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="w-3 h-3 animate-spin text-indigo-400" />
                    <span className="text-indigo-300">
                      {queue.researching > 1
                        ? `${queue.researching} characters in parallel`
                        : queue.current_character || '1 in progress'}
                    </span>
                    {queue.researching === 1 && queue.current_step && (
                      <span className="text-gray-500"> - {STEP_LABELS[queue.current_step] || queue.current_step}</span>
                    )}
                  </span>
                )}
                {queue.estimated_completion && (
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    ETA: {new Date(queue.estimated_completion).toLocaleTimeString()}
                  </span>
                )}
                {queue.started_at && (
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    Started: {new Date(queue.started_at).toLocaleTimeString()}
                  </span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabbed Job Lists */}
      {isError ? (
        <InlineError error={error} onRetry={() => refetch()} label="research queue" />
      ) : isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      ) : !queue || queue.jobs.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <Search className="w-12 h-12 mx-auto mb-4 opacity-30" />
          <p className="text-lg">No research jobs in queue</p>
          <p className="text-sm mt-1">Click &quot;Start Research&quot; to begin researching all characters</p>
        </div>
      ) : (
        <Tabs defaultValue="all" className="w-full">
          <TabsList className="bg-gray-800 border border-gray-700 mb-2">
            <TabsTrigger value="all" className="data-[state=active]:bg-gray-700">
              All <span className="ml-1.5 text-xs text-gray-400">({totalCount})</span>
            </TabsTrigger>
            <TabsTrigger value="queued" className="data-[state=active]:bg-gray-700">
              Queued <span className="ml-1.5 text-xs text-gray-400">({queuedJobs.length})</span>
            </TabsTrigger>
            <TabsTrigger value="in_progress" className="data-[state=active]:bg-gray-700">
              In Progress <span className="ml-1.5 text-xs text-indigo-400">({inProgressJobs.length})</span>
            </TabsTrigger>
            <TabsTrigger value="completed" className="data-[state=active]:bg-gray-700">
              Completed <span className="ml-1.5 text-xs text-green-400">({completedJobs.length})</span>
            </TabsTrigger>
            {failedJobs.length > 0 && (
              <TabsTrigger value="failed" className="data-[state=active]:bg-gray-700">
                Failed <span className="ml-1.5 text-xs text-red-400">({failedJobs.length})</span>
              </TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="all" className="space-y-2">
            {queue.jobs.map((job) => (
              <ResearchJobCard key={job.id} job={job} productionPaused={productionPaused} onSelect={() => navigate(`/characters/${job.character_id}`)} />
            ))}
          </TabsContent>

          <TabsContent value="queued" className="space-y-2">
            {queuedJobs.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <Clock className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No queued jobs</p>
              </div>
            ) : (
              queuedJobs.map((job) => (
                <ResearchJobCard key={job.id} job={job} productionPaused={productionPaused} onSelect={() => navigate(`/characters/${job.character_id}`)} />
              ))
            )}
          </TabsContent>

          <TabsContent value="in_progress" className="space-y-2">
            {inProgressJobs.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <Loader2 className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No jobs in progress</p>
              </div>
            ) : (
              inProgressJobs.map((job) => (
                <ResearchJobCard key={job.id} job={job} productionPaused={productionPaused} onSelect={() => navigate(`/characters/${job.character_id}`)} />
              ))
            )}
          </TabsContent>

          <TabsContent value="completed" className="space-y-2">
            {completedJobs.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <CheckCircle className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No completed jobs yet</p>
              </div>
            ) : (
              completedJobs.map((job) => (
                <ResearchJobCard key={job.id} job={job} productionPaused={productionPaused} onSelect={() => navigate(`/characters/${job.character_id}`)} />
              ))
            )}
          </TabsContent>

          {failedJobs.length > 0 && (
            <TabsContent value="failed" className="space-y-2">
              {failedJobs.map((job) => (
                <ResearchJobCard key={job.id} job={job} productionPaused={productionPaused} onSelect={() => navigate(`/characters/${job.character_id}`)} />
              ))}
            </TabsContent>
          )}
        </Tabs>
      )}

    </div>
  )
}


function useLiveTimer(active: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [active])
}

function ResearchJobCard({ job, productionPaused }: {
  job: ResearchJob
  productionPaused: boolean
  onSelect: () => void
}) {
  const navigate = useNavigate()
  const isActive = job.status === 'researching'
  const isFailed = job.status === 'failed'
  const [expanded, setExpanded] = useState(false)
  const retryMutation = useRetryResearch()
  useLiveTimer(isActive)

  const elapsed = job.started_at ? getElapsedTime(job.started_at, job.completed_at) : null

  // Stuck detection: any running step > 2 minutes
  const runningStep = job.steps?.find(s => s.status === 'running')
  const stepElapsedSec = runningStep?.started_at
    ? Math.floor((Date.now() - new Date(runningStep.started_at).getTime()) / 1000)
    : 0
  const isStuck = !!(runningStep && stepElapsedSec > 120)

  const showRetry = isFailed || isStuck

  return (
    <Card className={`bg-gray-800/50 border-gray-700 transition-all ${
      isStuck ? 'border-amber-500/50 ring-1 ring-amber-500/20' :
      isActive ? 'border-indigo-500/50 ring-1 ring-indigo-500/20' : ''
    }`} aria-label={`Research job for ${job.character_name}, status: ${isStuck ? 'possibly stuck' : job.status}`}>
      <CardContent className="py-2.5">
        {/* Clickable header */}
        <div
          className="flex items-start gap-3 cursor-pointer select-none"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-label={`Toggle details for ${job.character_name}`}
        >
          {/* Status indicator */}
          <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
            job.status === 'queued' ? 'bg-gray-700' :
            isStuck ? 'bg-amber-600 animate-pulse' :
            job.status === 'researching' ? 'bg-indigo-600 animate-pulse' :
            job.status === 'completed' ? 'bg-green-600' :
            'bg-red-600'
          }`}>
            {job.status === 'queued' && <Clock className="w-4 h-4 text-gray-400" />}
            {job.status === 'researching' && <Loader2 className="w-4 h-4 text-white animate-spin" />}
            {job.status === 'completed' && <CheckCircle className="w-4 h-4 text-white" />}
            {job.status === 'failed' && <XCircle className="w-4 h-4 text-white" />}
          </div>

          {/* Main content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5 flex-wrap">
              <button
                className="text-white font-medium hover:text-indigo-400 hover:underline transition-colors"
                onClick={(e) => { e.stopPropagation(); navigate(`/characters/${job.character_id}`) }}
                title="View character details"
              >
                {job.character_name}
              </button>
              <Badge className={`${STATUS_COLORS[job.universe] || 'bg-gray-600'} text-white text-xs`}>
                {UNIVERSE_LABELS[job.universe] || job.universe}
              </Badge>
              <Badge className={`text-white text-xs ${
                isStuck ? 'bg-amber-500' :
                job.status === 'queued' ? 'bg-gray-500' :
                job.status === 'researching' ? 'bg-indigo-500' :
                job.status === 'completed' ? 'bg-green-500' :
                'bg-red-500'
              }`}>
                {isStuck ? 'possibly stuck' : job.status}
              </Badge>

              {/* Live timer badge */}
              {elapsed && (
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex items-center gap-1 ${
                  isStuck ? 'bg-amber-900/50 text-amber-300 border border-amber-500/30' :
                  isActive ? 'bg-indigo-900/50 text-indigo-300 border border-indigo-500/30' :
                  job.status === 'completed' ? 'bg-green-900/50 text-green-300 border border-green-500/30' :
                  isFailed ? 'bg-red-900/50 text-red-300 border border-red-500/30' :
                  'bg-gray-700 text-gray-400'
                }`}>
                  <Timer className="w-3 h-3" />
                  {elapsed}
                </span>
              )}

              {/* ETA badge for queued + running jobs with range estimate */}
              {(job.status === 'queued' || job.status === 'researching') && typeof job.eta_seconds === 'number' && job.eta_seconds > 0 && (
                <span
                  className="text-xs font-medium px-2 py-0.5 rounded-full flex items-center gap-1 bg-gray-800 text-gray-300 border border-gray-600"
                  title="Estimated time range: optimistic to pessimistic based on historical data"
                >
                  ETA {formatSeconds(Math.round(job.eta_seconds * 0.6))}-{formatSeconds(Math.round(job.eta_seconds * 1.5))}
                </span>
              )}

              {isStuck && (
                <span className="flex items-center gap-1 text-xs text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Stuck on {STEP_LABELS[runningStep!.name] || runningStep!.name}
                </span>
              )}
            </div>

            {/* Compact step dots (always visible) */}
            {(job.status === 'researching' || job.status === 'completed' || job.status === 'failed') && job.steps?.length > 0 && (
              <ResearchStepStepper steps={job.steps} compact={!expanded} isStuck={isStuck} />
            )}

            {/* Completed stats */}
            {job.status === 'completed' && !expanded && (
              <div className="flex items-center gap-3 mt-1 text-xs">
                <span className="flex items-center gap-1 text-green-400">
                  <Brain className="w-3.5 h-3.5" />
                  {job.facts_found} facts
                </span>
                <span className="flex items-center gap-1 text-blue-400">
                  <ImageIcon className="w-3.5 h-3.5" />
                  {job.images_found} images
                </span>
                <span className="flex items-center gap-1 text-indigo-400">
                  <BookOpen className="w-3.5 h-3.5" />
                  {job.sources_used?.length || 0} sources
                </span>
                <span className="flex items-center gap-1 text-yellow-400">
                  <TrendingUp className="w-3.5 h-3.5" />
                  Depth: {job.depth_score}/10
                </span>
              </div>
            )}
          </div>

          {/* Expand chevron + retry + view details */}
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs border-gray-600 hover:bg-gray-700"
              onClick={(e) => { e.stopPropagation(); navigate(`/characters/${job.character_id}`) }}
              aria-label={`View full details for ${job.character_name}`}
            >
              <Eye className="w-3 h-3 mr-1" />
              Details
            </Button>
            {showRetry && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs border-gray-600 hover:bg-gray-700"
                onClick={(e) => { e.stopPropagation(); retryMutation.mutate(job.character_id) }}
                disabled={retryMutation.isPending || productionPaused}
                title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Retry research'}
                aria-label={`Retry research for ${job.character_name}`}
              >
                {retryMutation.isPending ? (
                  <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                ) : (
                  <RotateCcw className="w-3 h-3 mr-1" />
                )}
                Retry
              </Button>
            )}
            {expanded ? (
              <ChevronUp className="w-5 h-5 text-gray-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-gray-400" />
            )}
          </div>
        </div>

        {/* Expanded detail panel */}
        {expanded && (
          <div className="mt-3 pt-3 border-t border-gray-700 space-y-2">
            {/* Step timeline table */}
            <div className="bg-gray-900/50 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-gray-700">
                    <th className="text-left px-2.5 py-1.5 font-medium">Step</th>
                    <th className="text-left px-2.5 py-1.5 font-medium">Status</th>
                    <th className="text-left px-2.5 py-1.5 font-medium">Duration</th>
                    <th className="text-left px-2.5 py-1.5 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {(job.steps || []).map((step) => {
                    const stepDuration = step.started_at
                      ? getElapsedTime(step.started_at, step.completed_at)
                      : typeof step.avg_duration_ms === 'number' && step.avg_duration_ms > 0
                      ? `~${formatSeconds(Math.round(step.avg_duration_ms / 1000))} (avg)`
                      : '-'
                    const stepSec = step.started_at && step.status === 'running'
                      ? Math.floor((Date.now() - new Date(step.started_at).getTime()) / 1000)
                      : 0
                    const stepStuck = step.status === 'running' && stepSec > 120

                    return (
                      <tr key={step.name} className="border-b border-gray-800 last:border-0 hover:bg-gray-800/50">
                        <td className="px-2.5 py-1 text-gray-300">{STEP_LABELS[step.name] || step.name}</td>
                        <td className="px-2.5 py-1">
                          {step.status === 'completed' && <span className="text-green-400">done</span>}
                          {step.status === 'running' && (
                            <span className={stepStuck ? 'text-amber-400' : 'text-indigo-400'}>
                              {stepStuck ? 'stuck?' : 'running'}
                            </span>
                          )}
                          {step.status === 'failed' && <span className="text-red-400">failed</span>}
                          {step.status === 'pending' && <span className="text-gray-600">pending</span>}
                        </td>
                        <td className="px-2.5 py-1 text-gray-400 font-mono text-xs">{stepDuration}</td>
                        <td className="px-2.5 py-1 text-gray-400 text-xs truncate max-w-[200px]">
                          {step.result_summary || (step.error ? <span className="text-red-400">{step.error}</span> : '-')}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Completed stats in expanded view */}
            {job.status === 'completed' && (
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1 text-green-400">
                  <Brain className="w-3.5 h-3.5" />
                  {job.facts_found} facts
                </span>
                <span className="flex items-center gap-1 text-blue-400">
                  <ImageIcon className="w-3.5 h-3.5" />
                  {job.images_found} images
                </span>
                <span className="flex items-center gap-1 text-indigo-400">
                  <BookOpen className="w-3.5 h-3.5" />
                  {job.sources_used?.length || 0} sources
                </span>
                <span className="flex items-center gap-1 text-yellow-400">
                  <TrendingUp className="w-3.5 h-3.5" />
                  Depth: {job.depth_score}/10
                </span>
              </div>
            )}

            {/* Sources list */}
            {job.sources_used && job.sources_used.length > 0 && (
              <div className="text-xs text-gray-500">
                Sources: {job.sources_used.join(', ')}
              </div>
            )}

            {/* Error in expanded view */}
            {isFailed && job.error && (
              <div className="flex items-start gap-2 bg-red-900/20 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-300">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span className="break-all">{job.error}</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ResearchStepStepper({ steps, compact = false, isStuck: _isStuck = false }: { steps: ResearchJobStep[]; compact?: boolean; isStuck?: boolean }) {
  const [selectedStep, setSelectedStep] = useState<ResearchJobStep | null>(null)

  // Sort steps to match canonical order, then append any extras
  const orderedSteps: ResearchJobStep[] = []
  const stepsByName = new Map(steps.map(s => [s.name, s]))

  for (const stepName of STEP_ORDER) {
    const step = stepsByName.get(stepName)
    if (step) {
      orderedSteps.push(step)
      stepsByName.delete(stepName)
    }
  }
  for (const step of stepsByName.values()) {
    orderedSteps.push(step)
  }

  return (
    <>
      <div className="flex items-center gap-0.5 mt-1">
        {orderedSteps.map((step, i) => {
          const isLast = i === orderedSteps.length - 1
          const stepSec = step.started_at && step.status === 'running'
            ? Math.floor((Date.now() - new Date(step.started_at).getTime()) / 1000)
            : 0
          const stepStuck = step.status === 'running' && stepSec > 120

          const color =
            step.status === 'completed' ? 'bg-green-500' :
            stepStuck ? 'bg-amber-500 animate-pulse' :
            step.status === 'running' ? 'bg-indigo-500 animate-pulse' :
            step.status === 'failed' ? 'bg-red-500' :
            'bg-gray-600'
          const textColor =
            step.status === 'completed' ? 'text-green-400' :
            stepStuck ? 'text-amber-300' :
            step.status === 'running' ? 'text-indigo-300' :
            step.status === 'failed' ? 'text-red-400' :
            'text-gray-500'
          const duration = step.started_at && step.completed_at
            ? getElapsedTime(step.started_at, step.completed_at)
            : step.started_at && step.status === 'running'
            ? getElapsedTime(step.started_at, null)
            : null

          return (
            <div key={step.name} className="flex items-center">
              <button
                className="flex flex-col items-center cursor-pointer hover:opacity-80 transition-opacity"
                onClick={(e) => { e.stopPropagation(); step.status !== 'pending' && setSelectedStep(step) }}
                title={`${STEP_LABELS[step.name] || step.name}: ${step.status}${step.result_summary ? ` - ${step.result_summary}` : ''}${duration ? ` (${duration})` : ''}`}
              >
                <div className={`w-5 h-5 rounded-full ${color} flex items-center justify-center`}>
                  {step.status === 'completed' && <CheckCircle className="w-3 h-3 text-white" />}
                  {step.status === 'running' && <Loader2 className="w-3 h-3 text-white animate-spin" />}
                  {step.status === 'failed' && <XCircle className="w-3 h-3 text-white" />}
                </div>
                {!compact && (
                  <>
                    <span className={`text-[10px] mt-0.5 whitespace-nowrap ${textColor}`}>
                      {STEP_LABELS[step.name] || step.name}
                    </span>
                    {duration && (
                      <span className="text-[9px] text-gray-500">{duration}</span>
                    )}
                    {!duration && typeof step.avg_duration_ms === 'number' && step.avg_duration_ms > 0 && (
                      <span className="text-[9px] text-gray-600" title="Historical average duration for this step">
                        avg {formatSeconds(Math.round(step.avg_duration_ms / 1000))}
                      </span>
                    )}
                  </>
                )}
              </button>
              {!isLast && (
                <div className={`w-4 h-0.5 ${compact ? '' : 'mb-4'} ${
                  step.status === 'completed' ? 'bg-green-500/50' : 'bg-gray-600'
                }`} />
              )}
            </div>
          )
        })}
      </div>

      {/* Step Details Modal */}
      <Dialog open={!!selectedStep} onOpenChange={() => setSelectedStep(null)}>
        <DialogContent className="bg-gray-800 border-gray-700 max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              {selectedStep && (
                <>
                  <div className={`w-3 h-3 rounded-full ${
                    selectedStep.status === 'completed' ? 'bg-green-500' :
                    selectedStep.status === 'running' ? 'bg-indigo-500' :
                    selectedStep.status === 'failed' ? 'bg-red-500' : 'bg-gray-500'
                  }`} />
                  {STEP_LABELS[selectedStep.name] || selectedStep.name}
                </>
              )}
            </DialogTitle>
          </DialogHeader>
          {selectedStep && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-900 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">Status</div>
                  <Badge className={`${
                    selectedStep.status === 'completed' ? 'bg-green-600' :
                    selectedStep.status === 'running' ? 'bg-indigo-600' :
                    selectedStep.status === 'failed' ? 'bg-red-600' : 'bg-gray-600'
                  } text-white`}>{selectedStep.status}</Badge>
                </div>
                <div className="bg-gray-900 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">Duration</div>
                  <div className="text-white font-medium">
                    {selectedStep.started_at && selectedStep.completed_at
                      ? getElapsedTime(selectedStep.started_at, selectedStep.completed_at)
                      : selectedStep.started_at && selectedStep.status === 'running'
                      ? getElapsedTime(selectedStep.started_at, null) + ' (running)'
                      : '-'}
                  </div>
                  {typeof selectedStep.avg_duration_ms === 'number' && selectedStep.avg_duration_ms > 0 && (
                    <div className="text-[10px] text-gray-500 mt-1">
                      avg {formatSeconds(Math.round(selectedStep.avg_duration_ms / 1000))}
                    </div>
                  )}
                </div>
              </div>
              {selectedStep.started_at && (
                <div className="bg-gray-900 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">Timing</div>
                  <div className="text-sm text-gray-300">
                    Started: {new Date(selectedStep.started_at).toLocaleTimeString()}
                    {selectedStep.completed_at && (
                      <> | Completed: {new Date(selectedStep.completed_at).toLocaleTimeString()}</>
                    )}
                  </div>
                </div>
              )}
              {selectedStep.result_summary && (
                <div className="bg-gray-900 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">Result</div>
                  <div className="text-sm text-green-300">{selectedStep.result_summary}</div>
                </div>
              )}
              {selectedStep.error && (
                <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-3">
                  <div className="text-xs text-red-400 mb-1">Error</div>
                  <div className="text-sm text-red-300 font-mono break-all">{selectedStep.error}</div>
                </div>
              )}
              {selectedStep.links_found && selectedStep.links_found.length > 0 && (
                <div className="bg-gray-900 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-2 flex items-center gap-1">
                    <Link className="w-3 h-3" />
                    {selectedStep.links_found.length} links found
                  </div>
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {selectedStep.links_found.map((link, li) => (
                      <a
                        key={li}
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 group"
                        title={link.url}
                      >
                        <ExternalLink className="w-3 h-3 shrink-0 opacity-50 group-hover:opacity-100" />
                        <span className="truncate">{link.title || link.url.replace(/^https?:\/\//, '').split('/')[0]}</span>
                        {link.source && link.source !== 'searxng' && (
                          <span className="text-gray-600 shrink-0">({link.source})</span>
                        )}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

function getElapsedTime(startedAt: string, completedAt: string | null): string {
  const start = new Date(startedAt).getTime()
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const seconds = Math.floor((end - start) / 1000)

  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${remainingMinutes}m`
}

function formatSeconds(totalSec: number): string {
  if (totalSec < 60) return `${totalSec}s`
  const minutes = Math.floor(totalSec / 60)
  const remainingSeconds = totalSec % 60
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${remainingMinutes}m`
}

// ============================================
// CONTENT STUDIO TAB
// ============================================

function ContentStudioTab() {
  const { data: characters } = useCharacters({ research_status: 'completed' })
  const { data: templates } = useTemplates()
  const [selectedCharId, setSelectedCharId] = useState('')
  const [selectedAngle, setSelectedAngle] = useState<ContentAngle>('hidden_truths')
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [selectedHookStyle, setSelectedHookStyle] = useState('')
  const [slideCount, setSlideCount] = useState(6)
  const { data: carousels, isLoading: loadingCarousels, isError: carouselError, error: carouselErrorObj, refetch: refetchCarousels } = useCarousels(
    selectedCharId ? { character_id: selectedCharId } : undefined
  )
  const generateMutation = useGenerateCarousel()
  const aiReviewMutation = useAiReviewCarousel()
  const seriesMutation = useGenerateSeries()
  const smartBatchMutation = useSmartBatchGenerate()
  const seedTemplatesMutation = useSeedTemplates()
  const seedMusicMutation = useSeedMusic()
  const { data: contentControl } = useContentProductionStatus()
  const productionPaused = contentControl?.paused ?? true

  return (
    <div className="space-y-3">
      <Card className="bg-gray-800/50 border-gray-700">
        <CardHeader>
          <CardTitle className="text-white">Generate Carousel</CardTitle>
          <CardDescription>Pick a researched character, template, and angle to create a viral carousel</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="space-y-2">
              <label className="text-sm text-gray-400" id="studio-char-label">Character</label>
              <Select value={selectedCharId} onValueChange={setSelectedCharId}>
                <SelectTrigger className="bg-gray-900 border-gray-700" aria-label="Select character for carousel">
                  <SelectValue placeholder="Select character..." />
                </SelectTrigger>
                <SelectContent>
                  {characters?.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name} ({c.fact_bank?.length || 0} facts)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-gray-400" id="studio-angle-label">Angle</label>
              <Select value={selectedAngle} onValueChange={(v) => setSelectedAngle(v as ContentAngle)}>
                <SelectTrigger className="bg-gray-900 border-gray-700" aria-label="Select content angle"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ANGLE_LABELS).map(([val, label]) => (
                    <SelectItem key={val} value={val}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-gray-400" id="studio-template-label">Story Template</label>
              <Select value={selectedTemplate} onValueChange={setSelectedTemplate}>
                <SelectTrigger className="bg-gray-900 border-gray-700" aria-label="Select story template">
                  <SelectValue placeholder="Auto-select" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto-select best</SelectItem>
                  {templates?.map((t) => (
                    <SelectItem key={t.template_type} value={t.template_type}>
                      {TEMPLATE_LABELS[t.template_type] || t.name} (used {t.times_used}x)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-gray-400" id="studio-slides-label">Slides</label>
              <Select value={String(slideCount)} onValueChange={(v) => setSlideCount(Number(v))}>
                <SelectTrigger className="bg-gray-900 border-gray-700" aria-label="Select number of slides"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[5, 6, 7, 8].map((n) => (
                    <SelectItem key={n} value={String(n)}>{n} slides</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-gray-400" id="studio-hook-label">Hook Style</label>
              <Select value={selectedHookStyle} onValueChange={setSelectedHookStyle}>
                <SelectTrigger className="bg-gray-900 border-gray-700" aria-label="Select hook style">
                  <SelectValue placeholder="Auto-rotate" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto-rotate</SelectItem>
                  {Object.entries(HOOK_STYLE_LABELS).map(([val, label]) => (
                    <SelectItem key={val} value={val}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <Button
              onClick={() => generateMutation.mutate({
                character_id: selectedCharId,
                angle: selectedAngle,
                story_template: selectedTemplate === 'auto' ? undefined : selectedTemplate,
                slide_count: slideCount,
                hook_style: selectedHookStyle === 'auto' || !selectedHookStyle ? undefined : selectedHookStyle,
              })}
              disabled={!selectedCharId || generateMutation.isPending || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Generate carousel'}
              aria-label="Generate single carousel"
            >
              {generateMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}
              Generate
            </Button>
            <Button
              variant="outline"
              onClick={() => seriesMutation.mutate({
                character_id: selectedCharId,
                story_template: selectedTemplate === 'auto' ? undefined : selectedTemplate,
                angle: selectedAngle,
                parts: 3,
              })}
              disabled={!selectedCharId || seriesMutation.isPending || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Generate carousel series'}
              aria-label="Generate 3-part carousel series"
            >
              {seriesMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Layers className="w-4 h-4 mr-2" />}
              Generate Series (3 parts)
            </Button>
            <Button
              variant="outline"
              onClick={() => smartBatchMutation.mutate({ count: 12 })}
              disabled={smartBatchMutation.isPending || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Smart batch generate carousels'}
              aria-label="Smart batch generate 12 carousels"
            >
              {smartBatchMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
              Smart Batch (12)
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => seedTemplatesMutation.mutate()}
              disabled={seedTemplatesMutation.isPending || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Seed story templates'}
              aria-label="Seed story templates"
            >
              Seed Templates
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => seedMusicMutation.mutate()}
              disabled={seedMusicMutation.isPending || productionPaused}
              title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Seed music library'}
              aria-label="Seed music library"
            >
              Seed Music
            </Button>
          </div>

          {smartBatchMutation.data && (
            <div className="bg-green-900/20 border border-green-500/30 rounded-lg p-3 text-sm">
              <span className="text-green-400 font-medium">Batch complete:</span>{' '}
              {smartBatchMutation.data.generated} generated, {smartBatchMutation.data.top_scored?.length || 0} top-scored
            </div>
          )}
        </CardContent>
      </Card>

      {carouselError ? (
        <InlineError error={carouselErrorObj} onRetry={() => refetchCarousels()} label="carousels" />
      ) : loadingCarousels ? (
        <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
      ) : (
        <div className="space-y-2">
          {carousels?.map((carousel) => (
            <CarouselCard
              key={carousel.id}
              carousel={carousel}
              onAiReview={() => aiReviewMutation.mutate(carousel.id)}
              isReviewing={aiReviewMutation.isPending}
            />
          ))}
          {carousels?.length === 0 && selectedCharId && (
            <div className="text-center py-12 text-gray-500">No carousels yet. Select a character and generate one.</div>
          )}
        </div>
      )}
    </div>
  )
}

function AIReviewScores({ review }: { review: AIReview }) {
  const scores = [
    { label: 'Hook', value: review.hook_strength as number },
    { label: 'Facts', value: review.fact_quality as number },
    { label: 'Engagement', value: review.engagement_potential as number },
    { label: 'Caption', value: review.caption_quality as number },
    { label: 'Overall', value: review.overall_score as number },
  ]

  return (
    <div className="bg-gray-900/50 rounded-lg p-3 space-y-2">
      <div className="text-xs text-gray-400 font-medium">AI Review</div>
      <div className="flex items-center gap-4">
        {scores.map((s) => (
          <div key={s.label} className="text-center">
            <div className={`text-lg font-bold ${(s.value || 0) >= 7 ? 'text-green-400' : (s.value || 0) >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
              {s.value ?? '-'}
            </div>
            <div className="text-xs text-gray-500">{s.label}</div>
          </div>
        ))}
      </div>
      {(review.suggestions as string[])?.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-gray-400">Suggestions:</div>
          <ul className="text-xs text-gray-300 list-disc list-inside">
            {(review.suggestions as string[]).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ============================================
// REVIEW QUEUE TAB
// ============================================

function ReviewQueueTab() {
  const [useSmartQueue, setUseSmartQueue] = useState(true)
  const { data: smartQueue, isLoading: smartLoading, isError: smartError, error: smartErrorObj, refetch: refetchSmart } = useSmartReviewQueue()
  const { data: regularQueue, isLoading: regularLoading, isError: regularError, error: regularErrorObj, refetch: refetchRegular } = useReviewQueue()
  const approveMutation = useApproveCarousel()
  const rejectMutation = useRejectCarousel()
  const updateMutation = useUpdateCarousel()
  const reimageMutation = useReimageSlide()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Partial<CharacterCarousel>>({})
  const [musicPickerForId, setMusicPickerForId] = useState<string | null>(null)
  const [reimagingSlide, setReimagingSlide] = useState<{ id: string; idx: number } | null>(null)
  const { data: contentControl } = useContentProductionStatus()
  const productionPaused = contentControl?.paused ?? true

  const queue = useSmartQueue ? smartQueue : regularQueue
  const isLoading = useSmartQueue ? smartLoading : regularLoading
  const isError = useSmartQueue ? smartError : regularError
  const errorObj = useSmartQueue ? smartErrorObj : regularErrorObj
  const doRefetch = useSmartQueue ? refetchSmart : refetchRegular

  const startEdit = (id: string) => {
    setEditingId(id)
    setDraft({})
  }
  const cancelEdit = () => {
    setEditingId(null)
    setDraft({})
  }
  const saveEdit = async (id: string) => {
    const patch: Parameters<typeof updateMutation.mutate>[0] = { id }
    if (draft.hook_text !== undefined) patch.hook_text = draft.hook_text
    if (draft.slides !== undefined) patch.slides = draft.slides
    if (draft.caption !== undefined) patch.caption = draft.caption
    if (draft.hashtags !== undefined) patch.hashtags = draft.hashtags
    if (draft.human_notes !== undefined) patch.human_notes = draft.human_notes
    await updateMutation.mutateAsync(patch)
    setEditingId(null)
    setDraft({})
  }

  const applyDraft = (carousel: CharacterCarousel): CharacterCarousel => {
    if (editingId !== carousel.id) return carousel
    return { ...carousel, ...draft }
  }

  const handleReimageSlide = (carouselId: string, slideIdx: number, query?: string) => {
    if (productionPaused) return
    setReimagingSlide({ id: carouselId, idx: slideIdx })
    reimageMutation.mutate(
      { carouselId, slideIndex: slideIdx, query },
      {
        onSettled: () => setReimagingSlide(null),
      },
    )
  }

  const handleHashtagChange = (value: string) => {
    const tags = value
      .split(/[,\s]+/)
      .map(t => t.trim())
      .filter(Boolean)
      .map(t => (t.startsWith('#') ? t : `#${t}`))
    setDraft(d => ({ ...d, hashtags: tags }))
  }

  if (isError) return <InlineError error={errorObj} onRetry={() => doRefetch()} label="review queue" />
  if (isLoading) return <div className="flex justify-center py-12"><Loader2 className="w-8 h-8 animate-spin text-gray-400" /></div>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">
          {useSmartQueue ? 'Priority' : 'Pending'} Review ({queue?.length || 0})
        </h2>
        <Button variant="outline" size="sm" onClick={() => setUseSmartQueue(!useSmartQueue)} aria-label={useSmartQueue ? 'Switch to regular queue' : 'Switch to smart queue'}>
          {useSmartQueue ? <Award className="w-4 h-4 mr-2" /> : <CheckCircle className="w-4 h-4 mr-2" />}
          {useSmartQueue ? 'Smart Queue' : 'Regular Queue'}
        </Button>
      </div>

      {queue?.length === 0 && (
        <div className="text-center py-12 text-gray-500">No carousels pending review. Generate content in the Content Studio tab.</div>
      )}

      {queue?.map((raw) => {
        const carousel = applyDraft(raw)
        const isEditing = editingId === carousel.id
        const hashtagsValue = (carousel.hashtags || []).join(' ')
        const currentHashtagDraft = draft.hashtags !== undefined ? draft.hashtags.join(' ') : hashtagsValue
        const reimagingIdx =
          reimagingSlide && reimagingSlide.id === carousel.id ? reimagingSlide.idx : null
        return (
          <Card key={carousel.id} className="bg-gray-800/50 border-gray-700">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-white">
                    {carousel.character_name} - {ANGLE_LABELS[carousel.angle] || carousel.angle}
                  </CardTitle>
                  <CardDescription className="flex items-center gap-2 mt-1 flex-wrap">
                    {carousel.title}
                    {carousel.story_template && (
                      <Badge variant="outline" className="text-xs border-purple-500/30 text-purple-400">
                        {TEMPLATE_LABELS[carousel.story_template] || carousel.story_template}
                      </Badge>
                    )}
                    {carousel.series_id && (
                      <Badge variant="outline" className="text-xs border-cyan-500/30 text-cyan-400">
                        Part {carousel.series_part}
                      </Badge>
                    )}
                    {carousel.hook_style && (
                      <Badge variant="outline" className="text-xs border-amber-500/30 text-amber-400">
                        {HOOK_STYLE_LABELS[carousel.hook_style] || carousel.hook_style}
                      </Badge>
                    )}
                    {carousel.content_format && carousel.content_format !== 'fact_list' && (
                      <Badge variant="outline" className="text-xs border-pink-500/30 text-pink-400">
                        {carousel.content_format}
                      </Badge>
                    )}
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  {carousel.auto_approved && (
                    <Badge
                      className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      title={carousel.auto_approve_reason || 'Auto-approved by autopilot'}
                    >
                      AUTO {carousel.final_review_score?.toFixed(0) ?? ''}
                    </Badge>
                  )}
                  <Badge className={`${STATUS_COLORS[carousel.status]} text-white`} aria-label={`Status: ${carousel.status.replace('_', ' ')}`}>
                    {carousel.status.replace('_', ' ')}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-6 md:grid-cols-[360px_1fr]">
                {/* Left: TikTok phone preview */}
                <div>
                  <TikTokPhonePreview
                    carousel={carousel}
                    editMode={isEditing}
                    onChange={patch => setDraft(d => ({ ...d, ...patch }))}
                    onReimageSlide={
                      productionPaused
                        ? undefined
                        : (idx, q) => handleReimageSlide(carousel.id, idx, q)
                    }
                    onOpenMusicPicker={
                      productionPaused ? undefined : () => setMusicPickerForId(carousel.id)
                    }
                    reimagingSlideIdx={reimagingIdx}
                  />
                </div>

                {/* Right: meta + AI review + actions */}
                <div className="flex flex-col gap-4">
                  {isEditing ? (
                    <div className="space-y-3">
                      <div>
                        <label className="text-xs font-medium text-gray-400 mb-1 block">Caption</label>
                        <textarea
                          value={carousel.caption || ''}
                          onChange={e => setDraft(d => ({ ...d, caption: e.target.value }))}
                          rows={3}
                          className="w-full rounded bg-gray-900 border border-gray-700 px-2 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500"
                          placeholder="TikTok caption..."
                        />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-400 mb-1 block">
                          Hashtags (space or comma separated)
                        </label>
                        <input
                          value={currentHashtagDraft}
                          onChange={e => handleHashtagChange(e.target.value)}
                          className="w-full rounded bg-gray-900 border border-gray-700 px-2 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500"
                          placeholder="#starwars #vader #fanfacts"
                        />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-400 mb-1 block">Reviewer notes</label>
                        <textarea
                          value={carousel.human_notes || ''}
                          onChange={e => setDraft(d => ({ ...d, human_notes: e.target.value }))}
                          rows={2}
                          className="w-full rounded bg-gray-900 border border-gray-700 px-2 py-1.5 text-sm text-white focus:outline-none focus:border-indigo-500"
                          placeholder="Optional notes for the next run..."
                        />
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="bg-indigo-950/30 border border-indigo-500/30 rounded-lg p-3">
                        <div className="text-xs text-gray-400 mb-1">Hook</div>
                        <div className="text-white font-bold text-lg">{carousel.hook_text}</div>
                      </div>
                      {carousel.caption && (
                        <div className="text-sm text-gray-300 bg-gray-900/50 rounded-lg p-3">
                          <div className="text-xs text-gray-500 mb-1">Caption</div>
                          {carousel.caption}
                        </div>
                      )}
                      {(carousel.hashtags || []).length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {(carousel.hashtags || []).map((tag, i) => (
                            <Badge key={i} variant="outline" className="text-xs border-gray-700 text-gray-300">
                              {tag.startsWith('#') ? tag : `#${tag}`}
                            </Badge>
                          ))}
                        </div>
                      )}
                      {carousel.music_track && (
                        <div className="flex items-center gap-2 text-sm text-gray-400">
                          <Music className="w-4 h-4 text-indigo-400" />
                          <span className="text-gray-200">{carousel.music_track.name}</span>
                          {carousel.music_track.artist && (
                            <span className="text-gray-500">- {carousel.music_track.artist}</span>
                          )}
                          {carousel.music_mood && (
                            <Badge variant="outline" className="text-[10px] border-gray-700 text-gray-400">
                              {MOOD_LABELS[carousel.music_mood] || carousel.music_mood}
                            </Badge>
                          )}
                        </div>
                      )}
                    </>
                  )}

                  {carousel.ai_review && <AIReviewScores review={carousel.ai_review} />}

                  {carousel.brain_context_used && (
                    <div className="bg-yellow-900/10 border border-yellow-500/20 rounded-lg p-3 text-xs text-yellow-400">
                      <Brain className="w-3 h-3 inline mr-1" /> Brain learnings applied to this carousel
                    </div>
                  )}

                  <div className="mt-auto flex items-center gap-2 pt-2 flex-wrap">
                    {isEditing ? (
                      <>
                        <Button
                          className="flex-1 min-w-[120px] bg-indigo-600 hover:bg-indigo-500"
                          onClick={() => saveEdit(carousel.id)}
                          disabled={updateMutation.isPending || Object.keys(draft).length === 0 || productionPaused}
                          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Save carousel changes'}
                        >
                          <Save className="w-4 h-4 mr-2" />
                          Save changes
                        </Button>
                        <Button
                          variant="outline"
                          className="flex-1 min-w-[120px]"
                          onClick={cancelEdit}
                          disabled={updateMutation.isPending}
                        >
                          <X className="w-4 h-4 mr-2" />
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button
                          variant="outline"
                          className="flex-1 min-w-[120px]"
                          onClick={() => startEdit(carousel.id)}
                          disabled={productionPaused}
                          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Edit carousel'}
                        >
                          <Pencil className="w-4 h-4 mr-2" />
                          Edit
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setMusicPickerForId(carousel.id)}
                          disabled={productionPaused}
                          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Change music'}
                        >
                          <Music2 className="w-4 h-4" />
                        </Button>
                        <Button
                          className="flex-1 min-w-[120px] bg-green-600 hover:bg-green-700"
                          onClick={() => approveMutation.mutate({ id: carousel.id })}
                          disabled={approveMutation.isPending || productionPaused}
                          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Approve carousel'}
                          aria-label={`Approve carousel for ${carousel.character_name}`}
                        >
                          <CheckCircle className="w-4 h-4 mr-2" />
                          Approve
                        </Button>
                        <Button
                          variant="destructive"
                          className="flex-1 min-w-[120px]"
                          onClick={() => rejectMutation.mutate({ id: carousel.id, reason: 'Not engaging enough' })}
                          disabled={rejectMutation.isPending || productionPaused}
                          title={productionPaused ? CONTENT_PRODUCTION_PAUSED_TOOLTIP : 'Reject carousel'}
                          aria-label={`Reject carousel for ${carousel.character_name}`}
                        >
                          <XCircle className="w-4 h-4 mr-2" />
                          Reject
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )
      })}

      {musicPickerForId && (
        <MusicPickerModal
          open={!!musicPickerForId}
          onOpenChange={open => { if (!open) setMusicPickerForId(null) }}
          carouselId={musicPickerForId}
          currentTrackId={queue?.find(c => c.id === musicPickerForId)?.music_track?.id}
          onAssigned={() => setMusicPickerForId(null)}
        />
      )}
    </div>
  )
}

// ============================================
// INSPIRATION TAB
// ============================================

function InspirationTab() {
  const { data: inspirations, isLoading, isError, error, refetch } = useInspirations()
  const { data: patterns } = useInspirationPatterns()
  const discoverMutation = useDiscoverInspirations()
  const analyzeMutation = useAnalyzeInspiration()
  const [analyzeUrl, setAnalyzeUrl] = useState('')

  return (
    <div className="space-y-6">
      {/* Discover & Analyze */}
      <Card className="bg-gray-800/50 border-gray-700">
        <CardHeader>
          <CardTitle className="text-white">Content Inspiration</CardTitle>
          <CardDescription>Discover viral carousel creators and analyze winning patterns</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-end gap-4">
            <div className="flex-1 space-y-2">
              <label className="text-sm text-gray-400">Analyze Carousel URL</label>
              <Input
                placeholder="Paste TikTok or Instagram carousel URL..."
                value={analyzeUrl}
                onChange={(e) => setAnalyzeUrl(e.target.value)}
                className="bg-gray-900 border-gray-700"
                aria-label="Carousel URL to analyze"
              />
            </div>
            <Button
              onClick={() => { analyzeMutation.mutate(analyzeUrl); setAnalyzeUrl('') }}
              disabled={!analyzeUrl || analyzeMutation.isPending}
              aria-label="Analyze carousel URL"
            >
              {analyzeMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}
              Analyze
            </Button>
            <Button
              variant="outline"
              onClick={() => discoverMutation.mutate(undefined)}
              disabled={discoverMutation.isPending}
              aria-label="Auto-discover viral carousel creators"
            >
              {discoverMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Lightbulb className="w-4 h-4 mr-2" />}
              Auto-Discover
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Winning Patterns */}
      {patterns && (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Winning Patterns</CardTitle>
            <CardDescription>{patterns.total_analyzed} carousels analyzed</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-900/50 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-indigo-400">{patterns.avg_slide_count?.toFixed(1) || '-'}</div>
                <div className="text-xs text-gray-500">Avg Slides</div>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-green-400">{patterns.total_analyzed}</div>
                <div className="text-xs text-gray-500">Analyzed</div>
              </div>
            </div>
            {patterns.top_hook_types?.length > 0 && (
              <div>
                <div className="text-sm text-gray-400 mb-2">Top Hook Types</div>
                <div className="flex flex-wrap gap-2">
                  {patterns.top_hook_types.map((h, i) => (
                    <Badge key={i} variant="outline" className="border-indigo-500/30 text-indigo-400">{h}</Badge>
                  ))}
                </div>
              </div>
            )}
            {patterns.engagement_insights?.length > 0 && (
              <div>
                <div className="text-sm text-gray-400 mb-2">Engagement Insights</div>
                <ul className="text-sm text-gray-300 space-y-1">
                  {patterns.engagement_insights.map((ins, i) => (
                    <li key={i} className="flex items-start gap-2"><TrendingUp className="w-3 h-3 mt-1 text-green-400 shrink-0" />{ins}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Analyzed Inspirations */}
      {isError ? (
        <InlineError error={error} onRetry={() => refetch()} label="inspirations" />
      ) : isLoading ? (
        <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {inspirations?.map((insp) => (
            <Card key={insp.id} className="bg-gray-800/50 border-gray-700">
              <CardContent className="pt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <Badge className="bg-indigo-600 text-white text-xs">{insp.platform}</Badge>
                  <Badge className={insp.status === 'analyzed' ? 'bg-green-600 text-white text-xs' : 'bg-gray-600 text-white text-xs'}>
                    {insp.status}
                  </Badge>
                </div>
                {insp.creator_handle && <div className="text-sm text-gray-300">@{insp.creator_handle}</div>}
                {insp.hook_text && <div className="text-sm text-white font-medium">{insp.hook_text}</div>}
                {insp.slide_count && <div className="text-xs text-gray-500">{insp.slide_count} slides</div>}
                {insp.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {insp.tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-xs border-gray-600 text-gray-400">#{tag}</Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
          {inspirations?.length === 0 && (
            <div className="col-span-3 text-center py-12 text-gray-500">
              No inspirations yet. Click "Auto-Discover" or paste a URL to analyze.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ============================================
// ANALYTICS TAB
// ============================================

function AnalyticsTab() {
  const { data: stats, isLoading: statsLoading, isError: statsError, error: statsErrorObj, refetch: refetchStats } = useCharacterStats()
  const { data: sourceAnalytics } = useSourceAnalytics()
  const { data: templateAnalytics } = useTemplateAnalytics()

  if (statsError) return <InlineError error={statsErrorObj} onRetry={() => refetchStats()} label="analytics" />
  if (statsLoading) return <div className="flex justify-center py-12"><Loader2 className="w-8 h-8 animate-spin text-gray-400" /></div>

  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Characters" value={stats?.total_characters || 0} icon={<Users className="w-5 h-5" />} />
        <StatCard label="Researched" value={stats?.characters_researched || 0} icon={<Brain className="w-5 h-5" />} />
        <StatCard label="Carousels" value={stats?.total_carousels || 0} icon={<Sparkles className="w-5 h-5" />} />
        <StatCard label="Published" value={stats?.total_published || 0} icon={<CheckCircle className="w-5 h-5" />} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard label="Total Views" value={formatNumber(stats?.total_views || 0)} icon={<Eye className="w-5 h-5" />} />
        <StatCard label="Total Likes" value={formatNumber(stats?.total_likes || 0)} icon={<Heart className="w-5 h-5" />} />
        <StatCard label="Avg Engagement" value={`${(stats?.avg_engagement_rate || 0).toFixed(1)}%`} icon={<Zap className="w-5 h-5" />} />
      </div>

      {/* Template Performance */}
      {templateAnalytics?.templates?.length ? (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Template Performance</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {templateAnalytics.templates.map((t, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-gray-700 last:border-0">
                  <div className="flex items-center gap-3">
                    <Layers className="w-4 h-4 text-purple-400" />
                    <span className="text-white">{TEMPLATE_LABELS[t.template_type] || t.name}</span>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-gray-400">
                    <span>{t.times_used} uses</span>
                    <span className={t.avg_score >= 7 ? 'text-green-400' : t.avg_score >= 5 ? 'text-yellow-400' : 'text-gray-400'}>
                      {t.avg_score?.toFixed(1) || '-'}/10
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Research Source Effectiveness */}
      {sourceAnalytics?.sources?.length ? (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Research Sources</CardTitle>
            <CardDescription>{sourceAnalytics.total_fragments} total fragments collected</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {sourceAnalytics.sources.map((s, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-gray-700 last:border-0">
                  <span className="text-white capitalize">{s.source.replace('_', ' ')}</span>
                  <div className="flex items-center gap-4 text-sm text-gray-400">
                    <span>{s.fragment_count} fragments</span>
                    <span className="text-indigo-400">{(s.avg_relevance * 100).toFixed(0)}% relevance</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Pipeline Status */}
      {stats?.carousels_by_status && Object.keys(stats.carousels_by_status).length > 0 && (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Pipeline Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.carousels_by_status).map(([status, count]) => (
                <div key={status} className="flex items-center gap-2">
                  <Badge className={`${STATUS_COLORS[status] || 'bg-gray-600'} text-white`}>
                    {status.replace('_', ' ')}
                  </Badge>
                  <span className="text-white font-semibold">{count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top Characters */}
      {stats?.top_characters?.length ? (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Top Characters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {stats.top_characters.map((c, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-gray-700 last:border-0">
                  <span className="text-white">{c.name}</span>
                  <div className="flex items-center gap-4 text-sm text-gray-400">
                    <span>{c.posts} posts</span>
                    <span><Heart className="w-3 h-3 inline mr-1" />{formatNumber(c.likes)}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Top Angles */}
      {stats?.top_angles?.length ? (
        <Card className="bg-gray-800/50 border-gray-700">
          <CardHeader>
            <CardTitle className="text-white">Content Angles</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              {stats.top_angles.map((a, i) => (
                <Badge key={i} variant="outline" className="border-indigo-500/30 text-indigo-400">
                  {ANGLE_LABELS[a.angle] || a.angle} ({a.count})
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function StatCard({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <Card className="bg-gray-800/50 border-gray-700">
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-2xl font-bold text-white">{value}</div>
            <div className="text-sm text-gray-400">{label}</div>
          </div>
          <div className="text-indigo-400">{icon}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toString()
}
