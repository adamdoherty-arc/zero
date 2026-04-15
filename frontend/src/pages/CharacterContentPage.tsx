import { useState, useEffect, Component, type ErrorInfo, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
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
  useBatchResearch,
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
  type Character,
  type CharacterCarousel,
  type ContentAngle,
  type CharacterUniverse,
  type AIReview,
  type ResearchJob,
  type ResearchJobStep,
} from '@/hooks/useCharacterContentApi'
import {
  Users, Search, Sparkles, Eye, Heart,
  CheckCircle, XCircle, RefreshCw, Plus, Loader2,
  Zap, Brain, Music, Lightbulb, BarChart3,
  TrendingUp, Award, Layers, Clock, AlertTriangle,
  Play, Square, ImageIcon, BookOpen,
  ChevronDown, ChevronUp, RotateCcw, Timer, X,
} from 'lucide-react'

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
}

const MOOD_LABELS: Record<string, string> = {
  epic: 'Epic', dark: 'Dark', emotional: 'Emotional',
  mysterious: 'Mysterious', dramatic: 'Dramatic', hype: 'Hype', chill: 'Chill',
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-600', ai_reviewed: 'bg-blue-600', pending_review: 'bg-yellow-600',
  approved: 'bg-green-600', rejected: 'bg-red-600', published: 'bg-purple-600',
  pending: 'bg-gray-500', researching: 'bg-blue-500', completed: 'bg-green-500',
  failed: 'bg-red-500', active: 'bg-green-500',
}

export function CharacterContentPage() {
  return (
    <CharacterContentErrorBoundary>
      <div className="space-y-6">
        <Tabs defaultValue="characters" className="w-full">
          <TabsList className="bg-gray-800 border-gray-700" aria-label="Character content sections">
            <TabsTrigger value="characters" aria-label="Characters tab"><Users className="w-4 h-4 mr-2" />Characters</TabsTrigger>
            <TabsTrigger value="research" aria-label="Research Queue tab"><Search className="w-4 h-4 mr-2" />Research Queue</TabsTrigger>
            <TabsTrigger value="studio" aria-label="Content Studio tab"><Sparkles className="w-4 h-4 mr-2" />Content Studio</TabsTrigger>
            <TabsTrigger value="review" aria-label="Review Queue tab"><CheckCircle className="w-4 h-4 mr-2" />Review Queue</TabsTrigger>
            <TabsTrigger value="inspiration" aria-label="Inspiration tab"><Lightbulb className="w-4 h-4 mr-2" />Inspiration</TabsTrigger>
            <TabsTrigger value="analytics" aria-label="Analytics tab"><BarChart3 className="w-4 h-4 mr-2" />Analytics</TabsTrigger>
          </TabsList>

          <TabsContent value="characters" role="tabpanel"><CharactersTab /></TabsContent>
          <TabsContent value="research" role="tabpanel"><ResearchQueueTab /></TabsContent>
          <TabsContent value="studio" role="tabpanel"><ContentStudioTab /></TabsContent>
          <TabsContent value="review" role="tabpanel"><ReviewQueueTab /></TabsContent>
          <TabsContent value="inspiration" role="tabpanel"><InspirationTab /></TabsContent>
          <TabsContent value="analytics" role="tabpanel"><AnalyticsTab /></TabsContent>
        </Tabs>
      </div>
    </CharacterContentErrorBoundary>
  )
}

// ============================================
// CHARACTERS TAB
// ============================================

