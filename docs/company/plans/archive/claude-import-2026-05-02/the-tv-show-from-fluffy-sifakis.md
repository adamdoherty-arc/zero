# Plan: Next Carousel System Improvements — Quality Floor, Visual Variety, Feedback Loop

## Context

The carousel content-quality fixes (A/B/C/D) have shipped and verified on Homelander's regenerated carousel: slide-1 duplication gone, 30-fact + character_sketch context in the prompt, colored `**bold**` runs in published PNGs, auto-approval guardrail logging regressions. User is asking "what else can we do as a whole?" — a broader, strategic roadmap question rather than a single bug fix.

This plan ranks the next-best improvements by impact/effort ratio, grouped into three phases. Each phase is independently shippable.

---

## Observed Remaining Gaps (evidence)

| # | Observed today | File |
|---|---|---|
| 1 | **Carousel gen routed to slow qwen3-chat** (`default_model: vllm/qwen3-chat`, no `character_carousel_generation` task override in router_config.json). Caused today's visible symptoms: only 4 slides when 7 requested, no `**bold**` markers in first run, ~60-180s gen latency. | [workspace/llm/router_config.json](workspace/llm/router_config.json) |
| 2 | **4 scheduler call sites** invoke `generate_carousel()`; most pass only `angle`, leaving `hook_style` and `story_template` NULL. Kills prompt-variety + breaks PromptBreeder's ability to learn hook-style performance. | [backend/app/services/scheduler_service.py:2837,3515,3693,3766](backend/app/services/scheduler_service.py) |
| 3 | **Same character image repeats across all 7 slides** of Homelander's rendered carousel. The `_assign_slide_images` 3-tier matcher (line 2019) falls through to "least-used existing" without a reuse-count cap when per-slide SearXNG returns nothing. | [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py#L2019) |
| 4 | **Stage 2 final review only runs on carousels with Stage-1 score ≥ 7**. Low-scoring carousels (the ones that most need the polish pass) skip it. Per scheduler survey, ~30% coverage. | `_final_review_carousel` call sites |
| 5 | **No TikTok performance sync into carousel rows**. `character_performance_sync` logs counts but never pulls back views/likes/shares. Brain/PromptBreeder can't learn from real audience data — only `final_review_score` (a self-judged proxy). | [backend/app/services/scheduler_service.py:3049](backend/app/services/scheduler_service.py#L3049) |
| 6 | **Research refresh is a flat 7-day window**, regardless of whether the show is currently airing. "From" and "The Boys" get new episodes weekly; facts go stale fast. | `character_research_refresh` job |
| 7 | **LLM sometimes returns fewer slides than requested** (4 vs 7) with no retry. | `generate_carousel` around the LLM chat call |

---

## Phased Roadmap

### Phase 1 — Quality Floor (≈5h total)

Goal: every carousel hits a minimum quality bar before it leaves the pipeline. Self-contained, no schema changes.

**1.1 Route `character_carousel_generation` to Kimi K2 / MiniMax M2.7** (2h)
- Edit `workspace/llm/router_config.json`: add task override
  ```json
  "character_carousel_generation": {
    "provider": "kimi",
    "model": "kimi-k2.5",
    "fallback": ["minimax/MiniMax-M2.7", "vllm/qwen3-chat"]
  }
  ```
- Kimi follows structured-JSON instructions far better than qwen3. Expected impact: slide_count honored, `**bold**` markers used, 3-line rhythm followed. Confirmed by recent commit `f7eac50` which uses Kimi for `swarm_routing` and `character_content_review_final`.
- Cost: ~$0.02/carousel at Kimi K2.5 rates; acceptable given current ~10/day volume.

**1.2 Thread `hook_style` + `story_template` through all scheduler call sites** (1h)
- Fix the 4 `CarouselCreate(...)`/`MediaCarouselCreate(...)` calls at [scheduler_service.py:2837, 3515, 3693, 3766](backend/app/services/scheduler_service.py).
- Use the rotation logic that already exists on `character_content_service.py` (`pick_hook_style`, `pick_story_template`). Bonus: persists hook_style to `generation_metadata` so PromptBreeder can finally compare.

**1.3 Auto-retry on slide-count shortfall** (1h)
- In `generate_carousel`, after parse, if `len(slides) < requested_slide_count - 1`, re-send prompt with explicit "Return exactly {N} slides. You returned {actual}. Regenerate." Allow 1 retry.
- Reuses `_carousel_raw` call pattern already present for placeholder retries ([character_content_service.py:1643](backend/app/services/character_content_service.py)).

**1.4 Run Stage 2 final review on every carousel** (1h)
- Lower the Stage 1 gate so Stage 2 fires even for mid-tier Stage 1 scores (currently ≥ 7; drop to ≥ 5 or remove gate entirely). Stage 2 is the highest-quality polish step — running it on the weak ones is where the biggest lift comes from.

---

### Phase 2 — Visual Variety (≈4h total)

Goal: published carousels look designed, not just stamped.

