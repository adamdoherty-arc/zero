# Character Content System — Deep Review & Reliability Sprint Plan

## Context

The character/development/TV/movie content system is supposed to generate carousels 24/7 from a roster of characters (Marvel/DC/anime/dev figures), pulling images, facts, and relationship metadata. In practice it is **not running 24/7**, it **silently ships carousels with no images**, and the **learning loop never closes** because AI review never auto-fires and hook-style metadata is never persisted. This plan captures the audit findings and breaks remediation into hot-fix tasks for the current sprint plus reliability/architecture tasks for the next sprint.

---

## Audit Findings

### Cadence reality (not 24/7)
The scheduler runs character content on a fixed grid, not a continuous loop:

| Job | Cadence | File |
|---|---|---|
| `character_content_generation` | hourly (`0 * * * *`) | [scheduler_service.py:426-429](backend/app/services/scheduler_service.py#L426) |
| `character_content_gate` | every 15 min | [scheduler_service.py](backend/app/services/scheduler_service.py) |
| `carousel_watchdog` | every 10 min | [scheduler_service.py:436-440](backend/app/services/scheduler_service.py#L436) |
| `character_research_refresh` | 1×/day, 03:00 UTC | [scheduler_service.py:421-424](backend/app/services/scheduler_service.py#L421) |
| `character_auto_approval` | every 30 min | [scheduler_service.py:487-490](backend/app/services/scheduler_service.py#L487) |
| Publishing | 10:00 / 14:00 / 18:00 UTC | [scheduler_service.py:446-449](backend/app/services/scheduler_service.py#L446) |

So gaps of up to 60 minutes are normal between generation runs, and research only drains once per day.

### Critical bugs (root causes for "not working")

**P1 — Carousels persist with `image_url=null`** ([character_content_service.py:1866-1960](backend/app/services/character_content_service.py#L1866))
`_assign_slide_images` runs three tiers (existing match → SearXNG on-demand → least-used existing). Tier 3 is gated on `if not assigned and existing:` — when `existing` is empty, the slide is saved as-is with no image and no exception. Frontend renders broken.

**P1 — `hook_style` and `story_template` never saved to `generation_metadata`** ([character_content_service.py:1757-1773](backend/app/services/character_content_service.py#L1757), [scheduler_service.py:2732-2737](backend/app/services/scheduler_service.py#L2732))
Scheduler passes them in, `generate_carousel` ignores them on the persistence path. Thompson Sampling in `pick_next_variant()` therefore has no signal — ~80% of carousels train nothing.

**P2 — AI Stage-2 review never auto-triggers** ([character_content_service.py:1790-1801](backend/app/services/character_content_service.py#L1790))
`_background_review` only fires when `swarm_enabled` is true. Default path leaves `ai_review_score = null` and `final_review_score = null`, so auto-approval has nothing to grade and the learning loop is dead.

**P2 — Image discovery silently returns `[]`** ([image_source_service.py:197-364](backend/app/services/image_source_service.py#L197), [image_source_service.py:366-373](backend/app/services/image_source_service.py#L366))
`_safe_source` swallows every exception. Rate limits, missing API keys (TMDB/Fanart/ComicVine/SuperHero), Fandom domain miss, or Wikipedia title ambiguity all yield empty results with no operator alert. This is why some characters were generated with zero images.

**P3 — Placeholder-token leak in retry prompt** ([character_content_service.py:1527-1535](backend/app/services/character_content_service.py#L1527))
Qwen3 echoed schema example strings ("hook text", "fact 1") verbatim into slides. Guard added for known tokens only; other LLMs (Minimax, Kimi) may reproduce.

**P3 — Research queue not draining** ([IMPROVEMENT_PLAN.md:56-63](.claude/skills/zero-character-content/knowledge/IMPROVEMENT_PLAN.md#L56))
1×/day cadence + characters marked `completed` with `fact_bank.length < 3`. No alert on empty success.

**P4 — TV/movie ↔ character graph is hand-coded** ([CHARACTER_GRAPH.md](.claude/skills/zero-character-content/knowledge/CHARACTER_GRAPH.md), [models.py:1594-1612](backend/app/db/models.py#L1594))
`relationship_map`, `multi_character_ids`, `media_title_id`, `franchise`, `universe` fields exist, but no LLM-driven discovery walks them post-research. Cross-character/franchise carousels can't be planned automatically.

---

## Fix Plan — Sprints

Tasks below are sized for autonomous execution and should be created in Legion (`project_id=8`) via [legion_client.py:702](backend/app/services/legion_client.py#L702) `get_legion_client().create_task(sprint_id, {...})`. Active sprint must be looked up first via `list_sprints(project_id=8, status="active")`.

### CURRENT SPRINT — Reliability hot-fixes (target: ship in <1 day)

1. **Block carousel persistence when any slide lacks `image_url`.** Edit [character_content_service.py:1866-1960](backend/app/services/character_content_service.py#L1866). After Tier 3, if `assigned` is still false AND `existing` is empty, raise a typed `CarouselImageMissingError`. Caller marks character `image_status="needs_sourcing"`, schedules immediate `discover_images`, and skips persisting the carousel. Add structured log `event="carousel_blocked_no_images"`.
2. **Persist `hook_style` and `story_template` into `generation_metadata`.** Edit [character_content_service.py:1757-1773](backend/app/services/character_content_service.py#L1757) so both fields are written into the row at insert time. Backfill existing draft rows where metadata is null by re-deriving from logs (one-shot script).
3. **Auto-trigger Stage-2 review after every generation, not just swarm path.** Edit [character_content_service.py:1790-1801](backend/app/services/character_content_service.py#L1790) so `_background_review` is awaited (or fire-and-forgotten via `asyncio.create_task`) on every successful `generate_carousel`, swarm or not. Verify `ai_review_score` populates within 60s of generation.
4. **Force `discover_images` on character create.** When a new character is added with `image_urls=[]`, queue `image_source_service.discover_images` synchronously (with a 30s timeout) before any carousel job can pick it up. Set `eligible_for_generation=False` until at least 3 valid images exist.

### NEXT SPRINT — Observability & learning loop

5. **Research-completion validator.** In [character_content_service.py:688-717](backend/app/services/character_content_service.py#L688), after research run, if `fact_bank.length < 3` flip status back to `needs_retry` and log `event="research_completed_empty"`. Add Prometheus counter.
6. **Image-source health metrics + operator alert.** Replace silent `_safe_source` swallowing in [image_source_service.py:366-373](backend/app/services/image_source_service.py#L366) with per-source success/failure counters. Daily report flags any source with <50% success rate or any character with 0 images after retry.
7. **Carousel-watchdog actually rescues stuck rows.** [scheduler_service.py:436-440](backend/app/services/scheduler_service.py#L436): scan for carousels in `draft` >2h with `final_review_score=null`, re-trigger Stage-2 review. Scan for characters with `image_urls=[]` and re-queue discovery.
8. **Bump research cadence.** Move `character_research_refresh` from 1×/day to every 2h (`0 */2 * * *`) for characters with `research_status in ('needs_retry','pending')`. Keep daily full refresh for `completed` characters.
9. **Generalize placeholder-token guard.** [character_content_service.py:1527-1535](backend/app/services/character_content_service.py#L1527): replace token-set guard with a regex check that also rejects any slide where >40% of chars match the schema's example tokens, and add an LLM-agnostic post-parse validator.

### FUTURE SPRINT — Cross-character/franchise architecture

10. **Relationship-graph walker.** New service `character_graph_service.py` that consumes `relationship_map` + `multi_character_ids` + `franchise` + `universe` and emits "rivalry", "team-up", "franchise crossover" carousel ideas. Feed into `content_swarm_service.py`. Reuse [CHARACTER_GRAPH.md](.claude/skills/zero-character-content/knowledge/CHARACTER_GRAPH.md) as seed corpus.
11. **TV/movie source linkage UI.** Frontend [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx): show `media_title_id` chip on each character with deep-link to source. Surface "characters in this title" cluster.
12. **Frontend broken-image fallback.** [CarouselCard.tsx](frontend/src/components/character-content/CarouselCard.tsx) + [TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx): if `slide.image_url` is null/404, render an `InlineError` with "Re-source images" button calling the new endpoint from task 4.

---

## Critical Files To Modify

- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — bugs #1, #2, #3, #5, #9
- [backend/app/services/image_source_service.py](backend/app/services/image_source_service.py) — bug #4, task #6
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — tasks #7, #8
- [backend/app/services/content_swarm_service.py](backend/app/services/content_swarm_service.py) — task #10 hook-in
- [backend/app/db/models.py](backend/app/db/models.py) — possible new column `image_status`, no schema change otherwise
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) — new "re-source images" endpoint for task #12
- [frontend/src/components/character-content/CarouselCard.tsx](frontend/src/components/character-content/CarouselCard.tsx), [TikTokPhonePreview.tsx](frontend/src/components/character-content/TikTokPhonePreview.tsx), [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) — task #11, #12

## Reusable Code (Don't Rewrite)

- `_assign_slide_images` 3-tier strategy — extend, don't replace
- `_final_review_carousel` — already implemented, just wire it up
- `image_source_service.discover_images` — already aggregates 18+ sources
- `pick_next_variant` Thompson Sampling — works once metadata is persisted
- `legion_client.create_task` — task creation path is ready

## Verification

After hot-fix sprint ships:

1. `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
2. Wait for next `character_content_generation` run, then query: `SELECT id, slides FROM character_carousels WHERE created_at > NOW() - INTERVAL '2 hours'` — expect zero rows with any `slides[i].image_url IS NULL`.
3. Same window: `SELECT generation_metadata->>'hook_style', count(*) FROM character_carousels WHERE created_at > NOW() - INTERVAL '2 hours' GROUP BY 1` — expect non-null hook_style for every row.
4. Same window: `SELECT count(*) FROM character_carousels WHERE created_at > NOW() - INTERVAL '2 hours' AND final_review_score IS NULL` — expect 0 after a 60s grace.
5. `docker logs zero-api 2>&1 | grep -E "carousel_blocked_no_images|research_completed_empty"` — investigate any hits.
6. UI smoke: open `/character-content`, scroll the queue, confirm no broken images. Manually add a brand-new character; confirm it does not appear in generation queue until it has ≥3 images.

## Legion Tasks To Create

Create 12 tasks (one per numbered item) in active Zero sprint. Items 1-4 = current sprint, priority `high`. Items 5-9 = next sprint, priority `medium`. Items 10-12 = future sprint, priority `low`. Use [legion_client.py:702](backend/app/services/legion_client.py#L702) `get_legion_client().create_task(sprint_id, {title, description, prompt, priority})`. Each task's `prompt` should reference this plan file path so the executor has full context.
