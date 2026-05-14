import { Link } from 'react-router-dom'
import {
    CheckSquare,
    Film,
    Users,
    Share2,
    ArrowRight,
    Loader2,
    Sparkles,
    Bot,
    Mic,
    Lock,
    MoonStar,
    Hand,
    CalendarClock,
    Timer,
    Eye,
    Home as HomeIcon,
} from 'lucide-react'
import { useSmartReviewQueue } from '@/hooks/useCharacterContentApi'
import { useReferenceVideos } from '@/hooks/useCharacterReferenceVideoApi'
import {
    type CompanionMode,
    useCreateCompanionEvent,
    useReachyCompanionStatus,
    useSetCompanionMode,
    useSettleReachyAssistant,
} from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

/**
 * Dashboard-style home surface for the installed PWA.
 *
 * Shows counts for the three main actionable buckets and a couple of quick
 * actions. Intentionally minimal; the phone is for triage, not editing.
 */
function StatCard({
    to,
    icon: Icon,
    label,
    count,
    loading,
    subtitle,
    accent,
}: {
    to: string
    icon: React.ElementType
    label: string
    count: number | undefined
    loading: boolean
    subtitle: string
    accent: 'indigo' | 'emerald' | 'amber'
}) {
    const accentMap = {
        indigo: 'bg-indigo-500/10 text-indigo-300 ring-indigo-500/30',
        emerald: 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30',
        amber: 'bg-amber-500/10 text-amber-300 ring-amber-500/30',
    } as const
    return (
        <Link
            to={to}
            className="group block rounded-2xl bg-gray-800/70 border border-gray-800 p-4 active:scale-[0.99] transition"
        >
            <div className="flex items-start justify-between gap-3">
                <div className={`w-10 h-10 rounded-xl ring-1 flex items-center justify-center ${accentMap[accent]}`}>
                    <Icon className="w-5 h-5" />
                </div>
                <ArrowRight className="w-4 h-4 text-gray-500 group-hover:text-gray-300" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
                {loading ? (
                    <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
                ) : (
                    <span className="text-3xl font-bold text-white tabular-nums">
                        {count ?? 0}
                    </span>
                )}
                <span className="text-sm text-gray-400">{label}</span>
            </div>
            <p className="mt-1 text-xs text-gray-500">{subtitle}</p>
        </Link>
    )
}

function ReachyQuickControls() {
    const companion = useReachyCompanionStatus(7000)
    const setMode = useSetCompanionMode()
    const settle = useSettleReachyAssistant()
    const createEvent = useCreateCompanionEvent()
    const { toast } = useToast()
    const mode = companion.data?.mode ?? 'ambient'
    const next = companion.data?.next_suggested_action?.label ?? 'Zero is checking local signals'

    const switchMode = async (nextMode: CompanionMode) => {
        try {
            await setMode.mutateAsync({ mode: nextMode, reason: 'mobile' })
            toast({ title: `Zero: ${nextMode}` })
        } catch (err) {
            toast({ title: 'Zero mode failed', description: String(err), variant: 'destructive' })
        }
    }

    const notice = async () => {
        try {
            await createEvent.mutateAsync({
                type: 'notice',
                source: 'mobile',
                summary: 'Mobile user asked what Zero noticed.',
                payload: { mode },
                importance: 0.5,
            })
            toast({ title: 'Zero noticed', description: next })
        } catch (err) {
            toast({ title: 'Could not ask Zero', description: String(err), variant: 'destructive' })
        }
    }

    const ActionButton = ({
        icon: Icon,
        label,
        onClick,
        active,
        loading,
    }: {
        icon: React.ElementType
        label: string
        onClick: () => void
        active?: boolean
        loading?: boolean
    }) => (
        <button
            type="button"
            onClick={onClick}
            disabled={loading}
            className={`min-h-14 rounded-xl border px-3 py-2 text-sm font-semibold flex flex-col items-center justify-center gap-1 active:scale-[0.98] ${
                active
                    ? 'border-indigo-500/50 bg-indigo-500/20 text-white'
                    : 'border-gray-800 bg-gray-900/70 text-gray-300'
            } disabled:opacity-50`}
        >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Icon className="w-4 h-4" />}
            {label}
        </button>
    )

    return (
        <section className="rounded-2xl border border-gray-800 bg-gray-900/80 p-4">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-indigo-300">
                        <Bot className="w-3.5 h-3.5" />
                        Zero
                    </div>
                    <h2 className="mt-1 text-lg font-bold text-white capitalize">{mode} mode</h2>
                    <p className="mt-0.5 text-xs text-gray-400 line-clamp-2">{next}</p>
                </div>
                {companion.isLoading && <Loader2 className="w-4 h-4 animate-spin text-gray-500" />}
            </div>

            <div className="mt-4 grid grid-cols-4 gap-2">
                <Link
                    to="/zero"
                    className="min-h-14 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm font-semibold text-emerald-100 flex flex-col items-center justify-center gap-1 active:scale-[0.98]"
                >
                    <Mic className="w-4 h-4" />
                    Talk
                </Link>
                <ActionButton icon={Lock} label="Privacy" active={mode === 'privacy'} loading={setMode.isPending} onClick={() => void switchMode('privacy')} />
                <ActionButton icon={MoonStar} label="Sleep" active={mode === 'sleep'} loading={setMode.isPending} onClick={() => void switchMode('sleep')} />
                <ActionButton icon={Hand} label="Settle" loading={settle.isPending} onClick={() => void settle.mutateAsync({ reason: 'mobile' })} />
                <ActionButton icon={CalendarClock} label="Meeting" active={mode === 'meeting'} loading={setMode.isPending} onClick={() => void switchMode('meeting')} />
                <ActionButton icon={Timer} label="Focus" active={mode === 'focus'} loading={setMode.isPending} onClick={() => void switchMode('focus')} />
                <ActionButton icon={HomeIcon} label="Ambient" active={mode === 'ambient'} loading={setMode.isPending} onClick={() => void switchMode('ambient')} />
                <ActionButton icon={Eye} label="Notice" loading={createEvent.isPending} onClick={() => void notice()} />
            </div>
        </section>
    )
}

