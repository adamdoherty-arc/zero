# High-Priority Re-Seed: Marvel / DC / The Boys / From / Invincible + Movies

## Context

The `characters` table was wiped (live count: **0**) and the `media_titles` table is also empty (**0** movies/TV). The user needs a rapid, comprehensive re-seed of Marvel, DC, The Boys, From, and Invincible characters plus their movies, then to let the existing 24/7 pipeline generate carousels with rich research and many images per character.

What we already have (verified):
- A complete pipeline at [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py): `seed_characters()` (line 5286), `start_batch_research_async()` (line 4354), `_run_research_queue()` (3-concurrency sliding window with 30min timeout, line 4555), `_source_images()` (sources 20-30 images per character, line 1161), `enhance_character(add_images=8)` (line 5145), `smart_batch_generate(count=12)` (line 6017).
- 12 character-related scheduler jobs already running ([scheduler_service.py](backend/app/services/scheduler_service.py)): research refresh (11 AM), retry (12 PM), generation (every 3h), approval (3 PM), publish (every 4h), backlog gate (2 PM), image cleanup (3 AM), discovery (9 AM), gap audit (Sunday 10 AM), and more.
- All-local LLM routing via `vllm/qwen3-chat` for `character_research` task type — research and carousel generation run at **$0** through the unified router.
- 11 image-source providers wired up in [backend/app/services/image_sources/](backend/app/services/image_sources/) including TMDB, ComicVine, Fanart.tv, IMDb GraphQL, Wikimedia, Unsplash, Pexels, Reddit PRAW.
- World-class playbook in [.claude/skills/zero-character-content/knowledge/WORLD_CLASS_PLAYBOOK.md](.claude/skills/zero-character-content/knowledge/WORLD_CLASS_PLAYBOOK.md) (18 layouts, 22 text effects, 12 image grades, 25 hook formulas, brand-kit schema).
- Scratch ingest tool [tmp_ingest_characters.py](tmp_ingest_characters.py) with The Boys + From character lists from the prior seeding — **reusable as a reference**, but the ingest belongs in the persistent `seed_characters()` so it never gets lost again.
- Movie seeding endpoint `POST /api/media-content/seed?count=N&media_type=movie` backed by TMDB (`media_content_service.seed_from_tmdb`, line 853).

The boys + Invincible + From were never in the persistent seed list, so a redeploy or wipe loses them every time. This plan fixes that, in addition to triggering the immediate re-seed.

## Scope

1. **Persistent seed expansion** — add The Boys (~15), From (~12), Invincible (~14), and broaden Marvel (+~25) and DC (+~22) inside `seed_characters()`. New total: ~190 characters, all in the canonical seed.
2. **Movie re-seed** — call `POST /api/media-content/seed` for popular movies (TMDB) plus targeted franchise sweeps (Marvel, DC, The Boys-adjacent, Invincible has no movies, From has none).
3. **Kick off immediate batch research** — drain everything through the existing 3-concurrency queue.
4. **Boost images per character** — after research, run a one-shot batch of `enhance_character(add_images=12)` so each character lands at 30+ images (initial 20-30 from `_source_images` + 12 enhancement = 32-42).
5. **Let the scheduler take over** — every 3h generation, auto-approve, auto-publish, gap audit, etc., already cover "around the clock."
6. **Surface a single trigger endpoint** — add `POST /api/character-content/rush-reseed` that does steps 1-4 in one call so this is a one-button operation if it ever happens again.

## Files to modify

### 1. [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py)

**Edit `seed_characters()` (line 5286)** — append three new universe blocks and broaden two existing ones. Keep the existing dict format (`name`, `universe`, `franchise`, `real_name`, `tags`).

The Boys block (universe="tv", franchise="The Boys"): Billy Butcher, Hughie Campbell, Mother's Milk, Frenchie, Kimiko, Starlight, Homelander, A-Train, Black Noir, The Deep, Ashley Barrett, Victoria Neuman, Ryan Butcher, Sister Sage, Soldier Boy, Stormfront, Stan Edgar, Firecracker, Translucent, Queen Maeve. (Source actor names from [tmp_ingest_characters.py](tmp_ingest_characters.py).)

