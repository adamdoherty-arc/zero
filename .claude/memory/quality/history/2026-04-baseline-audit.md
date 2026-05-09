# Baseline Quality Audit - 2026-04-04

**Audit Type**: Baseline (first formal audit)
**Methodology**: 3 parallel agents (Backend Scanner, Frontend Scanner, Test/API Verifier)
**Reviewer**: Claude Opus 4.6

---

## Platform Summary

| Metric | Value |
|--------|-------|
| **Overall Grade** | **64/100 (D)** |
| Backend Average | 77/100 |
| Frontend Average | 73/100 |
| Testing Average | 15/100 |
| Documentation Average | 55/100 |
| Architecture Average | 80/100 |
| Features Audited | 20 |
| Routers | 56 |
| Services | 98 |
| Frontend Pages | 37 |
| Custom Hooks | 30 |
| Scheduler Jobs | 71 |
| DB Migrations | 15 |
| Total Backend Tests | 98 functions across 6 files |
| Total Frontend Tests | 23 cases across 2 files |

---

## Baseline Scores

| # | Feature | Backend | Frontend | Testing | Docs | Arch | **Overall** | Grade | Priority |
|---|---------|---------|----------|---------|------|------|-------------|-------|----------|
| 1 | Orchestration/LangGraph | 82 | 75 | 55 | 65 | 88 | **74** | C | Low |
| 2 | Multi-Provider LLM Router | 85 | 72 | 5 | 60 | 90 | **66** | D | High |
| 3 | Scheduler System (71 jobs) | 72 | 65 | 5 | 55 | 80 | **57** | F | Critical |
| 4 | TikTok Shop Pipeline | 78 | 82 | 45 | 60 | 82 | **72** | C- | Low |
| 5 | AI Company (5 agents) | 80 | 72 | 5 | 50 | 78 | **61** | D | Medium |
| 6 | Deep Research (STORM) | 78 | 68 | 5 | 50 | 78 | **59** | F | Medium |
| 7 | Council of Agents | 82 | 70 | 5 | 50 | 78 | **61** | D | Medium |
| 8 | Experiment Lab | 80 | 68 | 5 | 50 | 78 | **60** | D | Medium |
| 9 | Email/Gmail | 76 | 70 | 45 | 60 | 78 | **67** | D | Medium |
| 10 | Calendar | 68 | 68 | 10 | 55 | 72 | **56** | F | High |
| 11 | Meeting Intelligence | 80 | 78 | 50 | 55 | 82 | **72** | C- | Low |
| 12 | Prediction Markets | 72 | 70 | 5 | 50 | 75 | **57** | F | High |
| 13 | Money Maker | 75 | 68 | 5 | 50 | 75 | **58** | F | Medium |
| 14 | Content Agent | 76 | 72 | 5 | 50 | 78 | **60** | D | Medium |
| 15 | Ecosystem Sync | 72 | 70 | 5 | 50 | 78 | **57** | F | High |
| 16 | Sprint/Task Management | 78 | 80 | 15 | 60 | 82 | **67** | D | Medium |
| 17 | Knowledge Base | 78 | 75 | 5 | 55 | 80 | **62** | D | Low |
| 18 | Frontend UI/UX | -- | 83 | 15 | 60 | 82 | **66** | D | Medium |
| 19 | Docker Infrastructure | 82 | -- | 5 | 70 | 85 | **67** | D | Low |
| 20 | Discord/Messaging Bridge | 75 | -- | 5 | 50 | 72 | **55** | F | Low |

---

## Dimension Averages

| Dimension | Weight | Platform Avg | Strongest | Weakest |
|-----------|--------|-------------|-----------|---------|
| Backend | 30% | 77 | LLM Router (85) | Calendar (68) |
| Frontend | 25% | 73 | Frontend UI/UX (83) | Scheduler (65) |
| Testing | 20% | **15** | Orchestration (55) | 7 features at 5 |
| Docs | 15% | 55 | Docker (70) | 8 features at 50 |
| Architecture | 10% | 80 | LLM Router (90) | Calendar (72) |

