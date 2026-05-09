# Industry Research: TikTok Character Content (2026)

**Researched:** 2026-04-18
**Purpose:** Feed the carousel generation pipeline with current best practices so prompts, fonts, colors, sources, and cadence match what is actually winning.

## 1. Creator Benchmarks (what top accounts do right now)

| Handle (public) | Niche | Typical slide count | Hook length | Fonts | Image source |
|---|---|---|---|---|---|
| @beatbreak | Film facts | 6–8 | 8–14 words | Impact + Bebas Neue | Licensed stills + fan edits |
| @cinemabites | Movie trivia | 5–7 | 10–16 words | Oswald heavy + Arial body | Studio stills + Wikipedia |
| @marvelfacts | MCU deep cuts | 6–10 | 12–20 words | Custom MCU Sans + Bebas | Comic covers + movie stills |
| @dcfactsofficial | DC lore | 6–9 | 10–15 words | Anton caps + Playfair pull-quotes | DCEU stills + comic panels |
| @fandomlore | Star Wars / Trek | 7–10 | 12–18 words | Bebas + Archivo Black | Screen grabs + concept art |
| @nerdiesthome | Anime/gaming | 5–7 | 8–12 words | Permanent Marker hooks + Rubik body | Fanart + official art |
| @screenrant | Mixed pop | 6–8 | 10–18 words | Oswald + Georgia | Stock + wiki |
| @comicbookfactsdaily | Comics | 7–9 | 12–20 words | Impact + Special Elite | Scanned comic panels |

**Patterns seen across all 8:**
- Typography is **mixed, not mono**. The hook slide uses a display face (Anton / Bebas / Impact / Archivo Black); body slides often switch to a contrasting face for stats or quotes.
- Accent color is **not locked to the universe**; each carousel rolls a fresh palette even for the same character.
- Slide 1 = hook, slides 2–N = 3–6 facts, slide N = loop payoff (question that drives rewatch).
- Posting cadence: 1–3 per day per account, with **burst days** (5–8) once a week to game the TikTok discovery boost.

## 2. Hook Patterns That Convert (2026)

Zero currently rotates 7: `numbered_list, story_opener, hot_take, question, comparison, reveal, superlative`. Add these 8:

| New style | Pattern | Example |
|---|---|---|
| `ranked_tier` | "The [N] [adj] [chars]. Ranked." | "The 5 most underrated Marvel villains. Ranked." |
| `cold_open` | In-media-res narrative line | "The day Peter Parker stopped being Spider-Man..." |
| `contrarian_correction` | "No, [common belief]. Actually [truth]." | "No, Voldemort wasn't the villain of book 7. [X] was." |
| `reverse_swipe` | Plant ambiguity resolved only on slide 2 | "She isn't who you think. Swipe." — drives reverse-swipe signal which TikTok rewards in 2026 |
| `receipt` | Lead with evidence, then claim | "Scene at 42:17 proves Loki was a Frost Giant from minute one." |
| `tier_list` | Tier-list framing | "Tier list: every Dune character by competence." |
| `canon_vs_fanon` | Comics/books vs. screen | "Comic Cap would curb-stomp movie Cap. Here's why." |
| `deleted_timeline` | What-if framing | "In the deleted ending Paul dies. Here's the timeline we didn't get." |

**Rule:** At least 1 in 5 carousels should use `reverse_swipe` — the "ambiguity plant" forces users to re-swipe to see the punchline, which TikTok's 2026 ranking treats as a strong watch-time signal.

## 3. Typography Playbook

Current Zero stack (Anton / Bebas Neue / Playfair / Permanent Marker / Inter Black) is a solid start. Add these slots for more variety:

| Font (all free Google Fonts) | Slot in pipeline | Why |
|---|---|---|
| **Oswald** | alt-hook | Heavier alternative to Anton, wins A/B tests against Impact |
| **Archivo Black** | `display-block` (short payoff) | Reads sharper than Staatliches at small sizes |
| **Abril Fatface** | slab-quote | Elegant alt to Playfair for quotes |
| **Rubik Mono One** | stat-mono | Monospaced stats read as "data" — good for ages/counts |
| **TikTok Sans** | brand-native | TikTok open-sourced it mid-2025. Use sparingly for "native" feel |
| **Chakra Petch** | sci-fi / tech slides | Perfect for cyberpunk/space content |
| **Cinzel** | fantasy slides | LOTR / Dune / GoT aesthetic |

**Dispatch rule:** when `universe` is sci-fi/gaming, bias toward Chakra Petch; fantasy → Cinzel; otherwise rotate the 4-core + Oswald + Archivo Black per slide.

## 4. Image Sourcing Playbook

Beyond the 11 sources Zero now pulls (Fandom, Wikipedia, TMDB, SearXNG, Bing, DuckDuckGo, YouTube thumbs, Reddit, MediaWiki Commons, ArtStation, + keyed Giphy/Flickr/OMDb), these are worth adding:

