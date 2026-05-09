---
name: zero-deep-review
description: "[DEPRECATED — use deep-review (global) with --project=zero] Comprehensive feature completeness and code quality auditor for Zero. Reads source code, verifies logic, runs tests, checks API health, and grades each of 20 features across 5 dimensions."
owner_project: zero
category: review
deprecated: true
superseded_by: "deep-review"
---

# /zero-deep-review

Comprehensive feature completeness and code quality auditor for Zero. Reads actual source code, verifies logic correctness, runs tests, checks API health, and grades feature implementation quality across 20 features and 5 dimensions.

## Usage

```
/zero-deep-review              # Full review (all phases, ~45 min)
/zero-deep-review --quick      # Quick scan (inventory + quality only, ~15 min)
/zero-deep-review --test       # Focus on test coverage (phases 0,3 only, ~10 min)
/zero-deep-review --api        # Focus on API verification (phases 0,4 only, ~8 min)
/zero-deep-review --grade      # Just calculate and display current grade (~5 min)
```

## Knowledge Files

```
.Codex/skills/zero-deep-review/knowledge/
  (symlinks to .Codex/memory/quality/ — the canonical location)

.Codex/memory/quality/
  SCORING_RUBRIC.md                    # Dimension definitions & scoring guide
  MASTER_SCORECARD.md                  # Full 20-feature score table
  history/
    2026-04-baseline-audit.md          # Baseline audit (first run)
    YYYY-MM-audit.md                   # Subsequent runs
```

Legion integration files (update after each run):
```
C:\code\legion\.Codex\skills\legion-deep-review\knowledge\
  deep_review_history.json             # Last 20 run scores (includes Zero runs)
  feature_grades.json                  # Per-feature tracking with trends
  improvement_backlog.md               # Ranked fixes needed
```

## 20 Features to Audit

| # | Feature | Primary Backend Files | Primary Frontend Files |
|---|---------|----------------------|----------------------|
| 1 | Orchestration/LangGraph | `orchestration_graph.py`, `orchestrator_service.py`, `autonomous_orchestration_service.py` | `OrchestratorPage.tsx` |
| 2 | Multi-Provider LLM Router | `llm_router.py`, `unified_llm_client.py`, `llm_providers/*.py` | `LlmTab.tsx` |
| 3 | Scheduler System | `scheduler_service.py`, `scheduler_dashboard_service.py` | `SystemHealthPage.tsx` |
| 4 | TikTok Shop Pipeline | `tiktok_shop_service.py`, `tiktok_agent_graph.py`, `tiktok_video_service.py`, `url_import_service.py`, `reference_video_service.py` | `TikTokShopPage.tsx`, `ProductDetailPage.tsx` |
| 5 | AI Company | `agent_company_service.py` | `AiCompanyPage.tsx` |
| 6 | Deep Research (STORM) | `deep_research_service.py` | `DeepResearchPage.tsx` |
| 7 | Council of Agents | `council_service.py` | `CouncilRoomPage.tsx` |
| 8 | Experiment Lab | `experiment_service.py` | `ExperimentLabPage.tsx` |
| 9 | Email/Gmail | `gmail_service.py`, `gmail_oauth_service.py`, `email_classifier.py`, `email_rule_service.py`, `email_automation_service.py`, `email_draft_service.py` | `EmailPage.tsx` |
| 10 | Calendar | `calendar_service.py` | `CalendarPage.tsx` |
| 11 | Meeting Intelligence | `meeting_recording_service.py`, `meeting_transcription_service.py`, `meeting_diarization_service.py`, `meeting_summary_service.py`, `meeting_vector_service.py`, `meeting_rag_service.py`, `meeting_search_service.py`, `meeting_audio_capture.py` | `MeetingsPage.tsx`, `MeetingDetailPage.tsx`, `MeetingSearchPage.tsx` |
| 12 | Prediction Markets | `prediction_market_service.py`, `prediction_legion_manager.py` | `PredictionMarketsPage.tsx` |
| 13 | Money Maker | `money_maker_service.py`, `continuous_enhancement_service.py`, `daily_improvement_service.py` | `MoneyMakerPage.tsx` |
| 14 | Content Agent | `content_agent_service.py`, `publishing_service.py` | `ContentAgentPage.tsx` |
| 15 | Ecosystem Sync | `ecosystem_sync_service.py`, `ecosystem_health_service.py`, `self_healing_service.py` | `EcosystemPage.tsx` |
| 16 | Sprint/Task Management | `sprint_service.py`, `task_service.py`, `task_execution_service.py`, `sprint_intelligence_service.py` | `SprintsPage.tsx`, `BoardPage.tsx` |
| 17 | Knowledge Base | `knowledge_service.py` | `KnowledgePage.tsx` |
| 18 | Frontend UI/UX | N/A (cross-cutting) | All pages in `frontend/src/pages/` |
| 19 | Docker Infrastructure | `docker-compose.sprint.yml`, `backend/Dockerfile` | N/A |
| 20 | Discord/Messaging Bridge | `discord_bot.py`, `messaging_bridge.py`, `discord_notifier.py` | N/A |

