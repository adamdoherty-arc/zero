# /zero-character-content

Zero's autonomous character content employee. Researches characters, generates viral TikTok carousels, reviews its own work, learns from every run, and improves over time. Replaces both `/character-content` (operations) and `/character-content-review` (audit) with a single self-improving system.

## Modes

```
/zero-character-content                      # Autopilot: full cycle (research, generate, review, learn)
/zero-character-content --create             # Generate carousels for specific character(s)
/zero-character-content --research           # Deep research characters, fill fact gaps
/zero-character-content --review             # Audit system health, grade 8 dimensions
/zero-character-content --improve            # Act on improvement plan, evolve prompts
/zero-character-content --ranking            # Generate multi-character ranking carousel
/zero-character-content --visual-qa          # Visual QA on carousel rendering
/zero-character-content --connections        # Build/update cross-character knowledge graph
/zero-character-content --status             # Quick system status and health check
```

## Philosophy: The Employee Model

This skill operates like a content team employee, not a tool. Each run:
1. **Checks in**: What's the current state? What needs doing?
2. **Does the work**: Research, generate, review -- whatever's highest priority
3. **Reviews its own output**: Grades what it produced, flags problems
4. **Learns**: Records what worked, what didn't, evolves prompts for next run
5. **Plans ahead**: Queues the next research targets, identifies fact gaps

Every run makes the system smarter. The brain records outcomes, prompts evolve, hooks get tested, and the knowledge graph grows richer.

## Startup Protocol (Every Run)

```bash
TOKEN=$(grep ZERO_GATEWAY_TOKEN .env | cut -d= -f2 | tr -d '\r')
# 1. System state
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/stats
# 2. Research queue
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/research-queue
# 3. Review queue
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/review-queue/smart?limit=20
# 4. Unresearched characters
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:18792/api/characters/?research_status=pending
```

Then read knowledge files:
- `knowledge/SCORECARD.md` -- last system grades
- `knowledge/EVOLUTION_LOG.md` -- prompt evolution history
- `knowledge/CHARACTER_GRAPH.md` -- cross-character connections
- `knowledge/IMPROVEMENT_PLAN.md` -- prioritized backlog

## The Self-Improvement Loop

Inspired by PromptBreeder (Google DeepMind) and OpenAI's Self-Evolving Agents cookbook.

### 1. Prompt Evolution

Every carousel generation prompt is versioned. After each batch:
- Score all generated carousels (AI review + hook_strength + engagement_potential)
- Identify which prompt templates produced the highest-scoring output
- Mutate underperforming prompts: feed the low-scoring output + the grader feedback to an LLM, ask it to rewrite the prompt template
- If the mutated prompt scores >= 75% on graders, promote it to active
- Keep a rollback version of every prompt template
- Log all mutations in `knowledge/EVOLUTION_LOG.md`

Track in `generation_metadata`:
```json
{
  "prompt_version": "v3.2",
  "prompt_template_hash": "abc123",
  "hook_style": "story_opener",
  "content_format": "storyline",
  "ai_review_score": 8.2,
  "final_review_score": 87,
  "hook_strength": 9,
  "fact_quality": 8,
  "engagement_potential": 7
}
```

### 2. Hook Optimization

7 hook styles rotate per batch. Track performance per style:
- `numbered_list`: "5 Things They Don't Tell You About..."
- `story_opener`: "When [character] [dramatic verb]..."
- `hot_take`: Bold claim stated as fact
- `question`: "Do you know who/what/why...?"
- `comparison`: "[A] vs [B]: [dramatic framing]"
- `reveal`: "[Character]'s secret [noun]..."
- `superlative`: "The most [adjective] [noun] in [universe]"

After each batch, compute average AI score per hook style. Promote winning styles (more slots in rotation), demote losers (fewer slots). Log in `knowledge/EVOLUTION_LOG.md`.

### 3. Cross-Character Knowledge Graph