---

## Scoring Justifications

### Backend Scores (avg 77/100)

**Strengths**:
- 96% of services use structlog (129/154 files)
- Only 3 actual TODO/FIXME debt markers across entire codebase
- Only 5 `print()` statements (all in discord_bot.py startup)
- Full async/await everywhere
- Service-layer separation is consistent

**Weaknesses**:
- **564 bare `except Exception` catches** -- scheduler_service.py (83), orchestration_graph.py (31), tiktok_shop_service.py (31) are worst offenders
- **165 timezone-unsafe datetime calls** (10 bare `now()` + 155 deprecated `utcnow()`)
- **27 functions over 100 lines** (worst: `run_daily_research_cycle()` at 212 lines)
- **5 services over 1,000 lines** (scheduler_service.py: 2,334, tiktok_shop_service.py: 2,103)
- **Only 31% of endpoints have Pydantic response_model** (150/482)

### Frontend Scores (avg 73/100)

**Strengths**:
- TypeScript quality is exceptional: only 3 `any` in 29,364 production lines (0.01%)
- React Query adoption: 100% of API hooks (26/26), 311 total useQuery/useMutation
- shadcn/ui adoption: 17/19 installed components actively used
- Loading states: 31/37 pages (84%) with proper skeletons/spinners
- Zustand architecture: 2 focused stores, server state via React Query

**Weaknesses**:
- **15 active data-fetching pages have zero error handling** (48% of data pages)
- **TikTokShopPage.tsx is 2,363 lines** (8+ internal sub-components need extraction)
- **Theme inconsistency**: CalendarPage, PredictionMarketsPage use `zinc-*` instead of `gray-*`
- **1 dead page**: LoginPage.tsx has no route in App.tsx
- **2 unused shadcn components**: Avatar, DropdownMenu

### Testing Scores (avg 15/100) -- CRITICAL WEAKNESS

**98 backend tests across 6 files, 23 frontend tests across 2 files**

| Coverage Level | Features | Count |
|----------------|----------|-------|
| Good (40+ tests) | Orchestration, TikTok Shop, Email, Meetings | 4 |
| Moderate (10-39) | Calendar, Sprint/Task | 2 |
| Minimal (1-9) | -- | 0 |
| **ZERO tests** | Scheduler, LLM Router, AI Company, Deep Research, Council, Experiment, Predictions, Money Maker, Content Agent, Ecosystem, Knowledge, Docker, Discord | **13** |

**65% of features (13/20) have absolutely no test coverage.**

The 98 backend tests are concentrated: Orchestration (21), TikTok Shop (28), Email (17), Meetings (24) = 90 of 98 tests in 4 features.

### Documentation Scores (avg 55/100)

- CLAUDE.md is comprehensive and accurate
- MEMORY.md provides good operational context
- No per-feature documentation exists
- No API endpoint documentation (OpenAPI auto-generated only)
- No architecture decision records

### Architecture Scores (avg 80/100)

**Strengths**:
- Clean router-service-data separation
- 15 Alembic migrations with proper versioning
- pgvector for embeddings
- Multi-provider LLM with fallback chains
- LangGraph for orchestration workflows
- Circuit breakers on external APIs (Gmail, SearXNG)

**Weaknesses**:
- No connection pooling configuration visible
- Calendar service has 11 deprecated `utcnow()` calls (timezone-unsafe)
- ecosystem_sync has NoneType errors in production
- Prediction market push to ADA has misconfigured URL

---

## Grade Distribution

| Tier | Count | % | Features |
|------|-------|---|----------|
| **A (90+)** | 0 | 0% | -- |
| **B (80-89)** | 0 | 0% | -- |
| **C (70-79)** | 3 | 15% | Orchestration (74), TikTok Shop (72), Meeting Intelligence (72) |
| **D (60-69)** | 10 | 50% | LLM Router (66), AI Company (61), Council (61), Experiment (60), Email (67), Sprint/Task (67), Knowledge (62), Frontend UI/UX (66), Docker (67), Content Agent (60) |
| **F (<60)** | 7 | 35% | Scheduler (57), Deep Research (59), Calendar (56), Predictions (57), Money Maker (58), Ecosystem (57), Discord (55) |

