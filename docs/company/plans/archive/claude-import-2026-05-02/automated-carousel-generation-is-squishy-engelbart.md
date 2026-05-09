# Zero as 24/7 Carousel Employee

## Context

Zero's character-content pipeline has 14 scheduler jobs and generates ~25 carousels/hr, but it does not feel like a 24/7 employee because:

1. **The learning loop is broken.** `hook_style` and `story_template` are accepted by the API but never persisted on scheduler-generated carousels (~80% of output). EVOLUTION_LOG shows template avg_score stuck, PromptBreeder has no feedback to evolve on. Recent text-formatting improvements cannot compound.
2. **No daily check-in.** `daily_report_service` exists for infra jobs but does not summarize character-content work. The user has no "what did Zero do today" surface in Discord or the UI.
3. **Throughput is fixed, not demand-driven.** Jobs run on fixed cron; backlog swells silently. 49 media titles sat orphaned until a recent hotfix. No watchdog restarts stalled workers.
4. **Output is JSON only.** Image compositing is missing and `publish_carousel()` is a stub — carousels sit approved but unpublished, so there is no real-world outcome signal feeding the learning loop.

Goal: close the loop so each carousel is measurably better than the last, throughput scales with backlog, and Zero reports in twice a day with what it did, what it found, and what it needs.

---

## Phased Plan

Delivered in four phases. Each phase is independently shippable and ordered so the learning loop has data to learn from before we amplify volume.

### Phase 1 — Fix the learning loop (highest leverage, smallest diff)

Wire the metadata Zero already collects so self-improvement actually works.