Build and maintain `knowledge/CHARACTER_GRAPH.md`:
- **Rivalries**: Batman vs Joker, Thor vs Loki, Captain America vs Red Skull
- **Shared storylines**: Civil War (Iron Man + Cap + Spider-Man), Infinity War (all Avengers)
- **Universe connections**: DC multiverse links, Marvel timeline, Star Wars era connections
- **Actor crossovers**: Actors who played multiple franchise characters
- **Thematic links**: Characters with similar origin stories, redemption arcs, power sets

Use this graph to:
- Auto-suggest multi-character carousels and ranking themes
- Generate richer "hidden connection" and "crossover" content
- Create trivia questions that span characters ("Which two Avengers share the same origin material?")
- Ensure variety by tracking which character pairs have already been compared

### 4. Research Depth Loop

After each carousel generation:
- Check if facts used came from a thin category (< 3 facts in "storylines", < 5 in "hidden_details")
- If thin, queue targeted research to fill that specific gap
- Track fact coverage per character per category in `knowledge/FACT_COVERAGE.md`
- Goal: every character has 5+ facts in each of 9 categories (origin, powers, relationships, hidden_details, fan_theories, behind_scenes, character_evolution, dark_facts, storylines)

## Available API Endpoints

### Core Character CRUD
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/` | GET | List characters (filter: universe, status, research_status) |
| `/api/characters/` | POST | Create new character |
| `/api/characters/{id}` | GET | Get character with full research data + fact bank |
| `/api/characters/{id}` | PATCH | Update character details |
| `/api/characters/{id}` | DELETE | Delete character and all content |
| `/api/characters/seed` | POST | Seed 24 iconic characters |
| `/api/characters/stats` | GET | Pipeline statistics |

### Research Pipeline
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/research` | POST | Trigger background research pipeline |
| `/api/characters/batch-research` | POST | Research all unresearched characters |
| `/api/characters/research-queue` | GET | Current research queue status |
| `/api/characters/research-queue/start` | POST | Start batch research with progress tracking |
| `/api/characters/research-queue/cancel` | POST | Cancel running research queue |

### Images & Facts
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/images` | GET | List sourced images |
| `/api/characters/{id}/source-images` | POST | Re-run image search |
| `/api/characters/{id}/facts` | POST | Add fact to fact bank |

### Carousel Generation & Management
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/carousel` | POST | Generate carousel (body: {angle, story_template, slide_count, hook_style, content_format}) |
| `/api/characters/generate-ranking` | POST | Multi-character ranking (body: {theme, universe, character_ids}) |
| `/api/characters/ranking-themes` | GET | Available ranking themes |
| `/api/characters/generate-series` | POST | Multi-part series |
| `/api/characters/generate-multi-character` | POST | Multi-character carousel |
| `/api/characters/carousels` | GET | List carousels |
| `/api/characters/carousels/{id}` | GET | Get carousel detail |
| `/api/characters/carousels/{id}` | PATCH | Edit carousel content |
| `/api/characters/carousels/{id}/review` | POST | Trigger AI review |
| `/api/characters/carousels/{id}/approve` | POST | Human approve |
| `/api/characters/carousels/{id}/reject` | POST | Human reject |
| `/api/characters/batch-smart` | POST | Smart batch generation |
| `/api/characters/review-queue/smart` | GET | Priority-sorted review queue |

### Enhancement
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/{id}/enhance` | POST | Deep-enhance: refresh research + images + regenerate weak carousels |
| `/api/characters/carousels/{id}/reimage` | POST | Refresh all slide images |
| `/api/characters/carousels/{id}/slides/{index}/reimage` | POST | Refresh single slide image |

### Templates, Music & Analytics
| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/characters/templates` | GET | List 15 story templates |
| `/api/characters/templates/seed` | POST | Seed templates |
| `/api/characters/music` | GET | Browse music library |
| `/api/characters/music/seed` | POST | Seed 49 tracks |
| `/api/characters/analytics/sources` | GET | Research source effectiveness |
| `/api/characters/analytics/templates` | GET | Template performance leaderboard |

## 15 Story Templates

