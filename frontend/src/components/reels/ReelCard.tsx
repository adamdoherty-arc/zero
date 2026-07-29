import { useState } from 'react'
import {
    BadgeCheck,
    Check,
    Clock,
    Loader2,
    Mic,
    Music,
    Send,
    X,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
    apiBase,
    useApproveReel,
    usePublishReel,
    useRejectReel,
    type ReelRow,
} from '@/hooks/useReelsApi'
import { useToast } from '@/hooks/use-toast'

const SUB_NICHE_LABELS: Record<string, string> = {
    stoicism: 'Stoicism',
    discipline: 'Discipline',
    wealth_mindset: 'Wealth Mindset',
    self_improvement: 'Self Improvement',
    faith: 'Faith',
    grindset: 'Grindset',
    mental_health: 'Mental Health',
    entrepreneurship: 'Entrepreneurship',
    affirmations: 'Affirmations',
}

const MOOD_LABELS: Record<string, string> = {
    epic: 'Epic',
    calm: 'Calm',
    hopeful: 'Hopeful',
    dark: 'Dark',
    intense: 'Intense',
    reflective: 'Reflective',
    uplifting: 'Uplifting',
}

const STATUS_COLORS: Record<string, string> = {
    pending: 'bg-gray-600',
    sourcing: 'bg-sky-600',
    planning: 'bg-sky-600',
    rendering: 'bg-blue-600',
    assembling: 'bg-blue-600',
    awaiting_review: 'bg-yellow-600',
    publishing: 'bg-indigo-600',
    published: 'bg-purple-600',
    abandoned: 'bg-gray-700',
    failed: 'bg-red-600',
}

const IN_PROGRESS = new Set([
    'pending',
    'sourcing',
    'planning',
    'rendering',
    'assembling',
    'publishing',
])

