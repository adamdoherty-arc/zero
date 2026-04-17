import { useMemo, useState } from 'react'
import {
    Film,
    Loader2,
    AlertTriangle,
    RefreshCw,
    Inbox,
    Lightbulb,
    BookOpen,
    Search as SearchIcon,
    Plus,
    X,
    PlayCircle,
    ExternalLink,
    UserPlus,
    Sparkles,
    UserCheck,
    Trash2,
    Check,
    ChevronLeft,
} from 'lucide-react'
import {
    useReferenceVideos,
    useIngestReferenceVideo,
    useAssignReferenceVideoCharacter,
    useApplyReferenceVideoFacts,
    usePromoteReferenceVideoToCharacter,
    useRetryReferenceVideo,
    useDeleteReferenceVideo,
    type CharacterReferenceVideo,
    type RefVideoIntent,
    type RefVideoStatus,
} from '@/hooks/useCharacterReferenceVideoApi'
import { useCharacters, type Character } from '@/hooks/useCharacterContentApi'

const INTENT_PILLS: { value: 'all' | RefVideoIntent; label: string; icon: React.ElementType }[] = [
    { value: 'all', label: 'All', icon: Film },
    { value: 'inbox', label: 'Inbox', icon: Inbox },
    { value: 'inspiration', label: 'Inspiration', icon: Lightbulb },
    { value: 'facts', label: 'Facts', icon: BookOpen },
    { value: 'discovery', label: 'Discovery', icon: SearchIcon },
]