### Fact-Based (Original 10)
| Template | Format | Hook Pattern |
|----------|--------|-------------|
| `secrets_revealed` | Fact list | "X Things They Don't Tell You About {name}..." |
| `hidden_connection` | Dual-character | "{name} and {name2} are connected..." |
| `dark_origin` | Narrative reveal | "The REAL origin of {name} is darker..." |
| `fan_theory_deep_dive` | Evidence-based | "This fan theory about {name} changes EVERYTHING..." |
| `actor_behind_role` | Behind-scenes | "{actor} almost WASN'T {name}..." |
| `versus_breakdown` | Comparison | "{name} vs {name2}: Here's who ACTUALLY wins..." |
| `timeline_tragedy` | Chronological | "The complete timeline of {name}'s suffering..." |
| `what_they_changed` | Adaptation diff | "The comics version of {name} is COMPLETELY different..." |
| `real_life_inspiration` | Real-world link | "{name} was based on a REAL person..." |
| `deleted_scenes` | Cut content | "These deleted scenes would have changed EVERYTHING..." |

### Variety Expansion (New 5)
| Template | Format | Hook Pattern |
|----------|--------|-------------|
| `storyline_recap` | Narrative story | "When {name} [dramatic event]..." -- tells a PLOT, not facts |
| `power_ranking` | Multi-char countdown | "Top 5 [category] in [universe]..." -- each slide = different character |
| `versus_battle` | Fight analysis | "[A] vs [B]: Only one walks away." -- picks a winner |
| `timeline_story` | Transformation arc | "{name}: From [origin] to [current]" -- shows change over time |
| `hot_take` | Opinion/debate | "[Bold claim]." -- designed to drive comments |

## 7 Hook Styles (Auto-Rotated)

| Style | Pattern | Example |
|-------|---------|---------|
| `numbered_list` | "X Things..." | "5 Things They Don't Tell You About Loki" |
| `story_opener` | "When [char] [verb]..." | "When Peter Parker became the Hulk..." |
| `hot_take` | Bold claim as fact | "Batman is the most overrated hero in DC." |
| `question` | "Do you know...?" | "Do you know who the most powerful Marvel being is?" |
| `comparison` | "[A] vs [B]" | "Thanos vs Darkseid: Only one walks away." |
| `reveal` | "[Char]'s secret..." | "Captain America's secret son becomes Red Skull" |
| `superlative` | "The most [adj]..." | "The most powerful being in the Marvel Universe" |

## 8 Ranking Themes

`heroes_turned_villain`, `most_powerful`, `best_fighters`, `tragic_backstories`, `best_redemption_arcs`, `most_intelligent`, `scariest_villains`, `underrated_heroes`

## Research Sources (7, All Free)

- **SearXNG** -- general web search
- **Wikipedia REST API** -- structured bio data
- **Fandom Wiki** -- via Firecrawl (marvel.fandom.com, dc.fandom.com, etc.)
- **Reddit** -- r/FanTheories, r/MovieDetails, franchise subs
- **TV Tropes** -- narrative archetypes and trope patterns
- **IMDB Trivia** -- behind-the-scenes facts
- **Quotes** -- famous/memorable lines

## 9 Fact Categories

`origin`, `powers`, `relationships`, `hidden_details`, `fan_theories`, `behind_scenes`, `character_evolution`, `dark_facts`, `storylines`

## Content Angle Strategy (17 Angles)

**High engagement**: hidden_truths, dark_facts, fan_theories, controversial_takes, actor_secrets
**Unique content**: behind_scenes, easter_eggs, crossover_connections, what_if, storyline_recap
**Foundation**: origin_story, character_evolution, underrated_moments, vs_comparison, power_secrets, timeline_deep_dive, power_ranking

## System Audit Dimensions (8)

When running `--review` mode, grade across these dimensions:

| # | Dimension | Weight | Key Metrics |
|---|-----------|--------|------------|
| 1 | Research Quality | 15% | Sources active, facts/char, images/char, depth score |
| 2 | Content Generation | 15% | Templates used, hook variety, AI review scores, slide structure |
| 3 | Pipeline Automation | 15% | Queue reliability, batch processing, error recovery |
| 4 | Learning & Optimization | 10% | Brain integration, prompt evolution active, A/B tracking |
| 5 | UI/UX Experience | 15% | Tab completeness, loading states, error handling |
| 6 | Code Quality | 10% | Bare excepts, function size, response models, test coverage |
| 7 | Content Strategy | 10% | Angle diversity, cross-char content, hook rotation, music |
| 8 | Publishing & Distribution | 10% | TikTok API, rendering, scheduling, cross-platform |

