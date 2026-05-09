# Character Content Pipeline: Expansion, Enhancement, and Final Review

## Context

The Zero character content system currently supports 24 seeded Marvel/DC/TV/Film characters with a solid 7-source research pipeline, 10 story templates, and a single-stage Ollama AI review. During usage, four gaps surfaced:

1. **No per-carousel image refresh**: Once a carousel is generated, there is no way to swap images. Users must regenerate the entire carousel to fix one bad image.
2. **No per-character enhance**: Characters that end up with thin fact banks or weak carousels have no one-click "improve me" action.
3. **Single-stage review only**: The Ollama review (qwen3-coder-next) is fast and free but lacks the viral-instinct quality of a frontier model. Legion has production-hardened Minimax M2.7 integration with Kimi fallback, sophisticated circuit breakers, and budget controls that we can port.
4. **Narrow genre coverage**: Only 24 characters, heavily Marvel/DC biased. The `CharacterUniverse` enum supports 10 universes but most are empty. TikTok audiences span anime, gaming, prestige TV, and fantasy.

Additionally, the user asked about the difference between two skill files at `c:\code\zero\.claude\skills\character-content\SKILL.md` (operational) and `c:\code\zero\.claude\skills\character-content-review\SKILL.md` (strategic audit). This distinction needs to be documented inside both skills so the difference is obvious to future sessions.

Intended outcome: a richer character roster, a two-stage quality gate with Minimax as final polish, flexible per-carousel and per-slide image refresh, and a one-click character enhance that also regenerates weak carousels using improved facts.

---

## Skill Distinction (Documentation Clarification)

| Skill | Purpose | Scope | When to Use |
|-------|---------|-------|-------------|
| `/character-content` | Day-to-day operational content creation | Tactical | "Generate carousels", "add character", "fix thin fact bank", "review queue" |
| `/character-content-review` | Audit, grade, plan improvements | Strategic | Quarterly audit, "how good is the system?", "what should we improve?" |

Both skill README headers will get a one-paragraph cross-reference so the difference is obvious.

---

## Phase 1: Minimax Provider (Port from Legion)

### Files to Create
- `backend/app/infrastructure/llm_providers/minimax_provider.py` - new provider

### Files to Modify
- `backend/app/infrastructure/llm_providers/__init__.py` - register provider
- `backend/app/infrastructure/config.py` - add `minimax_api_key`, `minimax_base_url`, `minimax_daily_budget_usd`
- `backend/app/models/llm.py` - add `CHARACTER_CONTENT_REVIEW` task type, pre-populate `task_assignments`
- `.env.example` - add `ZERO_MINIMAX_API_KEY` comment

### Key Implementation Details
- **Reference implementation**: `c:\code\legion\backend\app\services\llm_clients\minimax_client.py` (production-ready, no Legion deps)
- **Model ID**: `MiniMax-M2.7`
- **Base URL**: `https://api.minimax.io/v1`
- **Auth**: `Bearer ${MINIMAX_API_KEY}` header
- **Pricing**: $0.30/1M input, $1.20/1M output (cheaper than Kimi-K2.5)
- **Context**: 200K tokens
- **Interface contract** (from `backend/app/infrastructure/llm_providers/base.py`):
  - `async def chat(messages, model, temperature, max_tokens, **kwargs) -> str`
  - `async def chat_stream(...) -> AsyncIterator[str]`
  - `async def is_healthy() -> bool`
  - `def estimate_cost(prompt_tokens, completion_tokens, model) -> float`
  - `@property name -> str` (returns `"minimax"`)
  - `@property is_configured -> bool`
- **Reuse existing pattern** from `kimi_provider.py:32-80` - httpx client, circuit breaker via `get_circuit_breaker("llm_minimax", failure_threshold=5, recovery_timeout=120.0)`
- **JSON mode**: Minimax supports `response_format: {"type": "json_schema", "json_schema": {...}}` - see Legion `minimax_client.py:139-148`
- **Skip Legion extras** (for now): sliding-window rate limiter, balance breaker, daily budget latch. Zero's existing budget system in `llm_router.py` handles cost control.

### Routing Table Update
Add to `LlmRouterConfig.task_assignments` in `backend/app/models/llm.py`:
```python
"character_content_review_final": ModelAssignment(
    model="minimax/MiniMax-M2.7",
    fallbacks=["kimi/kimi-k2.5"],
    temperature=0.3,
    num_predict=2048,
),
```

---

## Phase 2: Two-Stage Review Pipeline

### Files to Modify
- `backend/app/services/character_content_service.py` - extend `ai_review_carousel()` around line 1372
- `backend/app/routers/character_content.py` - add optional query param `final=true` to `/review` endpoint

