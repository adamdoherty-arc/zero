import { useEffect, useMemo, useRef, useState } from 'react'
import {
    Bookmark,
    Eye,
    EyeOff,
    Heart,
    Home,
    Image as ImageIcon,
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
import ChangeImageModal from './ChangeImageModal'

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

// Accent color palettes for visual variety across carousels.
// Each carousel gets a consistent palette based on its ID hash unless the
// backend stamped a universe-specific accent_color on text_overlay_specs.
const ACCENT_PALETTES = [
    { pill: 'bg-yellow-300 text-black', label: 'bg-yellow-300 text-black', hex: '#FDE047' },
    { pill: 'bg-rose-400 text-black', label: 'bg-rose-400 text-black', hex: '#FB7185' },
    { pill: 'bg-emerald-400 text-black', label: 'bg-emerald-400 text-black', hex: '#34D399' },
    { pill: 'bg-violet-400 text-white', label: 'bg-violet-400 text-white', hex: '#A78BFA' },
    { pill: 'bg-orange-400 text-black', label: 'bg-orange-400 text-black', hex: '#FB923C' },
    { pill: 'bg-sky-400 text-black', label: 'bg-sky-400 text-black', hex: '#38BDF8' },
    { pill: 'bg-lime-400 text-black', label: 'bg-lime-400 text-black', hex: '#A3E635' },
    { pill: 'bg-fuchsia-400 text-black', label: 'bg-fuchsia-400 text-black', hex: '#E879F9' },
    { pill: 'bg-red-500 text-white', label: 'bg-red-500 text-white', hex: '#EF4444' },
    { pill: 'bg-teal-400 text-black', label: 'bg-teal-400 text-black', hex: '#2DD4BF' },
    { pill: 'bg-amber-300 text-black', label: 'bg-amber-300 text-black', hex: '#FCD34D' },
    { pill: 'bg-pink-400 text-black', label: 'bg-pink-400 text-black', hex: '#F472B6' },
] as const

// Font-family dispatch. Backend assigns font_style per slide (see
// character_content_utils.pick_font_style_for_slide); frontend picks the
// matching Tailwind family. Falls back to Inter Black for unknown styles.
const FONT_STYLE_MAP: Record<string, string> = {
    'display-hook': 'font-display-hook font-normal',
    'display-stat': 'font-display-stat font-normal tracking-wider',
    'display-quote': 'font-display-quote font-black italic',
    'display-hot': 'font-display-hot font-normal',
    'display-shout': 'font-display-shout font-normal tracking-wide',
    'display-block': 'font-display-block font-normal tracking-wide',
    'display-body': 'font-sans font-black',
}

function fontClassFor(style: string | undefined): string {
    if (!style) return 'font-sans font-black'
    return FONT_STYLE_MAP[style] || 'font-sans font-black'
}

type Accent = {
    pill: string
    label: string
    hex: string
    /** When set, renderToken uses inline backgroundColor instead of the pill class. */
    inlineHex?: string
}

function accentForCarousel(carouselId: string): Accent {
    let hash = 0
    for (let i = 0; i < carouselId.length; i++) {
        hash = ((hash << 5) - hash + carouselId.charCodeAt(i)) | 0
    }
    return { ...ACCENT_PALETTES[Math.abs(hash) % ACCENT_PALETTES.length] }
}

// Pick the best contrasting text color (black/white) for a given hex bg.
// Uses a simple luminance heuristic so accent colors stamped by the backend
// (universe-specific) stay readable.
function pickReadableTextOnHex(hex: string): string {
    const m = hex.replace('#', '').match(/^([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i)
    if (!m) return '#000'
    const r = parseInt(m[1], 16)
    const g = parseInt(m[2], 16)
    const b = parseInt(m[3], 16)
    // perceptual luminance
    const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return lum > 0.55 ? '#000' : '#fff'
}

// Words that look like section headers or common content labels.
// These should NOT be highlighted as "shout" emphasis even though they're uppercase.
const SHOUT_SKIPLIST = new Set([
    'SCENE', 'ORIGIN', 'SHIFT', 'CHANGE', 'POLL', 'TIME', 'COMICS', 'SCREEN',
    'BIGGEST', 'DELETED', 'NOTE', 'FACT', 'WINNER', 'THEORY', 'SOURCE',
    'SEASON', 'EPISODE', 'PART', 'CHAPTER', 'STEP', 'RULE', 'TYPE',
])

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

// Trigram-overlap heuristic: true if slide body text is basically a restatement
// of the hook. Matches the backend's _trigram_overlap in carousel_audit_service.
// Used to suppress the bottom text block on slide 1 when the LLM (or legacy
// data) echoes the hook into slides[0].text.
function slideBodyMatchesHook(body: string, hook: string, threshold = 0.7): boolean {
    const norm = (s: string) =>
        (s || '')
            .toLowerCase()
            .replace(/[^a-z0-9 ]/g, '')
            .replace(/\s+/g, ' ')
            .trim()
    const a = norm(body)
    const b = norm(hook)
    if (a.length < 3 || b.length < 3) return false
    if (a === b) return true
    const trigrams = (s: string) => {
        const set = new Set<string>()
        for (let i = 0; i < s.length - 2; i++) set.add(s.slice(i, i + 3))
        return set
    }
    const ta = trigrams(a)
    const tb = trigrams(b)
    let inter = 0
    for (const t of ta) if (tb.has(t)) inter++
    const union = ta.size + tb.size - inter
    return union > 0 && inter / union >= threshold
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
 * Parses copy and breaks it into tokens. Only highlights:
 *   - **double asterisks** -> accent pill (explicitly marked emphasis)
 *   - UPPERCASE words -> accent pill (hooks only, disabled for slide text)
 *   - $numbers / percentages -> cyan stat pill
 * Everything else renders as plain white impact text with shadow.
 */
function CaptivatingText({
    text,
    variant,
    renderMode = 'clean',
    accent,
    fontStyle,
}: {
    text: string | undefined
    variant: TextVariant
    renderMode?: RenderMode
    accent?: Accent
    fontStyle?: string
}) {
    if (!text) return null

    const fontCls = fontClassFor(fontStyle)
    // Anton/Bebas/Staatliches are already heavy display caps — bump size a touch,
    // Playfair quotes stay smaller/italic for visual contrast, Permanent Marker
    // gets a slight size bump to compensate for its looser weight.
    const sizeByVariant = (() => {
        if (variant === 'hook') {
            if (fontStyle === 'display-hook') return 'text-[32px] leading-[0.98] tracking-tight uppercase'
            if (fontStyle === 'display-stat') return 'text-[34px] leading-[1.0] tracking-wider uppercase'
            if (fontStyle === 'display-quote') return 'text-[24px] leading-[1.1] tracking-tight'
            if (fontStyle === 'display-hot') return 'text-[28px] leading-[1.05] tracking-tight'
            if (fontStyle === 'display-shout' || fontStyle === 'display-block') return 'text-[32px] leading-[1.02] tracking-wide uppercase'
            return 'text-[26px] leading-[1.05] tracking-tight'
        }
        if (variant === 'slide') {
            if (fontStyle === 'display-hook') return 'text-[24px] leading-[1.05] tracking-tight uppercase'
            if (fontStyle === 'display-stat') return 'text-[26px] leading-[1.05] tracking-wider uppercase'
            if (fontStyle === 'display-quote') return 'text-[18px] leading-[1.2] tracking-tight'
            if (fontStyle === 'display-hot') return 'text-[20px] leading-[1.1] tracking-tight'
            if (fontStyle === 'display-shout' || fontStyle === 'display-block') return 'text-[24px] leading-[1.1] tracking-wide uppercase'
            return 'text-[19px] leading-[1.15] tracking-tight'
        }
        return 'text-[15px] leading-[1.2]'
    })()
    const sizeClasses = sizeByVariant

    // Only extract labels for hooks, not body slides (avoids over-pilling)
    const { label, body } = variant === 'hook' ? splitLeadLabel(text) : { label: null, body: text }
    const lines = body.split(/\r?\n/).filter((l, i, arr) => l.trim() || i < arr.length - 1)

    const containerStyle: React.CSSProperties =
        renderMode === 'stroked'
            ? {
                  textShadow: TEXT_SHADOW_LEGACY,
                  WebkitTextStroke: '0.4px rgba(0,0,0,0.55)',
              }
            : {
                  textShadow: TEXT_SHADOW_CLEAN,
                  filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.55))',
              }

    // Body slides also accept UPPERCASE highlights now, with the SHOUT_SKIPLIST
    // filtering out section-header words. This rescues old carousels that have
    // no **bold** markers but contain proper-noun ALL-CAPS payoff words.
    const enableShouts = true

    // Treat the last line as a payoff line when there are 3+ lines on a body
    // slide. The payoff gets bolder/larger to give the slide a punchy ending.
    const isBodyMultiLine = variant === 'slide' && lines.length >= 3

    const labelStyle: React.CSSProperties = accent?.inlineHex
        ? {
              backgroundColor: accent.inlineHex,
              color: pickReadableTextOnHex(accent.inlineHex),
              textShadow: 'none',
              WebkitTextStroke: '0',
              filter: 'none',
          }
        : { textShadow: 'none', WebkitTextStroke: '0', filter: 'none' }

    return (
        <div className={`${fontCls} text-white ${sizeClasses}`} style={containerStyle}>
            {label && (
                <div className="mb-1.5">
                    <span
                        className={`inline-block rounded-md ${accent?.inlineHex ? '' : (accent?.label ?? 'bg-yellow-300 text-black')} px-1.5 py-0.5 text-[13px] font-black uppercase tracking-wide ${
                            variant === 'hook' ? '-skew-x-3' : ''
                        }`}
                        style={labelStyle}
                    >
                        {label}
                    </span>
                </div>
            )}
            {lines.map((line, li) => {
                const isPayoff = isBodyMultiLine && li === lines.length - 1
                const lineClasses = isPayoff
                    ? 'flex flex-wrap items-baseline gap-x-1.5 gap-y-1 mt-1 text-[22px] tracking-tight'
                    : 'flex flex-wrap items-baseline gap-x-1.5 gap-y-1'
                return (
                    <div key={li} className={lineClasses}>
                        {coalesce(tokenize(line, enableShouts)).map((tok, ti) =>
                            renderToken(tok, `${li}-${ti}`, variant, accent),
                        )}
                    </div>
                )
            })}
        </div>
    )
}

// If copy starts with a short category-style label followed by a colon,
// extract it as a pill. Only matches labels that are 2-4 words and under
// 24 chars (e.g. "Hot Take:", "Dark Origin:", "Fan Theory Deep Dive:").
// Longer or sentence-like prefixes are left as plain text.
function splitLeadLabel(text: string): { label: string | null; body: string } {
    const idx = text.indexOf(':')
    if (idx <= 0 || idx > 24) return { label: null, body: text }
    const prefix = text.slice(0, idx).trim()
    const rest = text.slice(idx + 1).trim()
    if (!rest || /[\n]/.test(prefix)) {
        return { label: null, body: text }
    }
    // Only allow 1-4 words as labels
    const wordCount = prefix.split(/\s+/).length
    if (wordCount > 4) return { label: null, body: text }
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

// Markup tokenizer:
//   **word** / **a phrase** -> accent pill highlight (always active)
//   UPPERCASE (>=4 letters)  -> accent pill highlight (only when enableShouts=true, i.e. hooks)
//   number / percent / $amt  -> cyan stat pill
function tokenize(line: string, enableShouts = true): Token[] {
    if (!line) return [{ kind: 'plain', value: '' }]

    const tokens: Token[] = []
    const boldSplit = line.split(/(\*\*[^*]+\*\*)/g)

    for (const chunk of boldSplit) {
        if (!chunk) continue
        if (chunk.startsWith('**') && chunk.endsWith('**')) {
            tokens.push({ kind: 'bold', value: chunk.slice(2, -2) })
            continue
        }
        const words = chunk.split(/\s+/)
        for (const w of words) {
            if (!w) continue
            if (/^\$?\d[\d,.]*%?x?$/i.test(w) || /^\d+[kmb]\+?$/i.test(w)) {
                tokens.push({ kind: 'stat', value: w })
            } else if (
                enableShouts &&
                /^[A-Z0-9!?.,'-]{4,}$/.test(w) &&
                /[A-Z]{2,}/.test(w) &&
                !SHOUT_SKIPLIST.has(w.replace(/[^A-Z]/g, ''))
            ) {
                tokens.push({ kind: 'shout', value: w })
            } else {
                tokens.push({ kind: 'plain', value: w })
            }
        }
    }
    return tokens
}

function renderToken(
    tok: Token,
    key: string,
    _variant: TextVariant,
    accent?: Accent,
) {
    if (tok.kind === 'bold' || tok.kind === 'shout') {
        const useInline = Boolean(accent?.inlineHex)
        const pillClasses = useInline ? '' : (accent?.pill ?? 'bg-yellow-300 text-black')
        const pillStyle: React.CSSProperties = useInline
            ? {
                  backgroundColor: accent!.inlineHex,
                  color: pickReadableTextOnHex(accent!.inlineHex!),
                  textShadow: 'none',
                  WebkitTextStroke: '0',
                  letterSpacing: '-0.01em',
              }
            : { textShadow: 'none', WebkitTextStroke: '0', letterSpacing: '-0.01em' }
        return (
            <span
                key={key}
                className={`inline-block rounded-md ${pillClasses} px-1.5 py-0.5 -skew-x-3`}
                style={pillStyle}
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
    const [changeImageIdx, setChangeImageIdx] = useState<number | null>(null)
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

    const accent = useMemo<Accent>(() => {
        const base = accentForCarousel(carousel.id || '')
        const stamped = (carousel.text_overlay_specs || [])
            .map(spec => spec?.accent_color)
            .find(hex => typeof hex === 'string' && /^#[\da-f]{6}$/i.test(hex))
        if (stamped) {
            return { ...base, inlineHex: stamped, hex: stamped }
        }
        return base
    }, [carousel.id, carousel.text_overlay_specs])

    // Build per-slide accent + font style lookup by slide_num. Backend can stamp
    // these on text_overlay_specs (accent_color / font_style) to vary per slide.
    const slideAccents = useMemo(() => {
        const map = new Map<number, { accent?: Accent; fontStyle?: string }>()
        for (const spec of carousel.text_overlay_specs || []) {
            if (!spec) continue
            const snum = spec.slide_num
            if (typeof snum !== 'number') continue
            const hex = spec.accent_color
            const next: { accent?: Accent; fontStyle?: string } = {
                fontStyle: spec.font_style || undefined,
            }
            if (typeof hex === 'string' && /^#[\da-f]{6}$/i.test(hex)) {
                next.accent = { ...accent, inlineHex: hex, hex }
            }
            map.set(snum, next)
        }
        return map
    }, [carousel.text_overlay_specs, accent])
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
                            slides.map((slide, idx) => {
                                const slideNum = slide.slide_num ?? idx + 1
                                const perSlide = slideAccents.get(slideNum) || {}
                                const slideAccent = perSlide.accent || accent
                                // Prefer slide-level fields (slide.font_style / slide.accent_color)
                                // over text_overlay_specs when both are present, so the backend
                                // can stamp them at either layer.
                                const fontStyle = slide.font_style || perSlide.fontStyle
                                const slideLevelHex =
                                    typeof slide.accent_color === 'string' &&
                                    /^#[\da-f]{6}$/i.test(slide.accent_color)
                                        ? slide.accent_color
                                        : undefined
                                const finalAccent = slideLevelHex
                                    ? { ...slideAccent, inlineHex: slideLevelHex, hex: slideLevelHex }
                                    : slideAccent
                                return (
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
                                        accent={finalAccent}
                                        fontStyle={fontStyle}
                                    />
                                )
                            })
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
                                onClick={() => setChangeImageIdx(activeSlide)}
                                className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium bg-emerald-600 hover:bg-emerald-500 text-white"
                                title="Pick from pool, paste URL, or upload"
                            >
                                <ImageIcon className="w-3 h-3" />
                                Change image
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
            {changeImageIdx !== null && (
                <ChangeImageModal
                    carouselId={carousel.id}
                    slideIndex={changeImageIdx}
                    slideNum={slides[changeImageIdx]?.slide_num ?? changeImageIdx + 1}
                    currentUrl={slides[changeImageIdx]?.image_url}
                    onClose={() => setChangeImageIdx(null)}
                />
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
    accent?: Accent
    fontStyle?: string
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
    accent,
    fontStyle,
}: SlideViewProps) {
    const [imgErrored, setImgErrored] = useState(false)
    const hasImage = Boolean(slide.image_url) && !imgErrored
    const initial = initialFallback(characterName)

    return (
        <div className="relative w-full h-full shrink-0">
            {hasImage ? (
                <img
                    src={slide.image_url}
                    alt={slide.image_query || `Slide ${slide.slide_num}`}
                    className="absolute inset-0 w-full h-full object-cover"
                    draggable={false}
                    onError={() => setImgErrored(true)}
                />
            ) : (
                <div className="absolute inset-0 bg-gradient-to-br from-indigo-900 via-gray-900 to-black flex flex-col items-center justify-center gap-3">
                    <span className="text-7xl font-black text-white/15">{initial}</span>
                    {(!slide.image_url || imgErrored) && onReimage && (
                        <button
                            type="button"
                            onClick={onReimage}
                            className="flex items-center gap-1.5 rounded-full bg-rose-500/90 hover:bg-rose-500 px-3 py-1.5 text-xs font-semibold text-white shadow-lg backdrop-blur"
                            aria-label="Re-source slide image"
                        >
                            <RefreshCw className="w-3.5 h-3.5" />
                            {imgErrored ? 'Image broken — re-source' : 'No image — re-source'}
                        </button>
                    )}
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
                        <CaptivatingText text={hook} variant="hook" renderMode={renderMode} accent={accent} fontStyle={fontStyle} />
                    ) : null}
                </div>
            )}

            {/* Slide text - hidden on slide 1 (hook already fills that slot)
                when body is empty or duplicates the hook. Still rendered in
                edit mode so users can intentionally add different slide-1 body
                text if they want. */}
            <div
                className={`absolute z-10 left-4 ${
                    chromeVisible ? 'bottom-[170px] right-16' : 'bottom-10 right-4'
                } ${
                    !editMode && hook !== undefined && hook !== null &&
                    (!(slide.text || '').trim() || slideBodyMatchesHook(slide.text || '', hook || ''))
                        ? 'hidden'
                        : ''
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
                    <CaptivatingText text={slide.text} variant="slide" renderMode={renderMode} accent={accent} fontStyle={fontStyle} />
                )}
            </div>
        </div>
    )
}
