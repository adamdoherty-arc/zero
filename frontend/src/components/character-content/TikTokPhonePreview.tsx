import { useEffect, useMemo, useRef, useState } from 'react'
import {
    Bookmark,
    Eye,
    EyeOff,
    Heart,
    Home,
    Inbox,
    MessageCircle,
    Music2,
    Pause,
    Play,
    Plus,
    RefreshCw,
    Search,
    Share2,
    User,
} from 'lucide-react'
import type { CharacterCarousel, CarouselSlide } from '@/hooks/useCharacterContentApi'

export interface TikTokPhonePreviewProps {
    carousel: CharacterCarousel
    editMode: boolean
    onChange?: (patch: Partial<CharacterCarousel>) => void
    onReimageSlide?: (slideIdx: number, newQuery?: string) => void
    onOpenMusicPicker?: () => void
    reimagingSlideIdx?: number | null
    className?: string
    // 'clean' (default) renders with a single soft shadow and no text stroke,
    // which matches what the server-side PIL renderer produces. 'stroked'
    // reproduces the legacy triple-shadow + stroke look for back-compat with
    // older screenshots used in QA artifacts.
    renderMode?: 'clean' | 'stroked'
}

const SWIPE_THRESHOLD = 50

// Static plausible engagement counts so the preview looks like a real feed.
const RIGHT_RAIL = [
    { icon: Heart, label: '12.4K' },
    { icon: MessageCircle, label: '284' },
    { icon: Bookmark, label: '1.2K' },
    { icon: Share2, label: '517' },
]

function formatUsername(name: string | undefined): string {
    if (!name) return '@character'
    return '@' + name.toLowerCase().replace(/\s+/g, '').replace(/[^a-z0-9_]/g, '')
}

function initialFallback(name: string | undefined): string {
    if (!name) return '?'
    const trimmed = name.trim()
    if (!trimmed) return '?'
    return trimmed[0].toUpperCase()
}

// Single soft shadow keeps the text crisp and avoids the "ghosted / duplicated"
// look that a triple-shadow + text-stroke stack produces on high-DPI screens.
// The legacy stack is kept under renderMode='stroked' for screenshot parity.
const TEXT_SHADOW_CLEAN = '0 2px 6px rgba(0,0,0,0.85)'
const TEXT_SHADOW_LEGACY =
    '0 2px 4px rgba(0,0,0,0.9), 0 0 2px rgba(0,0,0,0.9), 0 4px 10px rgba(0,0,0,0.5)'

type TextVariant = 'hook' | 'slide' | 'chunk'
type RenderMode = 'clean' | 'stroked'

/**
 * Parses copy and breaks it into tokens, highlighting anything wrapped in
 * **double asterisks**, tokens in UPPERCASE, or numeric/percent/multiplier
 * punches (e.g. 100%, 3X, $5). Everything else renders as plain impact text
 * with a strong shadow so it stays readable on any frame.
 */
function CaptivatingText({
    text,
    variant,
    renderMode = 'clean',
}: {
    text: string | undefined
    variant: TextVariant
    renderMode?: RenderMode
}) {
    if (!text) return null

    const sizeClasses =
        variant === 'hook'
            ? 'text-[24px] leading-[1.05] tracking-tight'
            : variant === 'slide'
              ? 'text-[18px] leading-[1.15] tracking-tight'
              : 'text-[15px] leading-[1.2]'

    // Auto-captivate: if the copy leads with "<Label>: rest", promote the
    // label to a yellow pill so flat hooks like "The Hammer Lie: Why Batman..."
    // still feel like TikTok copy.
    const { label, body } = splitLeadLabel(text)
    const lines = body.split(/\r?\n/)

    const containerStyle: React.CSSProperties =
        renderMode === 'stroked'
            ? {
                  textShadow: TEXT_SHADOW_LEGACY,
                  WebkitTextStroke: '0.4px rgba(0,0,0,0.55)',
              }
            : {
                  textShadow: TEXT_SHADOW_CLEAN,
                  // Use drop-shadow as a subtle secondary layer, which avoids
                  // the "second outline" effect text-stroke produces.
                  filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.55))',
              }

    return (
        <div className={`font-black text-white ${sizeClasses}`} style={containerStyle}>
            {label && (
                <div className="mb-1.5">
                    <span
                        className={`inline-block rounded-md bg-yellow-300 px-1.5 py-0.5 text-black text-[13px] font-black uppercase tracking-wide ${
                            variant === 'hook' ? '-skew-x-3' : ''
                        }`}
                        style={{ textShadow: 'none', WebkitTextStroke: '0', filter: 'none' }}
                    >
                        {label}
                    </span>
                </div>
            )}
            {lines.map((line, li) => (
                <div key={li} className="flex flex-wrap items-baseline gap-x-1.5 gap-y-1">
                    {coalesce(tokenize(line)).map((tok, ti) =>
                        renderToken(tok, `${li}-${ti}`, variant),
                    )}
                </div>
            ))}
        </div>
    )
}