### Logic Change
Current flow in `character_content_service.py:1372-1461`:
```
Load carousel -> Ollama review -> Parse scores -> If < 7 rewrite, else pending_review
```

New flow (two-stage):
```
Load carousel -> Stage 1: Ollama review (cheap) -> Parse scores
  If overall_score < 7: rewrite with Ollama, status=pending_review (same as today)
  If overall_score >= 7: Stage 2: Minimax final review via unified_llm_client.chat(task_type="character_content_review_final")
    - Validates viral potential, tightens hook/caption
    - Stores `final_review` field on carousel with Minimax scores + suggestions
    - Sets status=ai_reviewed or pending_review
    - On Minimax failure (circuit breaker open / budget exceeded): auto-fallback to Kimi via router
```

### New Fields on CharacterCarouselModel
- `final_review: JSONB` (nullable) - Minimax output: `{scores, verdict, polish_suggestions, final_hook, final_caption}`
- `final_review_score: float` (nullable)
- `final_review_model: str` (nullable) - tracks which provider actually ran (minimax vs kimi fallback)

Add via new migration `022_character_final_review.py`.

### Stage-2 Prompt Location
New constant `FINAL_REVIEW_PROMPT` in `character_content_service.py` around line 160 (near existing `AI_REVIEW_SYSTEM_PROMPT`). Prompt focuses on viral-instinct polish: hook tension, caption CTA, fact sequencing, emotional arc.

---

## Phase 3: Per-Carousel and Per-Slide Image Refresh

User requested all three refresh modes.

### New Endpoints (in `backend/app/routers/character_content.py`)

| Endpoint | Method | Behavior |
|----------|--------|----------|
| `/api/characters/carousels/{id}/reimage` | POST | Refresh ALL slide images using existing character pool + fresh matching |
| `/api/characters/carousels/{id}/slides/{slide_index}/reimage` | POST | Refresh a SINGLE slide's image (with optional `query` body override) |
| `/api/characters/carousels/{id}/reimage-with-fresh-sources` | POST | Run `_source_images()` first to expand pool, THEN re-match all slides |

### New Service Methods (in `backend/app/services/character_content_service.py`)
- `reimage_carousel(carousel_id: str) -> CharacterCarousel` - re-runs 3-tier image matching at lines 1272-1370
- `reimage_slide(carousel_id: str, slide_index: int, query_override: Optional[str] = None) -> CharacterCarousel` - matches one slide
- `reimage_carousel_with_fresh_sources(carousel_id: str) -> CharacterCarousel` - calls `_source_images()` then `reimage_carousel()`

### Reuse
- 3-tier matching logic already exists at `character_content_service.py:1272-1370`. Extract into a helper `_match_image_for_slide(slide, character, image_pool)` that all three methods call.
- SearXNG search already implemented in `_source_images()` at line 910.

### Frontend
- Add hooks in `frontend/src/hooks/useCharacterContentApi.ts`:
  - `useReimageCarousel()`, `useReimageSlide()`, `useReimageWithFreshSources()`
- `frontend/src/pages/CharacterDetailPage.tsx` additions:
  - Carousel card "Refresh Images" button (calls reimage-all)
  - Carousel card "Get New Images First" button (calls fresh-sources variant)
  - Per-slide hover -> "Swap image" button (calls slide-level endpoint, opens tiny modal to enter custom query)

---

## Phase 4: Per-Character Enhance (with Weak Carousel Regeneration)

User picked "Enhance EVERYTHING" scope.

### New Endpoint
`POST /api/characters/{character_id}/enhance` in `backend/app/routers/character_content.py`

Body:
```json
{
  "refresh_research": true,
  "add_images": 8,
  "regenerate_weak_carousels": true,
  "weak_threshold": 7.0
}
```

### New Service Method
`character_content_service.enhance_character(character_id, opts) -> EnhanceResult`

Pipeline:
1. **Research refresh**: call `_research_pipeline()` at line 406 with deeper queries. Merge new facts into `fact_bank` (dedupe by text similarity).
2. **Image top-up**: call `_source_images()` at line 910 with higher result limits, preserving approved images.
3. **Fact re-extraction**: re-run `_extract_facts()` at line 819 using fresh research_data.
4. **Weak carousel scan**: query all carousels for this character where `ai_review_score < weak_threshold` AND `status in (draft, ai_reviewed, rejected)`.
5. **Regeneration**: for each weak carousel, call `generate_carousel()` at line 1028 with the same angle/template but new facts. Mark old ones as `archived` status (add enum value in `character_content.py:38`).
6. **Auto-review**: run Stage 1 (Ollama) on each regenerated carousel. High scorers get queued for Stage 2 (Minimax) via scheduler, not inline, to avoid long-running request.

