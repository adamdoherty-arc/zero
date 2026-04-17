import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import {
    ExternalLink,
    Loader2,
    RotateCcw,
    Trash2,
    Sparkles,
    UserPlus,
    Wand2,
    Check,
    AlertTriangle,
} from 'lucide-react'
import {
    type CharacterReferenceVideo,
    useAssignReferenceVideoCharacter,
    useApplyReferenceVideoFacts,
    usePromoteReferenceVideoToCharacter,
    useReanalyzeReferenceVideo,
    useRetryReferenceVideo,
    useDeleteReferenceVideo,
    getReferenceVideoFileUrl,
} from '@/hooks/useCharacterReferenceVideoApi'

interface Props {
    video: CharacterReferenceVideo
    characters: { id: string; name: string }[]
    onClose: () => void
}

export function ReferenceVideoDetailModal({ video, characters, onClose }: Props) {
    const [assignTo, setAssignTo] = useState(video.character_id ?? '')
    const [selectedFactIdx, setSelectedFactIdx] = useState<Set<number>>(
        () => new Set((video.extracted_facts ?? []).map((_, i) => i)),
    )

    const assign = useAssignReferenceVideoCharacter()
    const applyFacts = useApplyReferenceVideoFacts()
    const promote = usePromoteReferenceVideoToCharacter()
    const reanalyze = useReanalyzeReferenceVideo()
    const retry = useRetryReferenceVideo()
    const del = useDeleteReferenceVideo()

    const videoUrl = video.video_path ? getReferenceVideoFileUrl(video.id, 'video') : null
    const isIncomplete = ['pending', 'downloading', 'downloaded', 'transcribing', 'analyzing'].includes(video.status)

    const toggleFact = (idx: number) => {
        const next = new Set(selectedFactIdx)
        if (next.has(idx)) next.delete(idx)
        else next.add(idx)
        setSelectedFactIdx(next)
    }

    const handleAssign = async () => {
        if (!assignTo) return
        await assign.mutateAsync({ id: video.id, character_id: assignTo })
    }

    const handleApplyFacts = async () => {
        const indexes = Array.from(selectedFactIdx.values())
        await applyFacts.mutateAsync({ id: video.id, fact_indexes: indexes })
    }

    const handlePromote = async () => {
        try {
            await promote.mutateAsync({ id: video.id })
        } catch (err) {
            console.error('promote failed', err)
        }
    }

    const handleDelete = async () => {
        if (!confirm('Delete this reference video? This removes the record and files on disk.')) return
        await del.mutateAsync(video.id)
        onClose()
    }

    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-5xl max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2 pr-8">
                        <span className="truncate">{video.title || video.caption || 'TikTok Reference'}</span>
                        <Badge variant="outline" className="ml-2 bg-gray-800 border-gray-700 text-xs uppercase">
                            {video.status}
                        </Badge>
                    </DialogTitle>
                </DialogHeader>

                {video.status === 'failed' && video.error_message && (
                    <div className="bg-red-950 border border-red-800 rounded p-3 flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                            <p className="text-sm text-red-200 font-medium">Processing failed</p>
                            <p className="text-xs text-red-300/80 mt-1">{video.error_message}</p>
                            <Button
                                size="sm"
                                onClick={() => retry.mutate(video.id)}
                                className="mt-2 bg-red-800 hover:bg-red-700"
                            >
                                <RotateCcw className="w-3 h-3 mr-1" /> Retry
                            </Button>
                        </div>
                    </div>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {/* Left: video + transcript */}
                    <div className="space-y-3">
                        <div className="aspect-[9/16] bg-black rounded overflow-hidden">
                            {videoUrl ? (
                                <video
                                    controls
                                    playsInline
                                    className="w-full h-full"
                                    src={videoUrl}
                                    preload="metadata"
                                />
                            ) : (
                                <div className="w-full h-full flex items-center justify-center text-gray-500">
                                    {isIncomplete ? (
                                        <div className="text-center">
                                            <Loader2 className="w-8 h-8 animate-spin mx-auto mb-2" />
                                            <p className="text-sm">Processing...</p>
                                        </div>
                                    ) : (
                                        <p className="text-sm">No video file</p>
                                    )}
                                </div>
                            )}
                        </div>
                        <div className="space-y-1 text-sm">
                            <a
                                href={video.tiktok_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-indigo-300 hover:underline inline-flex items-center gap-1"
                            >
                                <ExternalLink className="w-3 h-3" />
                                Open on TikTok
                            </a>
                            <p className="text-gray-400">
                                {video.author_name ? `@${video.author_name}` : 'Unknown author'}
                                {video.duration_seconds ? ` · ${Math.round(video.duration_seconds)}s` : ''}
                            </p>
                            {video.hashtags?.length > 0 && (
                                <p className="text-gray-500 text-xs flex flex-wrap gap-1">
                                    {video.hashtags.slice(0, 12).map((h) => (
                                        <span key={h} className="bg-gray-800 px-1.5 py-0.5 rounded">
                                            #{h}
                                        </span>
                                    ))}
                                </p>
                            )}
                        </div>
                    </div>

                    {/* Right: analysis tabs + actions */}
                    <div className="space-y-3">
                        {/* Assign character */}
                        <div className="bg-gray-800 border border-gray-700 rounded p-3 space-y-2">
                            <label className="text-xs text-gray-400 uppercase tracking-wide">Character</label>
                            <div className="flex gap-2">
                                <Select value={assignTo} onValueChange={setAssignTo}>
                                    <SelectTrigger className="bg-gray-900 border-gray-700 flex-1">
                                        <SelectValue placeholder="Select character" />
                                    </SelectTrigger>
                                    <SelectContent className="bg-gray-800 border-gray-700 text-white">
                                        {characters.map((c) => (
                                            <SelectItem key={c.id} value={c.id}>
                                                {c.name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <Button
                                    size="sm"
                                    onClick={handleAssign}
                                    disabled={!assignTo || assign.isPending || assignTo === video.character_id}
                                >
                                    {assign.isPending ? (
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                    ) : (
                                        <>
                                            <UserPlus className="w-4 h-4 mr-1" />
                                            Assign
                                        </>
                                    )}
                                </Button>
                            </div>
                        </div>

                        <Tabs defaultValue="style">
                            <TabsList className="bg-gray-800 border border-gray-700">
                                <TabsTrigger value="style">Style</TabsTrigger>
                                <TabsTrigger value="facts">Facts</TabsTrigger>
                                <TabsTrigger value="discovery">Discovery</TabsTrigger>
                                <TabsTrigger value="transcript">Transcript</TabsTrigger>
                            </TabsList>

                            <TabsContent value="style">
                                {video.style_analysis ? (
                                    <div className="space-y-2 text-sm bg-gray-800 border border-gray-700 rounded p-3">
                                        <Field label="Hook" value={video.style_analysis.hook} />
                                        <Field label="Structure" value={video.style_analysis.structure} />
                                        <Field label="Pacing" value={video.style_analysis.pacing} />
                                        <Field label="Visual style" value={video.style_analysis.visual_style} />
                                        <Field label="Transitions" value={video.style_analysis.transitions} />
                                        <Field
                                            label="Estimated engagement"
                                            value={video.style_analysis.estimated_engagement}
                                        />
                                    </div>
                                ) : (
                                    <EmptyPane label="No style analysis yet" />
                                )}
                            </TabsContent>

                            <TabsContent value="facts">
                                {video.extracted_facts?.length ? (
                                    <div className="space-y-2">
                                        <div className="space-y-1 max-h-80 overflow-y-auto bg-gray-800 border border-gray-700 rounded p-3">
                                            {video.extracted_facts.map((f, idx) => (
                                                <label
                                                    key={idx}
                                                    className="flex items-start gap-2 py-1 cursor-pointer hover:bg-gray-700/50 rounded px-1"
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedFactIdx.has(idx)}
                                                        onChange={() => toggleFact(idx)}
                                                        className="mt-1"
                                                    />
                                                    <div className="flex-1">
                                                        <p className="text-sm text-gray-200">{f.text}</p>
                                                        <div className="flex items-center gap-2 mt-0.5 text-[11px] text-gray-400">
                                                            {f.category && (
                                                                <span className="bg-gray-700 px-1.5 py-0.5 rounded">
                                                                    {f.category}
                                                                </span>
                                                            )}
                                                            {f.surprise_score != null && (
                                                                <span>surprise: {f.surprise_score.toFixed(2)}</span>
                                                            )}
                                                            {f.source_timecode && <span>@ {f.source_timecode}</span>}
                                                        </div>
                                                    </div>
                                                </label>
                                            ))}
                                        </div>
                                        <Button
                                            size="sm"
                                            onClick={handleApplyFacts}
                                            disabled={!video.character_id || applyFacts.isPending || selectedFactIdx.size === 0}
                                            className="bg-emerald-600 hover:bg-emerald-500"
                                        >
                                            {applyFacts.isPending ? (
                                                <Loader2 className="w-4 h-4 animate-spin" />
                                            ) : (
                                                <>
                                                    <Check className="w-4 h-4 mr-1" />
                                                    Apply {selectedFactIdx.size} facts
                                                </>
                                            )}
                                        </Button>
                                        {!video.character_id && (
                                            <p className="text-xs text-yellow-400/80">
                                                Assign a character first to apply facts.
                                            </p>
                                        )}
                                    </div>
                                ) : (
                                    <EmptyPane label="No facts extracted" />
                                )}
                            </TabsContent>

                            <TabsContent value="discovery">
                                {video.proposed_character?.name ? (
                                    <div className="space-y-3 bg-gray-800 border border-gray-700 rounded p-3">
                                        <div>
                                            <p className="text-xs text-gray-400 uppercase tracking-wide">Name</p>
                                            <p className="text-white font-medium">{video.proposed_character.name}</p>
                                        </div>
                                        {video.proposed_character.universe && (
                                            <Field label="Universe" value={video.proposed_character.universe} />
                                        )}
                                        {video.proposed_character.franchise && (
                                            <Field label="Franchise" value={video.proposed_character.franchise} />
                                        )}
                                        {video.proposed_character.description && (
                                            <Field
                                                label="Description"
                                                value={video.proposed_character.description}
                                            />
                                        )}
                                        {video.proposed_character.seed_facts &&
                                            video.proposed_character.seed_facts.length > 0 && (
                                                <div>
                                                    <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
                                                        Seed facts
                                                    </p>
                                                    <ul className="text-sm text-gray-200 space-y-1 list-disc pl-5">
                                                        {video.proposed_character.seed_facts.map((f, i) => (
                                                            <li key={i}>{f.text}</li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                        <Button
                                            size="sm"
                                            onClick={handlePromote}
                                            disabled={promote.isPending || !!video.promoted_character_id}
                                            className="bg-fuchsia-600 hover:bg-fuchsia-500"
                                        >
                                            {promote.isPending ? (
                                                <Loader2 className="w-4 h-4 animate-spin" />
                                            ) : video.promoted_character_id ? (
                                                'Already promoted'
                                            ) : (
                                                <>
                                                    <Sparkles className="w-4 h-4 mr-1" />
                                                    Promote to Character
                                                </>
                                            )}
                                        </Button>
                                    </div>
                                ) : (
                                    <EmptyPane label="No character proposed" />
                                )}
                            </TabsContent>

                            <TabsContent value="transcript">
                                <div className="bg-gray-800 border border-gray-700 rounded p-3 max-h-96 overflow-y-auto">
                                    {video.transcript ? (
                                        <p className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
                                            {video.transcript}
                                        </p>
                                    ) : (
                                        <p className="text-sm text-gray-500">No transcript yet.</p>
                                    )}
                                </div>
                            </TabsContent>
                        </Tabs>
                    </div>
                </div>

                {/* Footer actions */}
                <div className="flex items-center gap-2 pt-3 border-t border-gray-800">
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => reanalyze.mutate(video.id)}
                        disabled={reanalyze.isPending || !video.transcript}
                        className="bg-gray-800 border-gray-700"
                    >
                        {reanalyze.isPending ? (
                            <Loader2 className="w-4 h-4 animate-spin mr-1" />
                        ) : (
                            <Wand2 className="w-4 h-4 mr-1" />
                        )}
                        Re-analyze
                    </Button>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => retry.mutate(video.id)}
                        disabled={retry.isPending}
                        className="bg-gray-800 border-gray-700"
                    >
                        <RotateCcw className="w-4 h-4 mr-1" />
                        Retry pipeline
                    </Button>
                    <div className="flex-1" />
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={handleDelete}
                        disabled={del.isPending}
                        className="bg-red-950 border-red-800 text-red-200 hover:bg-red-900"
                    >
                        {del.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    )
}

function Field({ label, value }: { label: string; value?: string | null }) {
    if (!value) return null
    return (
        <div>
            <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
            <p className="text-sm text-gray-200">{value}</p>
        </div>
    )
}

function EmptyPane({ label }: { label: string }) {
    return (
        <div className="bg-gray-800 border border-gray-700 rounded p-6 text-center text-sm text-gray-500">
            {label}
        </div>
    )
}