function ScorePill({ value }: { value: number }) {
    const color =
        value >= 8
            ? 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/30'
            : value >= 6
              ? 'text-amber-300 bg-amber-500/10 ring-amber-500/30'
              : 'text-red-300 bg-red-500/10 ring-red-500/30'
    return (
        <div
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ring-1 ${color}`}
            title="Composite score"
        >
            <span className="opacity-70">Score</span>
            <span className="tabular-nums">{value.toFixed(1)}</span>
        </div>
    )
}

export interface ReelCardProps {
    reel: ReelRow
}

/**
 * Canonical Motivation Reels card. Renders the produced MP4 as a vertical
 * 9:16 HTML5 video plus the quote, niche/mood badges, music, caption,
 * hashtags, and approve / reject / publish actions. Dark theme — matches
 * the character-content CarouselCard styling.
 */
export function ReelCard({ reel }: ReelCardProps) {
    const { toast } = useToast()
    const approve = useApproveReel()
    const reject = useRejectReel()
    const publish = usePublishReel()
    const [captionOpen, setCaptionOpen] = useState(false)

    const inProgress = IN_PROGRESS.has(reel.status)
    const videoSrc = reel.video_url
        ? `${apiBase}${reel.video_url}`
        : `${apiBase}/api/reels/${reel.id}/video`

    const subNicheLabel = SUB_NICHE_LABELS[reel.sub_niche] || reel.sub_niche
    const moodLabel = reel.mood ? MOOD_LABELS[reel.mood] || reel.mood : null
    const showAuthor =
        !!reel.quote?.author && reel.quote?.attribution === 'verified'
    const score = reel.composite_score ?? null

    const busy = approve.isPending || reject.isPending || publish.isPending

    const handleApprove = () => {
        approve.mutate(reel.id, {
            onSuccess: () =>
                toast({ title: 'Approved', description: 'Reel published (dry-run).' }),
            onError: (e) =>
                toast({
                    title: 'Approve failed',
                    description: String((e as Error).message || e),
                    variant: 'destructive',
                }),
        })
    }

    const handleReject = () => {
        if (!window.confirm('Reject this reel? It will be abandoned.')) return
        reject.mutate(reel.id, {
            onSuccess: () => toast({ title: 'Rejected', description: 'Reel abandoned.' }),
            onError: (e) =>
                toast({
                    title: 'Reject failed',
                    description: String((e as Error).message || e),
                    variant: 'destructive',
                }),
        })
    }

    const handlePublish = () => {
        publish.mutate(
            { id: reel.id, platforms: ['tiktok', 'instagram'] },
            {
                onSuccess: () =>
                    toast({ title: 'Published', description: 'Sent to TikTok + Instagram (dry-run).' }),
                onError: (e) =>
                    toast({
                        title: 'Publish failed',
                        description: String((e as Error).message || e),
                        variant: 'destructive',
                    }),
            },
        )
    }

    return (
        <Card className="bg-gray-800/50 border-gray-700 overflow-hidden">
            <CardContent className="p-3 space-y-3">
                {/* Header: niche / mood / status / score */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                        <Badge className="bg-indigo-600 text-white text-xs">{subNicheLabel}</Badge>
                        {moodLabel && (
                            <Badge variant="outline" className="text-xs border-gray-600 text-gray-300">
                                {moodLabel}
                            </Badge>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                        {score != null && <ScorePill value={score} />}
                        <Badge
                            className={`${STATUS_COLORS[reel.status] || 'bg-gray-500'} text-white text-xs inline-flex items-center gap-1`}
                        >
                            {inProgress && <Loader2 className="w-3 h-3 animate-spin" />}
                            {reel.status.replace(/_/g, ' ')}
                        </Badge>
                    </div>
                </div>

                {/* Vertical 9:16 video */}
                <div className="flex justify-center">
                    <video
                        src={videoSrc}
                        controls
                        loop
                        muted
                        playsInline
                        preload="metadata"
                        className="w-full max-h-[520px] aspect-[9/16] rounded-lg bg-black object-contain"
                    />
                </div>

                {/* Quote */}
                {reel.quote?.text && (
                    <div className="bg-indigo-950/30 border border-indigo-500/30 rounded-lg p-2.5">
                        <div className="text-white font-medium italic leading-snug break-words">
                            "{reel.quote.text}"
                        </div>
                        {showAuthor && (
                            <div className="mt-1 flex items-center gap-1 text-xs text-indigo-300">
                                <BadgeCheck className="w-3 h-3" />
                                <span>{reel.quote.author}</span>
                                {reel.quote.source_work && (
                                    <span className="text-gray-500">- {reel.quote.source_work}</span>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* Meta row: music / duration / voiceover */}
                <div className="flex items-center gap-3 flex-wrap text-xs text-gray-500">
                    {reel.music?.title && (
                        <span className="flex items-center gap-1">
                            <Music className="w-3 h-3" />
                            {reel.music.title}
                            {reel.music.bpm ? ` - ${reel.music.bpm} BPM` : ''}
                        </span>
                    )}
                    {reel.duration_s != null && (
                        <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {reel.duration_s.toFixed(0)}s
                        </span>
                    )}
                    {reel.voiceover && (
                        <span className="flex items-center gap-1 text-indigo-300">
                            <Mic className="w-3 h-3" />
                            Voiceover
                        </span>
                    )}
                    {reel.scenes?.length > 0 && (
                        <span>{reel.scenes.length} scenes</span>
                    )}
                </div>

                {/* Caption (collapsed) */}
                {reel.caption && (
                    <div className="text-sm text-gray-300">
                        <button
                            type="button"
                            onClick={() => setCaptionOpen((v) => !v)}
                            className="text-xs text-indigo-400 hover:text-indigo-300 mb-1"
                            aria-expanded={captionOpen}
                        >
                            {captionOpen ? 'Hide caption' : 'Show caption'}
                        </button>
                        {captionOpen && (
                            <p className="whitespace-pre-wrap break-words text-gray-300 italic">
                                {reel.caption}
                            </p>
                        )}
                    </div>
                )}

                {/* CTA */}
                {reel.cta_text && (
                    <div className="text-xs text-gray-400">
                        <span className="text-gray-500">CTA: </span>
                        {reel.cta_text}
                    </div>
                )}

                {/* Hashtags */}
                {reel.hashtags?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                        {reel.hashtags.map((tag) => (
                            <Badge
                                key={tag}
                                variant="outline"
                                className="text-xs border-indigo-500/30 text-indigo-400"
                            >
                                #{tag.replace(/^#/, '')}
                            </Badge>
                        ))}
                    </div>
                )}

                {/* Platform publishes */}
                {reel.platform_publishes?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                        {reel.platform_publishes.map((p, i) => (
                            <Badge
                                key={`${p.platform}-${i}`}
                                variant="outline"
                                className="text-xs border-gray-600 text-gray-400"
                                title={p.post_id ? `post ${p.post_id}` : undefined}
                            >
                                {p.platform}: {p.status}
                                {p.dry_run ? ' (dry-run)' : ''}
                            </Badge>
                        ))}
                    </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 pt-1 flex-wrap">
                    <Button
                        size="sm"
                        onClick={handleApprove}
                        disabled={busy}
                        className="bg-emerald-600 hover:bg-emerald-500 text-white"
                        aria-label="Approve reel"
                    >
                        {approve.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                        ) : (
                            <Check className="w-3 h-3 mr-1" />
                        )}
                        Approve
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={handleReject}
                        disabled={busy}
                        className="border-red-500/40 text-red-300 hover:bg-red-500/10 hover:text-red-200"
                        aria-label="Reject reel"
                    >
                        {reject.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                        ) : (
                            <X className="w-3 h-3 mr-1" />
                        )}
                        Reject
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={handlePublish}
                        disabled={busy}
                        className="border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/10 hover:text-indigo-200"
                        aria-label="Publish reel"
                    >
                        {publish.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                        ) : (
                            <Send className="w-3 h-3 mr-1" />
                        )}
                        Publish
                    </Button>
                </div>
            </CardContent>
        </Card>
    )
}

export default ReelCard
