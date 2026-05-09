# Industry Research: Content Creation Systems

**Researched**: 2026-04-15
**Purpose**: Identify gaps between Zero's Character Content system and world-class content factories

## 1. Image Compositing (#1 Critical Gap)

Zero generates `TextOverlaySpec` objects (position, font weight, max chars, opacity) but **never renders actual images**. Without rendering, carousels exist only as JSON — they can't be published.

### Industry Standard
- **Pillow (Python)**: Most common for server-side image generation. Supports text rendering, layering, shadows.
- **Sharp (Node.js)**: High-performance image processing, used by Vercel/Next.js Image.
- **Canva-style rendering**: Canvas API or Puppeteer headless screenshot of HTML template.
- **Best approach for Zero**: Pillow — already in Python ecosystem, renders 1080x1350 PNGs locally.

### What to Build
- `carousel_renderer_service.py` — takes character image URL + TextOverlaySpec + slide text → 1080x1350 PNG
- White bold text with slight shadow (matching "everything.daily" TikTok format)
- Store rendered images in `workspace/content/rendered/{carousel_id}/`
- New endpoint: `POST /api/characters/carousels/{id}/render`

## 2. Content Calendar & Auto-Scheduling

### Industry Standard
- **Buffer/Hootsuite**: Queue-based scheduling with optimal time suggestions
- **Later.com**: Visual calendar, drag-and-drop, best-time-to-post AI
- **Key pattern**: Content calendar view + time slot optimization + auto-queue approved content

### What Zero Lacks
- No scheduling at all — approved carousels sit idle
- No posting time optimization
- No content calendar view
- No evergreen content recycling

## 3. TikTok-Specific SEO

### Industry Best Practices
- **3-layer hashtag strategy**: 3 broad (#marvel #comics) + 3 niche (#lokilore #thorhiddendetails) + 3 trending
- **Caption structure**: Hook question + value teaser + CTA + hashtags
- **On-screen text indexing**: TikTok OCRs visible text for discovery — optimize overlay text for searchability
- **Sound selection**: Trending sounds get 2-5x more reach; character-appropriate epic/dramatic music
- **Carousel-specific**: First slide is the thumbnail — must have strongest hook text + eye-catching image

### What Zero Has vs Needs
- Has 15 content angles and 10 story templates (good variety)
- Has 49 music tracks seeded by mood (good foundation)
- Missing: hashtag generation, caption optimization, first-slide thumbnail optimization
- Missing: trending sound correlation with content type

## 4. A/B Testing & Performance Learning

### Industry Standard
- **Thompson Sampling**: Multi-armed bandit for hook/angle/template selection (used by Netflix, Spotify)
- **Bayesian optimization**: Adjusts content mix based on engagement signals
- **Key metrics**: Save rate > share rate > comment rate > view completion > likes (weighted by value)

### What Zero Has vs Needs
- Has `content_learning_engine.py` — but it's never called
- Has prompt evolution service with Thompson Sampling — not connected to character content
- Needs: Record outcomes after AI review + after publishing, feed back into generation

## 5. Multi-Platform Publishing

### Industry Standard
- **Cross-posting**: TikTok → Instagram Reels → YouTube Shorts (same vertical format)
- **Platform adaptation**: Slight caption/hashtag adjustments per platform
- **API integration**: TikTok Content Posting API, Instagram Graph API, YouTube Data API v3

### What Zero Has
- TikTok Shop integration exists (product listing/affiliate) but NOT TikTok Content Posting
- No Instagram or YouTube integration
- Publishing dimension scored 5/100 — the biggest gap

## 6. Research Depth Benchmarks

### Top Character Content Creators
- **Screen Rant**: 30+ sources per article, cross-references comics/MCU/interviews
- **CBR**: Deep dive into comic history with issue numbers
- **everything.daily (TikTok)**: 5-7 curated "mind-blowing" facts per carousel, heavy use of fandom wiki data

### What Zero Has vs Needs
- Currently: Only Reddit fragments working (30 fragments). Fandom wiki, TV Tropes, IMDB, quotes sources all failing silently.
- Target: 50+ research fragments per character from 5+ sources
- Fix: Connect Firecrawl at `host.docker.internal:3002` for clean web scraping of fandom wikis and IMDB

## 7. Engagement Formula Patterns

From analyzing top-performing character fact carousels:

| Element | Pattern | Impact |
|---------|---------|--------|
| Hook slide | Question or shocking statement | +40% swipe-through |
| Slide count | 6-7 optimal (not 5, not 8+) | +15% completion |
| Fact escalation | Each fact more surprising than last | +25% saves |
| CTA slide | "Follow for Part 2" or "Which surprised you?" | +60% follows |
| Text positioning | Center-bottom, white bold, 40px max | +20% readability |
| Character image | Close-up face, high contrast | +30% stops |

## Priority Actions (Ordered by Impact)

1. **Connect Firecrawl** → Research Quality 45→65 (+20)
2. **Image compositing pipeline** → Publishing 5→35 (+30)
3. **Wire content_learning_engine** → Learning 20→35 (+15)
4. **Generate 10+ carousels** → Content Generation 25→50 (+25)
5. **Add tests** → Code Quality 68→83 (+15)
6. **TikTok SEO in prompts** → Strategy 55→65 (+10)
7. **Auto-scheduling** → Pipeline 72→82 (+10)
8. **TikTok Content Posting API** → Publishing 35→60 (+25)
