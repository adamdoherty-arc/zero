# Plan: Add Visual Slide Previews to Carousel Cards

## Context
The Carousels tab on the Character Detail page only shows metadata (status badge, hook text, slide count, AI review scores) but no actual visual preview of the carousel slides. Each slide already has `image_url` and `text` data available — it's just not rendered. The whole point of a carousel is to see the slides.

## Change
Enhance the `CarouselsSection` component in `CharacterDetailPage.tsx` to show a horizontal strip of slide image thumbnails with text overlays, so you can actually see what the carousel looks like at a glance.

## File to Modify
- [frontend/src/pages/CharacterDetailPage.tsx](frontend/src/pages/CharacterDetailPage.tsx) — `CarouselsSection` component (lines 234-320)

## Implementation

### Inside each carousel card (after the hook text line at line 273), add a slide preview strip:

1. **Horizontal scroll row of slide thumbnails** — show all slides in a flex row with `overflow-x-auto`
2. Each slide shows:
   - The slide image (`slide.image_url`) as a small card-sized thumbnail (e.g., 9:16 aspect ratio, ~80px wide)
   - If no image, show a placeholder with the slide number
   - Slide text overlaid at the bottom (truncated, small font)
   - Slide number badge in the corner
3. Keep the existing AI review score bars below
4. Add the hook text in a styled block (similar to the indigo box in `CarouselPreview`) instead of plain text
5. Show caption below slides if present

### Visual layout per carousel card:
```
┌──────────────────────────────────────────────────────┐
│ [pending review]  hidden truths          8.5/10 [Approve] │
│                                                      │
│ ┌─────────────────────────────────────────────┐      │
│ │ Hook: "The Truth Loki Hid From Everyone..." │      │
│ └─────────────────────────────────────────────┘      │
│                                                      │
│ [img1] [img2] [img3] [img4] [img5] [img6]  ← scroll │
│  Sl.1   Sl.2   Sl.3   Sl.4   Sl.5   Sl.6           │
│                                                      │
│ "Caption text here..."                               │
│ #hashtag1 #hashtag2 #hashtag3                        │
│                                                      │
│ ▓▓▓▓▓▓▓▓░░ 9  ▓▓▓▓▓▓▓░░░ 8  ▓▓▓▓▓▓▓▓▓░ 9  ▓▓▓▓▓▓▓░░░ 8 │
│ hook strength  fact quality  engagement   caption    │
└──────────────────────────────────────────────────────┘
```

### Code approach:
- Reuse patterns from `CarouselPreview` in `CharacterContentPage.tsx` (the slide grid at lines 874-883)
- Adapt to a horizontal thumbnail strip instead of a 2-3 column grid (better for the card layout)
- Slide thumbnails: `w-20 h-28` (roughly 9:16), `object-cover`, `rounded-lg`
- For slides without `image_url`: dark placeholder div with slide number centered
- Text overlay: absolute positioned at bottom of each thumbnail, small white text on dark gradient

## Verification
1. Rebuild frontend (volume-mounted, just restart): `docker compose -f docker-compose.sprint.yml restart zero-ui`
2. Navigate to a character's detail page → Carousels tab
3. Verify slide images are visible in each carousel card
4. Verify horizontal scrolling works when there are many slides
5. Verify cards without images show text-only placeholders gracefully
