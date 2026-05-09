# Zero as a 24/7 Employee — Employee Development + Carousel Quality Loop

## Context

Zero is meant to operate as an autonomous content employee that researches entities (characters, TV shows, movies), produces carousels, and continuously improves them. Today there are four gaps blocking "world-class":

1. **Research is shallow & uneven.** `CharacterModel.research_data` is freeform JSONB. There's no standard schema per entity type, and TV/movie entities go through the same character flow without a tailored research shape. `CharacterLoreChunkModel` + pgvector exists but isn't wired into synthesis.
2. **Carousels don't get re-examined.** Once a carousel is `approved` or `published` it's terminal. Swarm calibration and prompt breeder adjust *future* output, but existing carousels never get re-graded, re-imaged, or re-textured as the system gets smarter.
3. **Reference videos are broken.** Paths are stored relative to `Path.cwd()` at ingest time and re-resolved at request time — on Windows with Docker volume mounts this mismatches and returns 404. The `style_analysis` and `extracted_facts` LLM outputs are also never fed back into carousel generation, so the ML loop dead-ends.
4. **No single "employee" view.** `daily_report_service.py` grades ops 0-100 and has a `carousel_employee_report()` method, but nothing aggregates across subsystems, and there is no UI page to see what Zero accomplished today / this week. ADA's per-feature grade card pattern (`C:\code\ADA\.claude\memory\grades\`) is the reference to match.

Intended outcome: Zero wakes up every day, researches entities that need depth, re-audits a rolling window of carousels, learns from reference videos that now actually play, and reports its work on a dashboard with grades, wins, and regressions.

---

## Scope (5 workstreams, shippable in order)

### 1. Fix reference video playback + wire the learning loop