From block (universe="tv", franchise="From"): full 12-character list from [tmp_ingest_characters.py:9-21](tmp_ingest_characters.py#L9-L21).

Invincible block (universe="anime" — animated; reuse animation-leaning enum): Mark Grayson / Invincible, Omni-Man / Nolan Grayson, Atom Eve, Allen the Alien, Cecil Stedman, Debbie Grayson, Rex Splode, Robot, Monster Girl, Dupli-Kate, The Immortal, Conquest, Anissa, Battle Beast, Donald Ferguson.

Marvel expansion (~+25): Vision, Hawkeye, Bucky Barnes / Winter Soldier, Falcon (Sam pre-Cap), Ant-Man, Wasp, Star-Lord, Gamora, Rocket Raccoon, Groot, Drax, Mantis, Nebula, Captain Marvel, Ms. Marvel, Moon Knight, She-Hulk, Daredevil, Kingpin, Punisher, Jessica Jones, Luke Cage, Iron Fist, Storm, Cyclops, Jean Grey, Magneto, Gambit, Rogue, Beast, Professor X, Mystique, Carnage, Venom, Green Goblin, Mysterio, Doctor Octopus, Kang the Conqueror, Galactus, Silver Surfer, High Evolutionary.

DC expansion (~+22): Catwoman, Two-Face, Penguin, Riddler, Bane, Scarecrow, Ra's al Ghul, Nightwing, Robin (Damian Wayne), Red Hood, Cyborg, Shazam, Black Adam, Deadshot, Lex Luthor, Brainiac, Darkseid, Doomsday, Black Canary, Zatanna, John Constantine, Swamp Thing, Martian Manhunter, Supergirl, Lobo, Deathstroke.

**Add `rush_reseed()` method** (next to `seed_characters`, ~line 5440):

```python
async def rush_reseed(self, enhancement_per_char: int = 12) -> Dict[str, Any]:
    """High-priority re-seed: seed all canonical characters, kick off
    batch research, then enhancement for extra images. Returns a status
    dict the router exposes so the frontend can poll progress.
    """
    created = await self.seed_characters()
    char_ids = [c.id for c in created]
    queue_status = await self.start_batch_research_async(
        character_ids=char_ids, universe=None, limit=len(char_ids)
    )
    # The image-enhancement pass is fire-and-forget; the research queue
    # finishes first, then a background task tops images up to ~30+.
    asyncio.create_task(self._post_research_image_boost(char_ids, enhancement_per_char))
    return {
        "seeded": len(created),
        "queued_for_research": queue_status.queued,
        "concurrency": 3,
        "eta_minutes": queue_status.eta_minutes,
    }

async def _post_research_image_boost(self, char_ids: List[str], add_images: int) -> None:
    """Wait for research queue to drain, then enhance each character with
    add_images more images (no carousel regen — scheduler handles that)."""
    while True:
        status = await self.get_research_queue_status()
        if not status.running and status.queued == 0:
            break
        await asyncio.sleep(60)
    for cid in char_ids:
        try:
            await self.enhance_character(
                cid, refresh_research=False, add_images=add_images,
                regenerate_weak_carousels=False,
            )
        except Exception as e:
            logger.warning("rush_reseed_enhance_failed", character_id=cid, error=str(e))
```

### 2. [backend/app/routers/character_content.py](backend/app/routers/character_content.py)

Add a single endpoint near the existing `/seed` route:

```python
@router.post("/rush-reseed")
async def rush_reseed(
    enhancement_per_char: int = 12,
    svc: CharacterContentService = Depends(get_character_content_service),
):
    return await svc.rush_reseed(enhancement_per_char=enhancement_per_char)
```

### 3. No changes needed to scheduler

The 12 character jobs already cover every-3-hour carousel generation, auto-approval, auto-publish, image cleanup, weekly gap audit. Just verify enabled state after deploy: `curl /api/scheduler/status | grep character`.

## Trigger / Verify

Once deployed (rebuild `zero-api` per CLAUDE.md):

1. **Re-seed everything** (one HTTP call):
   ```bash
   curl -X POST "http://localhost:18792/api/character-content/rush-reseed?enhancement_per_char=12" \
        -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
   # → {"seeded": 190, "queued_for_research": 190, "concurrency": 3, "eta_minutes": ~3800}
   ```

2. **Re-seed movies** (TMDB popular + targeted batches):
   ```bash
   curl -X POST "http://localhost:18792/api/media-content/seed?count=50&media_type=movie" \
        -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
   curl -X POST "http://localhost:18792/api/media-content/seed?count=30&media_type=tv_show" \
        -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
   curl -X POST "http://localhost:18792/api/media-content/batch-research" \
        -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
   ```

3. **Watch the queue drain** (research at 3-concurrency, ~30 min/character → ~190/3*30 ≈ 32 hours wall-clock for 100% completion, but carousels will start firing well before that as soon as the first batch lands):
   ```bash
   watch -n 30 'curl -s "http://localhost:18792/api/character-content/research-queue/status" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" | jq ".running_count, .completed, .queued"'
   ```

4. **Verify carousels firing** (every 3h scheduler tick):
   ```bash
   curl -s "http://localhost:18792/api/character-content/carousels?status=ai_reviewed&limit=5" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" | jq '.[].title'
   ```

5. **Verify image counts per character**:
   ```bash
   curl -s "http://localhost:18792/api/character-content/characters?limit=200" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" | jq '[.[] | {name, image_count: (.image_urls|length)}] | sort_by(.image_count)'
   ```

6. **Frontend smoke**: open `http://localhost:5173/character-content` — see characters populating; `http://localhost:5173/character-autopilot` — confirm activity log ticking.

## Cost

All-local: research uses `vllm/qwen3-chat` (free), image discovery is HTTP scraping with TMDB/ComicVine/Fanart free tiers, carousel generation runs on vLLM. Daily LLM budget cap (`$5/day` in [router_config.json](workspace/llm/router_config.json)) is the hard ceiling — should stay near $0 unless MiniMax escalation gets invoked for the final-review polish (capped at $2/day).

## Risk + Rollback

- **Risk: research queue stalls.** Mitigation: scheduler has `character_research_retry` job at 12 PM daily that drains pending/failed; queue state persists in `research_queue_state` table and resumes on restart.
- **Risk: image sources rate-limit.** Mitigation: 11 sources rotate, blocklist auto-purges broken URLs at 3 AM (`character_image_cleanup`).
- **Risk: too many auto-approved carousels piled up.** Mitigation: `character_publish_backlog` job maintains target=6 backlog; if it overshoots just lower the auto-approve threshold (currently 8.0) via `/api/character-content/config`.
- **Rollback**: the persistent seed is the only durable change. Reverting that one commit + truncating `characters` would restore prior state. The rush-reseed endpoint is purely additive.