function StatusBadge({ status }: { status: RefVideoStatus }) {
    const map: Record<RefVideoStatus, string> = {
        pending: 'bg-gray-700 text-gray-300',
        downloading: 'bg-blue-500/20 text-blue-300',
        downloaded: 'bg-blue-500/20 text-blue-300',
        transcribing: 'bg-purple-500/20 text-purple-300',
        analyzing: 'bg-amber-500/20 text-amber-300',
        ready: 'bg-emerald-500/20 text-emerald-300',
        failed: 'bg-red-500/20 text-red-300',
    }
    return (
        <span className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full ${map[status]}`}>
            {status}
        </span>
    )
}

function VideoRow({
    video,
    onTap,
}: {
    video: CharacterReferenceVideo
    onTap: () => void
}) {
    return (
        <button
            onClick={onTap}
            className="w-full text-left rounded-xl border border-gray-800 bg-gray-900/60 hover:bg-gray-800 overflow-hidden transition flex items-stretch"
        >
            <div className="w-24 h-24 shrink-0 bg-gray-800 relative">
                {video.thumbnail_url ? (
                    <img
                        src={video.thumbnail_url}
                        alt={video.title || 'thumbnail'}
                        className="absolute inset-0 w-full h-full object-cover"
                        loading="lazy"
                    />
                ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-gray-600">
                        <Film className="w-8 h-8" />
                    </div>
                )}
                <div className="absolute bottom-1 right-1 bg-black/70 rounded-full p-0.5">
                    <PlayCircle className="w-3.5 h-3.5 text-white" />
                </div>
            </div>
            <div className="flex-1 p-3 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                    <StatusBadge status={video.status} />
                    <span className="text-[10px] text-gray-500 uppercase tracking-wide">
                        {video.intent}
                    </span>
                </div>
                <p className="text-sm font-medium text-white line-clamp-2">
                    {video.title || video.caption || 'Untitled'}
                </p>
                {video.author_name && (
                    <p className="text-xs text-gray-500 mt-0.5 truncate">
                        @{video.author_name}
                    </p>
                )}
            </div>
        </button>
    )
}

type Subsheet = 'assign' | 'promote' | 'facts' | null

function AssignCharacterSubsheet({
    video,
    onClose,
    onDone,
}: {
    video: CharacterReferenceVideo
    onClose: () => void
    onDone: () => void
}) {
    const { data: characters = [], isLoading } = useCharacters({ status: 'active' })
    const [search, setSearch] = useState('')
    const assign = useAssignReferenceVideoCharacter()

    const filtered = useMemo(() => {
        const q = search.trim().toLowerCase()
        const sorted = [...characters].sort((a, b) => a.name.localeCompare(b.name))
        if (!q) return sorted.slice(0, 30)
        return sorted.filter(
            (c) =>
                c.name.toLowerCase().includes(q) ||
                (c.universe ?? '').toLowerCase().includes(q) ||
                (c.franchise ?? '').toLowerCase().includes(q)
        )
    }, [characters, search])

    const choose = async (c: Character) => {
        try {
            await assign.mutateAsync({ id: video.id, character_id: c.id })
            onDone()
        } catch (err) {
            console.error('assign failed', err)
        }
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <button
                    onClick={onClose}
                    className="p-2 -ml-2 rounded-full text-gray-300 hover:bg-gray-800"
                    aria-label="Back"
                >
                    <ChevronLeft className="w-5 h-5" />
                </button>
                <h4 className="text-base font-semibold text-white">Assign to character</h4>
            </div>
            <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search characters…"
                className="w-full min-h-[44px] px-3 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
            />
            {isLoading ? (
                <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
                </div>
            ) : filtered.length === 0 ? (
                <p className="text-sm text-gray-400 py-4 text-center">No matching characters</p>
            ) : (
                <ul className="space-y-2 max-h-[50vh] overflow-y-auto">
                    {filtered.map((c) => {
                        const isCurrent = c.id === video.character_id
                        return (
                            <li key={c.id}>
                                <button
                                    onClick={() => choose(c)}
                                    disabled={assign.isPending}
                                    className="w-full min-h-[52px] text-left rounded-xl border border-gray-800 bg-gray-800/60 hover:bg-gray-800 p-3 flex items-center gap-3 disabled:opacity-50"
                                >
                                    {c.image_url ? (
                                        <img
                                            src={c.image_url}
                                            alt=""
                                            className="w-10 h-10 rounded-full object-cover bg-gray-700 shrink-0"
                                        />
                                    ) : (
                                        <div className="w-10 h-10 rounded-full bg-gray-700 flex items-center justify-center shrink-0">
                                            <UserCheck className="w-5 h-5 text-gray-400" />
                                        </div>
                                    )}
                                    <div className="min-w-0 flex-1">
                                        <p className="text-sm font-medium text-white truncate">{c.name}</p>
                                        <p className="text-xs text-gray-400 truncate">
                                            {c.universe}{c.franchise ? ` · ${c.franchise}` : ''}
                                        </p>
                                    </div>
                                    {isCurrent && <Check className="w-5 h-5 text-emerald-400" />}
                                </button>
                            </li>
                        )
                    })}
                </ul>
            )}
        </div>
    )
}

function PromoteSubsheet({
    video,
    onClose,
    onDone,
}: {
    video: CharacterReferenceVideo
    onClose: () => void
    onDone: () => void
}) {
    const proposed = video.proposed_character
    const [name, setName] = useState(proposed?.name ?? '')
    const [universe, setUniverse] = useState(proposed?.universe ?? '')
    const [franchise, setFranchise] = useState(proposed?.franchise ?? '')
    const [description, setDescription] = useState(proposed?.description ?? '')
    const promote = usePromoteReferenceVideoToCharacter()

    const submit = async () => {
        if (!name.trim()) return
        try {
            await promote.mutateAsync({
                id: video.id,
                name: name.trim(),
                universe: universe.trim() || undefined,
                franchise: franchise.trim() || undefined,
                description: description.trim() || undefined,
            })
            onDone()
        } catch (err) {
            console.error('promote failed', err)
        }
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <button
                    onClick={onClose}
                    className="p-2 -ml-2 rounded-full text-gray-300 hover:bg-gray-800"
                    aria-label="Back"
                >
                    <ChevronLeft className="w-5 h-5" />
                </button>
                <h4 className="text-base font-semibold text-white">Promote to character</h4>
            </div>
            <p className="text-xs text-gray-400">
                Creates a new character seeded from this video's extracted facts.
            </p>
            <div className="space-y-2">
                <label className="block">
                    <span className="text-xs uppercase tracking-wide text-gray-400">Name</span>
                    <input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Character name"
                        className="mt-1 w-full min-h-[44px] px-3 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                    />
                </label>
                <label className="block">
                    <span className="text-xs uppercase tracking-wide text-gray-400">Universe</span>
                    <input
                        value={universe}
                        onChange={(e) => setUniverse(e.target.value)}
                        placeholder="marvel, dc, anime…"
                        className="mt-1 w-full min-h-[44px] px-3 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                    />
                </label>
                <label className="block">
                    <span className="text-xs uppercase tracking-wide text-gray-400">Franchise</span>
                    <input
                        value={franchise}
                        onChange={(e) => setFranchise(e.target.value)}
                        placeholder="Optional"
                        className="mt-1 w-full min-h-[44px] px-3 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                    />
                </label>
                <label className="block">
                    <span className="text-xs uppercase tracking-wide text-gray-400">Description</span>
                    <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={3}
                        placeholder="Optional short description"
                        className="mt-1 w-full px-3 py-2 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none"
                    />
                </label>
            </div>
            <button
                onClick={submit}
                disabled={!name.trim() || promote.isPending}
                className="w-full min-h-[48px] rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
            >
                {promote.isPending ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                    <Sparkles className="w-5 h-5" />
                )}
                Create character
            </button>
        </div>
    )
}

function ApplyFactsSubsheet({
    video,
    onClose,
    onDone,
}: {
    video: CharacterReferenceVideo
    onClose: () => void
    onDone: () => void
}) {
    const facts = video.extracted_facts ?? []
    const [selected, setSelected] = useState<Set<number>>(() => new Set(facts.map((_, i) => i)))
    const apply = useApplyReferenceVideoFacts()

    if (!video.character_id) {
        return (
            <div className="space-y-3">
                <div className="flex items-center gap-2">
                    <button
                        onClick={onClose}
                        className="p-2 -ml-2 rounded-full text-gray-300 hover:bg-gray-800"
                        aria-label="Back"
                    >
                        <ChevronLeft className="w-5 h-5" />
                    </button>
                    <h4 className="text-base font-semibold text-white">Apply facts</h4>
                </div>
                <p className="text-sm text-gray-400">
                    Assign this video to a character first, then apply its extracted facts to that
                    character's fact bank.
                </p>
            </div>
        )
    }

    const toggle = (i: number) => {
        setSelected((prev) => {
            const next = new Set(prev)
            if (next.has(i)) next.delete(i)
            else next.add(i)
            return next
        })
    }

    const submit = async () => {
        const indexes = Array.from(selected).sort((a, b) => a - b)
        if (indexes.length === 0) return
        try {
            await apply.mutateAsync({ id: video.id, fact_indexes: indexes })
            onDone()
        } catch (err) {
            console.error('apply facts failed', err)
        }
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <button
                    onClick={onClose}
                    className="p-2 -ml-2 rounded-full text-gray-300 hover:bg-gray-800"
                    aria-label="Back"
                >
                    <ChevronLeft className="w-5 h-5" />
                </button>
                <h4 className="text-base font-semibold text-white">Apply facts</h4>
            </div>
            <p className="text-xs text-gray-400">
                {selected.size} of {facts.length} selected. Unchecked facts are skipped.
            </p>
            <ul className="space-y-2 max-h-[50vh] overflow-y-auto">
                {facts.map((f, i) => {
                    const checked = selected.has(i)
                    return (
                        <li key={i}>
                            <button
                                onClick={() => toggle(i)}
                                className={`w-full text-left rounded-xl border p-3 flex items-start gap-3 transition ${
                                    checked
                                        ? 'bg-indigo-500/10 border-indigo-500/40'
                                        : 'bg-gray-800/60 border-gray-800'
                                }`}
                            >
                                <div
                                    className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 mt-0.5 ${
                                        checked
                                            ? 'bg-indigo-500 border-indigo-500'
                                            : 'border-gray-600'
                                    }`}
                                >
                                    {checked && <Check className="w-3.5 h-3.5 text-white" />}
                                </div>
                                <div className="min-w-0">
                                    <p className="text-sm text-gray-100">{f.text}</p>
                                    {f.category && (
                                        <span className="text-[10px] uppercase tracking-wide text-gray-500">
                                            {f.category}
                                        </span>
                                    )}
                                </div>
                            </button>
                        </li>
                    )
                })}
            </ul>
            <button
                onClick={submit}
                disabled={selected.size === 0 || apply.isPending}
                className="w-full min-h-[48px] rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
            >
                {apply.isPending ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                    <BookOpen className="w-5 h-5" />
                )}
                Apply {selected.size} fact{selected.size === 1 ? '' : 's'}
            </button>
        </div>
    )
}

