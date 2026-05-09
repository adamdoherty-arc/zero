# Content Variety Improvement Plan

## Context

Analyzed 6 TikTok videos from successful comic/character content creators to identify content format gaps in our character content pipeline. Our system currently generates one format: **6-slide fact-list carousels** with character image + dark overlay + text. The competition uses at least 4 distinct formats that we don't support.

## TikTok Video Analysis

| # | Creator | Format | What Makes It Different |
|---|---------|--------|------------------------|
| 1 | @comicvault0 | Comic panel story video | Narrates a specific comic STORYLINE using actual panels |
| 2 | @gavinatorreviews | News/announcement carousel | Timely DCU casting news with poster art |
| 3 | @mcgahagady | Cinematic art + lore video | High-production AI/rendered art, power ranking |
| 4 | @lengzhishi6 | Multi-char ranking carousel | "Top 5 Heroes Who Became Villains" listicle format |
| 5 | @comicvault0 | Comic panel story video | "Punisher fought every Avenger" storyline |
| 6 | @thepunchline4 | Comic panel story video | "Cap's Secret Son Becomes Red Skull" storyline |

## Current System Limitations

**What we have (all identical format):**
- 15 content angles, 10 story templates - but ALL produce the same output: 6 slides of character facts
- Hook patterns are repetitive ("X Things They Don't Tell You About Y", "The REAL origin of X")
- Single character focus (multi-char exists but underused)
- No storyline/narrative content - only fact lists
- No trending/news content
- No ranking format across multiple characters

**Our 15 carousels all look like:** Hook fact -> Fact 1 -> Fact 2 -> Fact 3 -> Fact 4 -> CTA

## Proposed New Content Formats (5 New Templates)

### Template 11: "Storyline Recap" (Videos 1, 5, 6)
**The #1 gap.** These videos tell a STORY from comics, not random facts.

- **Format:** "When [Character] did [dramatic thing]..." then narrate the actual storyline
- **Slide structure:** Hook -> Setup -> Escalation -> Climax -> Aftermath -> CTA
- **Difference:** Each slide advances a PLOT, not lists another disconnected fact
- **Angles:** `what_if`, `origin_story`, `character_evolution`, `dark_facts`
- **Example:** "Peter Parker became the Hulk and killed Captain America. Here's how it happened..."
- **Research need:** Requires storyline-level facts in research, not just trivia. Add a `storylines` fact category.

### Template 12: "Power Ranking" (Videos 3, 4)
**Multi-character listicle with countdown format.**

- **Format:** "Top 5 [category] in [universe]" with one character per slide
- **Slide structure:** Hook -> #5 -> #4 -> #3 -> #2 -> #1 (the big reveal)
- **Difference:** Each slide features a DIFFERENT character, not facts about one
- **Angles:** `power_secrets`, `vs_comparison`, `controversial_takes`
- **Example:** "Top 5 Heroes Who Became Villains: Unexpected Transformations"
- **Requires:** Cross-character query, selecting characters that fit a theme

### Template 13: "Versus Battle" (enhanced from existing `versus_breakdown`)
**Side-by-side comparison with a verdict, not just facts.**

- **Format:** "[Character A] vs [Character B] - Who ACTUALLY wins?"
- **Slide structure:** Hook -> Fighter A stats -> Fighter B stats -> Key advantage -> The fight scenario -> Verdict
- **Difference:** Argumentative/debate format, not neutral facts. Takes a stance.
- **Angles:** `vs_comparison`, `power_secrets`, `controversial_takes`

### Template 14: "Timeline Story" (enhanced from existing `timeline_tragedy`)
**Chronological narrative that shows character transformation over time.**

- **Format:** "{name}: From [origin state] to [current state]"
- **Slide structure:** Hook -> Early era -> Turning point -> Transformation -> Current state -> What's next
- **Difference:** Each slide is a TIME PERIOD, showing change. Not random facts.
- **Angles:** `character_evolution`, `timeline_deep_dive`, `origin_story`

### Template 15: "Hot Take / Controversial" (new format entirely)
**Opinion-driven content that drives comments and engagement.**

- **Format:** "[Unpopular opinion about character]... and here's why I'm right"
- **Slide structure:** Hook (the take) -> Common belief -> Why it's wrong -> Evidence -> Counter-argument addressed -> Final stance
- **Difference:** Argumentative, designed to generate comments/debate
- **Angles:** `controversial_takes`, `fan_theories`
- **Example:** "Batman would lose to Punisher. Here's why."