### Returns
```typescript
{
  character_id: string
  facts_added: number
  images_added: number
  carousels_regenerated: number
  carousels_archived: number
  research_depth_delta: number
}
```

### Frontend
- `CharacterDetailPage.tsx`: header-level "Enhance Character" button with confirm dialog showing what will run
- Progress modal via existing `useCharacterContentApi.ts` polling pattern (similar to research queue)

---

## Phase 5: Genre Expansion (Curated Seed Characters)

User picked "Add curated seed characters across top franchises".

### Files to Modify
- `backend/app/services/character_content_service.py` - extend `seed_characters()` around line 2100
- `backend/app/services/character_research_sources.py` - add source mappings at lines 40-88

### Curated Additions (30-40 new characters)

**Prestige TV** (universe=`tv`, new franchises): Walter White already seeded. Add Tony Soprano, Tyrion Lannister (already), Jon Snow, Daenerys Targaryen, Don Draper, Logan Roy, Saul Goodman, Eleven (Stranger Things), Wednesday Addams, Geralt of Rivia, Jack Bauer.

**Fantasy/Sci-Fi** (universe=`lotr`, `star_wars`, `harry_potter`): Aragorn, Legolas, Frodo (lotr); Yoda, Obi-Wan, Luke, Rey, Grogu (star_wars); Harry, Hermione, Snape, Voldemort, Dumbledore (harry_potter).

**Anime** (universe=`anime`, new): Naruto, Goku, Luffy, Eren Yeager, Light Yagami, Levi Ackerman, Sukuna, Gojo Satoru.

**Gaming** (universe=`gaming`, new): Master Chief, Kratos, Geralt, Lara Croft, Mario, Link, Solid Snake, Arthur Morgan, Joel (TLOU), Ellie.

**Film** (universe=`film`, existing): Add The Joker (heath ledger film angle), Vito Corleone, Michael Corleone, Hannibal Lecter, Tyler Durden, Neo, Indiana Jones.

### Research Source Mappings to Add
In `character_research_sources.py`:
- Fandom domains: `gameofthrones.fandom.com`, `strangerthings.fandom.com`, `breakingbad.fandom.com`, `naruto.fandom.com`, `onepiece.fandom.com`, `halo.fandom.com`, `godofwar.fandom.com`, `witcher.fandom.com`, etc.
- Reddit subreddits: `r/gameofthrones`, `r/StrangerThings`, `r/Naruto`, `r/OnePiece`, `r/halo`, `r/GodofWar`, `r/thelastofus`, `r/cyberpunkgame`, etc.
- TV Tropes aliases: `GameOfThrones`, `StrangerThings`, `BreakingBad`, `AttackOnTitan`, `NarutoSeries`, `HaloSeries`, etc.

### Verification
After seeding, run batch research via `POST /api/characters/research-queue/start {"limit": 40}` to populate fact banks for new characters.

---

## Phase 6: Skill Documentation Update

### Files to Modify
- `c:\code\zero\.claude\skills\character-content\SKILL.md` - add new endpoints, add cross-reference to review skill at top
- `c:\code\zero\.claude\skills\character-content-review\SKILL.md` - add cross-reference back at top

### Content Updates in `/character-content`
- New "Workflow 5: Enhance Character + Regenerate Weak Carousels" section
- New "Workflow 6: Refresh Carousel Images" section (all 3 modes)
- Add Minimax final review note to Workflow 2
- Expand "Character Universes" section with the 30-40 new seeded characters
- One-paragraph box at top: "This skill is for OPERATIONS. For system audit, grading, and improvement planning, use `/character-content-review`."

### Content Updates in `/character-content-review`
- One-paragraph box at top: "This skill is for STRATEGIC AUDIT. For day-to-day content creation, use `/character-content`."
- Update scoring dimensions to include Minimax final-review quality signal

---

## Critical Files Reference

### Backend
| File | Role |
|------|------|
| `backend/app/routers/character_content.py:1-782` | 43 REST endpoints, add ~6 new |
| `backend/app/services/character_content_service.py:185-2100` | Core service, add enhance + reimage methods |
| `backend/app/services/character_research_sources.py:40-88` | Source mappings, expand for new franchises |
| `backend/app/models/character_content.py:12-22` | `CharacterUniverse` enum (already has needed values) |
| `backend/app/models/llm.py` | Add `CHARACTER_CONTENT_REVIEW` task type |
| `backend/app/infrastructure/llm_providers/__init__.py` | Register new Minimax provider |
| `backend/app/infrastructure/llm_providers/minimax_provider.py` | NEW - port from Legion |
| `backend/app/infrastructure/config.py` | Add `minimax_api_key` settings |
| `backend/app/infrastructure/unified_llm_client.py` | No changes needed - already supports new providers |
| `backend/app/db/models.py:1560-1709` | Add `final_review*` fields to CharacterCarouselModel |
| `backend/app/migrations/versions/022_character_final_review.py` | NEW - schema migration |