## 5 Scoring Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Backend | 30% | Async patterns, error handling, structlog usage, Pydantic models, service separation |
| Frontend | 25% | TypeScript quality (`any` count), React Query adoption, loading states, error boundaries, dark theme |
| Testing | 20% | Test files per feature, pass rates, integration coverage |
| Docs | 15% | AGENTS.md accuracy, inline docs, API documentation, per-feature docs |
| Architecture | 10% | Router-service-data separation, DB schema, resilience patterns, migrations |

**Formula**: `Overall = (Backend * 0.30) + (Frontend * 0.25) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`

**Infra-only features** (Docker, Discord — no frontend): Backend absorbs frontend weight:
`Overall = (Backend * 0.55) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`

**Frontend-only feature** (Frontend UI/UX): Frontend absorbs backend weight:
`Overall = (Frontend * 0.55) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`

**Grade Scale**: A+ (97-100), A (93-96), A- (90-92), B+ (87-89), B (83-86), B- (80-82), C+ (77-79), C (73-76), C- (70-72), D (60-69), F (0-59)

## Execution Phases

### Phase 0: Load Knowledge (1 min)
Read previous run data to detect trends:
1. Read `.Codex/memory/quality/MASTER_SCORECARD.md` for last scores
2. Read `.Codex/memory/quality/history/` for past audit documents
3. Compare current run to last run — flag features that regressed 5+ points
4. Note improvement targets from previous audit

### Phase 1: Feature Inventory (5 min)
Build complete feature map by parsing source:
1. **Routers**: Count `.py` files in `backend/app/routers/`. Read `backend/app/main.py` to verify all are imported.
2. **Services**: Count `.py` files in `backend/app/services/`.
3. **Models**: Count `.py` files in `backend/app/models/`.
4. **Frontend Pages**: Count `.tsx` files in `frontend/src/pages/`. Read `frontend/src/App.tsx` for route count.
5. **Hooks**: Count `.ts/.tsx` files in `frontend/src/hooks/`.
6. **Migrations**: Count files in `backend/app/migrations/versions/`.
7. **Tests**: Count files in `backend/tests/` and `frontend/src/tests/`.
8. **Scheduler Jobs**: Read `backend/app/services/scheduler_service.py`, count entries in `DAILY_SCHEDULE`.
9. **MCP Servers**: Count files in `mcp_servers/`.

Output: Structured inventory with counts and deltas from last run.

### Phase 2: Code Quality Scan (10 min)
For each of the 20 features, scan the primary backend files listed above. Use **3 parallel Explore agents** for speed:

**Agent 1 — Error Handling & Logging**:
- Count `except Exception` per feature (grep across service + router files)
- Count `print()` statements per feature (should be structlog)
- Count `structlog.get_logger()` adoption rate

**Agent 2 — Datetime & Type Safety**:
- Count `datetime.now()` without timezone arg per feature
- Count `datetime.utcnow()` (deprecated) per feature
- Count `response_model` usage on router endpoints (Pydantic coverage)

**Agent 3 — Code Complexity**:
- Count `TODO`, `FIXME`, `HACK`, `NotImplementedError` per feature
- Identify functions > 100 LOC (list file, function name, line count)
- List files > 1,000 LOC (decomposition candidates)