// If copy starts with "Something: rest", treat "Something" (max ~32 chars,
// no other colon) as a label and return the body separately so the renderer
// can style it as a pill. Falls back to plain text for everything else.
function splitLeadLabel(text: string): { label: string | null; body: string } {
    const idx = text.indexOf(':')
    if (idx <= 0 || idx > 40) return { label: null, body: text }
    const prefix = text.slice(0, idx).trim()
    const rest = text.slice(idx + 1).trim()
    if (!rest || prefix.length > 32 || /[\n]/.test(prefix)) {
        return { label: null, body: text }
    }
    // Avoid splitting on times, ratios, URLs etc. ("1:1", "https:...")
    if (/^[0-9]+$/.test(prefix) || /^https?$/i.test(prefix)) {
        return { label: null, body: text }
    }
    return { label: prefix, body: rest }
}

// Merge consecutive plain tokens into a single run so the rendered DOM
// preserves natural phrases ("What Darth Vader never wanted you to know")
// for assistive tech and substring matching.
function coalesce(tokens: Token[]): Token[] {
    const out: Token[] = []
    for (const t of tokens) {
        const last = out[out.length - 1]
        if (t.kind === 'plain' && last && last.kind === 'plain') {
            last.value = last.value + ' ' + t.value
        } else {
            out.push({ ...t })
        }
    }
    return out
}

type Token =
    | { kind: 'plain'; value: string }
    | { kind: 'bold'; value: string }
    | { kind: 'shout'; value: string }
    | { kind: 'stat'; value: string }

