import { useRef, useState, useEffect } from 'react'
import type { CarouselSlide } from '@/hooks/useCharacterContentApi'
import { ImageOff } from 'lucide-react'

export interface CarouselSlidesViewProps {
    slides: CarouselSlide[]
    /** Optional aspect ratio class; default is vertical 9/16 like TikTok. */
    aspectClass?: string
}

/**
 * Horizontal snap-scrolling slide carousel viewer for mobile review.
 *
 * Each slide is full-width within its container, text overlayed on the image,
 * and we surface a small "1/5" indicator + dots so the reviewer knows position.
 * Swipes use native CSS scroll-snap; no JS gesture handlers required, which
 * keeps it composable inside a parent that scrolls vertically.
 */
export function CarouselSlidesView({
    slides,
    aspectClass = 'aspect-[9/16]',
}: CarouselSlidesViewProps) {
    const scrollerRef = useRef<HTMLDivElement | null>(null)
    const [activeIndex, setActiveIndex] = useState(0)

    // Track active slide based on scroll position.
    useEffect(() => {
        const el = scrollerRef.current
        if (!el) return
        const onScroll = () => {
            const slideWidth = el.clientWidth
            if (slideWidth === 0) return
            const idx = Math.round(el.scrollLeft / slideWidth)
            setActiveIndex(idx)
        }
        el.addEventListener('scroll', onScroll, { passive: true })
        return () => el.removeEventListener('scroll', onScroll)
    }, [])

    if (!slides || slides.length === 0) {
        return (
            <div
                className={`${aspectClass} w-full rounded-xl bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-500 text-sm`}
            >
                No slides
            </div>
        )
    }

    const scrollTo = (idx: number) => {
        const el = scrollerRef.current
        if (!el) return
        el.scrollTo({ left: idx * el.clientWidth, behavior: 'smooth' })
    }

    return (
        <div className="relative w-full">
            <div
                ref={scrollerRef}
                className={`${aspectClass} w-full overflow-x-auto overflow-y-hidden flex snap-x snap-mandatory rounded-xl bg-gray-800 border border-gray-700`}
                style={{ scrollbarWidth: 'none' }}
            >
                {slides.map((slide, idx) => (
                    <div
                        key={`${slide.slide_num}-${idx}`}
                        className="relative flex-shrink-0 w-full h-full snap-center"
                    >
                        {slide.image_url ? (
                            <img
                                src={slide.image_url}
                                alt={slide.image_query || `Slide ${slide.slide_num}`}
                                className="absolute inset-0 w-full h-full object-cover"
                                loading={idx === 0 ? 'eager' : 'lazy'}
                            />
                        ) : (
                            <div className="absolute inset-0 bg-gradient-to-br from-indigo-950 via-gray-900 to-gray-950 flex items-center justify-center">
                                <ImageOff className="w-10 h-10 text-gray-600" />
                            </div>
                        )}
                        {/* Dim gradient so text reads even on bright images */}
                        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-black/40 pointer-events-none" />
                        {/* Slide text */}
                        <div className="absolute inset-0 p-4 flex flex-col justify-end">
                            <p className="text-white text-lg font-semibold leading-snug whitespace-pre-wrap drop-shadow-lg">
                                {slide.text}
                            </p>
                        </div>
                        {/* Counter badge */}
                        <div className="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-medium">
                            {idx + 1}/{slides.length}
                        </div>
                    </div>
                ))}
            </div>

            {/* Dots */}
            {slides.length > 1 && (
                <div className="flex items-center justify-center gap-1.5 mt-2">
                    {slides.map((_, idx) => (
                        <button
                            key={idx}
                            aria-label={`Go to slide ${idx + 1}`}
                            onClick={() => scrollTo(idx)}
                            className={`w-1.5 h-1.5 rounded-full transition-all ${
                                activeIndex === idx
                                    ? 'w-4 bg-indigo-400'
                                    : 'bg-gray-600 hover:bg-gray-500'
                            }`}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

export default CarouselSlidesView
