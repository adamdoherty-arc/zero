import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Film, Loader2, AlertTriangle, User, Clock } from 'lucide-react'
import {
    type CharacterReferenceVideo,
    type RefVideoStatus,
    getReferenceVideoFileUrl,
} from '@/hooks/useCharacterReferenceVideoApi'

interface Props {
    video: CharacterReferenceVideo
    characterName?: string
    onOpen: () => void
}

const STATUS_COLOR: Record<RefVideoStatus, string> = {
    pending: 'bg-gray-600',
    downloading: 'bg-blue-600',
    downloaded: 'bg-blue-500',
    transcribing: 'bg-indigo-600',
    analyzing: 'bg-purple-600',
    ready: 'bg-green-600',
    failed: 'bg-red-600',
}

const INTENT_COLOR: Record<string, string> = {
    inbox: 'bg-gray-700',
    inspiration: 'bg-yellow-700',
    facts: 'bg-emerald-700',
    discovery: 'bg-fuchsia-700',
}

function relativeTime(iso: string): string {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    const mins = Math.floor(diff / 60_000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(hours / 24)
    return `${days}d ago`
}

export function ReferenceVideoCard({ video, characterName, onOpen }: Props) {
    const thumb = video.thumbnail_path
        ? getReferenceVideoFileUrl(video.id, 'thumbnail')
        : video.thumbnail_url ?? null

    const incomplete = ['pending', 'downloading', 'downloaded', 'transcribing', 'analyzing'].includes(video.status)

    return (
        <Card
            onClick={onOpen}
            className="bg-gray-800 border-gray-700 overflow-hidden cursor-pointer hover:border-indigo-500 transition"
        >
            <div className="aspect-[9/16] bg-gray-900 relative">
                {thumb ? (
                    <img
                        src={thumb}
                        alt={video.title ?? 'TikTok reference'}
                        className="w-full h-full object-cover"
                        loading="lazy"
                        onError={(e) => {
                            ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                        }}
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-600">
                        <Film className="w-12 h-12" />
                    </div>
                )}

                {/* Top-right status */}
                <div className="absolute top-2 right-2 flex items-center gap-1">
                    <Badge className={`${STATUS_COLOR[video.status]} text-white text-[10px] uppercase tracking-wide`}>
                        {incomplete && <Loader2 className="w-3 h-3 mr-1 animate-spin" />}
                        {video.status === 'failed' && <AlertTriangle className="w-3 h-3 mr-1" />}
                        {video.status}
                    </Badge>
                </div>
                {/* Top-left intent */}
                <div className="absolute top-2 left-2">
                    <Badge className={`${INTENT_COLOR[video.intent] ?? 'bg-gray-700'} text-white text-[10px] uppercase tracking-wide`}>
                        {video.intent}
                    </Badge>
                </div>

                {/* Duration */}
                {video.duration_seconds != null && (
                    <div className="absolute bottom-2 right-2 bg-black/70 text-white text-[10px] px-1.5 py-0.5 rounded">
                        {Math.round(video.duration_seconds)}s
                    </div>
                )}
            </div>

            <div className="p-3 space-y-2">
                <div className="text-sm text-white font-medium line-clamp-2 min-h-[2.5rem]">
                    {video.title || video.caption || 'Untitled TikTok'}
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                    <User className="w-3 h-3" />
                    <span className="truncate">{video.author_name ?? 'Unknown'}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                    {characterName ? (
                        <Badge variant="outline" className="bg-indigo-950 text-indigo-200 border-indigo-800">
                            {characterName}
                        </Badge>
                    ) : (
                        <span className="text-gray-500">Unassigned</span>
                    )}
                    <span className="text-gray-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {relativeTime(video.created_at)}
                    </span>
                </div>
                {video.status === 'failed' && video.error_message && (
                    <p className="text-[11px] text-red-300/80 line-clamp-2">{video.error_message}</p>
                )}
            </div>
        </Card>
    )
}