### Frontend
| File | Role |
|------|------|
| `frontend/src/hooks/useCharacterContentApi.ts` | Add ~6 hooks |
| `frontend/src/pages/CharacterDetailPage.tsx` | Add Enhance + Reimage buttons |
| `frontend/src/pages/CharacterContentPage.tsx` | Minor: filter by new universes |
| `frontend/src/types/index.ts` | Extend types for new endpoints |

### Reference (Legion)
| File | Purpose |
|------|---------|
| `c:\code\legion\backend\app\services\llm_clients\minimax_client.py` | Port this verbatim with minor adaptation |
| `c:\code\legion\backend\app\core\legion_config.py` | Minimax pricing constants |

---

## Verification Plan

### Phase 1 (Minimax Provider)
1. Set `ZERO_MINIMAX_API_KEY` in `.env`
2. Rebuild: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
3. Verify provider registered: `curl http://localhost:18792/api/llm/providers` should list `minimax` as configured
4. Health check: `curl http://localhost:18792/api/llm/health` should show `minimax: healthy`
5. Router config check: `cat workspace/llm/router_config.json | grep character_content_review_final`

### Phase 2 (Two-Stage Review)
1. Pick an existing carousel: `GET /api/characters/carousels?status=draft&limit=1`
2. Trigger review: `POST /api/characters/carousels/{id}/review`
3. Confirm carousel has both `ai_review_score` (Ollama) and `final_review_score` (Minimax) populated
4. Force Kimi fallback: temporarily unset `ZERO_MINIMAX_API_KEY`, re-run review, confirm `final_review_model=kimi`

### Phase 3 (Image Refresh)
1. Reimage-all: `POST /api/characters/carousels/{id}/reimage` - confirm all `slides[].image_url` changed
2. Per-slide: `POST /api/characters/carousels/{id}/slides/2/reimage` - confirm only slide 2 changed
3. Fresh sources: `POST /api/characters/carousels/{id}/reimage-with-fresh-sources` - confirm character images table grew and slides updated

### Phase 4 (Enhance Character)
1. Pick a character with thin fact_bank: `GET /api/characters/?research_status=completed` and find one with <15 facts
2. Trigger: `POST /api/characters/{id}/enhance` with `{refresh_research: true, add_images: 5, regenerate_weak_carousels: true}`
3. Confirm: fact_bank grew, images_added > 0, carousels_regenerated > 0
4. Check archived status on old weak carousels: `GET /api/characters/carousels?character_id={id}&status=archived`

### Phase 5 (Genre Expansion)
1. Run `POST /api/characters/seed` (should add all new curated characters, idempotent)
2. Count: `GET /api/characters/stats` - total_characters should be ~60+ (from 24)
3. Filter by new universe: `GET /api/characters/?universe=anime` should return new anime entries
4. Research them: `POST /api/characters/research-queue/start {"limit": 40}`
5. Monitor: `GET /api/characters/research-queue` - all should complete with `fact_bank >= 10`

### Phase 6 (Skill Docs)
1. Read both skill files, confirm cross-references present
2. Invoke `/character-content` to confirm new workflows visible
3. Invoke `/character-content-review` to confirm updated rubric

### End-to-end Smoke Test
1. Add new character (e.g., Geralt) via `POST /api/characters/`
2. Research: `POST /api/characters/{id}/research`
3. Source images: `POST /api/characters/{id}/source-images`
4. Generate carousel: `POST /api/characters/{id}/carousel {angle: "hidden_truths", story_template: "secrets_revealed"}`
5. Review: `POST /api/characters/carousels/{cid}/review` -> confirm two-stage
6. Reimage single slide: `POST /api/characters/carousels/{cid}/slides/1/reimage`
7. Enhance character: `POST /api/characters/{id}/enhance {regenerate_weak_carousels: true}`
8. Verify final carousel ready for human approval in `GET /api/characters/review-queue/smart`

---

## Execution Order (Recommended)

1. **Phase 6 first** (documentation): quick win, clarifies skill purposes before heavy changes
2. **Phase 1** (Minimax provider): foundation for everything else
3. **Phase 5** (seed characters + source mappings): unblocks testing with variety
4. **Phase 3** (image refresh): independent, valuable, smaller scope
5. **Phase 2** (two-stage review): builds on Phase 1
6. **Phase 4** (enhance): most complex, benefits from Phases 1, 2, 3 being stable

Each phase independently shippable. Legion sprint must be created in project_id=8 with tasks per phase (per `CLAUDE.md` mandate).