// Basic markup tokenizer:
//   **word** / **a phrase** -> yellow pill highlight
//   UPPERCASE (>=3 letters)  -> yellow pill highlight
//   number / percent / $amt  -> cyan-accented stat
function tokenize(line: string): Token[] {
    if (!line) return [{ kind: 'plain', value: '' }]

    const tokens: Token[] = []
    const boldSplit = line.split(/(\*\*[^*]+\*\*)/g)

    for (const chunk of boldSplit) {
        if (!chunk) continue
        if (chunk.startsWith('**') && chunk.endsWith('**')) {
            tokens.push({ kind: 'bold', value: chunk.slice(2, -2) })
            continue
        }
        // Split on whitespace but keep trailing punctuation glued.
        const words = chunk.split(/\s+/)
        for (const w of words) {
            if (!w) continue
            if (/^\$?\d[\d,.]*%?x?$/i.test(w) || /^\d+[kmb]\+?$/i.test(w)) {
                tokens.push({ kind: 'stat', value: w })
            } else if (/^[A-Z0-9!?.,'-]{3,}$/.test(w) && /[A-Z]/.test(w)) {
                tokens.push({ kind: 'shout', value: w })
            } else {
                tokens.push({ kind: 'plain', value: w })
            }
        }
    }
    return tokens
}

function renderToken(tok: Token, key: string, variant: TextVariant) {
    if (tok.kind === 'bold' || tok.kind === 'shout') {
        return (
            <span
                key={key}
                className={`inline-block rounded-md bg-yellow-300 px-1.5 text-black ${
                    variant === 'hook' ? 'py-0.5 -skew-x-3' : 'py-0.5'
                }`}
                style={{ textShadow: 'none', WebkitTextStroke: '0', letterSpacing: '-0.01em' }}
            >
                {tok.value}
            </span>
        )
    }
    if (tok.kind === 'stat') {
        return (
            <span
                key={key}
                className="inline-block rounded-md bg-black/85 px-1.5 py-0.5 text-cyan-200"
                style={{ textShadow: 'none', WebkitTextStroke: '0' }}
            >
                {tok.value}
            </span>
        )
    }
    return (
        <span key={key} className="inline-block">
            {tok.value}
        </span>
    )
}

export default function TikTokPhonePreview({
    carousel,
    editMode,
    onChange,
    onReimageSlide,
    onOpenMusicPicker,
    reimagingSlideIdx = null,
    className,
    renderMode = 'clean',
}: TikTokPhonePreviewProps) {
    const slides = carousel.slides || []
    const slideCount = slides.length
    const [activeSlide, setActiveSlide] = useState(0)
    const [dragX, setDragX] = useState(0)
    const [dragging, setDragging] = useState(false)
    const [audioPlaying, setAudioPlaying] = useState(false)
    const [captionExpanded, setCaptionExpanded] = useState(false)
    const [queryEditIdx, setQueryEditIdx] = useState<number | null>(null)
    const [queryDraft, setQueryDraft] = useState('')
    const [chromeVisible, setChromeVisible] = useState(true)
    const audioRef = useRef<HTMLAudioElement | null>(null)
    const dragStartX = useRef<number>(0)

    useEffect(() => {
        if (activeSlide >= slideCount) {
            setActiveSlide(Math.max(0, slideCount - 1))
        }
    }, [slideCount, activeSlide])

    useEffect(() => {
        // Stop audio if user navigates or edits something that changes music.
        if (!carousel.music_track?.preview_url && audioPlaying) {
            audioRef.current?.pause()
            setAudioPlaying(false)
        }
    }, [carousel.music_track?.preview_url, audioPlaying])

    const handlePointerDown = (e: React.PointerEvent) => {
        if (slideCount <= 1) return
        setDragging(true)
        dragStartX.current = e.clientX
        ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    }

    const handlePointerMove = (e: React.PointerEvent) => {
        if (!dragging) return
        setDragX(e.clientX - dragStartX.current)
    }

    const handlePointerUp = () => {
        if (!dragging) return
        if (dragX > SWIPE_THRESHOLD && activeSlide > 0) {
            setActiveSlide(s => s - 1)
        } else if (dragX < -SWIPE_THRESHOLD && activeSlide < slideCount - 1) {
            setActiveSlide(s => s + 1)
        }
        setDragging(false)
        setDragX(0)
    }

    const togglePlay = () => {
        const el = audioRef.current
        if (!el) return
        if (audioPlaying) {
            el.pause()
            setAudioPlaying(false)
        } else {
            el.play().then(() => setAudioPlaying(true)).catch(() => setAudioPlaying(false))
        }
    }

    const updateSlideText = (idx: number, text: string) => {
        if (!onChange) return
        const next = slides.map((s, i) => (i === idx ? { ...s, text } : s))
        onChange({ slides: next })
    }

    const updateSlideQuery = (idx: number, image_query: string) => {
        if (!onChange) return
        const next = slides.map((s, i) => (i === idx ? { ...s, image_query } : s))
        onChange({ slides: next })
    }

    const startQueryEdit = (idx: number) => {
        setQueryEditIdx(idx)
        setQueryDraft(slides[idx]?.image_query || '')
    }

    const commitQueryEdit = () => {
        if (queryEditIdx === null) return
        const idx = queryEditIdx
        const q = queryDraft.trim()
        if (q) {
            updateSlideQuery(idx, q)
            onReimageSlide?.(idx, q)
        }
        setQueryEditIdx(null)
        setQueryDraft('')
    }

    const trackDisplay = useMemo(() => {
        const t = carousel.music_track
        if (!t) return null
        const parts = [t.name, t.artist].filter(Boolean)
        return parts.join(' - ')
    }, [carousel.music_track])

    const offsetPct = -(activeSlide * 100) + (dragging ? (dragX / 320) * 100 : 0)

    return (
        <div className={`flex flex-col items-center gap-3 ${className || ''}`}>
            <div className="flex items-center justify-between w-[340px]">
                <span className="text-[11px] uppercase tracking-wide text-gray-400">
                    TikTok preview
                </span>
                <button
                    type="button"
                    onClick={() => setChromeVisible(v => !v)}
                    className="inline-flex items-center gap-1 rounded-md border border-gray-700 bg-gray-900/70 px-2 py-1 text-[11px] font-medium text-gray-200 hover:bg-gray-800"
                    aria-pressed={!chromeVisible}
                    title={chromeVisible ? 'Hide TikTok UI overlay' : 'Show TikTok UI overlay'}
                >
                    {chromeVisible ? (
                        <>
                            <EyeOff className="w-3 h-3" />
                            Hide UI
                        </>
                    ) : (
                        <>
                            <Eye className="w-3 h-3" />
                            Show UI
                        </>
                    )}
                </button>
            </div>
            <div
                className="relative mx-auto w-[340px] select-none"
                style={{ aspectRatio: '9 / 19.5' }}
            >
                {/* Phone frame */}
                <div className="absolute inset-0 rounded-[44px] border-[10px] border-gray-950 bg-black shadow-2xl overflow-hidden">
                    {/* Dynamic island */}
                    {chromeVisible && (
                        <div
                            aria-hidden
                            className="absolute top-2 left-1/2 -translate-x-1/2 w-28 h-7 bg-gray-950 rounded-full z-30"
                        />
                    )}

                    {/* Top row: For You / Following + search */}
                    {chromeVisible && (
                        <div className="absolute top-14 left-0 right-0 z-20 flex items-center justify-between px-5 text-white">
                            <div className="flex-1" />
                            <div className="flex items-center gap-4 text-sm font-semibold">
                                <span className="opacity-70">Following</span>
                                <span className="border-b-2 border-white pb-0.5">For You</span>
                            </div>
                            <div className="flex-1 flex justify-end">
                                <Search className="w-5 h-5" />
                            </div>
                        </div>
                    )}

                    {/* Slide track */}
                    <div
                        className="absolute inset-0 flex h-full touch-pan-y"
                        style={{
                            transform: `translateX(${offsetPct}%)`,
                            transition: dragging ? 'none' : 'transform 300ms ease-out',
                        }}
                        onPointerDown={handlePointerDown}
                        onPointerMove={handlePointerMove}
                        onPointerUp={handlePointerUp}
                        onPointerCancel={handlePointerUp}
                    >
                        {slideCount === 0 ? (
                            <div className="w-full h-full shrink-0 flex items-center justify-center bg-gradient-to-br from-indigo-950 to-gray-950">
                                <p className="text-white/60 text-sm">No slides yet</p>
                            </div>
                        ) : (
                            slides.map((slide, idx) => (
                                <SlideView
                                    key={idx}
                                    slide={slide}
                                    idx={idx}
                                    characterName={carousel.character_name}
                                    hook={idx === 0 ? carousel.hook_text : undefined}
                                    editMode={editMode}
                                    chromeVisible={chromeVisible}
                                    onTextChange={text => updateSlideText(idx, text)}
                                    onHookChange={hook_text => onChange?.({ hook_text })}
                                    onReimage={() => onReimageSlide?.(idx)}
                                    onEditQuery={() => startQueryEdit(idx)}
                                    isReimaging={reimagingSlideIdx === idx}
                                    renderMode={renderMode}
                                />
                            ))
                        )}
                    </div>

                    {/* Dots / index indicator (top) */}
                    {slideCount > 1 && chromeVisible && (
                        <div
                            aria-hidden
                            className="absolute top-[88px] left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5"
                        >
                            {slideCount <= 6 ? (
                                slides.map((_, i) => (
                                    <span
                                        key={i}
                                        className={`h-1.5 rounded-full transition-all ${
                                            i === activeSlide ? 'w-5 bg-white' : 'w-1.5 bg-white/40'
                                        }`}
                                    />
                                ))
                            ) : (
                                <span className="px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-medium">
                                    {activeSlide + 1}/{slideCount}
                                </span>
                            )}
                        </div>
                    )}

                    {/* Right rail - engagement icons (decorative) */}
                    {chromeVisible && (
                    <div
                        aria-hidden
                        className={`absolute right-2 bottom-32 z-20 flex flex-col items-center gap-5 text-white ${
                            editMode ? 'opacity-40' : 'opacity-100'
                        }`}
                    >
                        <div className="flex flex-col items-center">
                            <div className="w-10 h-10 rounded-full bg-white/10 border-2 border-white flex items-center justify-center">
                                <User className="w-5 h-5" />
                            </div>
                            <div className="mt-1 w-5 h-5 rounded-full bg-rose-500 flex items-center justify-center -translate-y-2">
                                <Plus className="w-3 h-3" />
                            </div>
                        </div>
                        {RIGHT_RAIL.map(({ icon: Icon, label }, i) => (
                            <div key={i} className="flex flex-col items-center">
                                <Icon className="w-7 h-7 drop-shadow" />
                                <span className="text-[11px] font-semibold drop-shadow">{label}</span>
                            </div>
                        ))}
                        {/* Spinning music disc on right rail */}
                        <div
                            className={`w-9 h-9 rounded-full bg-gradient-to-br from-gray-700 to-black border border-white/20 flex items-center justify-center ${
                                audioPlaying ? 'animate-spin-slow' : ''
                            }`}
                        >
                            <Music2 className="w-4 h-4" />
                        </div>
                    </div>
                    )}

                    {/* Bottom overlay: username, caption, music row */}
                    {chromeVisible && (
                    <div className="absolute bottom-0 left-0 right-0 z-20 px-3 pt-10 pb-14 bg-gradient-to-t from-black via-black/70 to-transparent">
                        <div className="max-w-[72%]">
                            <div className="text-white font-bold text-sm drop-shadow">
                                {formatUsername(carousel.character_name)}
                            </div>
                            <CaptionBlock
                                caption={carousel.caption}
                                hashtags={carousel.hashtags}
                                expanded={captionExpanded}
                                onToggleExpand={() => setCaptionExpanded(e => !e)}
                            />
                        </div>

                        {/* Music row */}
                        <div className="mt-2 flex items-center gap-2 text-white max-w-[72%]">
                            <Music2 className="w-3.5 h-3.5 shrink-0" />
                            <div className="overflow-hidden flex-1">
                                {trackDisplay ? (
                                    <div className="whitespace-nowrap animate-marquee inline-block text-xs font-medium drop-shadow">
                                        {trackDisplay}&nbsp;&nbsp;&nbsp;{trackDisplay}
                                    </div>
                                ) : (
                                    <span className="text-xs opacity-70 italic">No sound</span>
                                )}
                            </div>
                            {carousel.music_track?.preview_url ? (
                                <button
                                    type="button"
                                    onClick={togglePlay}
                                    className="shrink-0 w-6 h-6 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center"
                                    aria-label={audioPlaying ? 'Pause preview' : 'Play preview'}
                                >
                                    {audioPlaying ? (
                                        <Pause className="w-3 h-3" />
                                    ) : (
                                        <Play className="w-3 h-3" />
                                    )}
                                </button>
                            ) : (
                                <div
                                    className="shrink-0 w-6 h-6 rounded-full bg-white/10 flex items-center justify-center opacity-60"
                                    title="Preview audio not available"
                                >
                                    <Music2 className="w-3 h-3" />
                                </div>
                            )}
                        </div>
                        {carousel.music_track?.preview_url ? (
                            <audio
                                ref={audioRef}
                                src={carousel.music_track.preview_url}
                                loop
                                preload="none"
                            />
                        ) : null}
                    </div>
                    )}

                    {/* Bottom nav (decorative) */}
                    {chromeVisible && (
                    <div
                        aria-hidden
                        className="absolute bottom-0 left-0 right-0 z-20 flex items-center justify-around py-2 bg-black/60 text-white/90 text-[10px] font-medium"
                    >
                        <NavIcon icon={Home} label="Home" />
                        <NavIcon icon={Search} label="Discover" />
                        <div className="w-11 h-7 rounded-md bg-white text-black flex items-center justify-center">
                            <Plus className="w-5 h-5" />
                        </div>
                        <NavIcon icon={Inbox} label="Inbox" />
                        <NavIcon icon={User} label="Me" />
                    </div>
                    )}
                </div>
            </div>

            {/* Per-slide controls below the phone (edit mode only) */}
            {editMode && slideCount > 0 && (
                <div className="w-full max-w-[360px] flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2">
                        <span className="text-xs text-gray-400">
                            Slide {activeSlide + 1} of {slideCount}
                        </span>
                        <div className="flex items-center gap-1">
                            <button
                                type="button"
                                onClick={() => onReimageSlide?.(activeSlide)}
                                disabled={reimagingSlideIdx === activeSlide}
                                className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white"
                                title="Regenerate image with current query"
                            >
                                <RefreshCw
                                    className={`w-3 h-3 ${reimagingSlideIdx === activeSlide ? 'animate-spin' : ''}`}
                                />
                                Regenerate
                            </button>
                            <button
                                type="button"
                                onClick={() => startQueryEdit(activeSlide)}
                                className="rounded px-2 py-1 text-xs font-medium bg-gray-700 hover:bg-gray-600 text-white"
                                title="Edit the image search query"
                            >
                                Edit query
                            </button>
                        </div>
                    </div>
                    {queryEditIdx === activeSlide && (
                        <div className="rounded-lg border border-indigo-700 bg-gray-900/70 p-3 flex flex-col gap-2">
                            <label className="text-xs font-medium text-gray-300">
                                New image query for slide {activeSlide + 1}
                            </label>
                            <input
                                className="rounded bg-gray-950 border border-gray-700 px-2 py-1 text-sm text-white focus:outline-none focus:border-indigo-500"
                                value={queryDraft}
                                onChange={e => setQueryDraft(e.target.value)}
                                placeholder="e.g. Vader helmet close-up, red rim light"
                                autoFocus
                            />
                            <div className="flex items-center gap-2 justify-end">
                                <button
                                    type="button"
                                    onClick={() => setQueryEditIdx(null)}
                                    className="rounded px-2 py-1 text-xs font-medium bg-gray-700 hover:bg-gray-600 text-white"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    onClick={commitQueryEdit}
                                    className="rounded px-2 py-1 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white"
                                >
                                    Search &amp; replace
                                </button>
                            </div>
                        </div>
                    )}
                    {onOpenMusicPicker && (
                        <button
                            type="button"
                            onClick={onOpenMusicPicker}
                            className="flex items-center justify-center gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2 text-xs font-medium text-white hover:bg-gray-800"
                        >
                            <Music2 className="w-3.5 h-3.5" />
                            {carousel.music_track ? 'Change music' : 'Pick music'}
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}

function NavIcon({ icon: Icon, label }: { icon: typeof Home; label: string }) {
    return (
        <div className="flex flex-col items-center gap-0.5">
            <Icon className="w-5 h-5" />
            <span>{label}</span>
        </div>
    )
}

function CaptionBlock({
    caption,
    hashtags,
    expanded,
    onToggleExpand,
}: {
    caption: string | undefined
    hashtags: string[] | undefined
    expanded: boolean
    onToggleExpand: () => void
}) {
    const tags = (hashtags || []).slice(0, expanded ? hashtags?.length : 4)
    const hasMoreTags = (hashtags?.length || 0) > tags.length
    const captionText = caption || ''
    const isLong = captionText.length > 120
    const displayText = expanded || !isLong ? captionText : captionText.slice(0, 120).trimEnd() + '...'

    return (
        <div className="text-white text-xs leading-snug drop-shadow">
            {captionText && (
                <span className="whitespace-pre-wrap">{displayText}</span>
            )}
            {isLong && (
                <button
                    type="button"
                    onClick={onToggleExpand}
                    className="ml-1 font-semibold opacity-80 hover:opacity-100"
                >
                    {expanded ? 'less' : 'more'}
                </button>
            )}
            {tags.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                    {tags.map((tag, i) => (
                        <span key={i} className="font-semibold">
                            {tag.startsWith('#') ? tag : `#${tag}`}
                        </span>
                    ))}
                    {hasMoreTags && !expanded && (
                        <button
                            type="button"
                            onClick={onToggleExpand}
                            className="opacity-70 hover:opacity-100"
                        >
                            +{(hashtags?.length || 0) - tags.length}
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}

interface SlideViewProps {
    slide: CarouselSlide
    idx: number
    characterName?: string
    hook?: string
    editMode: boolean
    chromeVisible: boolean
    onTextChange: (text: string) => void
    onHookChange: (text: string) => void
    onReimage: () => void
    onEditQuery: () => void
    isReimaging: boolean
    renderMode?: RenderMode
}

function SlideView({
    slide,
    characterName,
    hook,
    editMode,
    chromeVisible,
    onTextChange,
    onHookChange,
    onReimage,
    onEditQuery,
    isReimaging,
    renderMode = 'clean',
}: SlideViewProps) {
    const hasImage = Boolean(slide.image_url)
    const initial = initialFallback(characterName)

    return (
        <div className="relative w-full h-full shrink-0">
            {hasImage ? (
                <img
                    src={slide.image_url}
                    alt={slide.image_query || `Slide ${slide.slide_num}`}
                    className="absolute inset-0 w-full h-full object-cover"
                    draggable={false}
                />
            ) : (
                <div className="absolute inset-0 bg-gradient-to-br from-indigo-900 via-gray-900 to-black flex items-center justify-center">
                    <span className="text-7xl font-black text-white/15">{initial}</span>
                </div>
            )}

            {/* Legibility gradient */}
            <div
                aria-hidden
                className="absolute inset-0 bg-gradient-to-b from-black/50 via-transparent to-black/70"
            />

            {/* Reimage spinner overlay */}
            {isReimaging && (
                <div className="absolute inset-0 bg-black/60 flex items-center justify-center z-10">
                    <div className="flex items-center gap-2 text-white text-sm">
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Re-imaging...
                    </div>
                </div>
            )}

            {/* Edit-mode image actions */}
            {editMode && !isReimaging && (
                <div className="absolute top-24 left-1/2 -translate-x-1/2 z-10 flex gap-2">
                    <button
                        type="button"
                        onClick={onReimage}
                        className="flex items-center gap-1 rounded-full bg-black/70 hover:bg-black/90 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur"
                    >
                        <RefreshCw className="w-3 h-3" />
                        Regenerate
                    </button>
                    <button
                        type="button"
                        onClick={onEditQuery}
                        className="rounded-full bg-black/70 hover:bg-black/90 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur"
                    >
                        Edit query
                    </button>
                </div>
            )}

            {/* Hook (slide 1 top) */}
            {hook !== undefined && (
                <div className="absolute top-[140px] left-4 right-4 z-10">
                    {editMode ? (
                        <textarea
                            value={hook}
                            onChange={e => onHookChange(e.target.value)}
                            rows={3}
                            className="w-full resize-none rounded-md bg-black/60 backdrop-blur px-2 py-1.5 text-[22px] font-black text-white leading-[1.05] tracking-tight focus:outline-none focus:ring-2 focus:ring-indigo-500 placeholder:text-white/40"
                            placeholder="Hook..."
                        />
                    ) : hook ? (
                        <CaptivatingText text={hook} variant="hook" renderMode={renderMode} />
                    ) : null}
                </div>
            )}

            {/* Slide text */}
            <div
                className={`absolute z-10 left-4 ${
                    chromeVisible ? 'bottom-[170px] right-16' : 'bottom-10 right-4'
                }`}
            >
                {editMode ? (
                    <textarea
                        value={slide.text || ''}
                        onChange={e => onTextChange(e.target.value)}
                        rows={4}
                        className="w-full resize-none rounded-md bg-black/60 backdrop-blur px-2 py-1.5 text-[17px] font-bold text-white leading-[1.15] tracking-tight focus:outline-none focus:ring-2 focus:ring-indigo-500 placeholder:text-white/40"
                        placeholder="Slide text..."
                    />
                ) : (
                    <CaptivatingText text={slide.text} variant="slide" renderMode={renderMode} />
                )}
            </div>
        </div>
    )
}
