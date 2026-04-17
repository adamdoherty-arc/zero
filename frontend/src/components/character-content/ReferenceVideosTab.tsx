import { useMemo, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import {
    Film,
    Inbox,
    Lightbulb,
    BookOpen,
    Search,
    Loader2,
    AlertTriangle,
    RefreshCw,
    Smartphone,
    Plus,
} from 'lucide-react'
import {
    useReferenceVideos,
    useIngestReferenceVideo,
    type CharacterReferenceVideo,
    type RefVideoIntent,
    type RefVideoStatus,
} from '@/hooks/useCharacterReferenceVideoApi'
import { useCharacters } from '@/hooks/useCharacterContentApi'
import { ReferenceVideoCard } from './ReferenceVideoCard'
import { ReferenceVideoDetailModal } from './ReferenceVideoDetailModal'
import { AndroidSetupModal } from './AndroidSetupModal'

const INTENT_PILLS: { value: 'all' | RefVideoIntent; label: string; icon: React.ElementType }[] = [
    { value: 'all', label: 'All', icon: Film },
    { value: 'inbox', label: 'Inbox', icon: Inbox },
    { value: 'inspiration', label: 'Inspiration', icon: Lightbulb },
    { value: 'facts', label: 'Facts', icon: BookOpen },
    { value: 'discovery', label: 'Discovery', icon: Search },
]

export interface ReferenceVideosTabProps {
    /** Optional: pre-filter to a single character (used on CharacterDetailPage). */
    characterId?: string
    /** Hide the character selector (when already scoped to one character). */
    hideCharacterFilter?: boolean
}

export function ReferenceVideosTab({ characterId, hideCharacterFilter = false }: ReferenceVideosTabProps) {
    const [intent, setIntent] = useState<'all' | RefVideoIntent>('all')
    const [statusFilter, setStatusFilter] = useState<'all' | RefVideoStatus>('all')
    const [selectedCharacter, setSelectedCharacter] = useState<string>(characterId ?? 'all')
    const [pasteUrl, setPasteUrl] = useState('')
    const [detailId, setDetailId] = useState<string | null>(null)
    const [showAndroidSetup, setShowAndroidSetup] = useState(false)

    const effectiveCharacterId = characterId ?? (selectedCharacter !== 'all' ? selectedCharacter : undefined)

    const { data: videos = [], isLoading, error, refetch } = useReferenceVideos({
        character_id: effectiveCharacterId,
        intent: intent === 'all' ? undefined : intent,
        status: statusFilter === 'all' ? undefined : statusFilter,
        limit: 60,
    })

    const { data: characters = [] } = useCharacters()
    const characterMap = useMemo(() => {
        const m = new Map<string, string>()
        for (const c of characters) m.set(c.id, c.name)
        return m
    }, [characters])

    const ingest = useIngestReferenceVideo()

    const handlePaste = async () => {
        const url = pasteUrl.trim()
        if (!url) return
        try {
            await ingest.mutateAsync({
                url,
                character_id: effectiveCharacterId,
                intent: 'inbox',
            })
            setPasteUrl('')
        } catch (err) {
            console.error('ingest failed', err)
        }
    }

    const detail = detailId ? videos.find((v) => v.id === detailId) : null

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                    <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                        <Film className="w-6 h-6 text-indigo-400" />
                        Reference Videos
                    </h2>
                    <p className="text-sm text-gray-400 mt-1">
                        TikTok videos captured from your phone for style inspiration, facts, and discovery.
                    </p>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowAndroidSetup(true)}
                    className="bg-gray-800 border-gray-700 hover:bg-gray-700"
                >
                    <Smartphone className="w-4 h-4 mr-2" />
                    Set up Android sharing
                </Button>
            </div>

            {/* Intent pills */}
            <div className="flex items-center gap-2 flex-wrap">
                {INTENT_PILLS.map(({ value, label, icon: Icon }) => (
                    <button
                        key={value}
                        onClick={() => setIntent(value)}
                        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm transition ${
                            intent === value
                                ? 'bg-indigo-600 border-indigo-500 text-white'
                                : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700'
                        }`}
                    >
                        <Icon className="w-3.5 h-3.5" />
                        {label}
                    </button>
                ))}
            </div>

            {/* Filters + paste */}
            <div className="flex items-center gap-3 flex-wrap">
                <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as 'all' | RefVideoStatus)}>
                    <SelectTrigger className="w-40 bg-gray-800 border-gray-700 text-white">
                        <SelectValue placeholder="Status" />
                    </SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-700 text-white">
                        <SelectItem value="all">All statuses</SelectItem>
                        <SelectItem value="pending">Pending</SelectItem>
                        <SelectItem value="downloading">Downloading</SelectItem>
                        <SelectItem value="transcribing">Transcribing</SelectItem>
                        <SelectItem value="analyzing">Analyzing</SelectItem>
                        <SelectItem value="ready">Ready</SelectItem>
                        <SelectItem value="failed">Failed</SelectItem>
                    </SelectContent>
                </Select>

                {!hideCharacterFilter && (
                    <Select value={selectedCharacter} onValueChange={setSelectedCharacter}>
                        <SelectTrigger className="w-48 bg-gray-800 border-gray-700 text-white">
                            <SelectValue placeholder="Character" />
                        </SelectTrigger>
                        <SelectContent className="bg-gray-800 border-gray-700 text-white">
                            <SelectItem value="all">All characters</SelectItem>
                            {characters.map((c) => (
                                <SelectItem key={c.id} value={c.id}>
                                    {c.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                )}

                <div className="flex items-center gap-2 flex-1 min-w-[240px] max-w-md ml-auto">
                    <Input
                        value={pasteUrl}
                        onChange={(e) => setPasteUrl(e.target.value)}
                        placeholder="Paste TikTok URL…"
                        className="bg-gray-800 border-gray-700 text-white"
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') handlePaste()
                        }}
                    />
                    <Button
                        onClick={handlePaste}
                        disabled={!pasteUrl.trim() || ingest.isPending}
                        className="bg-indigo-600 hover:bg-indigo-500"
                    >
                        {ingest.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                    </Button>
                </div>
            </div>

            {/* Grid / states */}
            {isLoading && (
                <div className="flex items-center justify-center py-16">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
                </div>
            )}

            {error && !isLoading && (
                <Card className="bg-red-950 border-red-800">
                    <CardContent className="py-8 text-center">
                        <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-400" />
                        <p className="text-red-200 mb-3">Failed to load reference videos</p>
                        <p className="text-red-300/60 text-sm mb-4">{error.message}</p>
                        <Button onClick={() => refetch()} variant="outline" className="bg-red-900 border-red-700">
                            <RefreshCw className="w-4 h-4 mr-2" />
                            Try Again
                        </Button>
                    </CardContent>
                </Card>
            )}

            {!isLoading && !error && videos.length === 0 && (
                <Card className="bg-gray-800 border-gray-700">
                    <CardContent className="py-16 text-center">
                        <Film className="w-12 h-12 mx-auto mb-4 text-gray-600" />
                        <h3 className="text-lg font-semibold text-white mb-2">No reference videos yet</h3>
                        <p className="text-gray-400 mb-4 max-w-md mx-auto">
                            Share TikTok videos from your phone to feed the character content system with
                            style inspiration, facts, or new character ideas.
                        </p>
                        <div className="flex items-center justify-center gap-3">
                            <Button onClick={() => setShowAndroidSetup(true)} className="bg-indigo-600 hover:bg-indigo-500">
                                <Smartphone className="w-4 h-4 mr-2" />
                                Set up Android sharing
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            )}

            {!isLoading && !error && videos.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {videos.map((v: CharacterReferenceVideo) => (
                        <ReferenceVideoCard
                            key={v.id}
                            video={v}
                            characterName={v.character_id ? characterMap.get(v.character_id) : undefined}
                            onOpen={() => setDetailId(v.id)}
                        />
                    ))}
                </div>
            )}

            {/* Modals */}
            {detail && (
                <ReferenceVideoDetailModal
                    video={detail}
                    characters={characters.map((c) => ({ id: c.id, name: c.name }))}
                    onClose={() => setDetailId(null)}
                />
            )}
            {showAndroidSetup && <AndroidSetupModal onClose={() => setShowAndroidSetup(false)} />}
        </div>
    )
}

export default ReferenceVideosTab
