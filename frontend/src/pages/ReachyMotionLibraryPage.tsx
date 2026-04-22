import { useMemo, useState } from 'react'
import { Bot, Music, Sparkles, Play, Square, MoonStar, Sun, Search } from 'lucide-react'
import {
  useMotionLibrary,
  usePlayMotion,
  useReachyStatus,
  useStopMove,
  useWakeUp,
  useGoToSleep,
  type MotionClip,
  type MotionKind,
} from '@/hooks/useReachyApi'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import { useToast } from '@/hooks/use-toast'

function ConnectionBadge() {
  const { data } = useReachyStatus()
  const connected = data?.connected
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${
        connected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
      }`}
      title={data?.base_url}
    >
      {connected ? 'Reachy connected' : 'Reachy offline'}
    </span>
  )
}

function ClipCard({ clip, onPlay, busy }: { clip: MotionClip; onPlay: () => void; busy: boolean }) {
  return (
    <button
      onClick={onPlay}
      disabled={busy}
      className="glass-card-hover p-3 text-left flex flex-col gap-1 disabled:opacity-50"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-sm text-white truncate" title={clip.name}>
          {clip.name}
        </span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded-full ${
            clip.kind === 'emotion'
              ? 'bg-indigo-500/20 text-indigo-300'
              : 'bg-fuchsia-500/20 text-fuchsia-300'
          }`}
        >
          {clip.kind}
        </span>
      </div>
      <p className="text-xs text-gray-400 line-clamp-2">{clip.description}</p>
      {clip.aliases.length > 0 && (
        <p className="text-[10px] text-gray-500 truncate">
          aliases: {clip.aliases.join(', ')}
        </p>
      )}
    </button>
  )
}

export function ReachyMotionLibraryPage() {
  const [kindFilter, setKindFilter] = useState<MotionKind | 'all'>('all')
  const [q, setQ] = useState('')
  const effectiveKind = kindFilter === 'all' ? undefined : kindFilter
  const { data, isLoading } = useMotionLibrary(effectiveKind)
  const play = usePlayMotion()
  const stop = useStopMove()
  const wakeUp = useWakeUp()
  const sleep = useGoToSleep()
  const { toast } = useToast()

  const filteredByCategory = useMemo(() => {
    if (!data) return {}
    const needle = q.trim().toLowerCase()
    const out: Record<string, MotionClip[]> = {}
    for (const [cat, clips] of Object.entries(data.by_category)) {
      const picks = needle
        ? clips.filter(
            (c) =>
              c.name.toLowerCase().includes(needle) ||
              c.description.toLowerCase().includes(needle) ||
              c.aliases.some((a) => a.toLowerCase().includes(needle)),
          )
        : clips
      if (picks.length) out[cat] = picks
    }
    return out
  }, [data, q])

  const handlePlay = async (clip: MotionClip) => {
    try {
      const result = await play.mutateAsync({ name: clip.name, kind: clip.kind })
      if ((result as { error?: string })?.error) {
        toast({
          title: `Failed to play ${clip.name}`,
          description: (result as { error?: string }).error,
          variant: 'destructive',
        })
      } else {
        toast({ title: `Playing ${clip.name}`, description: clip.description })
      }
    } catch (e) {
      toast({
        title: `Failed to play ${clip.name}`,
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <div className="flex items-center justify-between gap-4 mb-6 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-500/10">
            <Bot className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Reachy Motion Library</h1>
            <p className="text-sm text-gray-400">
              {data ? `${data.emotions} emotions · ${data.dances} dances` : 'Loading catalog…'}
            </p>
          </div>
          <ConnectionBadge />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => wakeUp.mutate()}
            className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
          >
            <Sun className="w-4 h-4" /> Wake
          </button>
          <button
            onClick={() => sleep.mutate()}
            className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
          >
            <MoonStar className="w-4 h-4" /> Sleep
          </button>
          <button
            onClick={() => stop.mutate()}
            className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 text-red-400"
          >
            <Square className="w-4 h-4" /> Stop
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <div className="flex items-center gap-1 bg-gray-800/50 rounded-lg p-1">
          {(['all', 'emotion', 'dance'] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className={`px-3 py-1 text-sm rounded flex items-center gap-1.5 ${
                kindFilter === k ? 'bg-indigo-500/30 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {k === 'emotion' && <Sparkles className="w-3.5 h-3.5" />}
              {k === 'dance' && <Music className="w-3.5 h-3.5" />}
              {k === 'all' && <Play className="w-3.5 h-3.5" />}
              <span className="capitalize">{k}</span>
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search clips, descriptions, or aliases…"
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded-lg focus:outline-none focus:border-indigo-500"
          />
        </div>
      </div>

      {isLoading && <LoadingSkeleton />}

      {data && (
        <div className="space-y-6">
          {Object.entries(filteredByCategory)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([category, clips]) => (
              <section key={category}>
                <h2 className="text-sm font-semibold text-gray-300 mb-2 uppercase tracking-wide">
                  {category}{' '}
                  <span className="text-gray-500 font-normal">({clips.length})</span>
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                  {clips.map((clip) => (
                    <ClipCard
                      key={`${clip.kind}-${clip.name}`}
                      clip={clip}
                      onPlay={() => handlePlay(clip)}
                      busy={play.isPending}
                    />
                  ))}
                </div>
              </section>
            ))}
          {Object.keys(filteredByCategory).length === 0 && (
            <p className="text-center text-gray-500 py-12">No clips match {JSON.stringify(q)}.</p>
          )}
        </div>
      )}
    </div>
  )
}
