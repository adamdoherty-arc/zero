# Plan: Adopt Career-Ops Best Patterns into FortressOS

## Context

[Career-Ops](https://github.com/santifer/Career-Ops) is a battle-tested AI job-search system (its creator processed 740+ offers, generated 100+ tailored CVs, and landed a Head of Applied AI role with it). FortressOS already has a much richer architecture (FastAPI + React + Postgres + LangGraph + multi-LLM router), but Career-Ops contains several **high-leverage patterns** that FortressOS is missing:

1. **Deep "6-Block A–F" structured evaluation** vs. FortressOS's flat 5-factor numeric score
2. **STAR+Reflection interview story bank** that accumulates across evaluations
3. **Compensation research** from Glassdoor / Levels.fyi / Blind (FortressOS only uses in-job salary data)
4. **Salary negotiation toolkit** (counter-offer scripts, downlevel framing, geo-discount pushback)
5. **Job archetype classification** (FDE, SA, PM, LLMOps, Agentic, Transformation) used to bias evaluation
6. **Ashby scraper** (FortressOS has Greenhouse + Lever but not Ashby — third-largest ATS)
7. **Recruiter / contact tracking** (FortressOS has zero networking model)
8. **Target-company watchlist** (separate from per-job favorites)
9. **PDF resume generation** (FortressOS can read PDFs but not write them)
10. **Batch parallel evaluation** of N jobs through deep pipeline

This plan brings these in as **net-additive** features that complement (not replace) existing systems. Everything is layered on top of the current `MatchingService`, `LLMRouter`, `PersonaService`, etc. — no rewrites.

---

## Recommended Approach

Organized into 3 tiers so the work can ship incrementally. Each tier is independently valuable.

**Approved scope: All 3 tiers will be executed. Playwright will be added as a dependency to enable SPA scraping.**

### Tier 1 — Quick Wins (small, isolated additions)

#### 1.1 Ashby Scraper + Playwright Foundation
- **New file**: [backend/app/scrapers/ashby.py](backend/app/scrapers/ashby.py)
- Pattern: Inherit `BaseScraper` like [backend/app/scrapers/greenhouse.py](backend/app/scrapers/greenhouse.py)
- **Hybrid strategy**: Try `https://api.ashbyhq.com/posting-api/job-board/{org_slug}` first (public JSON, fast). Fall back to Playwright for orgs that disable the API or use the SPA (`jobs.ashbyhq.com/{slug}`).
- **New dependency**: `playwright` added to [backend/requirements.txt](backend/requirements.txt) — install browsers in `backend/Dockerfile` via `RUN playwright install chromium --with-deps`
- **New base mixin**: [backend/app/scrapers/playwright_base.py](backend/app/scrapers/playwright_base.py) — shared Playwright lifecycle (`async with browser`), reusable by future Workday/proprietary scrapers
- Register Ashby in [backend/app/scrapers/__init__.py](backend/app/scrapers/__init__.py)
- Seed companies via [backend/scripts/seed_job_sources.py](backend/scripts/seed_job_sources.py) — Ashby orgs include Linear, Posthog, Replicate, Vercel, Ramp, Notion, Mercury, Modal, etc.
- **Note**: Playwright unlocks Tier 3 saved-search templates that scrape Workday, Lever SPAs, and other JS-rendered portals

#### 1.2 Job Archetype Classification
- **New column**: `Job.archetype` (enum) on [backend/app/models/job.py](backend/app/models/job.py)
- Archetypes: `FDE` (forward-deployed), `SA` (solutions architect), `PM`, `LLMOps`, `AgenticEngineer`, `Transformation`, `SWE`, `MLEngineer`, `Researcher`, `Other`
- Classifier method on existing `LLMService` — short prompt, cached per job
- Alembic migration adds the column + enum
- Display as a colored chip in [frontend/src/pages/Jobs.jsx](frontend/src/pages/Jobs.jsx) and [frontend/src/components/JobDetailModal.jsx](frontend/src/components/JobDetailModal.jsx)

#### 1.3 Target Company Watchlist
- **New model**: `TargetCompany` in [backend/app/models/](backend/app/models/) with fields `user_id`, `company_name`, `priority` (S/A/B/C), `notes`, `careers_url`, `ats_type`, `last_checked_at`
- **New router**: [backend/app/api/target_companies.py](backend/app/api/target_companies.py) — full CRUD, gated on `CurrentUserId`
- **New page**: [frontend/src/pages/TargetCompanies.jsx](frontend/src/pages/TargetCompanies.jsx) + hook in `frontend/src/hooks/useTargetCompanies.js`
- Background task: every N hours, scrape only target-company sources first (high-priority queue) — extends [backend/app/workers/scrape_tasks.py](backend/app/workers/scrape_tasks.py)

#### 1.4 Recruiter / Contact Tracking
- **New model**: `Contact` (id, user_id, name, company, title, email, linkedin_url, source, last_contact_at, notes, contact_type ∈ {recruiter, employee, hiring_manager, referral})
- **New model**: `ContactInteraction` (id, contact_id, application_id, interaction_type ∈ {email, call, linkedin_msg, coffee, interview}, occurred_at, notes)
- Optional FK from `Application` → `Contact` (the recruiter who sourced it)
- **New router**: [backend/app/api/contacts.py](backend/app/api/contacts.py)
- **New page**: [frontend/src/pages/Contacts.jsx](frontend/src/pages/Contacts.jsx)

---

### Tier 2 — Core Enhancements (the highest ROI)

#### 2.1 Deep "6-Block A–F" Evaluation Service
This is the **headline feature** from Career-Ops. Today FortressOS computes a fast numeric `JobMatch` (semantic + skill + salary + location + experience). Career-Ops layers a much deeper structured evaluation on top, used for high-priority opportunities only.

- **New service**: [backend/app/services/deep_evaluation_service.py](backend/app/services/deep_evaluation_service.py)
- Uses `LLMRouter` from [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py) — routes to Claude/Kimi for high-quality reasoning
- Produces 6 blocks per job:
  - **Block A — Role Summary**: archetype + TL;DR + domain/seniority/remote table
  - **Block B — CV Match**: maps each JD requirement to specific resume lines (uses existing `Resume.parsed_content`); archetype-aware emphasis
  - **Block C — Level Strategy**: detects JD level vs. user's natural level, generates "sell senior" framing or downlevel tactics
  - **Block D — Compensation & Demand**: compensation research (see 2.3)
  - **Block E — CV Personalization**: table of top 5 resume changes + top 5 LinkedIn changes (reuses [backend/app/services/resume_enhancement_service.py](backend/app/services/resume_enhancement_service.py))
  - **Block F — Interview Prep**: pulls 6–10 STAR+R stories (see 2.2)
- **New model**: `DeepEvaluation` (id, user_id, job_id, archetype, blocks_json, overall_grade ∈ A–F, generated_at, llm_provider, cost_usd)
- **New router**: [backend/app/api/deep_evaluations.py](backend/app/api/deep_evaluations.py) with `POST /evaluate/{job_id}`, `GET /{id}`, `GET /by-job/{job_id}`
- **New page**: [frontend/src/pages/DeepEvaluation.jsx](frontend/src/pages/DeepEvaluation.jsx) — renders the 6 blocks beautifully (markdown + tables)
- **Trigger**: button on `MatchDetail` page — "Run Deep Evaluation" — opens the report
- Stored as artifacts so they persist even if the job is removed from feed
- **Grading rubric**: A=must apply, B=strong fit, C=stretch, D=fallback, F=skip — derived from block-level scores via a weighted formula in `DeepEvaluationService.compute_overall_grade()`

#### 2.2 STAR+Reflection Interview Story Bank
Reusable behavioral-interview narratives that grow with each evaluation.

- **New model**: `InterviewStory` (id, user_id, title, situation, task, action, result, reflection, tags, archetype, source_application_id, last_used_at, use_count)
- **New service**: [backend/app/services/story_bank_service.py](backend/app/services/story_bank_service.py)
  - `extract_stories_from_resume(resume)` — seed bank from existing experience
  - `select_stories_for_job(job, n=8)` — semantic + tag matching against JD requirements
  - `record_use(story_id, application_id)` — for analytics
- **New router**: [backend/app/api/stories.py](backend/app/api/stories.py)
- **New page**: [frontend/src/pages/StoryBank.jsx](frontend/src/pages/StoryBank.jsx) — CRUD + tag filter + "stories used in last interview" view
- Linked from `DeepEvaluation` Block F (top stories pre-selected for that job)

#### 2.3 Compensation Research Service
- **New service**: [backend/app/services/compensation_service.py](backend/app/services/compensation_service.py)
- Sources (use `WebSearch` / scraping with explicit rate limits + caching):
  - levels.fyi (free public pages)
  - Glassdoor (search snippets only — ToS-safe)
  - Blind (snippets via search)
  - Built-in salary data already in `Job.salary_min/max`
- **New model**: `CompensationData` (id, company_name, role_level, location, base_min, base_max, equity_min, equity_max, total_min, total_max, source, fetched_at, ttl)
- Cache per `(company, level, location)` for 30 days
- Surfaced in Block D of deep evaluation + as a chip on `JobDetailModal`
- Add `tenacity` retry + cache via existing `CacheService`

#### 2.4 PDF Resume Generation
- Add `weasyprint` (preferred — clean HTML/CSS → PDF) or `reportlab` to [backend/requirements.txt](backend/requirements.txt)
- **New service**: [backend/app/services/pdf_service.py](backend/app/services/pdf_service.py) with `render_resume(resume_variant, persona, template='ats')`
- HTML template at [backend/app/templates/resume_ats.html](backend/app/templates/resume_ats.html) — Career-Ops uses Space Grotesk + DM Sans typography (Google Fonts, ATS-safe)
- **New endpoint**: `GET /api/resume-variants/{id}/pdf` returns `application/pdf`
- Frontend: download button on [frontend/src/pages/ResumeVariants.jsx](frontend/src/pages/ResumeVariants.jsx)
- Note: weasyprint needs Cairo/Pango — already viable in our backend Docker image (Linux)

---

### Tier 3 — Advanced / Optional

#### 3.1 Salary Negotiation Toolkit
- **New service**: [backend/app/services/negotiation_service.py](backend/app/services/negotiation_service.py)
- LLM-driven scripts for:
  - Counter-offer ($X → $Y framing)
  - Downlevel pushback ("you offered L4, I'm L5 because…")
  - Geographic discount rebuttal ("remote-first means market-rate")
  - Competing-offer leverage
- Uses `CompensationData` from 2.3 as anchor
- **New router**: [backend/app/api/negotiation.py](backend/app/api/negotiation.py) with `POST /draft-counter`, `POST /draft-rebuttal`
- **New page**: [frontend/src/pages/Negotiation.jsx](frontend/src/pages/Negotiation.jsx) — wizard tied to an `Application` in `offer` state

#### 3.2 Saved Search Templates
- **New model**: `SearchTemplate` (id, user_id, name, queries [list], sources [list], filters_json, schedule_cron, last_run_at)
- Seed with the Career-Ops 19 reusable queries (e.g., `"Forward Deployed Engineer" site:jobs.ashbyhq.com`, `"AI Solutions Architect"`, etc.)
- **New router**: [backend/app/api/search_templates.py](backend/app/api/search_templates.py)
- Celery task `run_search_template_task` triggered by schedule

#### 3.3 Batch Deep-Evaluation Worker
- New Celery task `batch_deep_evaluate_task(job_ids: list[int], user_id: int)` in [backend/app/workers/](backend/app/workers/)
- Fans out to N parallel deep-eval calls, each routed via `LLMRouter` so circuit breakers protect cost
- Persists results as `DeepEvaluation` rows
- **New endpoint**: `POST /api/deep-evaluations/batch` with body `{"job_ids": [...]}`
- Frontend: bulk-select on `Matches` page → "Deep evaluate selected"

#### 3.4 Pipeline Integrity / Health Tools
- **New script**: [backend/scripts/pipeline_doctor.py](backend/scripts/pipeline_doctor.py)
- Checks:
  - Orphan `JobMatch` rows (job deleted)
  - Applications stuck in `applied` > 30 days with no follow-up
  - Duplicate jobs missed by hash dedup (fuzzy title+company)
  - Status enum drift between API and DB
  - `Resume.embedding` rows missing or wrong dim
- Outputs report → optional `--fix` flag
- Wire as Celery beat task `pipeline_health_check_task` once per day → writes `Notification` rows

---

## Critical Files to Modify or Create

### New backend files
- `backend/app/scrapers/ashby.py`
- `backend/app/services/deep_evaluation_service.py`
- `backend/app/services/story_bank_service.py`
- `backend/app/services/compensation_service.py`
- `backend/app/services/pdf_service.py`
- `backend/app/services/negotiation_service.py`
- `backend/app/api/target_companies.py`
- `backend/app/api/contacts.py`
- `backend/app/api/deep_evaluations.py`
- `backend/app/api/stories.py`
- `backend/app/api/negotiation.py`
- `backend/app/api/search_templates.py`
- `backend/app/templates/resume_ats.html`
- `backend/scripts/pipeline_doctor.py`
- New models in `backend/app/models/`: `target_company.py`, `contact.py`, `deep_evaluation.py`, `interview_story.py`, `compensation.py`, `search_template.py`
- Alembic migration adding all of the above + `Job.archetype` column

### Existing backend files to touch
- [backend/app/scrapers/__init__.py](backend/app/scrapers/__init__.py) — register Ashby
- [backend/app/models/__init__.py](backend/app/models/__init__.py) — export new models
- [backend/app/models/job.py](backend/app/models/job.py) — add `archetype` enum
- [backend/app/models/application.py](backend/app/models/application.py) — optional FK to `Contact`
- [backend/app/main.py](backend/app/main.py) — register new routers
- [backend/app/services/llm_service.py](backend/app/services/llm_service.py) — add `classify_archetype()` helper (or put it on the router)
- [backend/scripts/seed_job_sources.py](backend/scripts/seed_job_sources.py) — add Ashby seed orgs
- [backend/requirements.txt](backend/requirements.txt) — add `weasyprint`

### New frontend files
- `frontend/src/pages/TargetCompanies.jsx`
- `frontend/src/pages/Contacts.jsx`
- `frontend/src/pages/DeepEvaluation.jsx`
- `frontend/src/pages/StoryBank.jsx`
- `frontend/src/pages/Negotiation.jsx`
- `frontend/src/hooks/useTargetCompanies.js`, `useContacts.js`, `useDeepEvaluations.js`, `useStories.js`
- `frontend/src/components/ArchetypeChip.jsx`
- `frontend/src/components/SixBlockReport.jsx` (renders the deep evaluation)

### Existing frontend files to touch
- [frontend/src/App.jsx](frontend/src/App.jsx) — add lazy routes
- [frontend/src/components/Layout.jsx](frontend/src/components/Layout.jsx) — add nav links
- [frontend/src/components/JobDetailModal.jsx](frontend/src/components/JobDetailModal.jsx) — show archetype chip + "Run Deep Eval" button
- [frontend/src/components/MatchDetailModal.jsx](frontend/src/components/MatchDetailModal.jsx) — link to deep eval if exists

---

## Patterns to Reuse (do not rebuild)

- **AppException factories** from `backend/app/core/errors.py` — every new router uses `not_found_error()`, `validation_error()`
- **`get_or_404`, `paginate`, `CurrentUserId`** from [backend/app/api/deps.py](backend/app/api/deps.py) — all new endpoints
- **`LLMRouter`** from [backend/app/infrastructure/llm_router.py](backend/app/infrastructure/llm_router.py) — every LLM call goes through it (gives circuit breakers + cost tracking for free)
- **`CacheService`** — wrap `CompensationData` and deep-eval results
- **`ItemList`, `JobDetailModal`, `score utilities`** from existing frontend — reuse for new pages
- **`React.lazy()` + Suspense** pattern from existing pages
- **Tenacity retry** + Celery `autoretry_for` for all external calls
- **Static Tailwind class maps** for archetype chip colors (never `bg-${color}`)
- **Multi-user filtering** — every model includes `user_id`, every query filters by it (lesson from Sprint 2009 audit)

---

## Verification

### Tier 1
1. `cd c:/code/fortressOS && docker compose up -d --build backend celery-worker` then `curl http://localhost:8001/api/sources` shows Ashby
2. Trigger Ashby scrape: `curl -X POST http://localhost:8001/api/sources/ashby/scrape -H "X-User-Id: 1"` → check Jobs page for new entries
3. Open a job → archetype chip displays; run `pytest backend/tests/services/test_archetype_classifier.py`
4. Add a target company via UI → it appears in priority-scrape queue (check Celery logs)
5. Add a contact, link to an application → relationship round-trips through API

### Tier 2
6. From `MatchDetail`, click "Run Deep Evaluation" → 6-block report renders within ~30 s; record persists in `deep_evaluations` table
7. Check `StoryBank` page → seeded stories appear; tags filter works
8. Compensation lookup: `GET /api/compensation?company=Anthropic&role=Engineer&level=L5` → returns cached data the second time
9. `GET /api/resume-variants/1/pdf` → downloads a 1-page ATS-friendly PDF; open in Acrobat → text is selectable, no images
10. `pytest backend/tests/services/test_deep_evaluation_service.py` and `test_story_bank_service.py` — both green

### Tier 3
11. Draft a counter-offer via the Negotiation page → output references real comp data from 2.3
12. Run a search template → new jobs appear scoped to that template
13. Batch deep-evaluate 5 jobs → all 5 `DeepEvaluation` rows created in parallel; cost logged
14. `python -m scripts.pipeline_doctor` → outputs a clean health report; with `--fix` it heals known synthetic issues

### End-to-end smoke test
15. Seed a fresh user → scrape Ashby → 5-factor match → run deep eval on top hit → tailor resume → export PDF → log a contact → draft a counter-offer. Each step <60 s.
16. Run full test suite: `pytest backend/tests/ -v` — no regressions in existing 17 API test files.

---

## Out of Scope (intentionally)

- **Go TUI dashboard** from Career-Ops — FortressOS already has a far richer React frontend, not worth duplicating
- **Auto-apply / form submission automation** — Career-Ops is human-in-the-loop; we keep the same posture
- **Mobile app** — separate effort
- **Replacing existing 5-factor matching** — deep eval is additive, not a replacement (fast match still drives the daily feed; deep eval is on-demand for high-value targets)