function VideoDetailSheet({
    video,
    onClose,
}: {
    video: CharacterReferenceVideo
    onClose: () => void
}) {
    const [subsheet, setSubsheet] = useState<Subsheet>(null)
    const [confirmDelete, setConfirmDelete] = useState(false)
    const retry = useRetryReferenceVideo()
    const del = useDeleteReferenceVideo()

    const factsCount = video.extracted_facts?.length ?? 0
    const canApply = !!video.character_id && factsCount > 0
    const hasProposal = !!video.proposed_character?.name
    const canRetry = video.status === 'failed'

    const handleRetry = async () => {
        try {
            await retry.mutateAsync(video.id)
        } catch (err) {
            console.error('retry failed', err)
        }
    }

    const handleDelete = async () => {
        try {
            await del.mutateAsync(video.id)
            onClose()
        } catch (err) {
            console.error('delete failed', err)
        }
    }

    const anyPending = retry.isPending || del.isPending

    return (
        <div className="fixed inset-0 z-50 flex items-end">
            <button
                aria-label="Close"
                onClick={onClose}
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            />
            <div
                className="relative w-full max-h-[90vh] overflow-y-auto bg-gray-900 border-t border-gray-800 rounded-t-2xl shadow-2xl animate-in slide-in-from-bottom duration-200"
                style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
            >
                <div className="sticky top-0 flex items-center justify-between px-4 pt-4 pb-2 bg-gray-900 z-10">
                    <h3 className="text-base font-semibold text-white truncate pr-3">
                        {subsheet ? 'Action' : (video.title || 'Reference video')}
                    </h3>
                    <button
                        onClick={onClose}
                        className="p-2 -mr-2 rounded-full text-gray-400 hover:text-white hover:bg-gray-800"
                        aria-label="Close"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="px-4 pb-4 space-y-4">
                    {subsheet === 'assign' ? (
                        <AssignCharacterSubsheet
                            video={video}
                            onClose={() => setSubsheet(null)}
                            onDone={() => setSubsheet(null)}
                        />
                    ) : subsheet === 'promote' ? (
                        <PromoteSubsheet
                            video={video}
                            onClose={() => setSubsheet(null)}
                            onDone={() => setSubsheet(null)}
                        />
                    ) : subsheet === 'facts' ? (
                        <ApplyFactsSubsheet
                            video={video}
                            onClose={() => setSubsheet(null)}
                            onDone={() => setSubsheet(null)}
                        />
                    ) : (
                        <>
                            <div className="flex items-center gap-2 flex-wrap">
                                <StatusBadge status={video.status} />
                                <span className="text-xs text-gray-400 uppercase tracking-wide">
                                    {video.intent}
                                </span>
                                {video.author_name && (
                                    <span className="text-xs text-gray-500 truncate">
                                        @{video.author_name}
                                    </span>
                                )}
                                {video.character_id && (
                                    <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-emerald-300 bg-emerald-500/10 ring-1 ring-emerald-500/30 px-2 py-0.5 rounded-full">
                                        <UserCheck className="w-3 h-3" />
                                        Assigned
                                    </span>
                                )}
                            </div>

                            {video.thumbnail_url && (
                                <img
                                    src={video.thumbnail_url}
                                    alt="thumbnail"
                                    className="w-full aspect-[9/16] object-cover rounded-xl border border-gray-800"
                                />
                            )}

                            {video.error_message && (
                                <div className="rounded-xl bg-red-950/40 border border-red-800 p-3">
                                    <p className="text-xs uppercase text-red-300 tracking-wide mb-1">Error</p>
                                    <p className="text-sm text-red-200">{video.error_message}</p>
                                </div>
                            )}

                            {video.caption && (
                                <div className="rounded-xl bg-gray-800/60 border border-gray-800 p-3">
                                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Caption</p>
                                    <p className="text-sm text-gray-200 whitespace-pre-wrap">
                                        {video.caption}
                                    </p>
                                </div>
                            )}

                            {video.transcript && (
                                <div className="rounded-xl bg-gray-800/60 border border-gray-800 p-3">
                                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Transcript</p>
                                    <p className="text-sm text-gray-300 whitespace-pre-wrap">
                                        {video.transcript.length > 500
                                            ? video.transcript.slice(0, 500) + '…'
                                            : video.transcript}
                                    </p>
                                </div>
                            )}

                            {factsCount > 0 && (
                                <div className="rounded-xl bg-gray-800/60 border border-gray-800 p-3">
                                    <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">
                                        Extracted facts ({factsCount}
                                        {video.applied_fact_count > 0 ? ` · ${video.applied_fact_count} applied` : ''})
                                    </p>
                                    <ul className="space-y-1 text-sm text-gray-200 list-disc pl-5">
                                        {(video.extracted_facts ?? []).slice(0, 6).map((f, i) => (
                                            <li key={i}>{f.text}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            <a
                                href={video.tiktok_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-2 text-sm text-indigo-300 hover:text-indigo-200"
                            >
                                <ExternalLink className="w-4 h-4" />
                                Open on TikTok
                            </a>

                            {/* Action grid: assign / promote / apply-facts / retry / delete */}
                            <div className="grid grid-cols-2 gap-2 pt-2">
                                <button
                                    onClick={() => setSubsheet('assign')}
                                    disabled={anyPending}
                                    className="min-h-[48px] rounded-xl bg-indigo-600/10 border border-indigo-500/30 text-indigo-200 font-semibold text-sm hover:bg-indigo-600/20 disabled:opacity-50 flex items-center justify-center gap-2"
                                >
                                    <UserPlus className="w-4 h-4" />
                                    {video.character_id ? 'Reassign' : 'Assign'}
                                </button>
                                <button
                                    onClick={() => setSubsheet('promote')}
                                    disabled={anyPending}
                                    className="min-h-[48px] rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 font-semibold text-sm hover:bg-amber-500/20 disabled:opacity-50 flex items-center justify-center gap-2"
                                >
                                    <Sparkles className="w-4 h-4" />
                                    Promote{hasProposal ? '' : '…'}
                                </button>
                                <button
                                    onClick={() => setSubsheet('facts')}
                                    disabled={anyPending || !canApply}
                                    title={
                                        !video.character_id
                                            ? 'Assign to a character first'
                                            : factsCount === 0
                                              ? 'No facts extracted'
                                              : undefined
                                    }
                                    className="min-h-[48px] rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-200 font-semibold text-sm hover:bg-emerald-500/20 disabled:opacity-40 flex items-center justify-center gap-2"
                                >
                                    <BookOpen className="w-4 h-4" />
                                    Apply facts
                                </button>
                                {canRetry ? (
                                    <button
                                        onClick={handleRetry}
                                        disabled={anyPending}
                                        className="min-h-[48px] rounded-xl bg-gray-700/60 border border-gray-600 text-gray-200 font-semibold text-sm hover:bg-gray-700 disabled:opacity-50 flex items-center justify-center gap-2"
                                    >
                                        {retry.isPending ? (
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                        ) : (
                                            <RefreshCw className="w-4 h-4" />
                                        )}
                                        Retry
                                    </button>
                                ) : (
                                    <button
                                        onClick={() => setConfirmDelete(true)}
                                        disabled={anyPending}
                                        className="min-h-[48px] rounded-xl bg-red-600/10 border border-red-500/30 text-red-300 font-semibold text-sm hover:bg-red-600/20 disabled:opacity-50 flex items-center justify-center gap-2"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                        Delete
                                    </button>
                                )}
                            </div>

                            {/* Retry variant also keeps delete reachable */}
                            {canRetry && (
                                <button
                                    onClick={() => setConfirmDelete(true)}
                                    disabled={anyPending}
                                    className="w-full min-h-[44px] rounded-xl bg-red-600/10 border border-red-500/30 text-red-300 font-semibold text-sm hover:bg-red-600/20 disabled:opacity-50 flex items-center justify-center gap-2"
                                >
                                    <Trash2 className="w-4 h-4" />
                                    Delete
                                </button>
                            )}

                            {confirmDelete && (
                                <div className="rounded-xl bg-red-950/40 border border-red-800 p-3 space-y-3">
                                    <p className="text-sm text-red-200">
                                        Delete this reference video and its extracted facts? This
                                        cannot be undone.
                                    </p>
                                    <div className="flex items-center gap-2">
                                        <button
                                            onClick={() => setConfirmDelete(false)}
                                            disabled={anyPending}
                                            className="flex-1 min-h-[44px] rounded-lg bg-gray-800 border border-gray-700 text-gray-200 text-sm font-medium"
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            onClick={handleDelete}
                                            disabled={anyPending}
                                            className="flex-1 min-h-[44px] rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
                                        >
                                            {del.isPending ? (
                                                <Loader2 className="w-4 h-4 animate-spin" />
                                            ) : (
                                                <Trash2 className="w-4 h-4" />
                                            )}
                                            Delete
                                        </button>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}

export function MobileVideosPage() {
    const [intent, setIntent] = useState<'all' | RefVideoIntent>('all')
    const [pasteUrl, setPasteUrl] = useState('')
    const [detailId, setDetailId] = useState<string | null>(null)

    const {
        data: videos = [],
        isLoading,
        error,
        refetch,
    } = useReferenceVideos({
        intent: intent === 'all' ? undefined : intent,
        limit: 60,
    })

    const ingest = useIngestReferenceVideo()

    const detail = useMemo(
        () => (detailId ? videos.find((v) => v.id === detailId) ?? null : null),
        [detailId, videos]
    )

    const handlePaste = async () => {
        const url = pasteUrl.trim()
        if (!url) return
        try {
            await ingest.mutateAsync({ url, intent: 'inbox' })
            setPasteUrl('')
        } catch (err) {
            console.error('ingest failed', err)
        }
    }

    return (
        <div className="space-y-4">
            {/* Paste bar */}
            <div className="flex items-center gap-2">
                <input
                    type="url"
                    inputMode="url"
                    value={pasteUrl}
                    onChange={(e) => setPasteUrl(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handlePaste()}
                    placeholder="Paste TikTok URL…"
                    className="flex-1 min-h-[44px] px-3 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                />
                <button
                    onClick={handlePaste}
                    disabled={!pasteUrl.trim() || ingest.isPending}
                    className="min-h-[44px] min-w-[44px] px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-50 flex items-center justify-center"
                    aria-label="Add video"
                >
                    {ingest.isPending ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                        <Plus className="w-5 h-5" />
                    )}
                </button>
            </div>

            {/* Intent pills */}
            <div className="flex items-center gap-2 flex-wrap">
                {INTENT_PILLS.map(({ value, label, icon: Icon }) => (
                    <button
                        key={value}
                        onClick={() => setIntent(value)}
                        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition ${
                            intent === value
                                ? 'bg-indigo-600 border-indigo-500 text-white'
                                : 'bg-gray-800 border-gray-700 text-gray-300'
                        }`}
                    >
                        <Icon className="w-3.5 h-3.5" />
                        {label}
                    </button>
                ))}
            </div>

            {/* Loading */}
            {isLoading && (
                <div className="flex items-center justify-center py-16">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
                </div>
            )}

            {/* Error */}
            {error && !isLoading && (
                <div className="rounded-2xl border border-red-800 bg-red-950/40 p-6 text-center">
                    <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-400" />
                    <p className="text-red-200 mb-4">Failed to load videos</p>
                    <button
                        onClick={() => refetch()}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium"
                    >
                        <RefreshCw className="w-4 h-4" />
                        Try again
                    </button>
                </div>
            )}

            {/* Empty */}
            {!isLoading && !error && videos.length === 0 && (
                <div className="rounded-2xl border border-gray-800 bg-gray-900/60 p-10 text-center">
                    <Film className="w-10 h-10 mx-auto mb-3 text-gray-600" />
                    <h3 className="text-lg font-semibold text-white mb-1">
                        No reference videos
                    </h3>
                    <p className="text-sm text-gray-400">
                        Share TikTok videos from your phone or paste a URL above.
                    </p>
                </div>
            )}

            {/* List */}
            {!isLoading && !error && videos.length > 0 && (
                <ul className="space-y-2">
                    {videos.map((v) => (
                        <li key={v.id}>
                            <VideoRow video={v} onTap={() => setDetailId(v.id)} />
                        </li>
                    ))}
                </ul>
            )}

            {detail && <VideoDetailSheet video={detail} onClose={() => setDetailId(null)} />}
        </div>
    )
}

export default MobileVideosPage