**Root-cause fix (required before anything else):**
- [backend/app/services/character_reference_video_service.py:417-422](backend/app/services/character_reference_video_service.py#L417-L422) and [:444-448](backend/app/services/character_reference_video_service.py#L444-L448) — store **absolute** paths, not `relative_to(Path.cwd())`. The stored string must survive process restart and different cwd.
- Add `WORKSPACE_ROOT` anchor resolved once from `settings`; all reference video paths live under `${WORKSPACE_ROOT}/character_content/reference_videos/{ref_id}/`.
- [backend/app/routers/character_reference_videos.py:151-187](backend/app/routers/character_reference_videos.py#L151-L187) `get_reference_file()` — resolve stored path against `WORKSPACE_ROOT` if not absolute, normalize separators (`PurePosixPath`/`Path` agnostic), return a clearer 404 body naming the expected file for debugging.
- One-time backfill migration: walk existing `CharacterReferenceVideoModel` rows, rewrite relative paths to absolute using `WORKSPACE_ROOT`, mark missing files `status='failed'` with a reason so the UI can show "re-ingest" instead of silent breakage.

**Close the ML loop (the user's core ask: "so it can learn"):**
- New service method `character_reference_video_service.apply_learnings()`:
  - Auto-apply facts with `surprise_score >= 0.7` to `character.fact_bank` (mirrors the manual `apply_facts()` at [:758-819](backend/app/services/character_reference_video_service.py#L758-L819)).
  - Convert `style_analysis` (hook/structure/pacing/visual_style) into **reference style exemplars** stored on the character as `style_exemplars: list[dict]`, consumed by `character_content_service.generate_carousel()` as few-shot style hints.
  - Auto-promote `proposed_character` rows when `intent='discovery'` and LLM confidence ≥ threshold (reuses `promote_to_character()` at [:821-888](backend/app/services/character_reference_video_service.py#L821-L888)).
- New scheduler job `character_reference_video_learning` (every 30 min) calls `apply_learnings()` for rows in `status='ready'` that haven't been consumed yet (track via new `learnings_applied_at` column).

### 2. Deepen per-entity research (character / TV / movie)

**Model + data shape:**
- Introduce `entity_type` discrimination in research. Characters already have one; add typed research profile dataclasses in [backend/app/models/character_content.py](backend/app/models/character_content.py):
  - `CharacterResearchProfile` — biography, powers, relationships, arc highlights, quotes, fan theories
  - `TVShowResearchProfile` — seasons, cast, showrunner, critical reception, iconic episodes, behind-the-scenes
  - `MovieResearchProfile` — cast, director, box office, production trivia, cultural impact, cut scenes
- Persist as structured JSON inside `research_data` with a `profile_version` field so old records are detectable and re-researchable.

**Deepening pipeline (reuse, don't rebuild):**
- `character_content_service.start_research()` already orchestrates the queue. Add a `depth_goal` argument (`quick | standard | deep`). `deep` routes through existing `DeepResearchService` (STORM-style Kimi outline → Gemma synthesis → validator), which today is wired to `/api/research/deep` but not plugged into the character pipeline.
- Promote extracted sections into `CharacterLoreChunkModel` and embed via the existing unified embedding provider so carousel synthesis can RAG over them. This infrastructure is already built at [backend/app/db/models.py:2374-2392](backend/app/db/models.py#L2374-L2392); it just needs the ingest call.
- New scheduler job `entity_research_deepen` (daily at 02:00): picks the N entities with lowest `research_depth_score`, routes each through `depth_goal='deep'`.

### 3. Carousel re-audit loop (fix images, duplicate text, stale content)

This is the "check each carousel on a regular basis to keep improving" ask.

- New service `carousel_audit_service.py` with a single entry point `audit_carousel(carousel_id) -> AuditReport`:
  - **Visual audit:** for each slide image, re-check quality via existing `image_source_service.compute_quality_score()` at [:75-117](backend/app/services/image_source_service.py#L75-L117). Flag slides where score dropped below threshold, image is in `character.blocked_image_urls`, or phash matches another slide in the same carousel.
  - **Text audit:** run the existing duplicate-overlay detector (the "trigram overlap" logic in `normalize_slide_text`) across slides; detect placeholder tokens via `_carousel_has_placeholders` at [:106-126](backend/app/services/character_content_service.py#L106-L126); run the Critic role from `content_swarm_service` against current canon/safety rubric.
  - **Canon drift:** re-run swarm `canon_accuracy` check against the *current* `fact_bank` — because facts may have grown since the carousel was produced, old carousels can become newly-wrong.
- Auto-remediation tiers (safe → aggressive):
  - **Tier 1 (safe, auto):** re-image slides whose image failed quality check — reuses existing `PATCH /carousels/{id}/slides/{idx}/image` flow.
  - **Tier 2 (safe, auto):** de-duplicate text overlays via `text_overlay_specs` rewrite; already a known gap called out in the exploration.
  - **Tier 3 (requires review):** full regeneration via the existing `enhance` / Council Vote flow at `POST /carousels/{id}/enhance`. Writes a new `CharacterCarouselVersionModel` row; current version pointer stays until a human approves.
- New scheduler job `carousel_reaudit` (every 2 h): pulls a rolling batch of 20 carousels using FIFO on `last_audited_at` (new column), writes an `AuditReport` JSON to the carousel, applies Tier 1+2 automatically, queues Tier 3 into the existing review queue.

### 4. `/zero-employee-checkin` skill

Pattern-match on ADA's grade-card approach (`C:\code\ADA\.claude\memory\grades\ada-brain.md`) and Zero's existing `/zero-deep-review` skill at [.claude/skills/zero-deep-review/](.claude/skills/zero-deep-review/).

- New skill directory `.claude/skills/zero-employee-checkin/` with `SKILL.md` that runs a shorter (~5 min) daily pulse, not the 45-min deep review:
  1. Call `daily_report_service.generate_daily_report()` (existing, grades ops 0-100).
  2. Call `daily_report_service.generate_carousel_employee_report()` (existing).
  3. Call new `daily_report_service.generate_research_employee_report()` and `generate_reference_video_employee_report()` — thin wrappers in the same style as the carousel one, querying existing tables.
  4. Aggregate into one `EmployeeCheckin` object (pydantic), persist to a new `employee_checkins` table, and write a per-subsystem grade card to `.claude/memory/grades/{subsystem}.md` (matching ADA's file layout).
  5. If any subsystem regresses > 5 points vs. 7-day average, auto-create a Legion task via existing `LegionClient.create_task()` pointing at the regression.
- Register the same pulse as a scheduler job `employee_checkin` (daily 08:00) so it runs unattended even when no one invokes the skill.

### 5. Employee dashboard UI page

- New route `/employee` (or under existing Character Content workflow tabs — the layout at [frontend/src/layouts/CharacterContentLayout.tsx](frontend/src/layouts/CharacterContentLayout.tsx) already has an `employee-report` tab that's currently thin; upgrade that rather than add a new top-level page).
- New page `frontend/src/pages/EmployeeDashboardPage.tsx` rendering:
  - **Today header:** ops grade 0-100, arrow vs. yesterday, sparkline of last 14 days.
  - **Accomplishments cards:** carousels approved, entities researched, reference videos processed, facts applied, regressions fixed — each with delta.
  - **Subsystem grade cards** (one per subsystem: Research, Carousels, Reference Videos, Swarm/Brain, Autopilot) — score, top issue, top win, link to detailed view. Mirrors ADA's 5-dimension rubric.
  - **Learnings feed:** top prompt variants this week (already computed by prompt_breeder + prompt_evolution), top hook styles, top story templates.
  - **Open tasks:** pulled from Legion project_id=8 filtered to `auto_created_by='zero-employee-checkin'`.
- New backend endpoint `GET /api/employee/checkin/latest` and `GET /api/employee/checkin/history?days=30` reading the new `employee_checkins` table.
- New hook `frontend/src/hooks/useEmployeeCheckinApi.ts` following the React Query + key factory pattern used across the project.

---

## Critical files to modify

| Area | File |
|------|------|
| Video path bug | [backend/app/services/character_reference_video_service.py](backend/app/services/character_reference_video_service.py), [backend/app/routers/character_reference_videos.py](backend/app/routers/character_reference_videos.py) |
| Video learning loop | same service + [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) |
| Research deepening | [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py), [backend/app/services/deep_research_service.py](backend/app/services/deep_research_service.py), [backend/app/models/character_content.py](backend/app/models/character_content.py), [backend/app/db/models.py](backend/app/db/models.py) |
| Carousel re-audit | new [backend/app/services/carousel_audit_service.py](backend/app/services/carousel_audit_service.py), hooks into [image_source_service.py](backend/app/services/image_source_service.py) + [content_swarm_service.py](backend/app/services/content_swarm_service.py) |
| Employee report | [backend/app/services/daily_report_service.py](backend/app/services/daily_report_service.py) (extend), new [backend/app/routers/employee.py](backend/app/routers/employee.py) |
| Skill | new [.claude/skills/zero-employee-checkin/SKILL.md](.claude/skills/zero-employee-checkin/SKILL.md) |
| Migrations | new Alembic migration for `learnings_applied_at`, `last_audited_at`, `profile_version`, `style_exemplars`, `employee_checkins` table |
| Frontend | new [frontend/src/pages/EmployeeDashboardPage.tsx](frontend/src/pages/EmployeeDashboardPage.tsx), new [frontend/src/hooks/useEmployeeCheckinApi.ts](frontend/src/hooks/useEmployeeCheckinApi.ts), updated [frontend/src/layouts/CharacterContentLayout.tsx](frontend/src/layouts/CharacterContentLayout.tsx) |

## Reuse (do not rebuild)

- `DeepResearchService` — already STORM-style pipeline, plug it into character research
- `ImageSourceService.compute_quality_score` + phash dedup — reuse for re-audit
- `ContentSwarmService` Critic role + `SwarmRubric` — reuse for re-audit canon/safety checks
- `PromptBreederService` + `prompt_evolution_service` — already calibrates variants; surface their output, don't re-implement
- `LegionClient.create_task` — already wired
- `daily_report_service.generate_carousel_employee_report` — template for the new per-subsystem reports
- `CharacterLoreChunkModel` + pgvector — already modeled, just not ingested; no new table needed for RAG
- `CharacterCarouselVersionModel` — already handles re-gen provenance; Tier 3 re-audit writes into it

## Build sequence (recommended)

1. **Fix video playback bug + backfill** (30 min). Unblocks everything else and is the user's direct complaint.
2. **Wire reference-video learning loop** (half day). Auto-apply facts, style exemplars, auto-promote characters.
3. **Carousel re-audit service + Tier 1/2 auto-remediation** (1 day). Biggest quality-loop win.
4. **Research deepening with typed profiles + DeepResearchService wiring** (1 day).
5. **Employee report aggregation + Legion task creation** (half day).
6. **Employee dashboard UI + API** (1 day).
7. **`/zero-employee-checkin` skill + scheduler job** (2 h).

## Verification

- **Videos play:** open any existing reference video in [ReferenceVideoDetailModal.tsx](frontend/src/components/character-content/ReferenceVideoDetailModal.tsx); `<video>` must load, no 404 on `/api/character-content/reference-videos/{id}/file?kind=video`. Confirm after container rebuild per CLAUDE.md.
- **Learning loop:** post an inspiration TikTok URL to `/reference-videos/ingest-simple`, wait one cycle, confirm `style_exemplars` populated on linked character and next generated carousel for that character references them in `brain_context_used`.
- **Re-audit:** run `POST /api/character-content/carousels/{id}/audit` on a carousel with a known bad image; verify Tier 1 auto-swaps the image and writes an `AuditReport`. Run on a carousel with duplicate text; verify Tier 2 de-dupes overlay specs.
- **Research deepening:** trigger `depth_goal='deep'` research on one character; verify `CharacterLoreChunkModel` rows created with embeddings, `research_depth_score` climbs, subsequent carousel synthesis logs show chunks pulled into context.
- **Employee skill:** invoke `/zero-employee-checkin`; verify it writes `.claude/memory/grades/*.md` cards, creates a row in `employee_checkins`, and (if a regression is injected) creates a Legion task.
- **Dashboard:** visit `/character-content/employee-report` (or new `/employee`); verify today's grade, subsystem cards, accomplishments counts, and trend sparkline render against real data.
- **Docker rebuild:** per [CLAUDE.md](CLAUDE.md), finish each backend change with `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api` and confirm `docker ps` shows zero-api healthy.

---

# Follow-up Fix — "Run check-in now" spins with no feedback

## Context

After shipping the 7-workstream employee dashboard, the user clicked **Run check-in now** on `/employee` and saw the spinner spin indefinitely with no indication that anything happened. Root cause is two-fold and both ends need a small fix:

1. **Backend is too slow.** `POST /api/employee/checkin/run` calls `daily_report_service.generate_daily_report()` which runs five heavy sections (scheduler audit scan over 24h, LLM usage aggregation, system health probe, failure investigation, missing-jobs investigation) plus `generate_carousel_employee_report` which is also non-trivial. With a warm DB this still takes 10-30 s and a single slow subsystem can stall the whole endpoint for much longer. An interactive button is the wrong shape for that — it should return in ≤ 3 s.
2. **Frontend is silent.** The mutation has a spinner but no toast on success or error. If the fetch hangs or errors, the user sees nothing change. The dashboard also reads `useLatestCheckin` — which errored on the initial "no check-in yet" 404 — and doesn't fall back to the mutation's own return payload, so even on a successful run the UI can appear frozen.

Intended outcome: clicking the button returns a fresh check-in in under ~3 seconds, the dashboard immediately shows the new snapshot (without waiting for a separate refetch), and any failure surfaces a clear, visible error.

## Scope

### Backend — make `run_checkin` fast and self-healing

- [backend/app/services/employee_checkin_service.py](backend/app/services/employee_checkin_service.py)
  - Replace the inline `generate_daily_report()` call with a **lean ops grade**: query `SchedulerAuditLogModel` for the last 24 h (already the same source `_get_job_results` uses), reuse the existing `daily_report_service._calculate_grade(job_results)` function directly, and stop there. No file persistence, no LLM section, no health probe, no failure investigation narrative. These heavy sections are still produced by the existing daily-report scheduler job at its own cadence and don't need to run on an interactive click.
  - Wrap `generate_carousel_employee_report(window_hours=...)` in `asyncio.wait_for(..., timeout=3.0)`. On `TimeoutError`, use a degraded subsystem entry with `grade=50.0`, `issues=["carousel report timed out"]`, and continue.
  - Wrap each of `_research_report`, `_reference_video_report`, `_audit_report` the same way with a ~2 s timeout each. Independent failures of any subsystem must not stall the aggregate.
  - Log a single `employee_checkin_timings` structured entry with per-subsystem ms so regressions are observable.
- [backend/app/services/daily_report_service.py](backend/app/services/daily_report_service.py)
  - Expose a thin helper `compute_ops_grade_fast(window_hours: int = 24) -> tuple[int, dict]` that returns `(grade, job_summary_stats)` using only `_get_job_results` + `_calculate_grade`. This is the function the check-in calls. The existing `generate_daily_report` keeps its full behavior for the scheduler job.

### Frontend — make button feedback unmissable

- [frontend/src/hooks/useEmployeeCheckinApi.ts](frontend/src/hooks/useEmployeeCheckinApi.ts)
  - Add an explicit `AbortController`-based timeout (20 s) on the `run` mutation's fetch, so a stuck request surfaces as an error instead of an infinite spinner.
  - On `onSuccess`, seed the React Query cache for `['employee', 'checkin', 'latest']` with the mutation's response via `qc.setQueryData`, then also invalidate. That way the dashboard re-renders with the fresh data synchronously — no second round-trip needed.
- [frontend/src/pages/EmployeeDashboardPage.tsx](frontend/src/pages/EmployeeDashboardPage.tsx)
  - Read `run.data` as a fallback when `latest` is undefined or errored, so the post-click state always shows *something*.
  - Surface `run.isError` and `run.error?.message` in a visible inline banner.
  - Surface `run.isSuccess` as a brief confirmation ("Updated <timestamp>").
  - Optional polish: replace the "Loading…" + error empty state with a single unified panel that explains the state of the page, since today it can show both (spinner + "No check-in yet" panel) at the same time.

## Critical files to modify

| Area | File |
|------|------|
| Fast ops grade | [backend/app/services/daily_report_service.py](backend/app/services/daily_report_service.py) (new `compute_ops_grade_fast`) |
| Lean check-in orchestrator | [backend/app/services/employee_checkin_service.py](backend/app/services/employee_checkin_service.py) |
| Timeout + optimistic cache update | [frontend/src/hooks/useEmployeeCheckinApi.ts](frontend/src/hooks/useEmployeeCheckinApi.ts) |
| Visible success/error feedback + fallback to mutation data | [frontend/src/pages/EmployeeDashboardPage.tsx](frontend/src/pages/EmployeeDashboardPage.tsx) |

## Reuse (do not rebuild)

- `daily_report_service._calculate_grade` — already produces the ops 0-100 grade from a `job_results` dict. Keep the formula, just expose a narrower helper that skips the expensive sections.
- `asyncio.wait_for` + `asyncio.gather(return_exceptions=True)` — standard pattern for the subsystem fanout; no new utility needed.
- `useRunCheckin` already returns the mutation object with `data`, `isPending`, `isError`, `isSuccess`, `error` — frontend fix is pure wiring.

## Verification

- Hit `POST /api/employee/checkin/run?window_hours=24` with `time` and confirm < 3 s wall time on a warm DB. Check the `employee_checkin_timings` log entry to see per-subsystem ms.
- Hit it again and confirm that:
  - The response contains a fresh `id`, non-null `overall_grade`, `ops_grade`, and five `subsystems`.
  - Even if you kill the LLM-chat container first (already failing in current logs), the endpoint still returns in < 3 s — the ops grade is scheduler-audit-only and does not touch LLMs.
- In the UI:
  - Click **Run check-in now**. The spinner stops in ≤ 3 s.
  - On success: the "No check-in yet" banner is gone, the Overall Grade renders, the Accomplishments cards populate, the Subsystem Grades grid renders, and a brief "Updated <time>" confirmation appears.
  - On induced failure (stop `zero-api` and click): the spinner stops within 20 s (AbortController) and a red error banner shows the fetch error.
- Regression check: the scheduler job `employee_checkin` at 08:00 still runs the same lean path — confirm in logs after the next tick that it produces a row in `employee_checkins` and logs `employee_checkin_done`.
- Docker rebuild per [CLAUDE.md](CLAUDE.md) for the backend changes; frontend changes are volume-mounted and live via HMR.