**Per-file scoring formula** (start at 100, deduct):
- -5 per TODO/FIXME
- -3 per bare `except Exception`
- -15 per function > 100 LOC
- -10 per `datetime.now()` without UTC
- -10 per `datetime.utcnow()` (deprecated)
- -5 per `print()` statement

### Phase 3: Test Verification (8 min)
1. List all test files in `backend/tests/` and `frontend/src/tests/`
2. Read each test file — count test functions/methods
3. Map test files to features (using the 20-feature mapping above)
4. Run `docker exec zero-api python -m pytest tests/ --collect-only -q 2>&1` to get test inventory
5. Run `docker exec zero-api python -m pytest tests/ -v --timeout=300 2>&1` to get pass/fail counts
6. Flag features with 0 test coverage
7. Count frontend test cases from test files

Output: Per-feature test matrix, overall pass/fail, untested feature list.

### Phase 4: API Endpoint Verification (5 min)
Read `ZERO_GATEWAY_TOKEN` from `.env` file for auth. For each feature, test key GET endpoints:

```bash
# Auth header for all requests
TOKEN=$(grep ZERO_GATEWAY_TOKEN .env | cut -d= -f2)
AUTH="-H 'Authorization: Bearer $TOKEN'"

# Core
curl -s http://localhost:18792/health
curl -s http://localhost:18792/api/sprints/?limit=2 $AUTH
curl -s http://localhost:18792/api/llm/providers $AUTH

# TikTok
curl -s http://localhost:18792/api/tiktok-shop/stats $AUTH

# AI Company
curl -s http://localhost:18792/api/company/stats $AUTH

# Email
curl -s http://localhost:18792/api/email/digest $AUTH

# Calendar
curl -s http://localhost:18792/api/calendar/events $AUTH

# Knowledge
curl -s http://localhost:18792/api/knowledge/notes?limit=2 $AUTH

# Predictions
curl -s http://localhost:18792/api/predictions/markets?limit=2 $AUTH

# Research
curl -s http://localhost:18792/api/research/deep/topics $AUTH

# Council
curl -s http://localhost:18792/api/council/sessions $AUTH

# Experiments
curl -s http://localhost:18792/api/experiments/ $AUTH

# Money Maker
curl -s http://localhost:18792/api/money-maker/ideas $AUTH

# Ecosystem
curl -s http://localhost:18792/api/ecosystem/status $AUTH
```

For each: record HTTP status code, check response is not empty, flag 500s.

Skip POST/PUT/DELETE endpoints (not safe for review).

### Phase 5: Frontend Verification (5 min)
1. Run `docker exec zero-ui ls /usr/share/nginx/html/assets/` — verify production build exists
2. Check `docker logs --tail 50 zero-ui 2>&1` for errors
3. Count pages vs routes (identify dead pages — pages with no route in App.tsx)
4. Count `any` types in `.tsx` files: `grep -r ": any" frontend/src/ --include="*.tsx" --include="*.ts"`
5. Count error boundaries: `grep -r "ErrorBoundary" frontend/src/ --include="*.tsx"`
6. Count loading states: sample 10 pages for `isLoading`, `Skeleton`, `Loading`
7. Count error handling: sample 10 pages for `isError`, `error`, `catch`
8. Check theme consistency: count `bg-gray-*` vs `bg-zinc-*` usage

### Phase 6: Integration Flow Testing (5 min)
Test 5 critical E2E flows via API:

1. **Orchestrator**: POST `/api/orchestrator/invoke` with `{"message": "what's the weather?"}` — verify routing works
2. **LLM Health**: GET `/api/llm/providers` — verify all 5 providers respond
3. **Scheduler Health**: Check `docker logs --tail 200 zero-api 2>&1 | grep -c "Job executed"` — verify jobs running
4. **TikTok Pipeline**: GET `/api/tiktok-shop/stats` — verify product count > 0
5. **Container Health**: `docker ps --format "{{.Names}}\t{{.Status}}" | grep zero` — all healthy

### Phase 7: Grade Calculation (5 min)
Score each of the 20 features on each of the 5 dimensions (0-100). Use data from phases 1-6:

**Backend Score** (per feature):
- Start at 85 (Zero's services are generally well-structured)
- -3 per 10 `except Exception` catches in that feature's files
- -5 per `print()` statement
- -5 per 5 timezone-unsafe datetime calls
- -5 if no Pydantic response_model on any endpoint
- -5 per function > 100 LOC
- +5 if structlog used consistently

**Frontend Score** (per feature):
- Start at 80 (Zero's frontend is TypeScript-strict)
- +5 if proper loading state present
- +5 if error handling present
- -10 if page > 500 LOC
- -20 if page > 1000 LOC
- -10 if `zinc-*` theme tokens used (should be `gray-*`)
- +5 if React Query hooks used

**Testing Score** (per feature):
- 0 if no test file exists
- 10 if test file exists but < 5 tests
- 30 if 5-10 tests exist
- 50 if 10-20 tests exist and all pass
- 70 if 20+ tests exist and all pass
- 90+ if integration tests + unit tests + good coverage

**Documentation Score** (per feature):
- 40 base (AGENTS.md covers project-level)
- +10 if feature mentioned in AGENTS.md
- +15 if per-feature doc exists in `.Codex/memory/` or `docs/`
- +15 if inline docstrings on primary service functions
- +20 if API endpoint documentation exists

**Architecture Score** (per feature):
- 70 base (Zero has clean router-service-data separation)
- +10 if DB migration exists for feature
- +5 if circuit breaker / retry logic present
- +5 if proper connection pooling used
- +5 if caching layer present
- +5 if feature is decoupled (no circular imports)

Apply dimension weights per feature, compute overall.

### Phase 8: Persist Results + Create Improvement Plan (5 min)
1. **Update** `.Codex/memory/quality/MASTER_SCORECARD.md` with new scores
2. **Create** `.Codex/memory/quality/history/YYYY-MM-audit.md` with full audit document
3. **Update** Legion knowledge files:
   - `C:\code\legion\.Codex\skills\legion-deep-review\knowledge\deep_review_history.json` — append run
   - `C:\code\legion\.Codex\skills\legion-deep-review\knowledge\feature_grades.json` — update trends
   - `C:\code\legion\.Codex\skills\legion-deep-review\knowledge\improvement_backlog.md` — re-rank

4. **Display summary** to user:

```
Zero Deep Review — Grade: 64/100 (D) [+0 from last run]

  Backend:       77/100  (564 bare excepts, 165 unsafe datetimes)
  Frontend:      73/100  (15 pages missing error handling)
  Testing:       15/100  (13/20 features untested)
  Docs:          55/100  (No per-feature documentation)
  Architecture:  80/100  (Clean separation, pgvector, LangGraph)

  Grade Distribution: 0 A/B | 3 C | 10 D | 7 F

  Top 3 Improvements Needed:
  1. Testing: Add tests for 13 untested features (+4 platform pts)
  2. Frontend: Add error handling to 15 pages (+2 platform pts)
  3. Backend: Fix 165 datetime.utcnow() calls (+2 platform pts)

  Regressions: None (baseline run)
```

## Efficiency Guidelines

- **Use 3 parallel agents** in Phase 2 (code quality scan) for speed
- **Use 2 parallel agents** for Phase 3 (backend tests) + Phase 5 (frontend check) simultaneously
- **Cache grep results** — don't re-scan the same files across phases
- **Skip `--quick` phases**: If `--quick` flag, only run phases 0, 1, 2, 7, 8
- **Skip `--test` phases**: If `--test` flag, only run phases 0, 3, 8
- **Skip `--api` phases**: If `--api` flag, only run phases 0, 4, 8
- **Skip `--grade` phases**: If `--grade` flag, only run phases 0, 7 (from cached data)

## Rules

- **NEVER modify source code** — this skill is READ-ONLY analysis only
- Always read knowledge files FIRST to detect trends and regressions
- Always WRITE updated knowledge/quality files at the end of every run
- Keep run history to last 20 entries (prune oldest)
- If Docker containers are not running, skip phases 4 and 6 (API checks) — note in output
- If tests hang > 5 minutes, kill and report partial results
- Compare everything to previous run — **delta matters more than absolute score**
- Score based on hard data (grep counts, test results), not subjective assessment
- When scoring, be consistent with the baseline (2026-04-04) methodology so trends are meaningful