**2.1 Per-slide image dedup** (3h)
- In `_assign_slide_images` [character_content_service.py:2019](backend/app/services/character_content_service.py), track `image_url_reuse_count` across the loop. If Tier-3 fallback would reassign an already-used URL AND the character has >= slide_count different images available, pick the next unused one. If pool is genuinely shallow (<slide_count images), kick a background `discover_more_character_images` rather than silently repeating.
- Measured impact: Homelander's 7 rendered slides today use the same image; a dedup pass would give visual rhythm to the carousel.

**2.2 Slide-1 cover design** (stretch, 4h — defer if we want Phase 2 small)
- Currently slide 1 is "character photo + hook overlay". Custom typographic covers (no character photo, bold color field, oversized number, magazine-style layout) differentiate from every-other-carousel-on-TikTok. Would require a new renderer path + template set. Good candidate for Phase 3 or separate plan.

---

### Phase 3 — Feedback Loop & Freshness (≈13h total)

Goal: system gets better on its own as content ships.

**3.1 TikTok analytics → carousel_metrics** (8h)
- New table `carousel_metrics(carousel_id, views, likes, comments, shares, synced_at)`, one row per pull.
- Extend `character_performance_sync` to hit TikTok Creator Center API (already imported for tiktok_shop workflows; confirm same auth works for content analytics).
- Wire into [content_learning_engine.py](backend/app/services/content_learning_engine.py): feed views/engagement into prompt-variant scoring, not just `final_review_score`.
- This is the single biggest long-term unlock — closes the OODA loop from "Zero generates" → "audience reacts" → "Zero learns."

**3.2 Active-show aware research refresh** (5h)
- Add `next_episode_date` to `CharacterModel`. Populate from TVmaze (already used — [scheduler:trend_tvmaze_schedule](backend/app/services/scheduler_service.py)). On research complete, if character's franchise has an episode airing in next 14 days, set refresh window to 3 days. Otherwise keep 30.
- Stops "From"/"The Boys" carousels from citing season-2 facts when season 3 just aired.

---

## Critical Files

- [workspace/llm/router_config.json](workspace/llm/router_config.json) — Phase 1.1 routing override
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — Phase 1.2 call-site audit (lines 2837, 3515, 3693, 3766), Phase 3.1 analytics job, Phase 3.2 episode-aware refresh
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — Phase 1.3 retry, Phase 1.4 Stage 2 gate, Phase 2.1 image dedup
- [backend/app/services/content_learning_engine.py](backend/app/services/content_learning_engine.py) — Phase 3.1 metric-aware learning
- [backend/app/db/models.py](backend/app/db/models.py) — Phase 3.1 new `carousel_metrics` table, Phase 3.2 `next_episode_date` column (migration required)

## Verification per phase

**Phase 1 verification**:
- 1.1: Regenerate 3 carousels for different characters; expect `generation_metadata.provider="kimi"` on each, 7/7 slides, ≥3 `**bold**` markers per carousel.
- 1.2: After next scheduler cycle, query carousels created in last hour — expect `generation_metadata.hook_style IS NOT NULL` on 100% (was ~70%).
- 1.3: Force a short LLM response (mock or low max_tokens); verify retry fires and final carousel has requested slide count.
- 1.4: `SELECT count(*) FROM character_carousels WHERE final_review_score IS NOT NULL AND created_at > now() - interval '1 day'` should approach 100% of generated count (was ~30%).

**Phase 2 verification**:
- 2.1: Render 1 carousel with 7 slides. `SELECT DISTINCT image_url FROM jsonb_array_elements(slides)` should return ≥ min(slide_count, unique_pool_size) rows. Visually inspect PNGs for variety.

**Phase 3 verification**:
- 3.1: Publish a test carousel, wait for first analytics sync, `SELECT * FROM carousel_metrics WHERE carousel_id = '...'` returns non-zero views.
- 3.2: Pick a character in an airing show, set `last_researched = 5 days ago`, trigger `character_research_refresh` — expect the character to be picked (new 3-day window), not skipped (old 7-day window).

## Out of Scope / Defer

- New cover-design templates (2.2 stretch) — worth a dedicated plan.
- Slide-image AI generation (e.g. Midjourney per-slide) — high cost, separate experiment.
- Cross-platform scheduling (IG Reels, YouTube Shorts) — separate feature.
- Audio track generation (custom voiceover, music beds) — separate feature.

---

## Scope — All Three Phases In

User selected all three phases. Execution order is **Phase 1 → Phase 2 → Phase 3** — later phases depend on earlier ones:

- Phase 1 fixes model compliance and variety bypass first. Without it, Phase 3's feedback loop would be learning from noisy/malformed outputs.
- Phase 2 adds image-dedup variety on top of the now-compliant generator.
- Phase 3 wires real-audience metrics back into the prompt/variant scoring and keeps active-show research fresh — only meaningful once Phases 1-2 are producing good carousels.

Total estimated effort: ~22h. I will ship Phase 1 and rebuild/verify, then Phase 2, then Phase 3, stopping between phases for visual spot-check if any regression appears.
