# Career Strategy Engine — Tim Ferriss Frameworks for FortressOS

## Context

You shared 5 screenshots of Tim Ferriss-inspired AI career strategy prompts (from "Its AI Guide"). These define 4 structured frameworks for career analysis that go beyond job matching into strategic life/career design. FortressOS already has a strong foundation — skills tracking, deep evaluations, archetypes, compensation data, feedback loops — but lacks a **strategic layer** that synthesizes all this data into career direction and life design guidance.

This plan adds a **Career Strategy Engine** that mirrors the proven DeepEvaluation pattern (LLM-powered structured JSON analysis, stored per-user, re-runnable) but operates at the *career level* instead of the *job level*.

---

## The 4 Frameworks

| # | Framework | Tim Ferriss Concept | Core Question |
|---|-----------|-------------------|---------------|
| 1 | **Skill Stack Analysis** | Find Your Unfair Advantage | Which rare skill combinations give you maximum market leverage? |
| 2 | **Leverage Gaps** | DEAL Framework | What should you eliminate, automate, or delegate to reclaim time? |
| 3 | **Career Freedom** | Career Path Evaluation | Is your career building freedom or a golden cage? |
| 4 | **Wealth Strategy** | 10-Year Wealth Design | How do you build scalable income and ownership over 10 years? |

---

## Files to Create

| File | Purpose |
|------|---------|
| `backend/app/models/career_strategy.py` | SQLAlchemy model |
| `backend/app/services/career_strategy_service.py` | Service with 4 framework methods + LLM prompts |
| `backend/app/api/career_strategy.py` | FastAPI router |
| `frontend/src/hooks/useCareerStrategy.js` | React Query hooks |
| `frontend/src/pages/CareerStrategy.jsx` | Page with 4-tab layout |

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Import `CareerStrategy` |
| `backend/app/main.py` | Register `career_strategy` router |
| `frontend/src/App.jsx` | Add `/career-strategy` route with `React.lazy()` |
| `frontend/src/components/Layout.jsx` | Add nav link |
| `frontend/src/services/api.js` | Add API methods |

---

## Step 1: Database Model

**File**: `backend/app/models/career_strategy.py`

Follow the `DeepEvaluation` model pattern from [deep_evaluation.py](backend/app/models/deep_evaluation.py).

```
CareerStrategy:
  id                  PK
  user_id             FK -> user_profile.id (indexed)
  framework           String(30) — "skill_stack" | "leverage_gaps" | "career_freedom" | "wealth_strategy" (indexed)
  blocks_json         JSONB — the structured framework output
  score               Numeric(5,2) — overall framework score (0-100)
  grade               String(2) — A/B/C/D/F
  summary             Text — short summary for list views
  inputs_snapshot     JSONB — snapshot of input data used (for diff detection)
  llm_provider        String(40)
  llm_model           String(80)
  input_tokens        Integer
  output_tokens       Integer
  cost_usd            Numeric(10,6)
  latency_ms          Numeric(10,1)
  generated_at        DateTime (indexed)
  expires_at          DateTime — cache TTL (30 days default)
```

Register in `backend/app/models/__init__.py`.

---

## Step 2: Service Layer

**File**: `backend/app/services/career_strategy_service.py`

Follow the `DeepEvaluationService` pattern from [deep_evaluation_service.py](backend/app/services/deep_evaluation_service.py): constructor takes `(db, router)`, uses `router.generate_text_with_usage()` with `TaskType.REASONING`, parses JSON, persists model.

### Data Gathering (shared across frameworks)

Before calling the LLM, the service gathers the user's existing data as context:

- **Profile**: `UserProfile` — name, target_title, target_salary, years_experience, location, bio
- **Skills**: `UserSkill` — all skills with proficiency, categories, sources
- **Winning skills**: `FeedbackService.get_winning_skills()` — callback-correlated skills
- **Success patterns**: `FeedbackService.analyze_success_patterns()` — outcome distributions
- **Personas**: active `Persona` records — target titles, industries, success rates
- **Archetypes**: distribution of job archetypes from `DeepEvaluation` results
- **Compensation**: `CompensationData` for user's target companies/levels
- **Application funnel**: counts from `Application` table by status
- **Match stats**: average match scores, grade distribution from `JobMatch`

### Framework 1: Skill Stack Analysis ("skill_stack")

**LLM Prompt Context**: Skills list with proficiency + categories, winning skills data, match score correlations, persona skills, job market data from matches