**0% of features reach B-tier or above.** The entire platform is dragged down by near-zero test coverage (20% weight) and weak documentation (15% weight).

---

## Critical Issues Found

1. **zero-api container was UNHEALTHY** -- SearXNG not running, ADA URL misconfigured
2. **564 bare `except Exception`** -- masking real errors across the system
3. **165 timezone-unsafe datetime calls** -- will cause bugs with UTC/local time drift
4. **13 features with zero tests** -- 65% of the platform is untested
5. **15 pages with no error handling** -- users see blank screens on API failures

---

## Improvement Targets

### Quick Wins (estimated +12 points to platform average)

| Action | Current Score | Target Score | Impact |
|--------|-------------|-------------|--------|
| Add basic tests for 13 untested features (5 tests each = 65 tests) | Testing: 15 | Testing: 35 | +4 platform |
| Add error handling to 15 frontend pages | Frontend: 73 | Frontend: 82 | +2 platform |
| Fix 165 deprecated `datetime.utcnow()` calls | Backend: 77 | Backend: 82 | +2 platform |
| Add Pydantic response_model to top 20 endpoints | Backend: 77 | Backend: 80 | +1 platform |
| Start SearXNG + fix ADA URL | Arch: 80 | Arch: 83 | +1 platform |
| Write per-feature docs for top 5 features | Docs: 55 | Docs: 65 | +2 platform |

**Projected score after quick wins: 76/100 (C+)** -- from D to C+ tier

### Medium-Term (estimated +10 more points)

| Action | Impact |
|--------|--------|
| Decompose TikTokShopPage.tsx (2,363L) into 8 components | +1 |
| Decompose scheduler_service.py (2,334L) and tiktok_shop_service.py (2,103L) | +1 |
| Reduce `except Exception` from 564 to <100 with specific exceptions | +3 |
| Standardize zinc-* pages to gray-* | +1 |
| Add 200+ integration tests covering all features | +4 |

**Projected score after medium-term: 86/100 (B)** -- from C+ to B tier

---

## Operational Health at Audit Time

| Component | Status |
|-----------|--------|
| zero-api | Running (was unhealthy, now healthy after recent restart) |
| zero-ui | Healthy (production Nginx build) |
| zero-postgres | Healthy (pgvector/pg16) |
| zero-searxng | **DOWN** (docker-compose.searxng.yml not deployed) |
| API endpoints tested | 5/6 returned valid 200 responses |
| Frontend build | Valid (1.2 MB production bundle) |
| LLM providers | All 5 healthy (Ollama, Kimi, Gemini, OpenRouter, HuggingFace) |

---

## Comparison to ADA Baseline (2026-02-21)

| Metric | ADA | Zero | Delta |
|--------|-----|------|-------|
| Overall Grade | 81 (B-) | 64 (D) | -17 |
| Backend | 90 | 77 | -13 |
| Frontend | 83 | 73 | -10 |
| Testing | 57 | 15 | -42 |
| Docs | 83 | 55 | -28 |
| Architecture | 88 | 80 | -8 |
| Features Audited | 19 | 20 | +1 |
| Services | 277 | 98 | -179 |
| Routers | 155 | 56 | -99 |
| Test Files (backend) | 35 | 6 | -29 |
| Frontend Tests | 0 | 23 | +23 |

Zero's biggest gap vs ADA: **Testing (-42 points)** and **Documentation (-28 points)**. Architecture is comparable (-8). Zero actually has more frontend tests than ADA did at baseline.

---

## Files Created During Audit

| File | Purpose |
|------|---------|
| `.claude/memory/quality/SCORING_RUBRIC.md` | Dimension definitions and scoring guide |
| `.claude/memory/quality/MASTER_SCORECARD.md` | Aggregated 20-feature score table |
| `.claude/memory/quality/history/2026-04-baseline-audit.md` | This document |
