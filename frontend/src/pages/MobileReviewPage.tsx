import { useMemo, useState } from 'react'
import {
    Check,
    X,
    Loader2,
    AlertTriangle,
    RefreshCw,
    Inbox,
    ChevronLeft,
    ChevronRight,
    List,
    Rows3,
    Star,
    Flag,
    Hash,
} from 'lucide-react'
import {
    useSmartReviewQueue,
    useApproveCarousel,
    useRejectCarousel,
    type CharacterCarousel,
} from '@/hooks/useCharacterContentApi'
import { CarouselSlidesView } from '@/components/mobile/CarouselSlidesView'
import { RejectSheet } from '@/components/mobile/RejectSheet'

type Mode = 'card' | 'list'

function ScorePill({
    label,
    value,
}: {
    label: string
    value: number | undefined
}) {
    const v = value ?? 0
    const color =
        v >= 8 ? 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/30'
        : v >= 6 ? 'text-amber-300 bg-amber-500/10 ring-amber-500/30'
        : 'text-red-300 bg-red-500/10 ring-red-500/30'
    return (
        <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ring-1 ${color}`}>
            <span className="opacity-70">{label}</span>
            <span className="tabular-nums">{v.toFixed(1)}</span>
        </div>
    )
}

function AIReviewCard({ carousel }: { carousel: CharacterCarousel }) {
    const r = carousel.ai_review
    if (!r) return null
    return (
        <div className="rounded-xl bg-gray-800/60 border border-gray-800 p-3 space-y-2">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-400">
                <Star className="w-3.5 h-3.5" />
                AI review
            </div>
            <div className="flex items-center flex-wrap gap-1.5">
                <ScorePill label="Hook" value={r.hook_strength} />
                <ScorePill label="Fact" value={r.fact_quality} />
                <ScorePill label="Engage" value={r.engagement_potential} />
                <ScorePill label="Overall" value={r.overall_score} />
            </div>
            {r.suggestions && r.suggestions.length > 0 && (
                <ul className="text-xs text-gray-400 list-disc pl-5 space-y-0.5">
                    {r.suggestions.slice(0, 3).map((s, i) => (
                        <li key={i}>{s}</li>
                    ))}
                </ul>
            )}
            {r.fact_check_flags && r.fact_check_flags.length > 0 && (
                <div className="flex items-start gap-1.5 text-xs text-amber-300 bg-amber-500/5 rounded-lg p-2">
                    <Flag className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <div>
                        {r.fact_check_flags.slice(0, 2).map((f, i) => (
                            <div key={i}>{f}</div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

function CarouselCard({
    carousel,
    onApprove,
    onRejectClick,
    isApproving,
}: {
    carousel: CharacterCarousel
    onApprove: () => void
    onRejectClick: () => void
    isApproving: boolean
}) {
    return (
        <div className="space-y-4">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="text-xs uppercase tracking-wide text-indigo-300 truncate">
                        {carousel.character_name || 'Unknown character'}
                    </p>
                    <h3 className="text-base font-semibold text-white truncate">
                        {carousel.angle}
                    </h3>
                </div>
                {carousel.ai_review?.overall_score !== undefined && (
                    <ScorePill label="Score" value={carousel.ai_review.overall_score} />
                )}
            </div>

            {carousel.hook_text && (
                <p className="text-sm text-gray-200 font-medium leading-snug">
                    {carousel.hook_text}
                </p>
            )}

            <CarouselSlidesView slides={carousel.slides} />

            {carousel.caption && (
                <div className="rounded-xl bg-gray-800/60 border border-gray-800 p-3">
                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Caption</p>
                    <p className="text-sm text-gray-200 whitespace-pre-wrap">
                        {carousel.caption}
                    </p>
                </div>
            )}

            {carousel.hashtags && carousel.hashtags.length > 0 && (
                <div className="flex items-center flex-wrap gap-1.5">
                    <Hash className="w-3.5 h-3.5 text-gray-500" />
                    {carousel.hashtags.slice(0, 8).map((h, i) => (
                        <span
                            key={i}
                            className="text-xs text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded-full"
                        >
                            #{h.replace(/^#/, '')}
                        </span>
                    ))}
                </div>
            )}

            <AIReviewCard carousel={carousel} />

            {/* Action bar - sticky so it's always reachable on long carousels */}
            <div
                className="sticky bottom-0 -mx-4 px-4 py-3 bg-gray-900/95 backdrop-blur border-t border-gray-800 flex items-center gap-2"
                style={{ paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }}
            >
                <button
                    onClick={onRejectClick}
                    disabled={isApproving}
                    className="flex-1 min-h-[48px] px-4 py-3 rounded-xl bg-red-600/10 border border-red-500/30 text-red-300 font-semibold hover:bg-red-600/20 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                    <X className="w-5 h-5" />
                    Reject
                </button>
                <button
                    onClick={onApprove}
                    disabled={isApproving}
                    className="flex-1 min-h-[48px] px-4 py-3 rounded-xl bg-emerald-600 text-white font-semibold hover:bg-emerald-500 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                    {isApproving ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                        <Check className="w-5 h-5" />
                    )}
                    Approve
                </button>
            </div>
        </div>
    )
}

export function MobileReviewPage() {
    const { data: queue = [], isLoading, error, refetch } = useSmartReviewQueue()
    const approve = useApproveCarousel()
    const reject = useRejectCarousel()

    const [mode, setMode] = useState<Mode>('card')
    const [index, setIndex] = useState(0)
    const [rejectOpen, setRejectOpen] = useState(false)
    const [selectedId, setSelectedId] = useState<string | null>(null)

    const current = useMemo(() => {
        if (mode === 'list') {
            return queue.find((c) => c.id === selectedId) ?? null
        }
        return queue[index] ?? null
    }, [mode, queue, index, selectedId])

    const handleApprove = async () => {
        if (!current) return
        try {
            await approve.mutateAsync({ id: current.id })
            // Stay at same index; queue shrinks so next item slides in.
            if (mode === 'list') setSelectedId(null)
            else if (index >= queue.length - 1) setIndex(Math.max(0, queue.length - 2))
        } catch (err) {
            console.error('approve failed', err)
        }
    }

    const handleReject = async (payload: { reason: string; human_notes?: string }) => {
        if (!current) return
        try {
            await reject.mutateAsync({ id: current.id, ...payload })
            setRejectOpen(false)
            if (mode === 'list') setSelectedId(null)
            else if (index >= queue.length - 1) setIndex(Math.max(0, queue.length - 2))
        } catch (err) {
            console.error('reject failed', err)
        }
    }

    // Loading state
    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
            </div>
        )
    }

    // Error state
    if (error) {
        return (
            <div className="rounded-2xl border border-red-800 bg-red-950/40 p-6 text-center">
                <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-400" />
                <p className="text-red-200 mb-4">Failed to load review queue</p>
                <button
                    onClick={() => refetch()}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium"
                >
                    <RefreshCw className="w-4 h-4" />
                    Try again
                </button>
            </div>
        )
    }

    // Empty state
    if (queue.length === 0) {
        return (
            <div className="rounded-2xl border border-gray-800 bg-gray-900/60 p-10 text-center">
                <Inbox className="w-10 h-10 mx-auto mb-3 text-gray-600" />
                <h3 className="text-lg font-semibold text-white mb-1">All caught up</h3>
                <p className="text-sm text-gray-400">
                    No carousels waiting for review right now.
                </p>
                <button
                    onClick={() => refetch()}
                    className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium"
                >
                    <RefreshCw className="w-4 h-4" />
                    Refresh
                </button>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {/* Mode toggle + counter */}
            <div className="flex items-center justify-between">
                <span className="text-sm text-gray-400">
                    {mode === 'card' ? (
                        <>
                            <span className="text-white font-semibold">{index + 1}</span>{' '}
                            of {queue.length}
                        </>
                    ) : (
                        <>{queue.length} pending</>
                    )}
                </span>
                <div className="inline-flex rounded-lg bg-gray-800 p-0.5 border border-gray-700">
                    <button
                        onClick={() => setMode('card')}
                        className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1 ${
                            mode === 'card' ? 'bg-gray-700 text-white' : 'text-gray-400'
                        }`}
                    >
                        <Rows3 className="w-3.5 h-3.5" />
                        Card
                    </button>
                    <button
                        onClick={() => setMode('list')}
                        className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1 ${
                            mode === 'list' ? 'bg-gray-700 text-white' : 'text-gray-400'
                        }`}
                    >
                        <List className="w-3.5 h-3.5" />
                        List
                    </button>
                </div>
            </div>

            {/* Card mode */}
            {mode === 'card' && current && (
                <>
                    <CarouselCard
                        carousel={current}
                        onApprove={handleApprove}
                        onRejectClick={() => setRejectOpen(true)}
                        isApproving={approve.isPending || reject.isPending}
                    />
                    {queue.length > 1 && (
                        <div className="flex items-center justify-between pt-2">
                            <button
                                onClick={() => setIndex((i) => Math.max(0, i - 1))}
                                disabled={index === 0}
                                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 disabled:opacity-40"
                            >
                                <ChevronLeft className="w-4 h-4" />
                                Prev
                            </button>
                            <button
                                onClick={() => setIndex((i) => Math.min(queue.length - 1, i + 1))}
                                disabled={index >= queue.length - 1}
                                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-300 disabled:opacity-40"
                            >
                                Next
                                <ChevronRight className="w-4 h-4" />
                            </button>
                        </div>
                    )}
                </>
            )}

            {/* List mode */}
            {mode === 'list' && (
                <>
                    {current ? (
                        <>
                            <button
                                onClick={() => setSelectedId(null)}
                                className="inline-flex items-center gap-1 text-sm text-indigo-300"
                            >
                                <ChevronLeft className="w-4 h-4" />
                                Back to list
                            </button>
                            <CarouselCard
                                carousel={current}
                                onApprove={handleApprove}
                                onRejectClick={() => setRejectOpen(true)}
                                isApproving={approve.isPending || reject.isPending}
                            />
                        </>
                    ) : (
                        <ul className="space-y-2">
                            {queue.map((c) => (
                                <li key={c.id}>
                                    <button
                                        onClick={() => setSelectedId(c.id)}
                                        className="w-full text-left rounded-xl border border-gray-800 bg-gray-900/60 hover:bg-gray-800 p-3 transition"
                                    >
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="min-w-0">
                                                <p className="text-xs uppercase tracking-wide text-indigo-300 truncate">
                                                    {c.character_name || 'Unknown'}
                                                </p>
                                                <p className="text-sm font-medium text-white truncate">
                                                    {c.angle}
                                                </p>
                                                {c.hook_text && (
                                                    <p className="text-xs text-gray-400 truncate mt-0.5">
                                                        {c.hook_text}
                                                    </p>
                                                )}
                                            </div>
                                            {c.ai_review?.overall_score !== undefined && (
                                                <ScorePill
                                                    label=""
                                                    value={c.ai_review.overall_score}
                                                />
                                            )}
                                        </div>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}

            <RejectSheet
                open={rejectOpen}
                onClose={() => setRejectOpen(false)}
                onConfirm={handleReject}
                isSubmitting={reject.isPending}
            />
        </div>
    )
}

export default MobileReviewPage
