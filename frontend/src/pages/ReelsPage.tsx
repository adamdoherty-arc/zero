import { useMemo, useState } from 'react'
import { Film, Loader2, Music2, Sparkles } from 'lucide-react'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ReelCard } from '@/components/reels/ReelCard'
import { useToast } from '@/hooks/use-toast'
import {
    REEL_IN_PROGRESS_STATUSES,
    useGenerateReel,
    useReelMusic,
    useReels,
    useSeedReelMusic,
    type GenerateReelRequest,
    type ReelMood,
    type ReelStatus,
    type ReelSubNiche,
} from '@/hooks/useReelsApi'

const SUB_NICHES: { value: ReelSubNiche; label: string }[] = [
    { value: 'stoicism', label: 'Stoicism' },
    { value: 'discipline', label: 'Discipline' },
    { value: 'wealth_mindset', label: 'Wealth Mindset' },
    { value: 'self_improvement', label: 'Self Improvement' },
    { value: 'faith', label: 'Faith' },
    { value: 'grindset', label: 'Grindset' },
    { value: 'mental_health', label: 'Mental Health' },
    { value: 'entrepreneurship', label: 'Entrepreneurship' },
    { value: 'affirmations', label: 'Affirmations' },
]

const MOODS: { value: ReelMood; label: string }[] = [
    { value: 'epic', label: 'Epic' },
    { value: 'calm', label: 'Calm' },
    { value: 'hopeful', label: 'Hopeful' },
    { value: 'dark', label: 'Dark' },
    { value: 'intense', label: 'Intense' },
    { value: 'reflective', label: 'Reflective' },
    { value: 'uplifting', label: 'Uplifting' },
]

type StatusFilter = 'all' | 'awaiting_review' | 'published' | 'failed'

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'awaiting_review', label: 'Awaiting Review' },
    { value: 'published', label: 'Published' },
    { value: 'failed', label: 'Failed' },
]

const IN_PROGRESS = new Set<ReelStatus>(REEL_IN_PROGRESS_STATUSES)

function ToggleRow({
    label,
    checked,
    onChange,
}: {
    label: string
    checked: boolean
    onChange: (next: boolean) => void
}) {
    return (
        <label className="flex items-center justify-between gap-3 cursor-pointer select-none">
            <span className="text-sm text-gray-300">{label}</span>
            <button
                type="button"
                role="switch"
                aria-checked={checked}
                onClick={() => onChange(!checked)}
                className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                    checked ? 'bg-indigo-600' : 'bg-gray-700'
                }`}
            >
                <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        checked ? 'translate-x-4' : 'translate-x-0.5'
                    }`}
                />
            </button>
        </label>
    )
}