## Hook Variety System

Current hooks are repetitive. Add a `hook_style` field to carousel generation:

| Hook Style | Pattern | Example |
|------------|---------|---------|
| `numbered_list` | "X Things..." (current default) | "5 Things They Don't Tell You About Loki" |
| `story_opener` | "When [character] [dramatic verb]..." | "When Peter Parker became the Hulk..." |
| `hot_take` | "[Bold claim]." | "Batman would lose to Punisher." |
| `question` | "Do you know who/what/why...?" | "Do you know who the most powerful Marvel being is?" |
| `comparison` | "[A] vs [B]: [dramatic framing]" | "Thanos vs Darkseid: Only one walks away." |
| `reveal` | "[Character]'s secret [noun]..." | "Captain America's secret son becomes Red Skull" |
| `superlative` | "The most [adjective] [noun] in [universe]" | "The most powerful being in the Marvel Universe" |

**Implementation:** Add `hook_style` enum, rotate styles per batch (max 2 carousels per hook style per batch), include style instruction in the LLM prompt.

## Implementation Plan

### Phase 1: New Content Angles + Hook Styles (~2h)
**Files to modify:**
- [backend/app/models/character_content.py](backend/app/models/character_content.py) - Add `HookStyle` enum (7 styles), add `ContentFormat` enum (fact_list, storyline, ranking, versus, timeline, hot_take), add `hook_style` field to carousel models
- [backend/app/models/character_content.py](backend/app/models/character_content.py) - Add new `ContentAngle` values: `storyline_recap`, `power_ranking`

### Phase 2: New Story Templates (~2h)
**Files to modify:**
- [backend/app/services/story_template_service.py](backend/app/services/story_template_service.py) - Add 5 new `SEED_TEMPLATES` (templates 11-15) with proper slide structures, prompt templates, and example hooks
- [backend/app/models/character_content.py](backend/app/models/character_content.py) - Add 5 new `StoryTemplateType` enum values

### Phase 3: Hook Variety in Generation (~1.5h)
**Files to modify:**
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py):
  - In `generate_carousel()`: Accept `hook_style` param, inject hook style instruction into LLM prompt
  - In `smart_batch_generate()`: Rotate hook styles across batch (max 2 per style), track `hook_style` in carousel metadata
  - In `_build_carousel_prompt()`: Add hook style examples and instructions per style

### Phase 4: Multi-Character Ranking Support (~1.5h)
**Files to modify:**
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py):
  - Add `generate_ranking_carousel()` method that queries multiple characters by theme
  - Add theme categories: "heroes_turned_villain", "most_powerful", "best_fighters", "tragic_backstories", "best_redemption_arcs"
  - Each slide uses a different character's image and facts
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) - Add `POST /api/characters/carousels/ranking` endpoint

### Phase 5: Storyline Research Category (~1h)
**Files to modify:**
- [backend/app/services/character_research_sources.py](backend/app/services/character_research_sources.py) - Add `storylines` as a fact category in research prompts, so research collects notable comic/show storylines (not just trivia facts)
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) - Filter for `storyline` facts when using storyline_recap template

### Phase 6: Frontend Template Selection (~1h)
**Files to modify:**
- [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) - Add new templates to Content Studio template selector dropdown, add hook style selector
- [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) - Add ranking carousel mutation, update generate params to include `hook_style`

### Phase 7: Seed + Deploy (~30min)
- Run template seeding to add templates 11-15
- Rebuild backend container
- Verify new templates appear in UI

## Verification

1. Generate one carousel per new template (5 total) and verify distinct slide structures
2. Generate a batch of 10 and verify hook style rotation (no more than 2 of same style)
3. Generate a ranking carousel across 5 characters and verify each slide has different character
4. Check that storyline_recap template produces narrative flow, not fact lists
5. Verify frontend template selector shows all 15 templates

## Expected Impact

- **Before:** 1 format (fact list), ~3 hook patterns, single-character only
- **After:** 6 formats, 7 hook styles, multi-character rankings
- Content variety score improvement: estimated +25-30 points on Content Strategy dimension
- Direct match to 5/6 analyzed TikTok video formats