**Files:**
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — `generate_carousel()` (~L1230) and scheduler-called `generate_for_character()` (~L2565): persist `hook_style`, `story_template`, and chosen angle into `generation_metadata` and into the `Carousel` row.
- [backend/app/services/scheduler_service.py:2565-2651](backend/app/services/scheduler_service.py#L2565-L2651) — in `character_content_generation` job, pass a rotated `hook_style` and `story_template` alongside `angle` (deterministic rotation like the existing angle picker, seeded from character id + generation count).
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — `_update_template_score()` (~L2563): ensure it receives the template identifier on every Stage 2 review, then updates `template_stats.avg_score` and `usage_count`.
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — add `pick_winning_variant()` helper using Thompson Sampling over `(hook_style, story_template)` pairs, keyed on `template_stats`. Fall back to rotation when a pair has <5 samples.

**Verification:**
- Generate 20 carousels via scheduler, confirm all 20 have non-null `hook_style` and `story_template` in `generation_metadata`.
- After Stage 2 reviews complete, `template_stats` table shows `avg_score` moving.
- Log line `variant_selected hook_style=... story_template=... method=thompson|rotation`.

### Phase 2 — Daily check-in (Discord + dashboard)

Zero reports to the user at 8am and 8pm.

**Files:**
- [backend/app/services/daily_report_service.py](backend/app/services/daily_report_service.py) — add `generate_carousel_employee_report()` that aggregates from the last 12h: generated count, approved count, rejected + reasons, Stage-2 avg score, top 3 hook styles by score, research-queue depth, stalled jobs, self-diagnosed issues (queue depth > N, approval rate < X%, any job failed twice).
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — two new jobs: `carousel_morning_briefing` (cron `0 8 * * *`) and `carousel_evening_recap` (cron `0 20 * * *`), each calling the report + dispatching to Discord.
- [backend/app/services/discord_bot.py](backend/app/services/discord_bot.py) or the existing messaging bridge — post formatted digest (reuse `alerting_service` pattern).
- [frontend/src/pages/CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) — new "Employee Report" tab/section rendering the same report (reuse `useCharacterContentApi`). Add `GET /api/character-content/employee-report` endpoint in [backend/app/routers/character_content.py](backend/app/routers/character_content.py) returning the same payload the scheduler sends to Discord.

**Verification:**
- Manually trigger `generate_carousel_employee_report()` — JSON payload sane.
- Hit `/api/character-content/employee-report` — frontend renders stats.
- Temporarily set cron to `*/5 * * * *`, confirm Discord receives embed, revert.

### Phase 3 — Demand-driven throughput + watchdog

Make volume elastic and self-healing.

**Files:**
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — convert `character_content_generation` cadence from fixed hourly to adaptive: if research queue depth > 30 OR approved backlog < 10, raise to every 15 minutes; otherwise hourly. Implement via a single gating job that enqueues generation waves.
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — new `carousel_watchdog` job (every 10 min): detects jobs that haven't fired in 2x their expected interval, jobs stuck >5 min, research queue that hasn't advanced in 1h. Logs to `system_alerts` and resets stuck locks.
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — extend `media_content_generation` (already added) the same way so TV/movie carousels scale with their own queue.

**Verification:**
- Artificially inflate research queue to 50; confirm cadence flips to 15 min in logs.
- Kill a generation mid-run, confirm watchdog reports the stall in next cycle.
- `docker logs zero-api | grep watchdog` shows healthy heartbeats.

### Phase 4 — Image compositing + publishing (biggest unlock, largest scope)

Turn JSON into actual posts so post-publish engagement can feed back.

**Files:**
- `backend/app/services/carousel_renderer.py` (new) — Playwright or Pillow-based renderer taking carousel JSON → PNG slides. Start with Pillow (no new deps) for text-only slides using the existing font stack; upgrade to Playwright rendering the `TikTokPhonePreview` component later if needed.
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — `publish_carousel()`: replace stub with (a) call renderer, (b) upload PNGs to storage, (c) call TikTok Content Posting API (real client, not stub). Gate behind `ZERO_TIKTOK_PUBLISH_ENABLED` env flag so we can ship rendering first and publishing second.
- `backend/app/services/tiktok_publish_client.py` (new) — thin async wrapper around TikTok Content Posting API.
- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — new `ingest_post_engagement()` that pulls views/likes/saves 24h after publish and writes into `template_stats` as an outcome signal (weights Thompson Sampling from Phase 1).

**Verification:**
- Render one approved carousel to PNG locally; visually compare to `TikTokPhonePreview`.
- Dry-run publish with flag off: PNGs saved, no API call, status `rendered`.
- Flag on in staging, publish one test carousel, confirm TikTok receives it.
- 24h later, `template_stats` row shows updated outcome signal.

---

## Files to reuse (do not recreate)

- Thompson Sampling: if a helper exists in `backend/app/services/brain/` use it; otherwise write a ~40 LOC helper in `character_content_utils.py`.
- Daily report scaffolding: `daily_report_service.py` already handles Discord dispatch + EXPECTED_DAILY_JOBS — extend, don't duplicate.
- Alerts: `alerting_service.py` is the right channel for watchdog output.
- Frontend data: `useCharacterContentApi` already wraps the router; add one hook method for the employee report.

## Verification (end-to-end)

After all four phases:
1. `curl /api/character-content/employee-report` returns populated JSON.
2. Discord receives 8am + 8pm digests for 2 consecutive days.
3. `template_stats` shows monotonically improving avg_score across the Top 3 `(hook_style, story_template)` pairs.
4. One real TikTok post goes live from the pipeline.
5. SCORECARD grade (in `.claude/skills/zero-character-content/knowledge/SCORECARD.md`) moves from 83/100 toward 92+.

## Sequencing note

Phase 1 first. Without the learning loop fixed, Phase 3's extra volume just generates more un-learned-from carousels, and Phase 4's real publishing can't feed signal into a broken loop. Phase 2 goes second because it gives the user visibility into Phase 1's impact. Phase 3 and 4 can run in parallel if scope allows.

---

## Delivery Log (2026-04-18)

**Phases 1–3 shipped. Phase 4 scoped down and partially deferred.**

### Phase 1 — shipped
- `pick_winning_variant()` Thompson Sampling helper in [character_content_utils.py](backend/app/services/character_content_utils.py#L811)
- `get_variant_stats()` + `pick_next_variant()` on service: aggregates 30-day Stage 2 + ai_review data, seeds picker per character
- Scheduler [character_content_generation](backend/app/services/scheduler_service.py#L2623) now calls `pick_next_variant()`, passes both `hook_style` and `story_template` (was only `hook_style`). Per-run caps preserved: 3/hook_style, 4/template
- `_update_template_score()` already existed; verified it fires from Stage 2 review
- Log line `variant_selected` with `method=thompson|rotation` verified

### Phase 2 — shipped
- `generate_carousel_employee_report()` in [daily_report_service.py](backend/app/services/daily_report_service.py#L446): 12h window, approved/rejected counts, Stage 2 avg/min/max, top 3 variants, research queue depth, self-diagnosed issues, wins
- Two new scheduler jobs: `carousel_morning_briefing` (8am) + `carousel_evening_recap` (8pm), both dispatch to Discord via existing notification_service
- New endpoint `GET /api/characters/employee-report?window_hours=N` (router)
- New "Employee Report" tab in [CharacterContentLayout](frontend/src/layouts/CharacterContentLayout.tsx) + [EmployeeReportTab component](frontend/src/pages/CharacterContentPage.tsx) with metric cards, top variants, queue, issues, wins
- Verified: endpoint returns real data, correctly diagnosed "Stage 2 review lagging: 3% of new carousels reviewed" on live data

### Phase 3 — shipped
- `character_content_gate` (every 15m): runs ad-hoc generation wave only when approved backlog < 10 OR research queue > 30. Preserves hourly base cadence
- `carousel_watchdog` (every 10m): scans scheduler audit log, flags jobs stalled past 2× expected interval, fires Discord notification
- Verified: watchdog detected four real stalls on first run (`character_content_generation` 1039min old, `character_publish_backlog` 2504min old, `media_content_generation` 983min old). Self-healing signal confirmed.

### Phase 4 — scoped down
Turns out [carousel_renderer_service.py](backend/app/services/carousel_renderer_service.py) already renders slides to PNG with font + accent + overlay specs, and `publish_carousel()` already marks `published` and stores `download_urls`. The real remaining gap is:

- TikTok **photo-post** Content Posting API: current [tiktok_api_client.py](backend/app/infrastructure/tiktok_api_client.py) only implements video upload + `create_post`. Photo carousels require `PHOTO_MODE` with a different multi-image payload shape — this is multi-day work plus real OAuth credentials.
- Post-publish engagement sync + outcome learning feedback: gated on real publishing above.

Deferred to a follow-up phase. Rendering works today; carousels are export-ready.

### Rebuild + Verification
- `docker compose build --no-cache zero-api` run twice (first build had stale COPY layer, second caught up)
- `zero-api` healthy; all new jobs registered in scheduler startup log
- Employee report endpoint returning valid JSON with real statistics
- Watchdog validated against real production audit data