**LLM Output Structure** (JSON):
```json
{
  "core_skill_stack": {
    "score": 78,
    "content": "markdown analysis",
    "top_skills": ["skill1", "skill2", ...],
    "leverage_ratio": "top 20% producing 80% of results"
  },
  "eighty_twenty_analysis": {
    "score": 72,
    "content": "markdown",
    "high_leverage_skills": [{"skill": "...", "impact": "..."}],
    "low_leverage_skills": [{"skill": "...", "recommendation": "..."}]
  },
  "rare_combinations": {
    "score": 85,
    "content": "markdown",
    "combinations": [{"skills": [...], "rarity": "...", "market_premium": "..."}]
  },
  "market_premium": {
    "score": 70,
    "content": "markdown",
    "premium_estimate": "$X-$Y above baseline",
    "positioning": "..."
  },
  "ranked_potential": {
    "score": 75,
    "content": "markdown",
    "ranked_paths": [{"path": "...", "income_potential": "...", "lifestyle_fit": "..."}]
  }
}
```

### Framework 2: Leverage Gaps ("leverage_gaps")

**LLM Prompt Context**: Application funnel data, time-per-activity estimates, automation status (which scrapers active, which tasks automated), skill stack from F1 if available

**LLM Output Structure**:
```json
{
  "current_work_audit": {
    "score": 65,
    "content": "markdown audit of current activities",
    "activities": [{"activity": "...", "hours_per_week": N, "category": "define|eliminate|automate|liberate"}]
  },
  "deal_framework": {
    "score": 70,
    "content": "markdown DEAL analysis",
    "define": [...], "eliminate": [...], "automate": [...], "liberate": [...]
  },
  "outsource_automate_list": {
    "score": 72,
    "content": "markdown",
    "items": [{"task": "...", "method": "...", "time_saved": "..."}]
  },
  "muse_opportunity": {
    "score": 60,
    "content": "markdown muse business ideas based on skill stack",
    "ideas": [{"idea": "...", "effort": "...", "income_potential": "..."}]
  },
  "action_plan": {
    "score": 75,
    "content": "markdown concrete action plan",
    "next_90_days": [{"week": N, "action": "...", "expected_result": "..."}]
  }
}
```

### Framework 3: Career Freedom ("career_freedom")

**LLM Prompt Context**: Profile, years experience, target title/salary, archetype distribution, compensation data, current application funnel, deep evaluation grades

**LLM Output Structure**:
```json
{
  "work_classification": {
    "score": 55,
    "content": "markdown classification of work activities",
    "freedom_building": [...],
    "time_for_money": [...],
    "skill_building": [...]
  },
  "freedom_ratio": {
    "score": 45,
    "content": "markdown analysis of how work compounds vs consumes time",
    "ratio": 0.35,
    "interpretation": "...",
    "compounding_activities": [...]
  },
  "fear_setting": {
    "score": 70,
    "content": "markdown fear-setting analysis",
    "worst_case_change": "...",
    "worst_case_stay": "...",
    "cost_of_inaction": "...",
    "reversibility": "..."
  },
  "five_year_comparison": {
    "score": 65,
    "content": "markdown 5-year projection",
    "current_path": {"year_1": "...", "year_3": "...", "year_5": "..."},
    "redesigned_path": {"year_1": "...", "year_3": "...", "year_5": "..."}
  }
}
```

### Framework 4: Wealth Strategy ("wealth_strategy")

**LLM Prompt Context**: Skill stack analysis results (if available), compensation data, archetype strengths, career freedom analysis (if available), user's bio/background

**LLM Output Structure**:
```json
{
  "skill_foundation": {
    "score": 80,
    "content": "markdown analysis of highest-leverage skill set",
    "monetizable_skills": [...]
  },
  "muse_business_models": {
    "score": 65,
    "content": "markdown muse business ideas",
    "models": [{"model": "...", "startup_cost": "...", "time_to_revenue": "...", "scalability": "..."}]
  },
  "scalable_income_map": {
    "score": 60,
    "content": "markdown income stream analysis",
    "streams": [{"stream": "...", "type": "productized|digital|licensing|equity", "timeline": "..."}]
  },
  "ten_year_roadmap": {
    "score": 70,
    "content": "markdown roadmap",
    "phases": [
      {"years": "1-2", "focus": "muse launch", "milestones": [...]},
      {"years": "3-5", "focus": "automation", "milestones": [...]},
      {"years": "6-10", "focus": "ownership", "milestones": [...]}
    ]
  },
  "ninety_day_first_move": {
    "score": 85,
    "content": "markdown first move action plan",
    "single_move": "...",
    "weekly_breakdown": [...]
  }
}
```

### Scoring & Caching

