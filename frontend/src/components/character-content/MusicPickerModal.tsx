import { useMemo, useRef, useState } from 'react'
import { Flame, Music2, Pause, Play, Search as SearchIcon, Sparkles } from 'lucide-react'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import {
    useAssignMusic,
    useMusicTracks,
    useTrendingMusic,
} from '@/hooks/useCharacterContentApi'
import type { MusicTrack } from '@/hooks/useCharacterContentApi'

const MOODS = [
    { key: 'epic', label: 'Epic' },
    { key: 'dark', label: 'Dark' },
    { key: 'emotional', label: 'Emotional' },
    { key: 'mysterious', label: 'Mysterious' },
    { key: 'dramatic', label: 'Dramatic' },
    { key: 'hype', label: 'Hype' },
    { key: 'chill', label: 'Chill' },
] as const

export interface MusicPickerModalProps {
    open: boolean
    onOpenChange: (v: boolean) => void
    carouselId: string
    currentTrackId?: string
    onAssigned?: (trackId: string) => void
}

export default function MusicPickerModal({
    open,
    onOpenChange,
    carouselId,
    currentTrackId,
    onAssigned,
}: MusicPickerModalProps) {
    const [mood, setMood] = useState<string | undefined>(undefined)
    const [showTrending, setShowTrending] = useState(false)
    const [query, setQuery] = useState('')
    const moodQuery = useMusicTracks(mood)
    const trendingQuery = useTrendingMusic()
    const assign = useAssignMusic()

    const tracks: MusicTrack[] = showTrending
        ? trendingQuery.data || []
        : moodQuery.data || []

    const filtered = useMemo(() => {
        if (!query.trim()) return tracks
        const q = query.trim().toLowerCase()
        return tracks.filter(
            t =>
                t.name.toLowerCase().includes(q) ||
                (t.artist || '').toLowerCase().includes(q),
        )
    }, [tracks, query])

    const isLoading = showTrending ? trendingQuery.isLoading : moodQuery.isLoading

    const handleAssign = async (trackId: string) => {
        await assign.mutateAsync({ carouselId, trackId })
        onAssigned?.(trackId)
        onOpenChange(false)
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-gray-950 border-gray-800 text-white">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Music2 className="w-5 h-5 text-indigo-400" />
                        Pick music
                    </DialogTitle>
                </DialogHeader>

                <div className="flex flex-col gap-3">
                    {/* Search */}
                    <div className="relative">
                        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                        <input
                            type="text"
                            value={query}
                            onChange={e => setQuery(e.target.value)}
                            placeholder="Search by name or artist"
                            className="w-full pl-9 pr-3 py-2 rounded-md bg-gray-900 border border-gray-800 text-sm focus:outline-none focus:border-indigo-500"
                        />
                    </div>

                    {/* Mood + trending filters */}
                    <div className="flex items-center gap-2 flex-wrap">
                        <button
                            type="button"
                            onClick={() => {
                                setShowTrending(true)
                                setMood(undefined)
                            }}
                            className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold transition ${
                                showTrending
                                    ? 'bg-rose-500 text-white'
                                    : 'bg-gray-800 hover:bg-gray-700 text-gray-300'
                            }`}
                        >
                            <Flame className="w-3 h-3" />
                            Trending
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setShowTrending(false)
                                setMood(undefined)
                            }}
                            className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                                !showTrending && !mood
                                    ? 'bg-indigo-600 text-white'
                                    : 'bg-gray-800 hover:bg-gray-700 text-gray-300'
                            }`}
                        >
                            All
                        </button>
                        {MOODS.map(m => (
                            <button
                                key={m.key}
                                type="button"
                                onClick={() => {
                                    setShowTrending(false)
                                    setMood(m.key)
                                }}
                                className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                                    !showTrending && mood === m.key
                                        ? 'bg-indigo-600 text-white'
                                        : 'bg-gray-800 hover:bg-gray-700 text-gray-300'
                                }`}
                            >
                                {m.label}
                            </button>
                        ))}
                    </div>

                    {/* Track list */}
                    <div className="max-h-[50vh] overflow-y-auto flex flex-col gap-1 pr-1">
                        {isLoading ? (
                            <p className="text-gray-400 text-sm py-8 text-center">Loading tracks...</p>
                        ) : filtered.length === 0 ? (
                            <div className="text-gray-400 text-sm py-8 text-center">
                                <p>No tracks match your filters.</p>
                                <p className="text-xs mt-1">
                                    Try a different mood or search term, or seed the library from Content
                                    Studio.
                                </p>
                            </div>
                        ) : (
                            filtered.map(track => (
                                <TrackRow
                                    key={track.id}
                                    track={track}
                                    isSelected={track.id === currentTrackId}
                                    isAssigning={assign.isPending}
                                    onAssign={() => handleAssign(track.id)}
                                />
                            ))
                        )}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}

function TrackRow({
    track,
    isSelected,
    isAssigning,
    onAssign,
}: {
    track: MusicTrack
    isSelected: boolean
    isAssigning: boolean
    onAssign: () => void
}) {
    const [playing, setPlaying] = useState(false)
    const audioRef = useRef<HTMLAudioElement | null>(null)

    const togglePlay = () => {
        const el = audioRef.current
        if (!el) return
        if (playing) {
            el.pause()
            setPlaying(false)
        } else {
            el.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
        }
    }

    return (
        <div
            className={`flex items-center gap-3 rounded-lg px-3 py-2 ${
                isSelected
                    ? 'bg-indigo-950 border border-indigo-700'
                    : 'hover:bg-gray-900'
            }`}
        >
            {/* Preview button */}
            {track.preview_url ? (
                <>
                    <button
                        type="button"
                        onClick={togglePlay}
                        className="w-8 h-8 shrink-0 rounded-full bg-indigo-600 hover:bg-indigo-500 flex items-center justify-center text-white"
                        aria-label={playing ? 'Pause preview' : 'Play preview'}
                    >
                        {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    </button>
                    <audio
                        ref={audioRef}
                        src={track.preview_url}
                        onEnded={() => setPlaying(false)}
                        preload="none"
                    />
                </>
            ) : (
                <div
                    className="w-8 h-8 shrink-0 rounded-full bg-gray-800 flex items-center justify-center text-gray-500"
                    title="No audio preview"
                >
                    <Music2 className="w-3.5 h-3.5" />
                </div>
            )}

            {/* Name + artist */}
            <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-white truncate">{track.name}</div>
                <div className="text-xs text-gray-400 truncate">
                    {track.artist || 'Unknown artist'}
                </div>
            </div>

            {/* Mood + trending badges */}
            <div className="flex items-center gap-1 shrink-0">
                <span className="rounded bg-gray-800 px-2 py-0.5 text-[10px] font-semibold uppercase text-gray-300">
                    {track.mood}
                </span>
                {track.is_trending && (
                    <span className="flex items-center gap-0.5 rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">
                        <Sparkles className="w-3 h-3" />
                        Trending
                    </span>
                )}
            </div>

            {/* Assign button */}
            <button
                type="button"
                onClick={onAssign}
                disabled={isAssigning || isSelected}
                className="shrink-0 rounded px-3 py-1 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white"
            >
                {isSelected ? 'Selected' : isAssigning ? '...' : 'Assign'}
            </button>
        </div>
    )
}