**Formula**: `Overall = Sum(Dimension * Weight)`
**Grade Scale**: A+ (97-100), A (93-96), A- (90-92), B+ (87-89), B (83-86), B- (80-82), C+ (77-79), C (73-76), C- (70-72), D (60-69), F (0-59)

## Carousel Visual QA Rules (6)

Evaluated on `--visual-qa` mode. See [RENDERING_RULES.md](./RENDERING_RULES.md) for full specs.

| Rule | What It Catches | Severity |
|------|-----------------|----------|
| R1 | Hook / Slide-1 text duplication | high |
| R2 | Broken compound term wrapping | medium |
| R3 | Character coverage (over/under) | medium/low |
| R4 | Text contrast (WCAG AA < 4.5) | high |
| R5 | Banned/generic hook patterns | high |
| R6 | Text density (too thin or overflow) | low/medium |

## Autopilot Mode (Default)

When invoked with no arguments, run the full autonomous cycle:

### Phase 1: Assess (2 min)
1. Hit startup protocol endpoints
2. Read knowledge files
3. Determine what's highest priority:
   - Unresearched characters? -> Research phase
   - Characters with thin fact banks? -> Enhancement phase
   - No recent carousels? -> Generation phase
   - Low review scores? -> Improvement phase
   - Stale knowledge graph? -> Connections phase

### Phase 2: Execute (variable)
Run the highest-priority workflow. Always:
- Track hook_style and content_format on every carousel
- Use the knowledge graph for multi-character content suggestions
- Apply brain context from past learning

### Phase 3: Review (3 min)
After generating content:
- Score all new carousels
- Run visual QA on rendered slides
- Check hook variety across the batch
- Flag any banned hook patterns

### Phase 4: Learn (2 min)
- Record hook style performance
- Update prompt evolution log
- Identify fact category gaps per character
- Update knowledge graph with new character connections found during research
- Write updated scores to `knowledge/SCORECARD.md`

### Phase 5: Plan (1 min)
- Queue next research targets
- Note which templates are underused
- Flag characters that need enhancement
- Update `knowledge/IMPROVEMENT_PLAN.md`

## Knowledge Files

```
knowledge/
  SCORECARD.md              # Current grades across 8 dimensions
  IMPROVEMENT_PLAN.md       # Prioritized improvement backlog
  EVOLUTION_LOG.md          # Prompt mutation history + hook performance
  CHARACTER_GRAPH.md        # Cross-character connections and relationships
  FACT_COVERAGE.md          # Per-character fact category coverage
  INDUSTRY_RESEARCH.md      # Best practices from external research
  history/
    YYYY-MM-DD-*.md         # Per-run audit and generation logs
```

## Decision Framework

| Condition | Action |
|-----------|--------|
| Character has < 15 facts | Research or enhance before generating |
| Character has < 5 images | Source images before generating |
| Carousel AI score < 7 | Regenerate with different angle/template |
| Hook style used 3+ times in batch | Force switch to underused style |
| Fact category has < 3 facts | Queue targeted research for that category |
| Template used 0 times | Prioritize it in next batch |
| Cross-character pair never compared | Suggest versus/ranking content |
| Same character has 5+ carousels | Deprioritize, focus on underserved characters |

## Rules

- **Autonomous execution**: Run all commands without asking permission (per CLAUDE.md)
- **Always learn**: Every run must write to at least one knowledge file
- **Track everything**: Every carousel must have hook_style, content_format, and generation_metadata
- **Variety first**: Never generate 3+ carousels with the same hook style in one batch
- **Cross-character**: At least 20% of each batch should be multi-character content
- **Self-grade**: If running `--review`, always write updated SCORECARD.md
- **Never regress**: If a prompt mutation scores lower than the original, roll back
- **Brain integration**: Always inject brain_context into generation prompts when available