function GeneratePanel() {
    const { toast } = useToast()
    const generate = useGenerateReel()

    const [subNiche, setSubNiche] = useState<ReelSubNiche>('stoicism')
    const [mood, setMood] = useState<ReelMood>('epic')
    const [sceneCount, setSceneCount] = useState(5)
    const [duration, setDuration] = useState(18)
    const [voiceover, setVoiceover] = useState(true)
    const [autoPublish, setAutoPublish] = useState(false)
    const [quoteText, setQuoteText] = useState('')
    const [quoteAuthor, setQuoteAuthor] = useState('')

    const handleGenerate = () => {
        const payload: GenerateReelRequest = {
            sub_niche: subNiche,
            mood,
            scene_count: sceneCount,
            target_duration_s: duration,
            voiceover,
            auto_publish: autoPublish,
            platforms: ['tiktok', 'instagram'],
        }
        if (quoteText.trim()) payload.quote_text = quoteText.trim()
        if (quoteAuthor.trim()) payload.quote_author = quoteAuthor.trim()

        generate.mutate(payload, {
            onSuccess: (res) =>
                toast({
                    title: 'Generating reel',
                    description: `Started (${res.generation_id}). It will appear below as it renders.`,
                }),
            onError: (e) =>
                toast({
                    title: 'Generation failed',
                    description: String((e as Error).message || e),
                    variant: 'destructive',
                }),
        })
    }

    return (
        <Card className="bg-gray-800/50 border-gray-700">
            <CardHeader className="pb-3">
                <CardTitle className="text-white text-base flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-indigo-300" />
                    Generate Reel
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-gray-400">
                            Sub-niche
                        </label>
                        <Select
                            value={subNiche}
                            onValueChange={(v) => setSubNiche(v as ReelSubNiche)}
                        >
                            <SelectTrigger className="bg-gray-900 border-gray-700 text-gray-200">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {SUB_NICHES.map((s) => (
                                    <SelectItem key={s.value} value={s.value}>
                                        {s.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-gray-400">
                            Mood
                        </label>
                        <Select value={mood} onValueChange={(v) => setMood(v as ReelMood)}>
                            <SelectTrigger className="bg-gray-900 border-gray-700 text-gray-200">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {MOODS.map((m) => (
                                    <SelectItem key={m.value} value={m.value}>
                                        {m.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-gray-400">
                            Scenes: <span className="text-gray-200">{sceneCount}</span>
                        </label>
                        <input
                            type="range"
                            min={3}
                            max={7}
                            step={1}
                            value={sceneCount}
                            onChange={(e) => setSceneCount(Number(e.target.value))}
                            className="w-full accent-indigo-500"
                            aria-label="Scene count"
                        />
                    </div>

                    <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-gray-400">
                            Target duration: <span className="text-gray-200">{duration}s</span>
                        </label>
                        <input
                            type="range"
                            min={8}
                            max={45}
                            step={1}
                            value={duration}
                            onChange={(e) => setDuration(Number(e.target.value))}
                            className="w-full accent-indigo-500"
                            aria-label="Target duration in seconds"
                        />
                    </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-gray-400">
                            Custom quote (optional)
                        </label>
                        <Input
                            value={quoteText}
                            onChange={(e) => setQuoteText(e.target.value)}
                            placeholder="Leave blank to auto-source a quote"
                            className="bg-gray-900 border-gray-700 text-gray-200"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-xs uppercase tracking-wide text-gray-400">
                            Quote author (optional)
                        </label>
                        <Input
                            value={quoteAuthor}
                            onChange={(e) => setQuoteAuthor(e.target.value)}
                            placeholder="e.g. Marcus Aurelius"
                            className="bg-gray-900 border-gray-700 text-gray-200"
                        />
                    </div>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                    <ToggleRow label="Voiceover" checked={voiceover} onChange={setVoiceover} />
                    <ToggleRow
                        label="Auto-publish on approve"
                        checked={autoPublish}
                        onChange={setAutoPublish}
                    />
                </div>

                <div className="flex justify-end">
                    <Button
                        onClick={handleGenerate}
                        disabled={generate.isPending}
                        className="bg-indigo-600 hover:bg-indigo-500 text-white"
                    >
                        {generate.isPending ? (
                            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                        ) : (
                            <Sparkles className="w-4 h-4 mr-1" />
                        )}
                        Generate
                    </Button>
                </div>
            </CardContent>
        </Card>
    )
}

export function ReelsPage() {
    const { toast } = useToast()
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

    const filters = useMemo(
        () => ({
            limit: 60,
            ...(statusFilter !== 'all' ? { status: statusFilter as ReelStatus } : {}),
        }),
        [statusFilter],
    )

    // useReels self-polls every 5s while any reel is mid-pipeline (see hook),
    // so freshly generated reels appear and advance through statuses live.
    const { data: reels = [], isLoading, error } = useReels(filters)
    const { data: music = [] } = useReelMusic()
    const seedMusic = useSeedReelMusic()

    const anyInProgress = reels.some((r) => IN_PROGRESS.has(r.status))

    const handleSeedMusic = () => {
        seedMusic.mutate(undefined, {
            onSuccess: (res) =>
                toast({
                    title: 'Music seeded',
                    description: `${res.bakeable_tracks} bakeable tracks available.`,
                }),
            onError: (e) =>
                toast({
                    title: 'Seed failed',
                    description: String((e as Error).message || e),
                    variant: 'destructive',
                }),
        })
    }

    return (
        <div className="page-content space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                    <Film className="w-6 h-6 text-indigo-300" />
                    <div>
                        <h1 className="text-xl font-semibold text-white">Motivation Reels</h1>
                        <p className="text-sm text-gray-400">
                            Auto-sourced quotes, rendered to vertical video, ready to publish.
                        </p>
                    </div>
                </div>
                {music.length === 0 && (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={handleSeedMusic}
                        disabled={seedMusic.isPending}
                        className="border-gray-700 text-gray-300"
                    >
                        {seedMusic.isPending ? (
                            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                        ) : (
                            <Music2 className="w-4 h-4 mr-1" />
                        )}
                        Seed music
                    </Button>
                )}
            </div>

            <GeneratePanel />

            {/* Status filter */}
            <div className="flex items-center justify-between gap-3 flex-wrap border-b border-white/10 pb-2">
                <div className="flex gap-2 flex-wrap">
                    {STATUS_FILTERS.map((f) => (
                        <button
                            key={f.value}
                            onClick={() => setStatusFilter(f.value)}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                                statusFilter === f.value
                                    ? 'bg-indigo-600/20 text-indigo-300'
                                    : 'text-gray-400 hover:bg-white/5'
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
                {anyInProgress && (
                    <span className="inline-flex items-center gap-1.5 text-xs text-indigo-300">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Rendering in progress
                    </span>
                )}
            </div>

            {/* Reels grid */}
            {isLoading ? (
                <div className="flex items-center justify-center py-20">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
                </div>
            ) : error ? (
                <div className="rounded-2xl border border-red-800 bg-red-950/40 p-6 text-center text-red-200">
                    Failed to load reels: {String((error as Error).message || error)}
                </div>
            ) : reels.length === 0 ? (
                <div className="rounded-2xl border border-gray-800 bg-gray-900/60 p-10 text-center">
                    <Film className="w-10 h-10 mx-auto mb-3 text-gray-600" />
                    <h3 className="text-lg font-semibold text-white mb-1">No reels yet</h3>
                    <p className="text-sm text-gray-400">
                        Use the Generate Reel panel above to create your first motivation reel.
                    </p>
                </div>
            ) : (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {reels.map((reel) => (
                        <ReelCard key={reel.id} reel={reel} />
                    ))}
                </div>
            )}
        </div>
    )
}

export default ReelsPage