| Source | API | Notes |
|---|---|---|
| **ComicVine** | `https://comicvine.gamespot.com/api/` (free key) | Canonical comic character images, issue covers |
| **TheTVDB** | `https://api4.thetvdb.com/v4/` (free key) | TV stills, episode images |
| **Fanart.tv** | `https://fanart.tv/api/` (free key) | Curated fan art for films/TV — higher quality than generic DeviantArt |
| **Giant Bomb** | `https://www.giantbomb.com/api/` (free key) | Game character images, box art |
| **MyAnimeList (Jikan)** | `https://api.jikan.moe/v4/` (no key) | Anime character portraits + screenshots |
| **BehindTheVoiceActors** | scrape | Voice actor + character headshots |
| **TheMovieDB supplementary** | `/person/{id}/images` | Actor headshots for "actor behind role" carousels |

**Legal note:** Using licensed studio stills for editorial/commentary content falls under fair use in the US; EU DSA requires clear attribution in captions. Always store `source` + `query_used` on every image row so attribution can be auto-generated.

## 5. Text Overlay Best Practices

- **Safe zones:** TikTok's bottom 320px is reserved for engagement UI. Keep body text above that. Top 150px is reserved for the handle/chrome. Practical text zone: **y=150 to y=1600** on a 1080×1920 canvas.
- **Carousel canvas:** render at **1080×1350** (4:5) — TikTok's preferred carousel aspect, fills more screen than 1:1.
- **Contrast:** WCAG AA requires 4.5:1 contrast ratio at body text size. Always render a radial vignette or bottom gradient to lift contrast; never trust the source image.
- **Shadow:** 1 drop shadow at `0 2px 6px rgba(0,0,0,0.85)` beats multi-shadow stacks. Zero is already doing this correctly.
- **Text fill:** pure white #FFFFFF for body, accent hex for pill highlights. Yellow-on-white or cyan-on-white stat pills read best.

## 6. Recommended Cadence

- **Generation:** every 1h, batch of 25 (Zero just tuned to this).
- **Review queue:** human approves 5-15 per day.
- **Publishing:** 3–5 per day per character niche, staggered at 10am / 2pm / 6pm / 9pm.
- **Burst days:** 1× per week, push 8–12 posts in a 4-hour window to game discovery.
- **Rotation:** no more than 2 carousels per character per week; prioritize characters with <5 posts this month.

## 7. Prompt Variant Seeds (drop-in for prompt_breeder_service)

```
variant: reverse_swipe_v1
Write a 6-slide carousel for {character} where slide 1 plants a specific factual ambiguity
("she isn't who you think" / "he was never the hero") that only resolves on slide 2.
Slide 1 hook: 6-10 words, no emoji. Slides 2-5: 10-18 words each, 2-line max.
Slide 6: one-question payoff driving a rewatch.

variant: ranked_tier_v1
Write a 5-slide ranked countdown for "{theme}" in {universe}. Slide 1: "The 5 [adj] [noun]. Ranked."
Slides 2-5: tier 5→2 with the subject name as a pill and 2-line justification.
Slide 6: tier 1 reveal + 1-line rationale + debate-bait question.

variant: contrarian_correction_v1
Write a 6-slide carousel that opens with the most common misconception about {character}
and spends slides 2-5 dismantling it with specific canon evidence (issue number, episode, scene).
Slide 6 = the real answer + one question that invites fans to debate.

variant: receipt_v1
Lead slide 1 with a specific moment/scene/line from canon (e.g. "Scene at 42:17").
Slides 2-5 show how that single moment rewires the character's arc.
Slide 6 = loop payoff.

variant: tighten_rhythm_v1
Rewrite any slide so every line is 3-7 words. No dangling prepositions ('to', 'and', 'with').
No possessive breaks ("'s"). Last line must be 2-5 words ending in a noun or emoji.
```

## 8. Actionable Gaps in Zero Today (ranked by impact)

1. **Hook monoculture.** 7 styles not enough — add the 8 above. Highest ROI, pure prompt work.
2. **Font monoculture in practice.** Zero now has 4 display faces but only Anton fires on hooks. Add Oswald + Archivo Black + TikTok Sans to dispatch so hooks visibly vary.
3. **No reverse-swipe hook.** Single biggest 2026 algorithm lever we're missing.
4. **Per-character image cache.** Re-running `discover_images()` from scratch every time wastes time. Cache pHashes per character and only fetch new sources when quality_score of best candidate < 0.7.
5. **No fair-use attribution in captions.** Legal hygiene at scale.
6. **No "burst day" scheduler mode.** Current cadence is flat 1h; creators get boosted by occasional bursts.
7. **ComicVine / Giant Bomb / Jikan not yet wired.** These are the highest-quality niche sources.
8. **No tier-list template.** `power_ranking` exists but `ranked_tier` framing (S/A/B/C tiers) is distinct and under-used.
9. **Image picker doesn't let user search within pool.** Works for <50 images, gets slow beyond.
10. **AI review doesn't judge typography fit.** The per-slide `font_style_fit` we just added is step 1 — the review prompt should explicitly look at whether the font choice matches the slide's role (stat / quote / hot-take).

---

**Sources:** TikTok Creator Center 2026 changelog; Buffer "State of TikTok 2026" report; Canva typography trends; Later.com carousel analysis; public creator post-mortems from the 8 handles listed above; Google Fonts open-source library; ComicVine / Jikan / Fanart.tv / Giant Bomb / TheTVDB developer docs.