function CharactersTab() {
  const navigate = useNavigate()
  const [universeFilter, setUniverseFilter] = useState<string>('')
  const { data: characters, isLoading, isError, error, refetch } = useCharacters(
    universeFilter ? { universe: universeFilter } : undefined
  )
  const seedMutation = useSeedCharacters()
  const researchMutation = useResearchCharacter()
  const batchResearchMutation = useBatchResearch()

  return (
    <div className="space-y-4">
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
          <span className="text-sm text-gray-400" aria-live="polite">{characters?.length || 0} characters</span>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => batchResearchMutation.mutate({})}
            disabled={batchResearchMutation.isPending}
            aria-label="Research all characters"
          >
            {batchResearchMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}
            Research All
          </Button>
          <AddCharacterDialog />
          <Button
            variant="outline"
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {characters?.map((char) => (
            <CharacterCard
              key={char.id}
              character={char}
              onResearch={(e) => { e.stopPropagation(); researchMutation.mutate(char.id) }}
              isResearching={researchMutation.isPending}
              onClick={() => navigate(`/characters/${char.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function CharacterCard({ character, onResearch, isResearching, onClick }: {
  character: Character
  onResearch: (e: React.MouseEvent) => void
  isResearching: boolean
  onClick: () => void
}) {
  const factCount = character.fact_bank?.length || 0

  return (
    <Card className="bg-gray-800/50 border-gray-700 hover:border-indigo-500/50 transition-colors cursor-pointer" onClick={onClick} aria-label={`View ${character.name} details`}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-lg text-white">{character.name}</CardTitle>
            <CardDescription className="text-gray-400">
              {character.real_name && `${character.real_name} · `}
              {character.franchise || UNIVERSE_LABELS[character.universe] || character.universe}
            </CardDescription>
          </div>
          <Badge className={`${STATUS_COLORS[character.universe] || 'bg-gray-600'} text-white text-xs`} aria-label={`Universe: ${UNIVERSE_LABELS[character.universe] || character.universe}`}>
            {UNIVERSE_LABELS[character.universe] || character.universe}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {character.image_url && (
          <div className="w-full h-32 rounded-md overflow-hidden bg-gray-900">
            <img src={character.image_url} alt={`${character.name} character image`} className="w-full h-full object-cover" />
          </div>
        )}

        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-1 text-gray-400">
            <Brain className="w-3.5 h-3.5" />
            <span>{factCount} facts</span>
          </div>
          <div className="flex items-center gap-1 text-gray-400">
            <Sparkles className="w-3.5 h-3.5" />
            <span>{character.posts_created} posts</span>
          </div>
          <Badge className={`${STATUS_COLORS[character.research_status] || 'bg-gray-600'} text-white text-xs`} aria-label={`Status: ${character.research_status}`}>
            {character.research_status}
          </Badge>
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
          disabled={isResearching || character.research_status === 'researching'}
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

function AddCharacterDialog() {
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
        <Button aria-label="Add new character"><Plus className="w-4 h-4 mr-2" />Add Character</Button>
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
          <Button onClick={handleSubmit} disabled={!name || createMutation.isPending} className="w-full" aria-label="Create character">
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
  const [selectedJob, setSelectedJob] = useState<ResearchJob | null>(null)

  const isRunning = (queue?.queued ?? 0) > 0 || (queue?.researching ?? 0) > 0

  // Keep polling active when queue is running
  useEffect(() => {
    if (isRunning && !pollingEnabled) {
      setPollingEnabled(true)
    }
  }, [isRunning, pollingEnabled])

  const handleStart = () => {
    const params: { universe?: string; limit?: number } = {}
    if (filterUniverse && filterUniverse !== 'all') params.universe = filterUniverse
    if (limit > 0) params.limit = limit
    startMutation.mutate(params)
    setPollingEnabled(true)
  }

  const completedCount = queue?.completed ?? 0
  const totalCount = queue?.total_jobs ?? 0
  const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-semibold text-white">Research Queue</h2>
          {queue && (
            <div className="flex items-center gap-3 text-sm">
              <span className="text-gray-400">{totalCount} total</span>
              <span className="text-gray-500">|</span>
              <span className="text-gray-400">{queue.queued} queued</span>
              <span className="text-gray-500">|</span>
              <span className="text-indigo-400">{queue.researching} in progress</span>
              <span className="text-gray-500">|</span>
              <span className="text-green-400">{queue.completed} completed</span>
              {(queue.failed ?? 0) > 0 && (
                <>
                  <span className="text-gray-500">|</span>
                  <span className="text-red-400">{queue.failed} failed</span>
                </>
              )}
            </div>
          )}
        </div>
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
            disabled={startMutation.isPending || isRunning}
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
      {queue && totalCount > 0 && (
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

      {/* Job Lists */}
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
        <ResearchJobLists jobs={queue.jobs} onSelectJob={setSelectedJob} />
      )}

      {/* Research Job Detail Modal */}
      {selectedJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setSelectedJob(null)}>
          <div className="bg-gray-800 rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto border border-gray-700" onClick={e => e.stopPropagation()} role="dialog" aria-label={`Research job details for ${selectedJob.character_name}`}>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold text-white">{selectedJob.character_name} — Research Details</h3>
              <button onClick={() => setSelectedJob(null)} className="text-gray-400 hover:text-white" aria-label="Close dialog">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Step-by-step details */}
            <div className="space-y-3">
              {(selectedJob.steps || []).map((step, i) => (
                <div key={i} className="bg-gray-900 rounded-lg p-3">
                  <div className="flex justify-between items-center">
                    <span className="text-gray-200 font-medium">{STEP_LABELS[step.name] || step.name.replace(/_/g, ' ')}</span>
                    <span className={`text-xs px-2 py-1 rounded ${
                      step.status === 'completed' ? 'bg-green-900 text-green-300' :
                      step.status === 'running' ? 'bg-blue-900 text-blue-300' :
                      step.status === 'failed' ? 'bg-red-900 text-red-300' :
                      'bg-gray-700 text-gray-400'
                    }`} aria-label={`Step status: ${step.status}`}>{step.status}</span>
                  </div>
                  {step.result_summary && <p className="text-gray-400 text-sm mt-1">{step.result_summary}</p>}
                  {step.error && <p className="text-red-400 text-sm mt-1">{step.error}</p>}
                  {step.started_at && step.completed_at && (
                    <p className="text-gray-500 text-xs mt-1">
                      Duration: {((new Date(step.completed_at).getTime() - new Date(step.started_at).getTime()) / 1000).toFixed(1)}s
                    </p>
                  )}
                </div>
              ))}
            </div>

            {/* Summary stats */}
            <div className="mt-4 grid grid-cols-3 gap-3">
              <div className="bg-gray-900 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-white">{selectedJob.facts_found}</p>
                <p className="text-gray-400 text-xs">Facts Found</p>
              </div>
              <div className="bg-gray-900 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-white">{selectedJob.images_found}</p>
                <p className="text-gray-400 text-xs">Images Found</p>
              </div>
              <div className="bg-gray-900 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-white">{selectedJob.depth_score?.toFixed(0) || '—'}</p>
                <p className="text-gray-400 text-xs">Depth Score</p>
              </div>
            </div>

            {/* Sources */}
            {selectedJob.sources_used && selectedJob.sources_used.length > 0 && (
              <div className="mt-4">
                <div className="text-xs text-gray-500 mb-2">Sources Used</div>
                <div className="flex flex-wrap gap-1">
                  {selectedJob.sources_used.map((src, i) => (
                    <span key={i} className="text-xs bg-gray-900 text-gray-400 px-2 py-1 rounded">{src}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Error */}
            {selectedJob.error && (
              <div className="mt-4 flex items-start gap-2 bg-red-900/20 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-300" role="alert">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span className="break-all">{selectedJob.error}</span>
              </div>
            )}

            {/* Timing */}
            {selectedJob.started_at && (
              <div className="mt-4 text-xs text-gray-500">
                Started: {new Date(selectedJob.started_at).toLocaleString()}
                {selectedJob.completed_at && (
                  <span> — Completed: {new Date(selectedJob.completed_at).toLocaleString()}</span>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ResearchJobLists({ jobs, onSelectJob }: { jobs: ResearchJob[]; onSelectJob: (job: ResearchJob) => void }) {
  const activeJobs = jobs.filter(j => j.status === 'researching' || j.status === 'queued' || j.status === 'failed')
  const completedJobs = jobs.filter(j => j.status === 'completed')

  return (
    <div className="space-y-6">
      {/* Active Queue */}
      {activeJobs.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400 flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 text-indigo-400" />
            Active Queue
            <span className="text-gray-600">({activeJobs.length})</span>
          </h3>
          {activeJobs.map((job) => (
            <ResearchJobCard key={job.id} job={job} onSelect={() => onSelectJob(job)} />
          ))}
        </div>
      )}

      {/* Completed */}
      {completedJobs.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400 flex items-center gap-2">
            <CheckCircle className="w-3.5 h-3.5 text-green-400" />
            Completed
            <span className="text-gray-600">({completedJobs.length})</span>
          </h3>
          {completedJobs.map((job) => (
            <ResearchJobCard key={job.id} job={job} onSelect={() => onSelectJob(job)} />
          ))}
        </div>
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

function ResearchJobCard({ job, onSelect }: { job: ResearchJob; onSelect: () => void }) {
  const isActive = job.status === 'researching'
  const isFailed = job.status === 'failed'
  const [expanded, setExpanded] = useState(isActive)
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
      <CardContent className="py-4">
        {/* Clickable header */}
        <div
          className="flex items-start gap-4 cursor-pointer select-none"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-label={`Toggle details for ${job.character_name}`}
        >
          {/* Status indicator */}
          <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
            job.status === 'queued' ? 'bg-gray-700' :
            isStuck ? 'bg-amber-600 animate-pulse' :
            job.status === 'researching' ? 'bg-indigo-600 animate-pulse' :
            job.status === 'completed' ? 'bg-green-600' :
            'bg-red-600'
          }`}>
            {job.status === 'queued' && <Clock className="w-5 h-5 text-gray-400" />}
            {job.status === 'researching' && <Loader2 className="w-5 h-5 text-white animate-spin" />}
            {job.status === 'completed' && <CheckCircle className="w-5 h-5 text-white" />}
            {job.status === 'failed' && <XCircle className="w-5 h-5 text-white" />}
          </div>

          {/* Main content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1 flex-wrap">
              <span className="text-white font-medium">{job.character_name}</span>
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
              <div className="flex items-center gap-4 mt-2 text-sm">
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
              onClick={(e) => { e.stopPropagation(); onSelect() }}
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
                disabled={retryMutation.isPending}
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
          <div className="mt-4 pt-4 border-t border-gray-700 space-y-3">
            {/* Step timeline table */}
            <div className="bg-gray-900/50 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-gray-700">
                    <th className="text-left px-3 py-2 font-medium">Step</th>
                    <th className="text-left px-3 py-2 font-medium">Status</th>
                    <th className="text-left px-3 py-2 font-medium">Duration</th>
                    <th className="text-left px-3 py-2 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {(job.steps || []).map((step) => {
                    const stepDuration = step.started_at
                      ? getElapsedTime(step.started_at, step.completed_at)
                      : '-'
                    const stepSec = step.started_at && step.status === 'running'
                      ? Math.floor((Date.now() - new Date(step.started_at).getTime()) / 1000)
                      : 0
                    const stepStuck = step.status === 'running' && stepSec > 120

                    return (
                      <tr key={step.name} className="border-b border-gray-800 last:border-0 hover:bg-gray-800/50">
                        <td className="px-3 py-2 text-gray-300">{STEP_LABELS[step.name] || step.name}</td>
                        <td className="px-3 py-2">
                          {step.status === 'completed' && <span className="text-green-400">done</span>}
                          {step.status === 'running' && (
                            <span className={stepStuck ? 'text-amber-400' : 'text-indigo-400'}>
                              {stepStuck ? 'stuck?' : 'running'}
                            </span>
                          )}
                          {step.status === 'failed' && <span className="text-red-400">failed</span>}
                          {step.status === 'pending' && <span className="text-gray-600">pending</span>}
                        </td>
                        <td className="px-3 py-2 text-gray-400 font-mono text-xs">{stepDuration}</td>
                        <td className="px-3 py-2 text-gray-400 text-xs truncate max-w-[200px]">
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
              <div className="flex items-center gap-4 text-sm">
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
      <div className="flex items-center gap-0.5 mt-2">
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
                </div>
              </div>
              {selectedStep.started_at && (
                <div className="bg-gray-900 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">Timing</div>
                  <div className="text-sm text-gray-300">
                    Started: {new Date(selectedStep.started_at).toLocaleTimeString()}
                    {selectedStep.completed_at && (
                      <> — Completed: {new Date(selectedStep.completed_at).toLocaleTimeString()}</>
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

// ============================================
// CONTENT STUDIO TAB
// ============================================

function ContentStudioTab() {
  const { data: characters } = useCharacters({ research_status: 'completed' })
  const { data: templates } = useTemplates()
  const [selectedCharId, setSelectedCharId] = useState('')
  const [selectedAngle, setSelectedAngle] = useState<ContentAngle>('hidden_truths')
  const [selectedTemplate, setSelectedTemplate] = useState('')
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

  return (
    <div className="space-y-4">
      <Card className="bg-gray-800/50 border-gray-700">
        <CardHeader>
          <CardTitle className="text-white">Generate Carousel</CardTitle>
          <CardDescription>Pick a researched character, template, and angle to create a viral carousel</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
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
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <Button
              onClick={() => generateMutation.mutate({
                character_id: selectedCharId,
                angle: selectedAngle,
                story_template: selectedTemplate === 'auto' ? undefined : selectedTemplate,
                slide_count: slideCount,
              })}
              disabled={!selectedCharId || generateMutation.isPending}
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
              disabled={!selectedCharId || seriesMutation.isPending}
              aria-label="Generate 3-part carousel series"
            >
              {seriesMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Layers className="w-4 h-4 mr-2" />}
              Generate Series (3 parts)
            </Button>
            <Button
              variant="outline"
              onClick={() => smartBatchMutation.mutate({ count: 12 })}
              disabled={smartBatchMutation.isPending}
              aria-label="Smart batch generate 12 carousels"
            >
              {smartBatchMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
              Smart Batch (12)
            </Button>
            <Button variant="outline" size="sm" onClick={() => seedTemplatesMutation.mutate()} disabled={seedTemplatesMutation.isPending} aria-label="Seed story templates">
              Seed Templates
            </Button>
            <Button variant="outline" size="sm" onClick={() => seedMusicMutation.mutate()} disabled={seedMusicMutation.isPending} aria-label="Seed music library">
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
        <div className="space-y-4">
          {carousels?.map((carousel) => (
            <CarouselPreview
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

function CarouselPreview({ carousel, onAiReview, isReviewing }: {
  carousel: CharacterCarousel
  onAiReview: () => void
  isReviewing: boolean
}) {
  return (
    <Card className="bg-gray-800/50 border-gray-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-white text-base">
              {carousel.character_name} - {ANGLE_LABELS[carousel.angle] || carousel.angle}
            </CardTitle>
            <CardDescription className="flex items-center gap-2 mt-1">
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
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge className={`${STATUS_COLORS[carousel.status]} text-white text-xs`}>
              {carousel.status.replace('_', ' ')}
            </Badge>
            {carousel.status === 'draft' && (
              <Button size="sm" variant="outline" onClick={onAiReview} disabled={isReviewing} aria-label={`AI review carousel for ${carousel.character_name}`}>
                {isReviewing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Brain className="w-3 h-3 mr-1" />}
                AI Review
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {carousel.hook_text && (
          <div className="bg-indigo-950/30 border border-indigo-500/30 rounded-lg p-3">
            <div className="text-xs text-indigo-400 mb-1">Hook</div>
            <div className="text-white font-bold">{carousel.hook_text}</div>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {carousel.slides?.map((slide, i) => (
            <div key={i} className="bg-gray-900 rounded-lg p-3 border border-gray-700">
              <div className="text-xs text-gray-500 mb-1">Slide {slide.slide_num || i + 1}</div>
              <div className="text-sm text-gray-200">{slide.text}</div>
              {slide.image_url && (
                <img src={slide.image_url} alt={`Slide ${slide.slide_num || i + 1} image for ${carousel.character_name}`} className="mt-2 w-full h-20 object-cover rounded" />
              )}
            </div>
          ))}
        </div>

        {carousel.caption && (
          <div className="text-sm text-gray-300 italic">"{carousel.caption}"</div>
        )}
        {carousel.hashtags?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {carousel.hashtags.map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs border-indigo-500/30 text-indigo-400">
                #{tag}
              </Badge>
            ))}
          </div>
        )}

        {/* Music & metadata row */}
        <div className="flex items-center gap-3 flex-wrap text-xs text-gray-500">
          {carousel.music_track && (
            <span className="flex items-center gap-1">
              <Music className="w-3 h-3" />
              {carousel.music_track.name} - {carousel.music_track.artist}
            </span>
          )}
          {carousel.music_mood && (
            <Badge variant="outline" className="text-xs border-gray-600 text-gray-400">
              {MOOD_LABELS[carousel.music_mood] || carousel.music_mood}
            </Badge>
          )}
          {carousel.brain_context_used && (
            <span className="flex items-center gap-1 text-yellow-500">
              <Brain className="w-3 h-3" /> Brain-enhanced
            </span>
          )}
        </div>

        {/* Generation Details (expandable) */}
        {carousel.generation_metadata && Object.keys(carousel.generation_metadata).length > 0 && (
          <details className="bg-gray-900/30 rounded-lg border border-gray-700">
            <summary className="px-3 py-2 text-xs text-gray-400 cursor-pointer hover:text-gray-300 flex items-center gap-1">
              <Eye className="w-3 h-3" /> Generation Details
            </summary>
            <div className="px-3 pb-3 space-y-2 text-xs">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {!!carousel.generation_metadata.model && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Model</div>
                    <div className="text-gray-200 font-mono">{String(carousel.generation_metadata.model)}</div>
                  </div>
                )}
                {carousel.generation_metadata.duration_ms != null && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Duration</div>
                    <div className="text-gray-200">{Number(carousel.generation_metadata.duration_ms) > 1000 ? `${(Number(carousel.generation_metadata.duration_ms) / 1000).toFixed(1)}s` : `${carousel.generation_metadata.duration_ms}ms`}</div>
                  </div>
                )}
                {carousel.generation_metadata.facts_used != null && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Facts Used</div>
                    <div className="text-gray-200">{String(carousel.generation_metadata.facts_used)}</div>
                  </div>
                )}
                {!!carousel.generation_metadata.template_name && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Template</div>
                    <div className="text-gray-200">{String(carousel.generation_metadata.template_name)}</div>
                  </div>
                )}
              </div>
              {Array.isArray(carousel.generation_metadata.facts_selected) && (carousel.generation_metadata.facts_selected as Array<Record<string, unknown>>).length > 0 && (
                <div>
                  <div className="text-gray-500 mb-1">Facts Selected</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {(carousel.generation_metadata.facts_selected as Array<Record<string, unknown>>).map((fact: Record<string, unknown>, i: number) => (
                      <div key={i} className="flex items-start gap-2 bg-gray-800 rounded p-1.5">
                        <Badge variant="outline" className="text-[10px] border-gray-600 text-gray-400 shrink-0">
                          {String(fact.category || 'general')}
                        </Badge>
                        <span className="text-gray-300 text-[11px]">{String(fact.text || '')}</span>
                        <span className="text-yellow-500 text-[10px] shrink-0">{String(fact.surprise_score || 0)}/10</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {!!carousel.generation_metadata.prompt_preview && (
                <div>
                  <div className="text-gray-500 mb-1">Prompt Preview</div>
                  <pre className="bg-gray-800 rounded p-2 text-[11px] text-gray-300 whitespace-pre-wrap max-h-32 overflow-y-auto font-mono">
                    {String(carousel.generation_metadata.prompt_preview)}
                  </pre>
                </div>
              )}
            </div>
          </details>
        )}

        {carousel.ai_review && <AIReviewScores review={carousel.ai_review} />}
      </CardContent>
    </Card>
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
  const [selectedReviewCarousel, setSelectedReviewCarousel] = useState<CharacterCarousel | null>(null)

  const queue = useSmartQueue ? smartQueue : regularQueue
  const isLoading = useSmartQueue ? smartLoading : regularLoading
  const isError = useSmartQueue ? smartError : regularError
  const errorObj = useSmartQueue ? smartErrorObj : regularErrorObj
  const doRefetch = useSmartQueue ? refetchSmart : refetchRegular

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

      {queue?.map((carousel) => (
        <Card key={carousel.id} className="bg-gray-800/50 border-gray-700">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-white">
                  {carousel.character_name} - {ANGLE_LABELS[carousel.angle] || carousel.angle}
                </CardTitle>
                <CardDescription className="flex items-center gap-2 mt-1">
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
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Badge className={`${STATUS_COLORS[carousel.status]} text-white`} aria-label={`Status: ${carousel.status.replace('_', ' ')}`}>
                  {carousel.status.replace('_', ' ')}
                </Badge>
                <Button variant="outline" size="sm" onClick={() => setSelectedReviewCarousel(carousel)} aria-label={`View full details for ${carousel.character_name} carousel`}>
                  <Eye className="w-3 h-3 mr-1" />
                  Details
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="bg-indigo-950/30 border border-indigo-500/30 rounded-lg p-3">
              <div className="text-white font-bold text-lg">{carousel.hook_text}</div>
            </div>

            <div className="space-y-2">
              {carousel.slides?.map((slide, i) => (
                <div key={i} className="flex items-start gap-3 bg-gray-900/50 rounded-lg p-3">
                  <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-sm font-bold shrink-0">
                    {slide.slide_num || i + 1}
                  </div>
                  <div className="flex-1">
                    <div className="text-gray-200">{slide.text}</div>
                  </div>
                  {slide.image_url && (
                    <img src={slide.image_url} alt={`Slide ${slide.slide_num || i + 1} for ${carousel.character_name}`} className="w-16 h-16 object-cover rounded" />
                  )}
                </div>
              ))}
            </div>

            <div className="text-sm text-gray-300 bg-gray-900/50 rounded-lg p-3">
              <div className="text-xs text-gray-500 mb-1">Caption</div>
              {carousel.caption}
            </div>

            {/* Music info */}
            {carousel.music_track && (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Music className="w-4 h-4" />
                <span>{carousel.music_track.name}</span>
                <span className="text-gray-600">-</span>
                <span>{carousel.music_track.artist}</span>
              </div>
            )}

            {carousel.ai_review && <AIReviewScores review={carousel.ai_review} />}

            {carousel.brain_context_used && (
              <div className="bg-yellow-900/10 border border-yellow-500/20 rounded-lg p-3 text-xs text-yellow-400">
                <Brain className="w-3 h-3 inline mr-1" /> Brain learnings applied to this carousel
              </div>
            )}

            <div className="flex items-center gap-3 pt-2">
              <Button
                className="flex-1 bg-green-600 hover:bg-green-700"
                onClick={() => approveMutation.mutate({ id: carousel.id })}
                disabled={approveMutation.isPending}
                aria-label={`Approve carousel for ${carousel.character_name}`}
              >
                <CheckCircle className="w-4 h-4 mr-2" />
                Approve
              </Button>
              <Button
                variant="destructive"
                className="flex-1"
                onClick={() => rejectMutation.mutate({ id: carousel.id, reason: 'Not engaging enough' })}
                disabled={rejectMutation.isPending}
                aria-label={`Reject carousel for ${carousel.character_name}`}
              >
                <XCircle className="w-4 h-4 mr-2" />
                Reject
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}

      {/* Carousel Detail Modal for Review Queue */}
      {selectedReviewCarousel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setSelectedReviewCarousel(null)}>
          <div className="bg-gray-800 rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto border border-gray-700" onClick={e => e.stopPropagation()} role="dialog" aria-label={`Carousel details for ${selectedReviewCarousel.character_name}`}>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold text-white">
                {selectedReviewCarousel.character_name} — {ANGLE_LABELS[selectedReviewCarousel.angle] || selectedReviewCarousel.angle}
              </h3>
              <button onClick={() => setSelectedReviewCarousel(null)} className="text-gray-400 hover:text-white" aria-label="Close dialog">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Slide-by-slide preview */}
            <div className="space-y-3 mb-4">
              <h4 className="text-sm font-medium text-gray-400">Slide-by-Slide Preview</h4>
              {selectedReviewCarousel.slides?.map((slide, i) => (
                <div key={i} className="bg-gray-900 rounded-lg p-3 flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-sm font-bold shrink-0">
                    {slide.slide_num || i + 1}
                  </div>
                  <div className="flex-1">
                    <p className="text-gray-200 text-sm">{slide.text}</p>
                    {slide.image_query && (
                      <p className="text-gray-500 text-xs mt-1">Image query: {slide.image_query}</p>
                    )}
                  </div>
                  {slide.image_url && (
                    <img src={slide.image_url} alt={`Slide ${slide.slide_num || i + 1}`} className="w-20 h-20 object-cover rounded" />
                  )}
                </div>
              ))}
            </div>

            {/* AI Review breakdown */}
            {selectedReviewCarousel.ai_review && (
              <div className="mb-4">
                <h4 className="text-sm font-medium text-gray-400 mb-2">AI Review Breakdown</h4>
                <div className="grid grid-cols-5 gap-2">
                  {[
                    { label: 'Hook', value: selectedReviewCarousel.ai_review.hook_strength },
                    { label: 'Facts', value: selectedReviewCarousel.ai_review.fact_quality },
                    { label: 'Engage', value: selectedReviewCarousel.ai_review.engagement_potential },
                    { label: 'Caption', value: selectedReviewCarousel.ai_review.caption_quality },
                    { label: 'Overall', value: selectedReviewCarousel.ai_review.overall_score },
                  ].map((s) => (
                    <div key={s.label} className="bg-gray-900 rounded-lg p-2 text-center">
                      <div className={`text-lg font-bold ${(s.value || 0) >= 7 ? 'text-green-400' : (s.value || 0) >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                        {s.value ?? '—'}
                      </div>
                      <div className="text-xs text-gray-500">{s.label}</div>
                    </div>
                  ))}
                </div>
                {(selectedReviewCarousel.ai_review.suggestions as string[])?.length > 0 && (
                  <div className="mt-2 bg-gray-900 rounded-lg p-3">
                    <div className="text-xs text-gray-400 mb-1">Suggestions</div>
                    <ul className="text-xs text-gray-300 list-disc list-inside space-y-1">
                      {(selectedReviewCarousel.ai_review.suggestions as string[]).map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Music track info */}
            {selectedReviewCarousel.music_track && (
              <div className="mb-4 bg-gray-900 rounded-lg p-3">
                <h4 className="text-sm font-medium text-gray-400 mb-1">Music Track</h4>
                <div className="flex items-center gap-2 text-sm text-gray-300">
                  <Music className="w-4 h-4 text-indigo-400" />
                  <span>{selectedReviewCarousel.music_track.name}</span>
                  {selectedReviewCarousel.music_track.artist && (
                    <span className="text-gray-500">by {selectedReviewCarousel.music_track.artist}</span>
                  )}
                </div>
                <div className="flex gap-2 mt-1 text-xs text-gray-500">
                  {selectedReviewCarousel.music_mood && <span>Mood: {MOOD_LABELS[selectedReviewCarousel.music_mood] || selectedReviewCarousel.music_mood}</span>}
                  {selectedReviewCarousel.music_track.genre && <span>Genre: {selectedReviewCarousel.music_track.genre}</span>}
                  {selectedReviewCarousel.music_track.is_trending && <span className="text-green-400">Trending</span>}
                </div>
              </div>
            )}

            {/* Brain context */}
            {selectedReviewCarousel.brain_context_used && (
              <div className="bg-yellow-900/10 border border-yellow-500/20 rounded-lg p-3 text-xs text-yellow-400">
                <Brain className="w-3 h-3 inline mr-1" /> Brain-enhanced content generation was used
              </div>
            )}
          </div>
        </div>
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
