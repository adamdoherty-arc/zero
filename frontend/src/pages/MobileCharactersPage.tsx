import { useMemo, useState } from 'react'
import {
    Users,
    Loader2,
    AlertTriangle,
    RefreshCw,
    Search as SearchIcon,
    ImageOff,
} from 'lucide-react'
import { useCharacters, type Character } from '@/hooks/useCharacterContentApi'

function CharacterCard({ character }: { character: Character }) {
    return (
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 overflow-hidden">
            <div className="aspect-square bg-gray-800 relative">
                {character.image_url ? (
                    <img
                        src={character.image_url}
                        alt={character.name}
                        className="absolute inset-0 w-full h-full object-cover"
                        loading="lazy"
                    />
                ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-gray-600">
                        <ImageOff className="w-8 h-8" />
                    </div>
                )}
            </div>
            <div className="p-3">
                <p className="text-sm font-semibold text-white truncate">{character.name}</p>
                {character.universe && (
                    <p className="text-xs text-gray-400 truncate">{character.universe}</p>
                )}
                <div className="mt-2 flex items-center gap-3 text-[11px] text-gray-500">
                    <span>
                        <span className="text-gray-300 tabular-nums">
                            {character.carousels_created ?? 0}
                        </span>{' '}
                        carousels
                    </span>
                    <span>
                        <span className="text-gray-300 tabular-nums">
                            {character.fact_bank?.length ?? 0}
                        </span>{' '}
                        facts
                    </span>
                </div>
            </div>
        </div>
    )
}

export function MobileCharactersPage() {
    const { data: characters = [], isLoading, error, refetch } = useCharacters()
    const [query, setQuery] = useState('')

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase()
        if (!q) return characters
        return characters.filter(
            (c) =>
                c.name.toLowerCase().includes(q) ||
                (c.universe ?? '').toLowerCase().includes(q) ||
                (c.franchise ?? '').toLowerCase().includes(q)
        )
    }, [characters, query])

    return (
        <div className="space-y-4">
            {/* Search */}
            <div className="relative">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search characters…"
                    className="w-full min-h-[44px] pl-9 pr-3 rounded-xl bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                />
            </div>

            {/* States */}
            {isLoading && (
                <div className="flex items-center justify-center py-16">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
                </div>
            )}

            {error && !isLoading && (
                <div className="rounded-2xl border border-red-800 bg-red-950/40 p-6 text-center">
                    <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-red-400" />
                    <p className="text-red-200 mb-4">Failed to load characters</p>
                    <button
                        onClick={() => refetch()}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-medium"
                    >
                        <RefreshCw className="w-4 h-4" />
                        Try again
                    </button>
                </div>
            )}

            {!isLoading && !error && filtered.length === 0 && (
                <div className="rounded-2xl border border-gray-800 bg-gray-900/60 p-10 text-center">
                    <Users className="w-10 h-10 mx-auto mb-3 text-gray-600" />
                    <p className="text-sm text-gray-400">
                        {query ? 'No matches.' : 'No characters yet.'}
                    </p>
                </div>
            )}

            {!isLoading && !error && filtered.length > 0 && (
                <div className="grid grid-cols-2 gap-3">
                    {filtered.map((c) => (
                        <CharacterCard key={c.id} character={c} />
                    ))}
                </div>
            )}
        </div>
    )
}

export default MobileCharactersPage