export function MobileHomePage() {
    const { data: pendingCarousels, isLoading: loadingCarousels } = useSmartReviewQueue()
    const { data: pendingVideos, isLoading: loadingVideos } = useReferenceVideos({
        intent: 'inbox',
        limit: 30,
    })

    const carouselCount = pendingCarousels?.length ?? 0
    const videoInboxCount = (pendingVideos ?? []).filter(
        (v) => v.status === 'pending' || v.status === 'downloading' || v.status === 'transcribing' || v.status === 'analyzing'
    ).length

    return (
        <div className="space-y-6">
            {/* Hero */}
            <section className="rounded-2xl bg-gradient-to-br from-indigo-600/20 via-indigo-500/5 to-transparent border border-indigo-500/20 p-5">
                <div className="flex items-center gap-2 text-indigo-300 text-xs font-medium uppercase tracking-wider">
                    <Sparkles className="w-3.5 h-3.5" />
                    Zero Mobile
                </div>
                <h2 className="mt-2 text-xl font-bold text-white">
                    {carouselCount > 0
                        ? `${carouselCount} carousel${carouselCount === 1 ? '' : 's'} waiting on you`
                        : 'All caught up on reviews'}
                </h2>
                <p className="mt-1 text-sm text-gray-300">
                    {carouselCount > 0
                        ? 'Tap Review to approve or send back for edits.'
                        : 'New content will show up here when it is ready.'}
                </p>
                {carouselCount > 0 && (
                    <Link
                        to="/m/review"
                        className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold"
                    >
                        Start reviewing
                        <ArrowRight className="w-4 h-4" />
                    </Link>
                )}
            </section>

            <ReachyQuickControls />

            {/* Stats */}
            <section className="grid grid-cols-2 gap-3">
                <StatCard
                    to="/m/review"
                    icon={CheckSquare}
                    label="to review"
                    count={carouselCount}
                    loading={loadingCarousels}
                    subtitle="Carousels pending"
                    accent="indigo"
                />
                <StatCard
                    to="/m/videos"
                    icon={Film}
                    label="in inbox"
                    count={videoInboxCount}
                    loading={loadingVideos}
                    subtitle="Videos processing"
                    accent="emerald"
                />
                <StatCard
                    to="/m/characters"
                    icon={Users}
                    label="characters"
                    count={undefined}
                    loading={false}
                    subtitle="Browse roster"
                    accent="amber"
                />
                <Link
                    to="/share"
                    className="block rounded-2xl bg-gray-800/70 border border-gray-800 p-4 active:scale-[0.99] transition"
                >
                    <div className="w-10 h-10 rounded-xl bg-gray-700/50 text-gray-300 ring-1 ring-gray-600/40 flex items-center justify-center">
                        <Share2 className="w-5 h-5" />
                    </div>
                    <p className="mt-3 text-sm font-semibold text-white">Paste a URL</p>
                    <p className="text-xs text-gray-500 mt-0.5">Manual fallback</p>
                </Link>
            </section>

            {/* Tip */}
            <section className="rounded-2xl border border-gray-800 bg-gray-900/60 p-4">
                <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Pro tip
                </p>
                <p className="mt-1 text-sm text-gray-300">
                    Share any TikTok to Zero from the share sheet (if installed as an app)
                    or use HTTP Shortcuts for a guaranteed path. Carousels you approve here
                    queue up for publishing automatically.
                </p>
            </section>
        </div>
    )
}

export default MobileHomePage