- Overall score = weighted average of block scores (equal weights, 1/N per block)
- Grade: A>=85, B>=70, C>=55, D>=40, F<40 (same scale as DeepEvaluation)
- Cache TTL: 30 days. Check `expires_at` before returning cached results
- `inputs_snapshot`: Hash of key input data to detect when re-run would produce different results (e.g., new skills added, new outcomes recorded)

---

## Step 3: API Router

**File**: `backend/app/api/career_strategy.py`

Follow the pattern from [deep_evaluations.py](backend/app/api/deep_evaluations.py).

```
POST /api/career-strategy/run/{framework}     — Run a specific framework analysis
GET  /api/career-strategy/                     — List all user's strategy reports
GET  /api/career-strategy/{id}                 — Fetch single report
GET  /api/career-strategy/latest/{framework}   — Latest report for a framework (with cache check)
POST /api/career-strategy/run-all              — Run all 4 frameworks sequentially
DELETE /api/career-strategy/{id}               — Delete a report
```

- All endpoints gated on `CurrentUserId`
- `run/{framework}` validates framework is one of the 4 valid values
- `latest/{framework}` returns cached if not expired, otherwise returns null with `"expired": true`
- `run-all` runs F1 first (since F2/F4 can reference its output), then F2+F3 in parallel, then F4

Register in `backend/app/main.py` alongside other routers.

---

## Step 4: Frontend Hook

**File**: `frontend/src/hooks/useCareerStrategy.js`

React Query hooks following existing patterns from [useDeepEvaluations.js](frontend/src/hooks/useDeepEvaluations.js):

```javascript
useCareerStrategies()                    — list all reports
useCareerStrategy(id)                    — single report
useLatestStrategy(framework)             — latest for framework (cached)
useRunStrategy()                         — mutation: run single framework
useRunAllStrategies()                    — mutation: run all 4
useDeleteStrategy()                      — mutation: delete report
```

---

## Step 5: Frontend Page

**File**: `frontend/src/pages/CareerStrategy.jsx`

Layout: 4-tab interface (similar to Negotiation page's scenario selector pattern).

**Tab Structure:**
1. **Skill Stack** — "Find Your Unfair Advantage"
2. **Leverage Gaps** — "DEAL Framework"
3. **Career Freedom** — "Where Your Career Leads"
4. **Wealth Strategy** — "10-Year Roadmap"

**Each tab shows:**
- Header with framework title + Tim Ferriss concept attribution
- "Run Analysis" button (or "Re-run" if cached result exists)
- If cached result exists: rendered blocks with scores, grade badge, generation date, cost/latency
- If expired: banner suggesting re-run with "data may have changed" note
- Empty state with description of what this framework analyzes

**Block rendering:** Reuse the `SixBlockReport` component pattern — each block has a title, score badge (0-100), and markdown content rendered with `SafeHtml`.

**Stats bar at top:** Show across all tabs:
- Total frameworks run
- Average strategy grade
- Last updated date
- Total LLM cost

**Route**: `/career-strategy` added to `App.jsx` with `React.lazy()`.
**Nav link**: Added to `Layout.jsx` sidebar under a "Strategy" section.

---

## Step 6: Wire Up

1. **Model registration**: Add `from app.models.career_strategy import CareerStrategy` to `backend/app/models/__init__.py`
2. **Router registration**: Import and mount in `backend/app/main.py` as `app.include_router(career_strategy.router, prefix="/api/career-strategy", tags=["career-strategy"])`
3. **API service**: Add career strategy endpoints to `frontend/src/services/api.js`
4. **App route**: Add lazy-loaded route in `frontend/src/App.jsx`
5. **Nav link**: Add to sidebar in `frontend/src/components/Layout.jsx`
6. **DB table**: `init_db()` with `create_all` handles table creation (no Alembic)

---

## Verification

1. **Backend**: Start Docker, hit `POST /api/career-strategy/run/skill_stack` with `X-User-Id: 1` header. Verify structured JSON response with scores, grade, and block content.
2. **Cache**: Hit `GET /api/career-strategy/latest/skill_stack` — should return cached result. Verify `expires_at` is 30 days out.
3. **All frameworks**: Hit `POST /api/career-strategy/run-all` — verify all 4 frameworks produce results.
4. **Frontend**: Navigate to `/career-strategy`, switch between tabs, run analyses, verify block rendering.
5. **Re-run**: Wait or manually expire cache, verify re-run produces fresh results.
6. **Data integration**: Verify that adding new skills or recording new outcomes changes the `inputs_snapshot` and surfaces "data changed" indicator.
